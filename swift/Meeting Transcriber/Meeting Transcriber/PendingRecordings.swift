import Foundation

/// A recording whose raw capture has not yet become a finished m4a.
/// It is written next to the raw capture when recording starts and removed
/// once the m4a is safe, so a crash or force-quit at any point leaves
/// enough behind to finish the job the next time the app opens.
nonisolated struct PendingRecording: Codable, Sendable {
    var capturePath: String
    var outputPath: String
    var sampleRate: Int
    var channels: Int
    var startedAt: Double
    var attempts: Int = 0
}

nonisolated enum PendingRecordingStore {
    /// Raw captures are kept here instead of the system temp folder,
    /// which macOS may clear while a capture is still needed.
    static var directory: URL {
        let base: URL = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first ?? FileManager.default.temporaryDirectory

        return base
            .appendingPathComponent("Meeting Transcriber", isDirectory: true)
            .appendingPathComponent("PendingRecordings", isDirectory: true)
    }

    static let maxAttempts = 3

    static func sidecarURL(forCapturePath path: String) -> URL {
        URL(fileURLWithPath: path + ".json")
    }

    static func prepareDirectory() throws {
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
    }

    static func write(_ recording: PendingRecording) throws {
        let data = try JSONEncoder().encode(recording)
        try data.write(
            to: sidecarURL(forCapturePath: recording.capturePath),
            options: .atomic
        )
    }

    /// Removes the raw capture and its sidecar.
    static func remove(capturePath: String) {
        try? FileManager.default.removeItem(
            at: URL(fileURLWithPath: capturePath)
        )
        try? FileManager.default.removeItem(
            at: sidecarURL(forCapturePath: capturePath)
        )
    }

    static func all() -> [PendingRecording] {
        let files: [URL] = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: nil
        )) ?? []

        var found: [PendingRecording] = []

        for file in files where file.pathExtension == "json" {
            if let data = try? Data(contentsOf: file),
               let recording = try? JSONDecoder().decode(
                   PendingRecording.self,
                   from: data
               ) {
                found.append(recording)
            }
        }

        return found.sorted { $0.startedAt < $1.startedAt }
    }

    static func fileSize(atPath path: String) -> Int {
        let attributes = try? FileManager.default
            .attributesOfItem(atPath: path)
        return (attributes?[.size] as? NSNumber)?.intValue ?? 0
    }
}
