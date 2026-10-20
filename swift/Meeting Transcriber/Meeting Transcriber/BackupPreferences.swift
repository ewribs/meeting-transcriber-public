import SwiftUI

/// What the backup tool reports about itself.
nonisolated struct BackupStatus: Decodable, Sendable, Equatable {
    let lastBackup: String
    let lastFileCount: Int
    let snapshotCount: Int
    let mirrorState: String
    let mirrorMessage: String
    let mirrorSnapshotCount: Int

    enum CodingKeys: String, CodingKey {
        case lastBackup = "last_backup"
        case lastFileCount = "last_file_count"
        case snapshotCount = "snapshot_count"
        case mirrorState = "mirror_state"
        case mirrorMessage = "mirror_message"
        case mirrorSnapshotCount = "mirror_snapshot_count"
    }

    static let empty = BackupStatus(
        lastBackup: "",
        lastFileCount: 0,
        snapshotCount: 0,
        mirrorState: "off",
        mirrorMessage: "Not set",
        mirrorSnapshotCount: 0
    )
}

nonisolated struct BackupSettings: Decodable, Sendable {
    let mirrorDir: String
    let keepLocal: Int
    let keepMirror: Int

    enum CodingKeys: String, CodingKey {
        case mirrorDir = "mirror_dir"
        case keepLocal = "keep_local"
        case keepMirror = "keep_mirror"
    }
}

nonisolated struct BackupSettingsResponse: Decodable, Sendable {
    let settings: BackupSettings
    let status: BackupStatus
}

nonisolated struct BackupMirrorResult: Decodable, Sendable {
    let status: String
    let reason: String
}

nonisolated struct BackupRunResponse: Decodable, Sendable {
    let status: String
    let reason: String
    let mirror: BackupMirrorResult?
}

/// The "Backups" section of the Storage tab. The values are edited here
/// and saved with the rest of the Storage settings.
struct BackupSettingsSection: View {
    @Binding var mirrorDir: String
    @Binding var keepLocal: Int
    @Binding var keepMirror: Int

    let status: BackupStatus
    let message: String?
    let isBusy: Bool
    let chooseFolder: () -> Void
    let backUpNow: () -> Void

    var body: some View {
        Section("Backups") {
            Text("Your folders, saved sessions and local settings are backed up automatically each time the app starts, and only when something has changed.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            LabeledContent("Last backup") {
                Text(lastBackupText)
                    .foregroundStyle(.secondary)
            }

            HStack {
                TextField(
                    "Second backup folder",
                    text: $mirrorDir,
                    prompt: Text("Optional, for example a folder on your NAS")
                )

                Button("Choose…", action: chooseFolder)

                if !mirrorDir.isEmpty {
                    Button("Clear") {
                        mirrorDir = ""
                    }
                }
            }

            LabeledContent("Second folder") {
                Text(mirrorStatusText)
                    .foregroundStyle(mirrorStatusColor)
            }

            Stepper(
                value: $keepLocal,
                in: 1...500
            ) {
                LabeledContent("Keep on this Mac") {
                    Text(countText(keepLocal))
                }
            }

            Stepper(
                value: $keepMirror,
                in: 1...500
            ) {
                LabeledContent("Keep in second folder") {
                    Text(countText(keepMirror))
                }
            }
            .disabled(mirrorDir.isEmpty)

            HStack {
                Button("Back Up Now", action: backUpNow)
                    .disabled(isBusy)

                if isBusy {
                    ProgressView()
                        .controlSize(.small)
                }

                if let message {
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private func countText(_ value: Int) -> String {
        value == 1 ? "1 backup" : String(value) + " backups"
    }

    private var lastBackupText: String {
        if status.lastBackup.isEmpty {
            return "None yet"
        }

        let files: String = String(status.lastFileCount) + " files"
        return status.lastBackup + "  ·  " + files
    }

    private var mirrorStatusText: String {
        status.mirrorMessage
    }

    private var mirrorStatusColor: Color {
        switch status.mirrorState {
        case "ready":
            return .green
        case "unavailable":
            return .orange
        default:
            return .secondary
        }
    }
}
