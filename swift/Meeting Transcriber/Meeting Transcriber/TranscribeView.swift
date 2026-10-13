import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct TranscribeView: View {
    @EnvironmentObject
    private var controller:
        TranscriptionController

    @EnvironmentObject
    private var recordingController:
        RecordingController

    @State private var showCancelConfirmation =
        false

    @State private var showDiscardRecordingConfirmation =
        false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            recordingPane
            Divider()
            queuePane
            Divider()
            workflowPane
        }
        .navigationTitle("Transcribe")
        .task {
            if controller
                .recordingsDirectory
                .isEmpty {
                await controller
                    .loadRecordingsDirectory()
            }

            if !recordingController.isMonitoring {
                await recordingController.startMonitoring()
            }
        }
        .alert(
            "Cancel Current Transcription?",
            isPresented:
                $showCancelConfirmation
        ) {
            Button(
                "Keep Running",
                role: .cancel
            ) {}

            Button(
                "Cancel Transcription",
                role: .destructive
            ) {
                Task {
                    await controller
                        .cancelCurrent()
                }
            }
        } message: {
            Text(
                "The current transcription will be stopped. Remaining queued recordings will stay in the queue."
            )
        }
        .alert(
            "Transcription Queue Complete",
            isPresented: Binding(
                get: {
                    controller
                        .queueResultMessage
                        != nil
                },
                set: { showing in
                    if !showing {
                        controller
                            .queueResultMessage =
                            nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(
                controller
                    .queueResultMessage
                    ?? ""
            )
        }
        .confirmationDialog(
            "Discard Current Recording?",
            isPresented: $showDiscardRecordingConfirmation,
            titleVisibility: .visible
        ) {
            Button("Keep Recording", role: .cancel) {}
            Button("Discard Recording", role: .destructive) {
                recordingController.discardRecording()
            }
        } message: {
            Text("The current recording will be permanently discarded. The input monitor will remain active.")
        }
    }

    private var recordingPane: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center, spacing: 12) {
                HStack(spacing: 9) {
                    Image(systemName: recordingController.isRecording ? "record.circle.fill" : "mic.circle.fill")
                        .font(.title2)
                        .foregroundStyle(recordingController.isRecording ? .red : .blue)

                    VStack(alignment: .leading, spacing: 3) {
                        Text(recordingController.isRecording ? "Recording…" : "Record Meeting")
                            .font(.headline)

                        Text(
                            recordingController.isRecording
                                ? "Capturing Remote channel 1 and Mic channel 5."
                                : "Record both audio sources here. Finished recordings are added to the transcription queue."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }

                Spacer()

                if recordingController.isFinalizing {
                    HStack(spacing: 8) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Finalizing…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else if recordingController.isRecording {
                    HStack(spacing: 10) {
                        HStack(spacing: 7) {
                            Circle()
                                .fill(.red)
                                .frame(width: 9, height: 9)
                            Text(recordingController.formattedElapsedTime)
                                .font(.system(.body, design: .monospaced))
                                .fontWeight(.semibold)
                        }

                        Button("Discard…", role: .destructive) {
                            showDiscardRecordingConfirmation = true
                        }
                        .buttonStyle(.bordered)

                        Button {
                            Task {
                                if let path = await recordingController.stopRecording() {
                                    controller.addRecordingPaths([path])
                                }
                            }
                        } label: {
                            Label("Stop Recording", systemImage: "stop.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.red)
                    }
                } else {
                    Button {
                        Task {
                            if !recordingController.isMonitoring {
                                await recordingController.startMonitoring()
                            }
                            if controller.recordingsDirectory.isEmpty {
                                await controller.loadRecordingsDirectory()
                            }
                            await recordingController.startRecording(
                                recordingsDirectory: controller.recordingsDirectory
                            )
                        }
                    } label: {
                        Label("Record", systemImage: "record.circle")
                            .fontWeight(.semibold)
                            .padding(.horizontal, 8)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(
                        recordingController.isMonitoring
                        && !recordingController.hasExpectedChannelContract
                    )
                }
            }

            HStack(spacing: 12) {
                Text("Meeting name")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(width: 86, alignment: .leading)

                TextField(
                    "Optional — a timestamped name is used if blank",
                    text: $recordingController.meetingName
                )
                .textFieldStyle(.roundedBorder)
                .disabled(
                    recordingController.isRecording
                    || recordingController.isFinalizing
                )
            }

            HStack(alignment: .center, spacing: 24) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 7) {
                        Circle()
                            .fill(recordingController.isMonitoring ? .green : .secondary)
                            .frame(width: 7, height: 7)

                        Text(recordingController.isMonitoring ? "Ready" : "Input unavailable")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Text(recordingController.inputName.isEmpty ? "Transcribe" : recordingController.inputName)
                        .fontWeight(.medium)

                    if !recordingController.formatSummary.isEmpty {
                        Text(recordingController.formatSummary)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: 180, alignment: .leading)

                VStack(spacing: 9) {
                    audioMeter(
                        label: "Remote · channel 1",
                        value: recordingController.remoteLevel
                    )

                    audioMeter(
                        label: "Mic · channel 5",
                        value: recordingController.micLevel
                    )
                }

                if !recordingController.isMonitoring && !recordingController.isRecording {
                    Button {
                        Task {
                            await recordingController.startMonitoring()
                        }
                    } label: {
                        Label("Reconnect Input", systemImage: "waveform")
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let path = usableFilesystemPath(recordingController.recordingPath) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Label(
                        URL(fileURLWithPath: path).lastPathComponent,
                        systemImage: "checkmark.circle.fill"
                    )
                    .font(.caption)
                    .foregroundStyle(.green)

                    Text("Added to transcription queue")
                        .font(.caption2)
                        .foregroundStyle(.secondary)

                    Spacer()

                    Button("Reveal in Finder") {
                        recordingController.revealRecording()
                    }
                    .buttonStyle(.bordered)
                }
            }

            if let error = recordingController.errorMessage {
                HStack(alignment: .top, spacing: 10) {
                    Label("Recording error", systemImage: "exclamationmark.triangle.fill")
                        .font(.caption)
                        .fontWeight(.semibold)

                    Text(error)
                        .font(.caption2)
                        .textSelection(.enabled)

                    Spacer()

                    if usableFilesystemPath(recordingController.rawCapturePath) != nil {
                        Button("Reveal Recovery File") {
                            recordingController.revealRecoveryCapture()
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .foregroundStyle(.orange)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
        .background {
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(recordingController.isRecording ? Color.red.opacity(0.045) : Color(nsColor: .controlBackgroundColor))
                .overlay {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .stroke(
                            recordingController.isRecording ? Color.red.opacity(0.22) : Color.secondary.opacity(0.12),
                            lineWidth: 1
                        )
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
        }
    }

    private func audioMeter(
        label: String,
        value: Double
    ) -> some View {
        HStack(spacing: 10) {
            Text(label)
                .font(.caption)
                .frame(width: 125, alignment: .leading)

            ProgressView(value: value)
                .progressViewStyle(.linear)

            Text(value > 0.02 ? "Signal" : "Quiet")
                .font(.caption2)
                .foregroundStyle(
                    value > 0.02 ? .primary : .secondary
                )
                .frame(width: 42, alignment: .trailing)
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text("Transcribe")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text(
                    "Record a meeting or add an existing recording. Meetings are processed sequentially."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
    }

    private var queuePane: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Transcription Queue")
                        .font(.headline)

                    Text("Recordings are processed sequentially through transcription and analysis.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button {
                    chooseRecordings()
                } label: {
                    Label(
                        "Add Existing Recording…",
                        systemImage: "plus.circle"
                    )
                }
                .buttonStyle(.bordered)
                .disabled(controller.isRunning)

                if controller.isRunning {
                    Button(role: .destructive) {
                        showCancelConfirmation = true
                    } label: {
                        Label(
                            controller.isCanceling ? "Canceling…" : "Cancel Current…",
                            systemImage: "xmark.circle"
                        )
                    }
                    .disabled(controller.isCanceling)
                }

                Button {
                    controller.startQueue()
                } label: {
                    Label(
                        controller.isRunning ? "Queue Running…" : "Start Queue",
                        systemImage: controller.isRunning ? "waveform" : "play.fill"
                    )
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    controller.isRunning
                    || controller.waitingCount == 0
                )

                Toggle(
                    "Auto Publish & Archive",
                    isOn: $controller.autoPublish
                )
                .toggleStyle(.switch)
                .controlSize(.small)
                .disabled(controller.isRunning)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 12)

            if controller.queue.isEmpty {
                ContentUnavailableView(
                    "No recordings queued",
                    systemImage:
                        "waveform.badge.plus",
                    description: Text(
                        "Record a meeting above or add an existing M4A recording to begin."
                    )
                )
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )
            } else {
                List(
                    controller.queue,
                    selection:
                        $controller
                            .selectedItemID
                ) { item in
                    queueRow(item)
                        .tag(item.id)
                }
                .listStyle(.inset)
            }

            Divider()

            HStack(spacing: 10) {
                Button {
                    controller
                        .removeSelected()
                } label: {
                    Label(
                        "Remove Selected",
                        systemImage:
                            "minus.circle"
                    )
                }
                .disabled(
                    controller.isRunning
                    || controller
                        .selectedItemIndex
                        == nil
                )

                Button {
                    controller
                        .clearCompleted()
                } label: {
                    Label(
                        "Clear Completed",
                        systemImage:
                            "checkmark.circle"
                    )
                }
                .disabled(
                    controller.isRunning
                    || !controller
                        .hasCompleted
                )

                Button {
                    controller
                        .retryFailed()
                } label: {
                    Label(
                        "Retry Failed",
                        systemImage:
                            "arrow.clockwise"
                    )
                }
                .disabled(
                    controller.isRunning
                    || !controller
                        .hasFailed
                )

                Spacer()

                Button(role: .destructive) {
                    controller.clearQueue()
                } label: {
                    Label(
                        "Clear Queue",
                        systemImage:
                            "trash"
                    )
                }
                .disabled(
                    controller.isRunning
                    || controller
                        .queue.isEmpty
                )
            }
            .buttonStyle(.bordered)
            .padding(.horizontal, 24)
            .padding(.vertical, 10)
        }
    }

    private var workflowPane: some View {
        VStack(
            alignment: .leading,
            spacing: 10
        ) {
            HStack {
                VStack(
                    alignment: .leading,
                    spacing: 3
                ) {
                    Text("Workflow")
                        .font(.headline)

                    Text(
                        controller.currentSource
                            .map {
                                "Current: "
                                + URL(
                                    fileURLWithPath:
                                        $0
                                )
                                .lastPathComponent
                            }
                            ?? "Current: None"
                    )
                    .font(.caption)
                    .foregroundStyle(
                        .secondary
                    )
                }

                Spacer()

                VStack(
                    alignment: .trailing,
                    spacing: 2
                ) {
                    Text(
                        controller
                            .currentStage
                    )
                    .font(.caption)
                    .foregroundStyle(
                        .secondary
                    )

                    Text(
                        "Elapsed: "
                        + controller
                            .formattedElapsedTime
                    )
                    .font(
                        .caption
                            .monospacedDigit()
                    )
                    .foregroundStyle(
                        .secondary
                    )
                }
            }

            ProgressView(
                value:
                    controller
                        .progressValue,
                total: 100
            )

            Text(
                controller
                    .progressMessage
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    private func queueRow(
        _ item: TranscribeQueueItem
    ) -> some View {
        HStack(spacing: 12) {
            Image(
                systemName:
                    statusIcon(
                        item.status
                    )
            )

            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text(item.sourceName)
                    .fontWeight(.medium)

                if let error = item.error,
                   !error.isEmpty {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .lineLimit(2)
                } else if let runDir =
                    item.runDir {
                    Text(
                        URL(
                            fileURLWithPath:
                                runDir
                        )
                        .lastPathComponent
                    )
                    .font(.caption)
                    .foregroundStyle(
                        .secondary
                    )
                }
            }

            Spacer()

            Text(item.status.displayName)
                .font(.caption)
                .foregroundStyle(
                    .secondary
                )
        }
        .padding(.vertical, 4)
    }

    private func statusIcon(
        _ status: QueueItemStatus
    ) -> String {
        switch status {
        case .waiting:
            return "clock"
        case .transcribing:
            return "waveform"
        case .readyToPublish:
            return "tray"
        case .publishing:
            return "tray.and.arrow.up"
        case .published:
            return "checkmark.circle.fill"
        case .failed,
             .publishFailed:
            return "exclamationmark.triangle.fill"
        case .canceled:
            return "xmark.circle.fill"
        }
    }

    @MainActor
    private func chooseRecordings() {
        let panel = NSOpenPanel()

        panel.title =
            "Add Recordings"
        panel.prompt = "Add"
        panel.allowsMultipleSelection =
            true
        panel.canChooseDirectories =
            false
        panel.canChooseFiles =
            true

        if !controller
            .recordingsDirectory
            .isEmpty {
            let url = URL(
                fileURLWithPath:
                    controller
                        .recordingsDirectory,
                isDirectory: true
            )

            if FileManager.default
                .fileExists(
                    atPath:
                        url.path
                ) {
                panel.directoryURL = url
            }
        }

        if let m4a = UTType(
            filenameExtension: "m4a"
        ) {
            panel.allowedContentTypes =
                [m4a]
        }

        guard panel.runModal() == .OK
        else {
            return
        }

        controller.addRecordingPaths(
            panel.urls.map(\.path)
        )
    }
}
