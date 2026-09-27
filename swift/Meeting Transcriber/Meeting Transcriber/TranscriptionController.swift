import Combine
import Foundation
import SwiftUI

enum QueueItemStatus:
    Sendable
{
    case waiting
    case transcribing
    case readyToPublish
    case publishing
    case published
    case failed
    case publishFailed
    case canceled

    var displayName: String {
        switch self {
        case .waiting:
            return "Waiting"
        case .transcribing:
            return "Transcribing"
        case .readyToPublish:
            return "Ready to Publish"
        case .publishing:
            return "Publishing"
        case .published:
            return "Published"
        case .failed:
            return "Failed"
        case .publishFailed:
            return "Publish Failed"
        case .canceled:
            return "Canceled"
        }
    }
}

struct TranscribeQueueItem:
    Identifiable,
    Sendable
{
    let id: UUID
    let sourcePath: String
    let sourceName: String
    var status: QueueItemStatus
    var runDir: String?
    var error: String?

    init(sourcePath: String) {
        self.id = UUID()
        self.sourcePath = sourcePath
        self.sourceName = URL(
            fileURLWithPath: sourcePath
        ).lastPathComponent
        self.status = .waiting
    }
}

@MainActor
final class TranscriptionController:
    ObservableObject
{
    @Published var queue:
        [TranscribeQueueItem] = []
    @Published var selectedItemID:
        TranscribeQueueItem.ID?
    @Published var autoPublish = false
    @Published var isRunning = false
    @Published var isCanceling = false
    @Published var currentSource:
        String?
    @Published var progressValue:
        Double = 0
    @Published var progressMessage =
        "Ready for intake."
    @Published var currentStage = "Idle"
    @Published var elapsedSeconds = 0
    @Published var recordingsDirectory =
        ""
    @Published var queueResultMessage:
        String?
    @Published var queueErrorMessage:
        String?

    private let service =
        TranscriptionService()

    private var elapsedTask:
        Task<Void, Never>?

    private var queueTask:
        Task<Void, Never>?

    var waitingCount: Int {
        queue.filter {
            $0.status == .waiting
        }.count
    }

    var hasCompleted: Bool {
        queue.contains {
            $0.status == .published
            || $0.status == .readyToPublish
            || $0.status == .canceled
        }
    }

    var hasFailed: Bool {
        queue.contains {
            $0.status == .failed
            || $0.status == .publishFailed
        }
    }

    var selectedItemIndex: Int? {
        guard let selectedItemID else {
            return nil
        }

        return queue.firstIndex {
            $0.id == selectedItemID
        }
    }

    var formattedElapsedTime: String {
        let minutes = elapsedSeconds / 60
        let seconds = elapsedSeconds % 60

        return String(
            format: "%02d:%02d",
            minutes,
            seconds
        )
    }

    func loadRecordingsDirectory() async {
        do {
            let preferences =
                try await BackendService()
                    .loadPreferences()

            recordingsDirectory =
                preferences
                    .settings
                    .recordingsDir
        } catch {
            // Optional convenience only.
        }
    }

    func addRecordingPaths(
        _ paths: [String]
    ) {
        let existing =
            Set(
                queue.map {
                    URL(
                        fileURLWithPath:
                            $0.sourcePath
                    )
                    .standardizedFileURL
                    .path
                }
            )

        var seen = existing

        for rawPath in paths {
            let path =
                URL(
                    fileURLWithPath:
                        rawPath
                )
                .standardizedFileURL
                .path

            guard !seen.contains(path)
            else {
                continue
            }

            queue.append(
                TranscribeQueueItem(
                    sourcePath: path
                )
            )

            seen.insert(path)
        }

        if !queue.isEmpty {
            progressMessage =
                "Recordings queued. Ready to start."
            currentStage = "Ready"
        }
    }

    func removeSelected() {
        guard
            !isRunning,
            let index = selectedItemIndex
        else {
            return
        }

        queue.remove(at: index)
        selectedItemID = nil
    }

    func removeMeetingReference(
        run: String,
        sourcePath: String?
    ) {
        guard !isRunning else {
            return
        }

        let normalizedSource = usableFilesystemPath(sourcePath).map {
            URL(fileURLWithPath: $0)
                .standardizedFileURL
                .path
        }

        queue.removeAll { item in
            let runMatches: Bool
            if let runDir = item.runDir {
                runMatches = URL(
                    fileURLWithPath: runDir
                ).lastPathComponent == run
            } else {
                runMatches = false
            }

            let sourceMatches: Bool
            if let normalizedSource {
                sourceMatches = URL(
                    fileURLWithPath: item.sourcePath
                )
                .standardizedFileURL
                .path == normalizedSource
            } else {
                sourceMatches = false
            }

            return runMatches || sourceMatches
        }

        if let selectedItemID,
           !queue.contains(where: { $0.id == selectedItemID }) {
            self.selectedItemID = nil
        }
    }

    func clearCompleted() {
        guard !isRunning else {
            return
        }

        queue.removeAll {
            $0.status == .published
            || $0.status == .readyToPublish
            || $0.status == .canceled
        }

        selectedItemID = nil
    }

    func retryFailed() {
        guard !isRunning else {
            return
        }

        for index in queue.indices {
            switch queue[index].status {
            case .failed:
                queue[index].status =
                    .waiting
                queue[index].runDir =
                    nil
                queue[index].error =
                    nil

            case .publishFailed:
                queue[index].status =
                    .readyToPublish
                queue[index].error =
                    nil

            default:
                break
            }
        }

        progressMessage =
            "Failed items reset and ready to retry."
    }

    func clearQueue() {
        guard !isRunning else {
            return
        }

        queue.removeAll()
        selectedItemID = nil
        currentSource = nil
        progressValue = 0
        progressMessage =
            "Ready for intake."
        currentStage = "Idle"
        elapsedSeconds = 0
    }

    func startQueue() {
        guard
            !isRunning,
            waitingCount > 0
        else {
            return
        }

        queueTask = Task {
            await runQueue()
        }
    }

    func cancelCurrent() async {
        guard
            isRunning,
            !isCanceling
        else {
            return
        }

        isCanceling = true
        currentStage = "Canceling…"
        progressMessage =
            "Stopping the current transcription…"

        service.cancelActiveProcess()

        if let currentSource,
           let index = queue.firstIndex(
                where: {
                    $0.sourcePath
                        == currentSource
                }
           ) {
            queue[index].status =
                .canceled
        }

        queueTask?.cancel()
        stopElapsedTimer()

        isRunning = false
        isCanceling = false
        currentSource = nil
        progressValue = 0
        currentStage = "Canceled"
        progressMessage =
            "Current transcription canceled. Remaining recordings are still queued."
    }

    private func runQueue() async {
        isRunning = true
        isCanceling = false
        queueErrorMessage = nil
        queueResultMessage = nil
        startElapsedTimer()

        let useAutoPublish =
            autoPublish

        var succeeded = 0
        var published = 0
        var failures = 0
        var publishFailures = 0

        defer {
            stopElapsedTimer()

            if !isCanceling {
                isRunning = false
                currentSource = nil
            }
        }

        for index in queue.indices {
            if Task.isCancelled {
                break
            }

            guard queue[index].status
                == .waiting
            else {
                continue
            }

            let itemID =
                queue[index].id
            let sourcePath =
                queue[index].sourcePath

            currentSource = sourcePath
            progressValue = 0
            queue[index].status =
                .transcribing
            currentStage = "Transcribing"

            do {
                let result =
                    try await service
                        .processRecording(
                            sourcePath:
                                sourcePath,
                            autoPublish:
                                useAutoPublish
                        ) { event in
                            Task {
                                @MainActor in
                                self.handleEvent(
                                    event,
                                    for:
                                        itemID
                                )
                            }
                        }

                if Task.isCancelled {
                    break
                }

                guard
                    let currentIndex =
                        queue.firstIndex(
                            where: {
                                $0.id == itemID
                            }
                        )
                else {
                    continue
                }

                queue[currentIndex].runDir =
                    result.runDir
                queue[currentIndex].error =
                    result.error

                switch result.status {
                case "Published":
                    queue[currentIndex].status =
                        .published
                    succeeded += 1
                    published += 1

                case "Ready to Publish":
                    queue[currentIndex].status =
                        .readyToPublish
                    succeeded += 1

                case "Publish Failed":
                    queue[currentIndex].status =
                        .publishFailed
                    succeeded += 1
                    publishFailures += 1

                default:
                    queue[currentIndex].status =
                        .failed
                    failures += 1
                }

            } catch {
                if Task.isCancelled {
                    break
                }

                guard
                    let currentIndex =
                        queue.firstIndex(
                            where: {
                                $0.id == itemID
                            }
                        )
                else {
                    continue
                }

                queue[currentIndex].status =
                    .failed
                queue[currentIndex].error =
                    error.localizedDescription
                failures += 1
            }
        }

        guard !Task.isCancelled
        else {
            return
        }

        isRunning = false
        currentSource = nil
        progressValue = 100
        currentStage = "Queue complete"

        if useAutoPublish {
            progressMessage =
                "Queue complete: \(succeeded) transcribed, \(published) published, \(failures) transcription failure(s), \(publishFailures) publish failure(s)."
        } else {
            progressMessage =
                "Queue complete: \(succeeded) succeeded, \(failures) failed. Successful meetings are Unpublished and ready in Meetings."
        }

        queueResultMessage =
            progressMessage
    }

    private func handleEvent(
        _ event:
            TranscriptionProgressEvent,
        for itemID:
            TranscribeQueueItem.ID
    ) {
        guard
            let index =
                queue.firstIndex(
                    where: {
                        $0.id == itemID
                    }
                )
        else {
            return
        }

        if let percent =
            event.percent {
            progressValue =
                Double(percent)
        }

        if let message =
            event.message {
            progressMessage =
                message
        }

        if let runDir =
            event.runDir {
            queue[index].runDir =
                runDir
        }

        if let error =
            event.error {
            queue[index].error =
                error
        }

        switch event.stage {
        case "publish":
            currentStage = "Publishing"
            queue[index].status =
                event.type
                    == "publish_failed"
                    ? .publishFailed
                    : .publishing

        case "transcribe":
            currentStage = "Transcribing"

        default:
            break
        }
    }

    private func startElapsedTimer() {
        elapsedTask?.cancel()
        elapsedSeconds = 0

        elapsedTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(
                    for: .seconds(1)
                )

                if Task.isCancelled {
                    break
                }

                elapsedSeconds += 1
            }
        }
    }

    private func stopElapsedTimer() {
        elapsedTask?.cancel()
        elapsedTask = nil
    }
}
