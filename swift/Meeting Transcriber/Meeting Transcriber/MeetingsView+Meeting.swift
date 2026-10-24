import SwiftUI

extension MeetingsView {
    func meetingHeader(
        _ meeting: Meeting
    ) -> some View {
        HStack(
            alignment: .center,
            spacing: 12
        ) {
            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text(meeting.title)
                    .font(.title2)
                    .fontWeight(.semibold)

                Text(
                    meeting.isPublished
                        ? "Published"
                        : "Unpublished"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer()

            StatusBadge(
                status: meeting.status,
                isPublished: meeting.isPublished
            )

            Button {
                voicesSheetTarget = VoiceSheetTarget(
                    run: meeting.run,
                    title: meeting.title
                )
            } label: {
                Label(
                    "Voices…",
                    systemImage: "waveform"
                )
            }
            .buttonStyle(.bordered)
            .help(
                "Listen to the voices in this meeting and name the ones you know."
            )

            if !meeting.isPublished {
                Button(role: .destructive) {
                    Task {
                        await prepareDeleteSelectedMeeting()
                    }
                } label: {
                    if isDeletingMeeting {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Label(
                            "Delete Meeting…",
                            systemImage: "trash"
                        )
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isDeletingMeeting || isPublishing)
                .help(
                    "Delete this unpublished meeting and its generated artifacts."
                )
            }

            if meeting.canPublish {
                Button {
                    showingPublishConfirmation =
                        true
                } label: {
                    if isPublishing {
                        HStack(spacing: 7) {
                            ProgressView()
                                .controlSize(.small)

                            Text("Publishing…")
                        }
                    } else {
                        Label(
                            "Publish & Archive",
                            systemImage:
                                "tray.and.arrow.up"
                        )
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isPublishing)
                .help(
                    "Publish this meeting to the configured archive."
                )
            } else if meeting.isPublished {
                Button {
                    Task {
                        await prepareUnpublishSelectedMeeting()
                    }
                } label: {
                    if isUnpublishing {
                        HStack(spacing: 7) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Unpublishing…")
                        }
                    } else {
                        Label(
                            "Unpublish…",
                            systemImage: "tray.and.arrow.down"
                        )
                    }
                }
                .buttonStyle(.bordered)
                .disabled(isUnpublishing || isDeletingMeeting || isPublishing)
                .help(
                    "Return this published meeting to Unpublished status before deleting it."
                )
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    func meetingDocumentMarkdown(
        meeting: Meeting,
        detail: MeetingDetail
    ) -> String {
        var sections: [String] = []

        if detail.hasSummary,
           !detail.summary.isEmpty {
            sections.append(
                "# Summary\n\n\(detail.summary)"
            )
        }

        let summaryHasDecisions = summaryContainsHeading(
            detail.summary,
            matching: ["decisions"]
        )
        let summaryHasOpenQuestions = summaryContainsHeading(
            detail.summary,
            matching: ["open questions"]
        )
        let summaryHasActionItemsOrFollowUps = summaryContainsHeading(
            detail.summary,
            matching: ["action items", "follow-ups", "follow ups"]
        )
        let summaryHasTopics = summaryContainsHeading(
            detail.summary,
            matching: ["topics"]
        )

        if !detail.decisions.isEmpty,
           !summaryHasDecisions {
            let decisions = detail.decisions
                .map { "- \($0)" }
                .joined(separator: "\n\n")

            sections.append(
                "# Decisions\n\n\(decisions)"
            )
        }

        if !detail.commitments.isEmpty {
            let commitments = detail.commitments
                .map { commitment in
                    var prefix = ""

                    if !commitment.owner.isEmpty {
                        prefix = "**\(commitment.owner):** "
                    }

                    var suffix = ""
                    if !commitment.status.isEmpty {
                        suffix = " (\(commitment.status))"
                    }

                    return "- \(prefix)\(commitment.action)\(suffix)"
                }
                .joined(separator: "\n\n")

            sections.append(
                "# Commitments\n\n\(commitments)"
            )
        }

        if !detail.openQuestions.isEmpty,
           !summaryHasOpenQuestions {
            let questions = detail.openQuestions
                .map { "- \($0)" }
                .joined(separator: "\n\n")

            sections.append(
                "# Open Questions\n\n\(questions)"
            )
        }

        if !detail.followUps.isEmpty,
           !summaryHasActionItemsOrFollowUps {
            let followUps = detail.followUps
                .map { "- \($0)" }
                .joined(separator: "\n\n")

            sections.append(
                "# Follow-ups\n\n\(followUps)"
            )
        }

        if !detail.topics.isEmpty,
           !summaryHasTopics {
            let topics = detail.topics
                .map { topic in
                    var lines: [String] = []

                    if topic.status.isEmpty {
                        lines.append(
                            "### \(topic.name)"
                        )
                    } else {
                        lines.append(
                            "### \(topic.name) — \(topic.status)"
                        )
                    }

                    if !topic.summary.isEmpty {
                        lines.append(
                            topic.summary
                        )
                    }

                    return lines.joined(
                        separator: "\n"
                    )
                }
                .joined(
                    separator: "\n\n"
                )

            sections.append(
                "# Topics\n\n\(topics)"
            )
        }

        if let speakers = detail.speakers {
            var speakerLines: [String] = []

            if speakers.remoteSilent {
                speakerLines.append(
                    "The remote audio was not captured, so voices could not be told apart."
                )
            } else {
                for person in speakers.people {
                    speakerLines.append(
                        "- **\(person.name)** — \(String(format: "%.1f", person.minutes)) min"
                    )
                }

                if speakers.unnamedCount > 0 {
                    let noun = speakers.unnamedCount == 1
                        ? "unnamed voice"
                        : "unnamed voices"

                    speakerLines.append(
                        "- \(speakers.unnamedCount) \(noun) — \(String(format: "%.1f", speakers.unnamedMinutes)) min"
                    )
                }
            }

            if !speakerLines.isEmpty {
                sections.append(
                    "# Who Spoke\n\n"
                    + speakerLines.joined(separator: "\n\n")
                )
            }
        }

        if let processing = detail.processing {
            var runtimeLines: [String] = []

            if !processing.aiModel.isEmpty {
                runtimeLines.append(
                    "**AI Model:** \(processing.aiModel)"
                )
            }

            var profileParts: [String] = []
            if !processing.profileDisplay.isEmpty {
                profileParts.append(processing.profileDisplay)
            }
            if !processing.mode.isEmpty {
                profileParts.append(processing.mode)
            }
            if !profileParts.isEmpty {
                runtimeLines.append(
                    "**Processing:** \(profileParts.joined(separator: " · "))"
                )
            }

            if processing.contextSizeTokens > 0 {
                runtimeLines.append(
                    "**Context:** \(processing.contextSizeTokens.formatted()) tokens"
                )
            }

            if !processing.whisperModel.isEmpty {
                var whisper = processing.whisperModel
                if processing.whisperChunkMinutes > 0 {
                    whisper += " · \(processing.whisperChunkMinutes)-minute chunks"
                }
                runtimeLines.append(
                    "**Whisper:** \(whisper)"
                )
            }

            if !runtimeLines.isEmpty {
                sections.append(
                    "# Processing\n\n"
                    + runtimeLines.joined(separator: "\n\n")
                )
            }
        }

        sections.append(
            "# Run\n\n\(meeting.run)"
        )

        return sections.joined(
            separator: "\n\n"
        )
    }

    func summaryContainsHeading(
        _ summary: String,
        matching headings: Set<String>
    ) -> Bool {
        for rawLine in summary.components(separatedBy: .newlines) {
            var line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)

            while line.hasPrefix("#") {
                line.removeFirst()
                line = line.trimmingCharacters(in: .whitespaces)
            }

            while line.hasPrefix("**"), line.hasSuffix("**"), line.count >= 4 {
                line = String(line.dropFirst(2).dropLast(2))
                    .trimmingCharacters(in: .whitespaces)
            }

            line = line.trimmingCharacters(
                in: CharacterSet(charactersIn: "*_ :.-")
            )
            .lowercased()

            if headings.contains(line) {
                return true
            }
        }

        return false
    }

    func detailRow(
        label: String,
        value: String
    ) -> some View {
        VStack(
            alignment: .leading,
            spacing: 4
        ) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)

            Text(
                value.isEmpty
                    ? "—"
                    : value
            )
            .textSelection(.enabled)
        }
    }

    func formattedDate(_ rawDate: String) -> String {
        guard !rawDate.isEmpty else {
            return "—"
        }

        let input = DateFormatter()
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd"

        guard let date = input.date(from: rawDate) else {
            return rawDate
        }

        let output = DateFormatter()
        output.locale = Locale.current
        output.dateStyle = .long
        output.timeStyle = .none

        return output.string(from: date)
    }

    func deleteConfirmationMessage(
        _ plan: MeetingDeletePlanResponse
    ) -> String {
        var parts = [
            "The meeting output folder and all generated transcript/analysis artifacts will be moved to the macOS Trash."
        ]

        if plan.sourceFound && plan.sourceIsManaged {
            parts.append(
                "Choose ‘Delete Meeting, Keep Recording’ to preserve the app-managed source recording, or ‘Delete Meeting and Recording’ to move that recording to Trash too."
            )
        } else if plan.sourceFound {
            parts.append(
                "The source audio appears to be external/imported and will always be kept."
            )
        } else {
            parts.append(
                "No matching source recording was found, so there is no recording to remove."
            )
        }

        if plan.sessionReferenceCount > 0 {
            parts.append("It will also be removed from \(plan.sessionReferenceCount) saved Session\(plan.sessionReferenceCount == 1 ? "" : "s").")
        }

        return parts.joined(separator: " ")
    }

    func unpublishConfirmationMessage(
        _ plan: MeetingUnpublishPlanResponse
    ) -> String {
        var message: String

        if archiveRequiresPermanentDeletion(plan.archivePath) {
            message = "This meeting's published archive is stored on a network or non-local volume that does not use the macOS Trash. The published archive folder will be permanently deleted and cannot be recovered from Trash. The local meeting and source recording will remain available, and the meeting will return to Unpublished status."
        } else {
            message = "The published archive copy will be moved to the macOS Trash and this meeting will return to Unpublished status. The local meeting and source recording will remain available."
        }

        if plan.sessionReferenceCount > 0 {
            message += " It will also be removed from \(plan.sessionReferenceCount) saved Session\(plan.sessionReferenceCount == 1 ? "" : "s") because Sessions use published meetings."
        }

        message += " You can then delete the unpublished meeting separately if you want it removed entirely."
        return message
    }

    @MainActor
    func prepareDeleteSelectedMeeting() async {
        guard let selectedMeeting,
              !selectedMeeting.isPublished,
              !isDeletingMeeting,
              !isPublishing,
              !isUnpublishing
        else {
            return
        }

        isDeletingMeeting = true
        deleteErrorMessage = nil

        defer {
            isDeletingMeeting = false
        }

        do {
            pendingDeletePlan =
                try await backend.meetingDeletePlan(
                    run: selectedMeeting.run
                )
            showingDeleteConfirmation = true
        } catch {
            deleteErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    func deleteSelectedMeeting(
        operation: MeetingDeleteOperation
    ) async {
        guard let selectedMeeting,
              let plan = pendingDeletePlan,
              plan.run == selectedMeeting.run,
              !selectedMeeting.isPublished,
              !isDeletingMeeting
        else {
            return
        }

        isDeletingMeeting = true
        deleteErrorMessage = nil

        defer {
            isDeletingMeeting = false
        }

        do {
            guard let runPath = usableFilesystemPath(plan.runPath) else {
                throw NSError(
                    domain: "MeetingTranscriber.Delete",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "The meeting output folder path is unavailable."]
                )
            }
            let runURL = URL(fileURLWithPath: runPath)
            guard FileManager.default.fileExists(atPath: runURL.path) else {
                throw NSError(
                    domain: "MeetingTranscriber.Delete",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "The meeting output folder is missing."]
                )
            }

            var trashedRunURL: NSURL?
            try FileManager.default.trashItem(
                at: runURL,
                resultingItemURL: &trashedRunURL
            )

            if operation.deletesManagedRecording,
               plan.sourceIsManaged,
               let sourcePath = usableFilesystemPath(plan.sourcePath),
               plan.sourceFound {
                let sourceURL = URL(fileURLWithPath: sourcePath)
                if FileManager.default.fileExists(atPath: sourceURL.path) {
                    var trashedSourceURL: NSURL?
                    try FileManager.default.trashItem(
                        at: sourceURL,
                        resultingItemURL: &trashedSourceURL
                    )
                }
            }

            _ = try await backend.finalizeMeetingDelete(
                run: plan.run
            )

            transcriptionQueueCleanupRequest =
                MeetingTranscriptionQueueCleanupRequest(
                    run: plan.run,
                    sourcePath: plan.sourcePath
                )

            if meetingContextController.meetingIDs.contains(
                selectedMeeting.id
            ) {
                meetingContextController.toggleMeeting(
                    id: selectedMeeting.id
                )
            }

            pendingDeletePlan = nil
            selectedMeetingID = nil
            meetingDetail = nil
            detailErrorMessage = nil

            await reloadMeetings()
        } catch {
            deleteErrorMessage =
                error.localizedDescription
        }
    }

    enum PublishedArchiveDisposition {
        case systemTrash
        case permanentDelete
    }

    var unpublishUsesPermanentArchiveDeletion: Bool {
        guard let plan = pendingUnpublishPlan else {
            return false
        }
        return archiveRequiresPermanentDeletion(plan.archivePath)
    }

    func archiveRequiresPermanentDeletion(_ path: String?) -> Bool {
        guard let archivePath = usableFilesystemPath(path) else {
            return false
        }

        let archiveURL = URL(fileURLWithPath: archivePath)
        do {
            let values = try archiveURL.resourceValues(
                forKeys: [.volumeIsLocalKey]
            )
            return values.volumeIsLocal == false
        } catch {
            // If macOS cannot determine the volume type, do not silently
            // escalate to permanent deletion. The operation will fail later
            // rather than deleting without the stronger confirmation.
            return false
        }
    }

    func removePublishedArchive(
        _ archiveURL: URL,
        permanently: Bool
    ) throws -> PublishedArchiveDisposition {
        if permanently {
            try FileManager.default.removeItem(at: archiveURL)
            return .permanentDelete
        }

        var trashedArchiveURL: NSURL?
        try FileManager.default.trashItem(
            at: archiveURL,
            resultingItemURL: &trashedArchiveURL
        )
        return .systemTrash
    }

    @MainActor
    func prepareUnpublishSelectedMeeting() async {
        guard let selectedMeeting,
              selectedMeeting.isPublished,
              !isUnpublishing,
              !isPublishing,
              !isDeletingMeeting
        else {
            return
        }

        isUnpublishing = true
        unpublishErrorMessage = nil

        defer {
            isUnpublishing = false
        }

        do {
            pendingUnpublishPlan = try await backend.meetingUnpublishPlan(
                run: selectedMeeting.run
            )
            showingUnpublishConfirmation = true
        } catch {
            unpublishErrorMessage = error.localizedDescription
        }
    }

    @MainActor
    func unpublishSelectedMeeting() async {
        guard let selectedMeeting,
              let plan = pendingUnpublishPlan,
              plan.run == selectedMeeting.run,
              selectedMeeting.isPublished,
              !isUnpublishing
        else {
            return
        }

        isUnpublishing = true
        unpublishErrorMessage = nil

        defer {
            isUnpublishing = false
        }

        do {
            guard let archivePath = usableFilesystemPath(plan.archivePath) else {
                throw NSError(
                    domain: "MeetingTranscriber.Unpublish",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "The published archive folder path is unavailable."]
                )
            }
            let archiveURL = URL(fileURLWithPath: archivePath)
            guard FileManager.default.fileExists(atPath: archiveURL.path) else {
                throw NSError(
                    domain: "MeetingTranscriber.Unpublish",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "The published archive folder is missing."]
                )
            }

            let permanentlyDeleteArchive =
                archiveRequiresPermanentDeletion(plan.archivePath)

            let archiveDisposition = try removePublishedArchive(
                archiveURL,
                permanently: permanentlyDeleteArchive
            )

            _ = try await backend.finalizeMeetingUnpublish(
                run: plan.run
            )

            switch archiveDisposition {
            case .systemTrash:
                unpublishSuccessMessage =
                    "The meeting is now Unpublished. Its published archive copy was moved to the macOS Trash."
            case .permanentDelete:
                unpublishSuccessMessage =
                    "The meeting is now Unpublished. Its published archive copy was permanently deleted from the network/non-local archive volume."
            }

            if meetingContextController.meetingIDs.contains(
                selectedMeeting.id
            ) {
                meetingContextController.toggleMeeting(
                    id: selectedMeeting.id
                )
            }

            pendingUnpublishPlan = nil
            meetingDetail = nil
            detailErrorMessage = nil

            await reloadMeetings()
            selectedMeetingID = meetings.first(where: {
                $0.run == plan.run
            })?.id
        } catch {
            unpublishErrorMessage = error.localizedDescription
        }
    }

    @MainActor
    func publishSelectedMeeting() async {
        guard let selectedMeeting,
              selectedMeeting.canPublish,
              !isPublishing
        else {
            return
        }

        let run = selectedMeeting.run

        isPublishing = true
        publishErrorMessage = nil

        defer {
            isPublishing = false
        }

        do {
            _ = try await backend.publishMeeting(
                run: run
            )

            // Publishing changes the catalog status, not
            // the already-loaded readable meeting content.
            // Refresh the list in place and leave the detail
            // document untouched so the user's scroll
            // position stays where it was.
            await reloadMeetings()

        } catch {
            publishErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    func reloadSelectedMeetingDetail() async {
        meetingDetail = nil
        detailErrorMessage = nil

        guard let selectedMeeting else {
            return
        }

        isLoadingDetail = true

        defer {
            isLoadingDetail = false
        }

        do {
            meetingDetail =
                try await backend.loadMeetingDetail(
                    run: selectedMeeting.run
                )
        } catch {
            detailErrorMessage =
                error.localizedDescription
        }
    }

    /// Keeps Dynamic sessions current: whenever the set of meetings
    /// changes (new, published or deleted), re-run every Dynamic
    /// session's rules so its members stay up to date.
    @MainActor
    func refreshDynamicSessionsIfNeeded(
        for loadedMeetings: [Meeting]
    ) async {
        let runs = Set(loadedMeetings.map { $0.run + "|" + $0.status })

        guard runs != sessionRefreshedRuns else {
            return
        }

        try? await backend.refreshAllSessions()
        sessionRefreshedRuns = runs
    }

    /// Another part of the app (for example a Search result) asked to
    /// open a session: select it in the sidebar and show the Ask view.
    @MainActor
    func openRequestedSessionIfAny() {
        guard let name = navigation.requestedSessionName else {
            return
        }

        // If the session list has not loaded yet, keep the request;
        // reloadMeetings() tries again once it has.
        guard allSessions.contains(where: { $0.name == name }) else {
            return
        }

        navigation.requestedSessionName = nil
        selectLibrary(.session(name))
        selectedWorkspaceTab = .context
    }

    @MainActor
    func reloadMeetings() async {
        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            let loadedMeetings =
                try await backend.loadMeetings()

            meetings = loadedMeetings
            await refreshDynamicSessionsIfNeeded(
                for: loadedMeetings
            )
            await reloadSessionFilterChoices()
            openRequestedSessionIfAny()

            if let requestedRun = navigation.requestedMeetingRun,
               let requestedMeeting = loadedMeetings.first(
                    where: {
                        $0.run == requestedRun
                            || $0.id == requestedRun
                    }
               ) {
                selectedMeetingID = requestedMeeting.id
                selectedWorkspaceTab = .meeting
                navigation.requestedMeetingRun = nil
            }

            if let selectedMeetingID,
               !loadedMeetings.contains(
                    where: {
                        $0.id == selectedMeetingID
                    }
               ) {
                self.selectedMeetingID = nil
            }

        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
