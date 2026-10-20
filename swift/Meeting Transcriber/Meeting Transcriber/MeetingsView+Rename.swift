import SwiftUI

/// Rename a meeting's displayed title. The meeting's identity (its
/// folder name) does not change, so folders, sessions and search are
/// unaffected.
extension MeetingsView {
    func openRenameMeeting(_ meeting: Meeting) {
        renameMeetingText = meeting.title
        renameMeetingError = nil
        renameMeetingTarget = meeting
    }

    var renameMeetingSheet: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Rename Meeting")
                .font(.title2)
                .fontWeight(.semibold)

            TextField(
                "Meeting name",
                text: $renameMeetingText
            )
            .textFieldStyle(.roundedBorder)

            Text("Only the name shown in the app changes. The meeting's files and folders keep their original names.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if let renameMeetingError {
                Text(renameMeetingError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            HStack {
                Spacer()

                Button("Cancel") {
                    renameMeetingTarget = nil
                }
                .keyboardShortcut(.cancelAction)

                Button("Rename") {
                    Task {
                        await renameSelectedMeeting()
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(
                    renameMeetingText
                        .trimmingCharacters(
                            in: .whitespacesAndNewlines
                        )
                        .isEmpty
                    || isRenamingMeeting
                )
            }
        }
        .padding(24)
        .frame(width: 460)
    }

    @MainActor
    func renameSelectedMeeting() async {
        guard let target = renameMeetingTarget else {
            return
        }

        isRenamingMeeting = true
        renameMeetingError = nil

        defer {
            isRenamingMeeting = false
        }

        do {
            try await backend.renameMeeting(
                run: target.run,
                title: renameMeetingText
            )
            renameMeetingTarget = nil
            await reloadMeetings()
        } catch {
            renameMeetingError = error.localizedDescription
        }
    }
}
