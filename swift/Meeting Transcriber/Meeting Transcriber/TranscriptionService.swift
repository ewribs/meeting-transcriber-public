import Darwin
import Foundation

nonisolated struct TranscriptionProgressEvent:
    Decodable,
    Sendable
{
    let type: String
    let stage: String?
    let message: String?
    let percent: Int?
    let runDir: String?
    let status: String?
    let archivedPath: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case type
        case stage
        case message
        case percent
        case runDir = "run_dir"
        case status
        case archivedPath =
            "archived_path"
        case error
    }
}

nonisolated struct TranscriptionRunResult:
    Sendable
{
    let status: String
    let runDir: String?
    let archivedPath: String?
    let error: String?
}

final class TranscriptionService:
    @unchecked Sendable
{
    private let projectDirectory: URL

    nonisolated
    private let processLock = NSLock()

    nonisolated(unsafe)
    private var activeProcess: Process?

    init() {
        let username = NSUserName()

        self.projectDirectory = URL(
            fileURLWithPath:
                "/Users/\(username)/Projects/meeting-transcriber",
            isDirectory: true
        )
    }

    nonisolated func cancelActiveProcess() {
        processLock.lock()
        let process = activeProcess
        processLock.unlock()

        guard let process else {
            return
        }

        if process.isRunning {
            process.terminate()

            DispatchQueue.global(
                qos: .userInitiated
            ).asyncAfter(
                deadline: .now() + 1.0
            ) {
                if process.isRunning {
                    kill(
                        process.processIdentifier,
                        SIGKILL
                    )
                }
            }
        }
    }

    nonisolated func processRecording(
        sourcePath: String,
        autoPublish: Bool,
        onEvent:
            @escaping @Sendable
            (TranscriptionProgressEvent)
            -> Void
    ) async throws -> TranscriptionRunResult {
        var arguments = [
            "process",
            sourcePath,
        ]

        if autoPublish {
            arguments.append(
                "--auto-publish"
            )
        }

        return try await runStreamingBridge(
            arguments: arguments,
            onEvent: onEvent
        )
    }

    nonisolated func publishExistingRun(
        runDir: String,
        onEvent:
            @escaping @Sendable
            (TranscriptionProgressEvent)
            -> Void
    ) async throws -> TranscriptionRunResult {
        try await runStreamingBridge(
            arguments: [
                "publish",
                runDir,
            ],
            onEvent: onEvent
        )
    }

    private nonisolated func runStreamingBridge(
        arguments: [String],
        onEvent:
            @escaping @Sendable
            (TranscriptionProgressEvent)
            -> Void
    ) async throws -> TranscriptionRunResult {
        try await Task.detached(
            priority: .userInitiated
        ) { [self] in
            try self.runStreamingBridgeSynchronously(
                arguments: arguments,
                onEvent: onEvent
            )
        }.value
    }

    private nonisolated func runStreamingBridgeSynchronously(
        arguments: [String],
        onEvent:
            @escaping @Sendable
            (TranscriptionProgressEvent)
            -> Void
    ) throws -> TranscriptionRunResult {
        let fileManager =
            FileManager.default

        let pythonURL =
            projectDirectory
                .appendingPathComponent(
                    ".venv/bin/python"
                )

        let bridgeURL =
            projectDirectory
                .appendingPathComponent(
                    "transcribe_bridge.py"
                )

        guard
            fileManager.fileExists(
                atPath:
                    projectDirectory.path
            )
        else {
            throw BackendError
                .projectNotFound(
                    projectDirectory.path
                )
        }

        guard
            fileManager.isExecutableFile(
                atPath:
                    pythonURL.path
            )
        else {
            throw BackendError
                .pythonNotFound(
                    pythonURL.path
                )
        }

        guard
            fileManager.fileExists(
                atPath:
                    bridgeURL.path
            )
        else {
            throw BackendError
                .bridgeNotFound(
                    bridgeURL.path
                )
        }

        let process = Process()

        process.executableURL =
            pythonURL

        process.arguments = [
            bridgeURL.path
        ] + arguments

        process.currentDirectoryURL =
            projectDirectory

        var environment =
            ProcessInfo.processInfo.environment

        let preferredPaths = [
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]

        let existingPath =
            environment["PATH"]
            ?? ""

        let mergedPath =
            (
                preferredPaths
                + existingPath
                    .split(
                        separator: ":"
                    )
                    .map(String.init)
            )
            .reduce(
                into: [String]()
            ) {
                paths,
                candidate in

                if !candidate.isEmpty,
                   !paths.contains(
                        candidate
                   ) {
                    paths.append(
                        candidate
                    )
                }
            }
            .joined(
                separator: ":"
            )

        environment["PATH"] =
            mergedPath

        process.environment =
            environment

        let stdout = Pipe()
        let stderr = Pipe()

        process.standardOutput =
            stdout
        process.standardError =
            stderr

        do {
            try process.run()
        } catch {
            throw BackendError
                .launchFailed(
                    error.localizedDescription
                )
        }

        processLock.lock()
        activeProcess = process
        processLock.unlock()

        defer {
            processLock.lock()

            if activeProcess === process {
                activeProcess = nil
            }

            processLock.unlock()
        }

        let decoder =
            JSONDecoder()

        var buffer = Data()
        var lastEvent:
            TranscriptionProgressEvent?

        while true {
            let chunk =
                stdout
                    .fileHandleForReading
                    .availableData

            if chunk.isEmpty {
                break
            }

            buffer.append(chunk)

            while let newlineIndex =
                buffer.firstIndex(
                    of: 0x0A
                ) {
                let lineData =
                    buffer[
                        buffer.startIndex
                        ..< newlineIndex
                    ]

                buffer.removeSubrange(
                    buffer.startIndex
                    ... newlineIndex
                )

                guard
                    !lineData.isEmpty
                else {
                    continue
                }

                let event =
                    try decoder.decode(
                        TranscriptionProgressEvent.self,
                        from: Data(lineData)
                    )

                lastEvent = event
                onEvent(event)
            }
        }

        if !buffer.isEmpty {
            let event =
                try decoder.decode(
                    TranscriptionProgressEvent.self,
                    from: buffer
                )

            lastEvent = event
            onEvent(event)
        }

        let stderrData =
            stderr
                .fileHandleForReading
                .readDataToEndOfFile()

        process.waitUntilExit()

        if process.terminationStatus != 0 {
            let stderrText =
                String(
                    data: stderrData,
                    encoding: .utf8
                )
                ?? "Unknown transcription backend error"

            throw BackendError.backendFailed(
                process.terminationStatus,
                stderrText
            )
        }

        guard let lastEvent else {
            throw BackendError.invalidOutput(
                "Transcription backend returned no events."
            )
        }

        return TranscriptionRunResult(
            status:
                lastEvent.status
                ?? "Unknown",
            runDir:
                lastEvent.runDir,
            archivedPath:
                lastEvent.archivedPath,
            error:
                lastEvent.error
        )
    }
}
