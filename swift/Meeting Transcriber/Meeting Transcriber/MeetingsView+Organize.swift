import SwiftUI

extension MeetingsView {
    @ViewBuilder
    func meetingFolderMenu(
        for meeting: Meeting
    ) -> some View {
        let runs = contextMeetingIDs.contains(meeting.id)
            ? contextMeetingRuns
            : [meeting.run]

        Menu("Add to Folder") {
            ForEach(folders) { folder in
                Button(folder.name) {
                    Task {
                        await addRunsToFolder(
                            folder.name,
                            runs
                        )
                    }
                }
            }

            if !folders.isEmpty {
                Divider()
            }

            Button("New Folder…") {
                openCreateFolder(with: runs)
            }
        }

        if let session = sessionFilterSession,
           !session.isDynamic {
            Button("Remove from session “\(session.name)”") {
                Task {
                    await removeRunsFromSession(
                        session.name,
                        runs
                    )
                }
            }
        }

        if case .folder(let name) = librarySelection {
            Button("Remove from “\(name)”") {
                Task {
                    await removeRunsFromFolder(name, runs)
                }
            }
        }

        if folders.contains(where: {
            !Set($0.meetingRuns).isDisjoint(with: runs)
        }) {
            Button("Remove from All Folders") {
                Task {
                    await removeRunsFromAllFolders(runs)
                }
            }
        }
    }

    func openCreateFolder(
        with runs: [String]
    ) {
        folderNameText = ""
        folderErrorMessage = nil
        pendingFolderRuns = runs
        folderSheet = .create
    }

    func openRenameFolder(
        _ name: String
    ) {
        folderNameText = name
        folderErrorMessage = nil
        pendingFolderRuns = []
        folderSheet = .rename(name)
    }

    @MainActor
    func saveFolderSheet() async {
        guard let mode = folderSheet,
              !isSavingFolder
        else {
            return
        }

        isSavingFolder = true
        folderErrorMessage = nil

        defer {
            isSavingFolder = false
        }

        let name = folderNameText
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")

        do {
            switch mode {
            case .create:
                var result = try await backend
                    .createFolder(name: name)

                if !pendingFolderRuns.isEmpty {
                    result = try await backend
                        .addMeetingsToFolder(
                            name: name,
                            meetingRuns: pendingFolderRuns
                        )
                }

                folders = result

            case .rename(let oldName):
                folders = try await backend.renameFolder(
                    oldName: oldName,
                    newName: name
                )

                if meetingContextController
                    .folderFilterName == oldName {
                    meetingContextController
                        .folderFilterName = name
                }
            }

            pendingFolderRuns = []
            folderSheet = nil
        } catch {
            folderErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    func addRunsToFolder(
        _ name: String,
        _ runs: [String]
    ) async {
        guard !runs.isEmpty else {
            return
        }

        do {
            folders = try await backend
                .addMeetingsToFolder(
                    name: name,
                    meetingRuns: runs
                )
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func removeRunsFromFolder(
        _ name: String,
        _ runs: [String]
    ) async {
        guard !runs.isEmpty else {
            return
        }

        do {
            folders = try await backend
                .removeMeetingsFromFolder(
                    name: name,
                    meetingRuns: runs
                )
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    /// Takes meetings out of every folder they are in, which puts
    /// them back in "Not in a Folder". Meetings and sessions are
    /// untouched.
    @MainActor
    func removeRunsFromAllFolders(
        _ runs: [String]
    ) async {
        guard !runs.isEmpty else {
            return
        }

        let wanted = Set(runs)

        do {
            for folder in folders
            where !Set(folder.meetingRuns)
                .isDisjoint(with: wanted) {
                folders = try await backend
                    .removeMeetingsFromFolder(
                        name: folder.name,
                        meetingRuns: runs
                    )
            }
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func deleteFolder(
        _ name: String
    ) async {
        do {
            folders = try await backend.deleteFolder(
                name: name
            )

            pendingDeleteFolder = nil

            if meetingContextController
                .folderFilterName == name {
                selectLibrary(.all)
            }
        } catch {
            pendingDeleteFolder = nil
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func removeRunsFromSession(
        _ name: String,
        _ runs: [String]
    ) async {
        guard !runs.isEmpty else {
            return
        }

        do {
            _ = try await backend
                .removeMeetingsFromSession(
                    name: name,
                    meetingRuns: runs
                )

            await reloadSessionFilterChoices()
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func addDroppedRuns(
        _ runs: [String],
        toSession name: String
    ) async {
        guard !runs.isEmpty else {
            return
        }

        do {
            let result = try await backend
                .addMeetingsToSession(
                    name: name,
                    meetingRuns: runs
                )

            await reloadSessionFilterChoices()

            // Success is silent: the count next to the session in
            // the rail updates. Only "nothing changed" is worth a note.
            if result.isAlreadyCurrent && showNotices {
                addToSessionTitle = "Already Added"
                addToSessionResult =
                    "“\(name)” already contains that meeting."
            }
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func reloadSessionFilterChoices() async {
        if let loaded = try? await backend.loadSessions() {
            allSessions = loaded
        }

        if let loadedFolders = try? await backend.loadFolders() {
            folders = loadedFolders
        }
    }

    @MainActor
    func saveCurrentContextAsSession()
        async
    {
        if builtContext == nil,
           !contextMeetingIDs.isEmpty {
            await buildSelectedContext()
        }

        guard
            let builtContext,
            !isSavingContextSession,
            !isRunningContextQuery
        else {
            return
        }

        let name =
            saveContextSessionName
                .trimmingCharacters(
                    in:
                        .whitespacesAndNewlines
                )

        guard !name.isEmpty else {
            return
        }

        isSavingContextSession = true
        saveContextSessionError = nil

        defer {
            isSavingContextSession = false
        }

        do {
            let result = try await backend
                .saveMeetingContextSession(
                    name: name,
                    meetingRuns:
                        builtContext
                            .meetingRuns,
                    conversation:
                        contextConversation
                )

            isShowingSaveContextSessionSheet = false
            await reloadSessionFilterChoices()
            saveContextSessionResult =
                "Saved “\(result.sessionName)” with \(result.meetingCount) meeting\(result.meetingCount == 1 ? "" : "s") and \(result.turnCount) conversation turn\(result.turnCount == 1 ? "" : "s")."

        } catch {
            saveContextSessionError =
                error.localizedDescription
        }
    }
}
