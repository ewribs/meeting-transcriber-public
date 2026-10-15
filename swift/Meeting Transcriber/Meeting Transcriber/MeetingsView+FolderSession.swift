import SwiftUI

extension MeetingsView {
    /// Runs in the folder that belong to meetings currently loaded.
    func runsForFolderSession(
        _ folder: MeetingFolder
    ) -> [String] {
        let known: Set<String> = Set(meetings.map { $0.run })
        return folder.meetingRuns.filter { known.contains($0) }
    }

    func beginFolderSession(_ folder: MeetingFolder) {
        let runs: [String] = runsForFolderSession(folder)

        if runs.isEmpty {
            addToSessionTitle = "Empty Folder"
            addToSessionResult =
                "This folder has no meetings yet. Add some, then make a session from it."
            return
        }

        folderSessionError = nil
        folderSessionName = folder.name
        folderSessionSource = folder.name
    }

    var folderSessionSheetBinding: Binding<Bool> {
        Binding(
            get: { folderSessionSource != nil },
            set: { isPresented in
                if !isPresented {
                    folderSessionSource = nil
                }
            }
        )
    }

    var folderSessionSheet: some View {
        let source: String = folderSessionSource ?? ""
        let blurb: String = "Creates a Fixed session from the meetings now in the folder “"
            + source
            + "”. The folder is not changed, and the session will not follow later changes to it."
        let isEmpty: Bool = folderSessionName
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .isEmpty

        return VStack(alignment: .leading, spacing: 16) {
            Text("Make Session from Folder")
                .font(.title2)
                .fontWeight(.semibold)

            Text(blurb)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            TextField(
                "Session name",
                text: $folderSessionName
            )
            .textFieldStyle(.roundedBorder)

            if let folderSessionError {
                Text(folderSessionError)
                    .font(.caption)
                    .foregroundStyle(.red)
            }

            HStack {
                Spacer()

                Button("Cancel") {
                    folderSessionSource = nil
                }
                .keyboardShortcut(.cancelAction)

                Button("Create Session") {
                    Task {
                        await makeSessionFromFolder()
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(isEmpty || isMakingFolderSession)
            }
        }
        .padding(24)
        .frame(width: 440)
    }

    @MainActor
    func makeSessionFromFolder() async {
        guard let source = folderSessionSource,
              !isMakingFolderSession
        else {
            return
        }

        let name: String = folderSessionName
            .trimmingCharacters(in: .whitespacesAndNewlines)

        if name.isEmpty {
            folderSessionError = "Enter a session name."
            return
        }

        var runs: [String] = []

        for folder in folders where folder.name == source {
            runs = runsForFolderSession(folder)
        }

        if runs.isEmpty {
            folderSessionError = "This folder has no meetings."
            return
        }

        isMakingFolderSession = true
        folderSessionError = nil

        defer {
            isMakingFolderSession = false
        }

        do {
            let result = try await backend
                .saveMeetingContextSession(
                    name: name,
                    meetingRuns: runs,
                    conversation: []
                )

            folderSessionSource = nil
            await reloadSessionFilterChoices()
            selectLibrary(.session(result.sessionName))
        } catch {
            folderSessionError = friendlyFolderSessionError(error)
        }
    }

    func friendlyFolderSessionError(_ error: Error) -> String {
        let text: String = error.localizedDescription

        if text.contains("DuplicateSessionNameError") {
            return "A session with that name already exists. Choose a different name."
        }

        return text
    }
}
