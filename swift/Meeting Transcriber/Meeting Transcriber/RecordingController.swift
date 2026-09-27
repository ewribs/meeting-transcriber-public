import AppKit
import AVFoundation
import AudioToolbox
import CoreAudio
import Combine
import Darwin
import Foundation
import SwiftUI

struct AudioContractResponse: Decodable, Sendable {
    let schemaVersion: Int
    let path: String
    let codec: String
    let codecLongName: String
    let sampleRate: Int
    let channels: Int
    let channelLayout: String
    let remoteChannelIndex: Int
    let micChannelIndex: Int
    let remoteExtractBytes: Int
    let micExtractBytes: Int
    let extractionOk: Bool
    let compatible: Bool
    let message: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case path
        case codec
        case codecLongName = "codec_long_name"
        case sampleRate = "sample_rate"
        case channels
        case channelLayout = "channel_layout"
        case remoteChannelIndex = "remote_channel_index"
        case micChannelIndex = "mic_channel_index"
        case remoteExtractBytes = "remote_extract_bytes"
        case micExtractBytes = "mic_extract_bytes"
        case extractionOk = "extraction_ok"
        case compatible
        case message
    }
}

private struct AudioInputDeviceInfo: Sendable {
    let id: AudioDeviceID
    let name: String
    let inputChannels: Int
    let sampleRate: Double
}

nonisolated private final class AudioRecordingSink:
    @unchecked Sendable
{
    private let lock = NSLock()
    private var handle: FileHandle?
    private var writeError: String?

    func begin(url: URL) throws {
        lock.lock()
        defer { lock.unlock() }

        try? handle?.close()
        handle = nil
        writeError = nil

        FileManager.default.createFile(
            atPath: url.path,
            contents: nil
        )
        handle = try FileHandle(forWritingTo: url)
    }

    func write(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }

        guard let handle else {
            return
        }

        guard
            buffer.format.commonFormat == .pcmFormatFloat32,
            let channelData = buffer.floatChannelData,
            buffer.frameLength > 0
        else {
            writeError = "Expected Float32 PCM from the native input tap."
            try? handle.close()
            self.handle = nil
            return
        }

        let frames = Int(buffer.frameLength)
        let channels = Int(buffer.format.channelCount)

        do {
            if buffer.format.isInterleaved {
                let byteCount = frames * channels * MemoryLayout<Float>.size
                try handle.write(
                    contentsOf: Data(
                        bytes: channelData[0],
                        count: byteCount
                    )
                )
            } else {
                var interleaved = [Float](
                    repeating: 0,
                    count: frames * channels
                )

                for frame in 0..<frames {
                    for channel in 0..<channels {
                        interleaved[(frame * channels) + channel] =
                            channelData[channel][frame]
                    }
                }

                let data = interleaved.withUnsafeBytes { rawBuffer in
                    Data(rawBuffer)
                }
                try handle.write(contentsOf: data)
            }
        } catch {
            writeError = error.localizedDescription
            try? handle.close()
            self.handle = nil
        }
    }

    func writeInterleaved(_ samples: [Float]) {
        lock.lock()
        defer { lock.unlock() }

        guard let handle else {
            return
        }

        do {
            let data = samples.withUnsafeBytes { rawBuffer in
                Data(rawBuffer)
            }
            try handle.write(contentsOf: data)
        } catch {
            writeError = error.localizedDescription
            try? handle.close()
            self.handle = nil
        }
    }

    func finish() -> String? {
        lock.lock()
        defer { lock.unlock() }

        try? handle?.close()
        handle = nil
        let error = writeError
        writeError = nil
        return error
    }
}

nonisolated private final class AudioHALCapture: @unchecked Sendable {
    private var audioUnit: AudioUnit?
    private let channels: Int
    private let sampleRate: Double
    private let remoteChannelIndex: Int
    private let micChannelIndex: Int
    private let sink: AudioRecordingSink
    private let levelHandler: @Sendable (Double, Double) -> Void

    init(
        device: AudioInputDeviceInfo,
        remoteChannelIndex: Int,
        micChannelIndex: Int,
        sink: AudioRecordingSink,
        levelHandler: @escaping @Sendable (Double, Double) -> Void
    ) throws {
        self.channels = device.inputChannels
        self.sampleRate = device.sampleRate
        self.remoteChannelIndex = remoteChannelIndex
        self.micChannelIndex = micChannelIndex
        self.sink = sink
        self.levelHandler = levelHandler

        var description = AudioComponentDescription(
            componentType: kAudioUnitType_Output,
            componentSubType: kAudioUnitSubType_HALOutput,
            componentManufacturer: kAudioUnitManufacturer_Apple,
            componentFlags: 0,
            componentFlagsMask: 0
        )

        guard let component = AudioComponentFindNext(nil, &description) else {
            throw Self.error("Unable to create the macOS HAL audio component.")
        }

        var unit: AudioUnit?
        try Self.check(
            AudioComponentInstanceNew(component, &unit),
            "Unable to create the HAL audio unit"
        )
        guard let unit else {
            throw Self.error("Unable to create the HAL audio unit.")
        }
        self.audioUnit = unit

        do {
            // AUHAL bus 1 is hardware input. Input is disabled by default.
            var enabled: UInt32 = 1
            try Self.check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_EnableIO,
                    kAudioUnitScope_Input,
                    1,
                    &enabled,
                    UInt32(MemoryLayout<UInt32>.size)
                ),
                "Unable to enable HAL input bus 1"
            )

            // We only capture; no playback path is needed.
            var disabled: UInt32 = 0
            try Self.check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_EnableIO,
                    kAudioUnitScope_Output,
                    0,
                    &disabled,
                    UInt32(MemoryLayout<UInt32>.size)
                ),
                "Unable to disable HAL output bus 0"
            )

            var deviceID = device.id
            try Self.check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_CurrentDevice,
                    kAudioUnitScope_Global,
                    0,
                    &deviceID,
                    UInt32(MemoryLayout<AudioDeviceID>.size)
                ),
                "Unable to select the ‘\(device.name)’ HAL input device"
            )

            // Ask AUHAL to deliver one interleaved Float32 buffer containing
            // every aggregate-device channel in the original channel order.
            var format = AudioStreamBasicDescription(
                mSampleRate: sampleRate,
                mFormatID: kAudioFormatLinearPCM,
                mFormatFlags: kAudioFormatFlagIsFloat | kAudioFormatFlagIsPacked,
                mBytesPerPacket: UInt32(channels * MemoryLayout<Float>.size),
                mFramesPerPacket: 1,
                mBytesPerFrame: UInt32(channels * MemoryLayout<Float>.size),
                mChannelsPerFrame: UInt32(channels),
                mBitsPerChannel: 32,
                mReserved: 0
            )
            try Self.check(
                AudioUnitSetProperty(
                    unit,
                    kAudioUnitProperty_StreamFormat,
                    kAudioUnitScope_Output,
                    1,
                    &format,
                    UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
                ),
                "Unable to configure the HAL input client format"
            )

            var callback = AURenderCallbackStruct(
                inputProc: audioHALInputCallback,
                inputProcRefCon: Unmanaged.passUnretained(self).toOpaque()
            )
            try Self.check(
                AudioUnitSetProperty(
                    unit,
                    kAudioOutputUnitProperty_SetInputCallback,
                    kAudioUnitScope_Global,
                    0,
                    &callback,
                    UInt32(MemoryLayout<AURenderCallbackStruct>.size)
                ),
                "Unable to install the HAL input callback"
            )

            try Self.check(AudioUnitInitialize(unit), "Unable to initialize HAL input")
        } catch {
            AudioComponentInstanceDispose(unit)
            self.audioUnit = nil
            throw error
        }
    }

    deinit {
        stop()
    }

    func start() throws {
        guard let audioUnit else {
            throw Self.error("HAL input is unavailable.")
        }
        try Self.check(AudioOutputUnitStart(audioUnit), "Unable to start HAL input")
    }

    func stop() {
        guard let audioUnit else { return }
        AudioOutputUnitStop(audioUnit)
        AudioUnitUninitialize(audioUnit)
        AudioComponentInstanceDispose(audioUnit)
        self.audioUnit = nil
    }

    fileprivate func render(
        flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
        timestamp: UnsafePointer<AudioTimeStamp>,
        frames: UInt32
    ) -> OSStatus {
        guard let audioUnit else {
            return kAudioUnitErr_Uninitialized
        }

        let sampleCount = Int(frames) * channels
        var samples = [Float](repeating: 0, count: sampleCount)

        let status: OSStatus = samples.withUnsafeMutableBytes { rawBuffer in
            let audioBuffer = AudioBuffer(
                mNumberChannels: UInt32(channels),
                mDataByteSize: UInt32(rawBuffer.count),
                mData: rawBuffer.baseAddress
            )
            var bufferList = AudioBufferList(
                mNumberBuffers: 1,
                mBuffers: audioBuffer
            )
            return AudioUnitRender(
                audioUnit,
                flags,
                timestamp,
                1, // AUHAL hardware input bus
                frames,
                &bufferList
            )
        }

        guard status == noErr else {
            return status
        }

        sink.writeInterleaved(samples)

        let remote = Self.normalizedLevel(
            samples,
            frames: Int(frames),
            channels: channels,
            channel: remoteChannelIndex
        )
        let mic = Self.normalizedLevel(
            samples,
            frames: Int(frames),
            channels: channels,
            channel: micChannelIndex
        )
        levelHandler(remote, mic)
        return noErr
    }

    private static func normalizedLevel(
        _ samples: [Float],
        frames: Int,
        channels: Int,
        channel: Int
    ) -> Double {
        guard channel >= 0, channel < channels, frames > 0 else { return 0 }
        var sum: Float = 0
        for frame in 0..<frames {
            let value = samples[(frame * channels) + channel]
            sum += value * value
        }
        let rms = sqrt(sum / Float(frames))
        let decibels = 20 * log10(max(rms, 0.000_001))
        return Double(min(max((decibels + 60) / 60, 0), 1))
    }

    private static func check(_ status: OSStatus, _ message: String) throws {
        guard status == noErr else {
            throw NSError(
                domain: NSOSStatusErrorDomain,
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey: "\(message) (OSStatus \(status))."]
            )
        }
    }

    private static func error(_ message: String) -> NSError {
        NSError(
            domain: "MeetingTranscriber.Recording",
            code: 20,
            userInfo: [NSLocalizedDescriptionKey: message]
        )
    }
}

nonisolated private func audioHALInputCallback(
    _ refCon: UnsafeMutableRawPointer,
    _ flags: UnsafeMutablePointer<AudioUnitRenderActionFlags>,
    _ timestamp: UnsafePointer<AudioTimeStamp>,
    _ busNumber: UInt32,
    _ frames: UInt32,
    _ data: UnsafeMutablePointer<AudioBufferList>?
) -> OSStatus {
    let capture = Unmanaged<AudioHALCapture>
        .fromOpaque(refCon)
        .takeUnretainedValue()
    return capture.render(
        flags: flags,
        timestamp: timestamp,
        frames: frames
    )
}

@MainActor
final class RecordingController: ObservableObject {
    nonisolated static let preferredInputName = "Transcribe"
    nonisolated static let remoteChannelIndex = 0
    nonisolated static let micChannelIndex = 4

    @Published var isMonitoring = false
    @Published var isRecording = false
    @Published var isFinalizing = false
    @Published var meetingName = ""
    @Published var inputName = preferredInputName
    @Published var inputChannels = 0
    @Published var sampleRate: Double = 0
    @Published var remoteLevel: Double = 0
    @Published var micLevel: Double = 0
    @Published var statusText = "Input monitor is off."
    @Published var errorMessage: String?
    @Published var recordingPath: String?
    @Published var rawCapturePath: String?
    @Published var elapsedSeconds = 0

    private var halCapture: AudioHALCapture?
    private let recordingSink = AudioRecordingSink()
    private var elapsedTask: Task<Void, Never>?
    private var pendingOutputURL: URL?

    var formatSummary: String {
        guard inputChannels > 0, sampleRate > 0 else {
            return ""
        }

        return "\(inputChannels) input channels · \(String(format: "%.1f", sampleRate / 1000)) kHz"
    }

    var hasExpectedChannelContract: Bool {
        inputChannels > Self.micChannelIndex
    }

    var formattedElapsedTime: String {
        let hours = elapsedSeconds / 3600
        let minutes = (elapsedSeconds % 3600) / 60
        let seconds = elapsedSeconds % 60

        if hours > 0 {
            return String(format: "%02d:%02d:%02d", hours, minutes, seconds)
        }
        return String(format: "%02d:%02d", minutes, seconds)
    }

    func startMonitoring() async {
        guard !isMonitoring else {
            return
        }

        errorMessage = nil

        guard await requestMicrophonePermission() else {
            errorMessage = "Microphone access is required to monitor the Transcribe input."
            statusText = "Microphone permission denied."
            return
        }

        do {
            let devices = try Self.inputDevices()
            guard let device = devices.first(where: {
                $0.name.caseInsensitiveCompare(Self.preferredInputName) == .orderedSame
            }) else {
                let names = devices.map(\.name).joined(separator: ", ")
                throw NSError(
                    domain: "MeetingTranscriber.Recording",
                    code: 1,
                    userInfo: [
                        NSLocalizedDescriptionKey:
                            "Input device ‘\(Self.preferredInputName)’ was not found. Available inputs: \(names)"
                    ]
                )
            }

            let capture = try AudioHALCapture(
                device: device,
                remoteChannelIndex: Self.remoteChannelIndex,
                micChannelIndex: Self.micChannelIndex,
                sink: recordingSink
            ) { [weak self] remote, mic in
                Task { @MainActor [weak self] in
                    self?.remoteLevel = remote
                    self?.micLevel = mic
                }
            }
            try capture.start()

            halCapture = capture
            inputName = device.name
            inputChannels = device.inputChannels
            sampleRate = device.sampleRate
            isMonitoring = true
            statusText = hasExpectedChannelContract
                ? "Ready to record Remote channel 1 and Mic channel 5."
                : "Input is active, but it does not expose the expected five-channel layout."
        } catch {
            stopMonitoring()
            errorMessage = error.localizedDescription
            statusText = "Unable to start input monitor."
        }
    }

    func stopMonitoring() {
        guard !isRecording, !isFinalizing else {
            return
        }

        halCapture?.stop()
        halCapture = nil
        isMonitoring = false
        remoteLevel = 0
        micLevel = 0

        if errorMessage == nil {
            statusText = "Input monitor is off."
        }
    }

    func startRecording(recordingsDirectory: String) async {
        guard !isRecording, !isFinalizing else {
            return
        }

        errorMessage = nil
        recordingPath = nil
        rawCapturePath = nil

        if !isMonitoring {
            await startMonitoring()
        }

        guard isMonitoring else {
            return
        }

        guard hasExpectedChannelContract else {
            errorMessage = "The selected input does not expose the expected five-channel Remote=c0 / Mic=c4 layout."
            return
        }

        let trimmedDirectory = recordingsDirectory.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedDirectory.isEmpty else {
            errorMessage = "The Recordings folder is not configured. Choose one in Preferences before recording."
            statusText = "Recording folder is not configured."
            return
        }

        do {
            let directoryURL = URL(
                fileURLWithPath: trimmedDirectory,
                isDirectory: true
            )
            try FileManager.default.createDirectory(
                at: directoryURL,
                withIntermediateDirectories: true
            )

            let stem = Self.recordingStem(for: meetingName)
            let outputURL = Self.uniqueURL(
                in: directoryURL,
                stem: stem,
                extension: "m4a"
            )
            let captureURL = FileManager.default.temporaryDirectory
                .appendingPathComponent("MeetingTranscriber_Recording_\(UUID().uuidString).f32le")

            try recordingSink.begin(url: captureURL)
            pendingOutputURL = outputURL
            rawCapturePath = captureURL.path
            elapsedSeconds = 0
            isRecording = true
            statusText = "Recording…"
            startElapsedTimer()
        } catch {
            pendingOutputURL = nil
            errorMessage = error.localizedDescription
            statusText = "Unable to start recording."
        }
    }

    func stopRecording() async -> String? {
        guard isRecording, let outputURL = pendingOutputURL else {
            return nil
        }

        let writeError = recordingSink.finish()
        isRecording = false
        stopElapsedTimer()
        pendingOutputURL = nil

        if let writeError {
            errorMessage = writeError
            statusText = "Recording stopped, but the raw audio could not be completed."
            return nil
        }

        guard let rawCapturePath else {
            errorMessage = "The raw recording path was lost before finalization."
            statusText = "Unable to finalize recording."
            return nil
        }

        isFinalizing = true
        statusText = "Finalizing recording…"
        defer { isFinalizing = false }

        do {
            let result = try await BackendService()
                .finalizeAudioRecording(
                    sourcePath: rawCapturePath,
                    outputPath: outputURL.path,
                    sampleRate: Int(sampleRate),
                    channels: inputChannels
                )

            guard result.compatible else {
                try? FileManager.default.removeItem(at: outputURL)
                errorMessage = result.message
                statusText = "Recording did not satisfy the existing transcription contract. The recoverable raw capture was kept."
                return nil
            }

            try? FileManager.default.removeItem(
                at: URL(fileURLWithPath: rawCapturePath)
            )
            self.rawCapturePath = nil
            recordingPath = outputURL.path
            meetingName = ""
            statusText = "Recording saved and added to the transcription queue."
            return outputURL.path
        } catch {
            try? FileManager.default.removeItem(at: outputURL)
            errorMessage = error.localizedDescription
            statusText = "Unable to finalize recording. The recoverable raw capture was kept."
            return nil
        }
    }

    func discardRecording() {
        guard isRecording else {
            return
        }

        _ = recordingSink.finish()
        isRecording = false
        stopElapsedTimer()
        pendingOutputURL = nil

        if let rawCapturePath = usableFilesystemPath(rawCapturePath) {
            try? FileManager.default.removeItem(
                at: URL(fileURLWithPath: rawCapturePath)
            )
        }
        rawCapturePath = nil
        elapsedSeconds = 0
        statusText = "Recording discarded. Ready to record."
    }

    func revealRecording() {
        guard let recordingPath = usableFilesystemPath(recordingPath) else {
            return
        }

        NSWorkspace.shared.activateFileViewerSelecting([
            URL(fileURLWithPath: recordingPath)
        ])
    }

    func revealRecoveryCapture() {
        guard let rawCapturePath = usableFilesystemPath(rawCapturePath) else {
            return
        }

        NSWorkspace.shared.activateFileViewerSelecting([
            URL(fileURLWithPath: rawCapturePath)
        ])
    }

    private func startElapsedTimer() {
        elapsedTask?.cancel()
        elapsedTask = Task { [weak self] in
            while !Task.isCancelled {
                do {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                } catch {
                    return
                }
                guard let self, self.isRecording else {
                    return
                }
                self.elapsedSeconds += 1
            }
        }
    }

    private func stopElapsedTimer() {
        elapsedTask?.cancel()
        elapsedTask = nil
    }

    private static func recordingStem(for requestedName: String) -> String {
        let trimmed = requestedName.trimmingCharacters(in: .whitespacesAndNewlines)
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH.mm.ss"
        let fallback = "Meeting \(formatter.string(from: Date()))"
        let source = trimmed.isEmpty ? fallback : trimmed

        let invalid = CharacterSet(charactersIn: "/:\\?%*|\"<>")
        let cleaned = source
            .components(separatedBy: invalid)
            .joined(separator: "-")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        return cleaned.isEmpty ? fallback : cleaned
    }

    private static func uniqueURL(
        in directory: URL,
        stem: String,
        extension fileExtension: String
    ) -> URL {
        var candidate = directory
            .appendingPathComponent(stem)
            .appendingPathExtension(fileExtension)
        var suffix = 2

        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = directory
                .appendingPathComponent("\(stem) \(suffix)")
                .appendingPathExtension(fileExtension)
            suffix += 1
        }

        return candidate
    }

    private func requestMicrophonePermission() async -> Bool {
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            return await AVAudioApplication.requestRecordPermission()
        @unknown default:
            return false
        }
    }

    private static func inputDevices() throws -> [AudioInputDeviceInfo] {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )

        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject),
            &address,
            0,
            nil,
            &dataSize
        )
        guard status == noErr else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }

        let count = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: count)

        status = deviceIDs.withUnsafeMutableBytes { buffer in
            AudioObjectGetPropertyData(
                AudioObjectID(kAudioObjectSystemObject),
                &address,
                0,
                nil,
                &dataSize,
                buffer.baseAddress!
            )
        }
        guard status == noErr else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }

        return deviceIDs.compactMap { id in
            guard let name = try? deviceName(id) else {
                return nil
            }
            let channels = (try? inputChannelCount(id)) ?? 0
            guard channels > 0 else {
                return nil
            }
            let rate = (try? nominalSampleRate(id)) ?? 0
            return AudioInputDeviceInfo(
                id: id,
                name: name,
                inputChannels: channels,
                sampleRate: rate
            )
        }
    }

    private static func deviceName(
        _ id: AudioDeviceID
    ) throws -> String {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioObjectPropertyName,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var name: CFString? = nil
        var size = UInt32(MemoryLayout<CFString?>.size)
        let status = withUnsafeMutablePointer(to: &name) { namePointer in
            AudioObjectGetPropertyData(
                id,
                &address,
                0,
                nil,
                &size,
                namePointer
            )
        }
        guard status == noErr, let name else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
        return name as String
    }

    private static func inputChannelCount(
        _ id: AudioDeviceID
    ) throws -> Int {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyStreamConfiguration,
            mScope: kAudioDevicePropertyScopeInput,
            mElement: kAudioObjectPropertyElementMain
        )
        var size: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(
            id,
            &address,
            0,
            nil,
            &size
        )
        guard status == noErr else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }

        let pointer = UnsafeMutableRawPointer.allocate(
            byteCount: Int(size),
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { pointer.deallocate() }

        status = AudioObjectGetPropertyData(
            id,
            &address,
            0,
            nil,
            &size,
            pointer
        )
        guard status == noErr else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }

        let list = pointer.assumingMemoryBound(to: AudioBufferList.self)
        let buffers = UnsafeMutableAudioBufferListPointer(list)
        return buffers.reduce(0) { partial, buffer in
            partial + Int(buffer.mNumberChannels)
        }
    }

    private static func nominalSampleRate(
        _ id: AudioDeviceID
    ) throws -> Double {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyNominalSampleRate,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var rate: Double = 0
        var size = UInt32(MemoryLayout<Double>.size)
        let status = AudioObjectGetPropertyData(
            id,
            &address,
            0,
            nil,
            &size,
            &rate
        )
        guard status == noErr else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
        return rate
    }
}
