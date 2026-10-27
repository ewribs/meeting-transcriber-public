import SwiftUI

extension MeetingsView {
    var detailPane: some View {
        VStack(spacing: 0) {
            Picker(
                "Meetings workspace",
                selection:
                    $selectedWorkspaceTab
            ) {
                ForEach(visibleWorkspaceTabs) { tab in
                    Text(tab.rawValue)
                        .tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .id(visibleWorkspaceTabs.count)
            .frame(maxWidth: 480)
            .padding(.horizontal, 24)
            .padding(.vertical, 10)

            Divider()

            Group {
                switch selectedWorkspaceTab {
                case .meeting:
                    meetingWorkspace

                case .transcript:
                    transcriptWorkspace

                case .context:
                    contextWorkspace

                case .changes:
                    changesWorkspace
                }
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )
        }
        .onChange(of: sessionFilterName) {
            if selectedWorkspaceTab == .changes,
               sessionFilterSession == nil {
                selectedWorkspaceTab = .meeting
            }
        }
    }

    /// Changes compares a session's recent meetings, so that tab only
    /// exists while a session is open.
    var visibleWorkspaceTabs: [MeetingWorkspaceTab] {
        MeetingWorkspaceTab.allCases.filter { tab in
            tab != .changes || sessionFilterSession != nil
        }
    }

    @ViewBuilder
    var changesWorkspace: some View {
        if let session = sessionFilterSession {
            SessionChangesPanel(session: session)
        } else {
            meetingWorkspace
        }
    }

    /// The cleaned transcript with each speaker's name, read-only.
    @ViewBuilder
    var transcriptWorkspace: some View {
        if let meeting = selectedMeeting {
            VStack(spacing: 0) {
                meetingHeader(meeting)

                Divider()

                if isLoadingDetail {
                    ProgressView("Loading transcript…")
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity
                        )
                } else if let text = meetingDetail?.transcript,
                          !text.isEmpty {
                    ScrollView {
                        MeetingMarkdownView(markdown: text)
                            .frame(
                                maxWidth: .infinity,
                                alignment: .leading
                            )
                            .padding(24)
                    }
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )
                } else {
                    ContentUnavailableView(
                        "No transcript",
                        systemImage: "text.alignleft",
                        description: Text(
                            "This meeting has no saved transcript."
                        )
                    )
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )
                }
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity,
                alignment: .topLeading
            )
        } else {
            ContentUnavailableView(
                "Select a meeting",
                systemImage: "list.bullet.rectangle",
                description: Text(
                    "Choose a meeting from the list to view its transcript."
                )
            )
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )
        }
    }

    @ViewBuilder
    var meetingWorkspace: some View {
        if let meeting = selectedMeeting {
            VStack(spacing: 0) {
                meetingHeader(meeting)

                Divider()

                ScrollView {
                    VStack(
                        alignment: .leading,
                        spacing: 22
                    ) {
                        HStack(
                            alignment: .top,
                            spacing: 36
                        ) {
                            detailRow(
                                label: "Date",
                                value: formattedDate(meeting.date)
                            )

                            detailRow(
                                label: "Participants",
                                value: meeting.participantsText
                            )
                        }

                        if isLoadingDetail {
                            ProgressView(
                                "Loading meeting details…"
                            )
                        }

                        if let detailErrorMessage {
                            Text(detailErrorMessage)
                                .font(.caption)
                                .foregroundStyle(
                                    .secondary
                                )
                                .textSelection(
                                    .enabled
                                )
                        }

                        if let meetingDetail {
                            MeetingMarkdownView(
                                markdown:
                                    meetingDocumentMarkdown(
                                        meeting: meeting,
                                        detail: meetingDetail
                                    )
                            )
                        }
                    }
                    .frame(
                        maxWidth: .infinity,
                        alignment: .leading
                    )
                    .padding(24)
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity,
                    alignment: .topLeading
                )
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity,
                alignment: .topLeading
            )

        } else {
            ContentUnavailableView(
                "Select a meeting",
                systemImage: "list.bullet.rectangle",
                description: Text(
                    "Choose a meeting from the list to view its details."
                )
            )
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )
        }
    }

    /// Shown when a session is open in the rail and the context was
    /// built from ticked meetings: a scratch question that is not
    /// saved to the session.
    @ViewBuilder
    var scratchModeStrip: some View {
        if let session = sessionFilterSession,
           let built = builtContext {
            let picked: Int = built.meetingCount
            let total: Int = session.meetingCount
            let lead: String = "Scratch question about "
                + String(picked) + " of " + String(total)
                + " meetings. "
            let tail: String = "Answers are not saved to “"
                + session.name
                + "”. Use Save as Session to keep this set."

            Text(lead + tail)
                .font(.caption)
                .foregroundStyle(Color.orange)
                .frame(
                    maxWidth: .infinity,
                    alignment: .leading
                )
                .padding(.horizontal, 24)
                .padding(.vertical, 7)
                .background(Color.orange.opacity(0.12))
        }
    }

    /// A session open in the rail with nothing ticked shows that
    /// session's saved conversation; ticking meetings switches to a
    /// scratch question about just those meetings.
    @ViewBuilder
    var contextWorkspace: some View {
        if let session = sessionFilterSession,
           contextMeetingIDs.isEmpty {
            SessionChatPanel(
                session: session,
                meetings: meetings
            ) {
                Task {
                    await reloadSessionFilterChoices()
                }
            }
        } else {
            scratchContextWorkspace
        }
    }

    var scratchContextWorkspace: some View {
        VStack(spacing: 0) {
            scratchModeStrip

            if let builtContext {
                VStack(
                    alignment: .leading,
                    spacing: 8
                ) {
                    HStack {
                        VStack(
                            alignment: .leading,
                            spacing: 3
                        ) {
                            Text(
                                "Selected Meeting Context"
                            )
                            .font(.headline)

                            Text(
                                "\(builtContext.meetingCount) meeting\(builtContext.meetingCount == 1 ? "" : "s")"
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Button {
                            saveContextSessionError = nil
                            saveContextSessionName = ""
                            isShowingSaveContextSessionSheet = true
                        } label: {
                            Label(
                                "Save as Session",
                                systemImage:
                                    "square.and.arrow.down"
                            )
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(
                            isRunningContextQuery
                            || isBuildingContext
                        )

                        Button {
                            Task {
                                await buildSelectedContext()
                            }
                        } label: {
                            Label(
                                "Refresh",
                                systemImage:
                                    "arrow.clockwise"
                            )
                        }
                        .buttonStyle(.bordered)
                        .disabled(
                            isBuildingContext
                            || isRunningContextQuery
                            || contextMeetingIDs
                                .isEmpty
                        )
                    }

                    DisclosureGroup(
                        isExpanded:
                            $isShowingContextMeetings
                    ) {
                        VStack(
                            alignment: .leading,
                            spacing: 5
                        ) {
                            ForEach(
                                builtContext.meetingLabels,
                                id: \.self
                            ) { label in
                                Text(label)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .textSelection(.enabled)
                            }
                        }
                        .padding(.top, 5)
                    } label: {
                        Text(
                            "Meetings in Context (\(builtContext.meetingCount))"
                        )
                        .font(.caption)
                        .fontWeight(.semibold)
                    }

                }
                .padding(.horizontal, 24)
                .padding(.vertical, 12)

                Divider()

                VStack(spacing: 0) {
                    MeetingMarkdownScrollView(
                        markdown: contextConversation.isEmpty
                            ? "## Context Ready\n\n\(builtContext.prepText)"
                            : meetingContextConversationMarkdown,
                        scrollToBottomToken: contextConversation.count
                    )
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )
                    .padding(.horizontal, 24)
                    .padding(.vertical, 18)

                    if isRunningContextQuery {
                        HStack(spacing: 10) {
                            ProgressView()
                                .controlSize(.small)

                            Text("Qwen is working…")
                                .foregroundStyle(.secondary)

                            Spacer()
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 10)
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )

                Divider()

                meetingContextComposer

            } else if isBuildingContext {
                ProgressView("Building context…")
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )
            } else {
                ContentUnavailableView {
                    Label(
                        "Build a meeting context",
                        systemImage:
                            "square.stack.3d.up"
                    )
                } description: {
                    Text(
                        contextMeetingIDs.isEmpty
                            ? "Select meetings with the checkboxes in the meeting list, then build context."
                            : "Build context from the \(contextSelectionCount) selected meeting\(contextSelectionCount == 1 ? "" : "s")."
                    )
                } actions: {
                    if !contextMeetingIDs.isEmpty {
                        Button(
                            "Build Context"
                        ) {
                            Task {
                                await buildSelectedContext()
                            }
                        }
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )
            }

            if let contextErrorMessage {
                Text(contextErrorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                    .padding(
                        .horizontal,
                        24
                    )
                    .padding(
                        .bottom,
                        10
                    )
            }
        }
    }



    var meetingContextComposer:
        some View
    {
        VStack(
            alignment: .leading,
            spacing: 10
        ) {
            if showFavorites {
                PromptFavoritesBar(
                    promptText:
                        $meetingContextController
                            .prompt,
                    onSelect: { favorite in
                        switch favorite.category {
                        case "recipe":
                            meetingContextController
                                .queryMode = "synthesis"
                        case "changes":
                            meetingContextController
                                .queryMode = "changes"
                        default:
                            meetingContextController
                                .queryMode = "normal"
                        }
                    }
                )

                Divider()
                    .padding(.top, 2)
            }

            HStack {
                Text("Ask this Context")
                    .font(.headline)

                Spacer()

                if let contextStatusMessage {
                    Text(contextStatusMessage)
                        .font(.caption)
                        .foregroundStyle(
                            .secondary
                        )
                        .lineLimit(1)
                }
            }

            HStack(
                alignment: .bottom,
                spacing: 10
            ) {
                TextEditor(
                    text:
                        $meetingContextController
                            .prompt
                )
                .font(.body)
                .frame(
                    minHeight: 58,
                    maxHeight: 96
                )
                .padding(5)
                .background(
                    RoundedRectangle(
                        cornerRadius: 8
                    )
                    .fill(.quaternary)
                )
                .overlay(
                    RoundedRectangle(
                        cornerRadius: 8
                    )
                    .stroke(
                        .separator,
                        lineWidth: 1
                    )
                )
                .disabled(
                    isRunningContextQuery
                )

                if isRunningContextQuery {
                    Button(
                        role: .destructive
                    ) {
                        meetingContextController
                            .cancelQuery()
                    } label: {
                        Label(
                            "Cancel Query",
                            systemImage:
                                "xmark.circle.fill"
                        )
                        .frame(
                            minWidth: 96,
                            minHeight: 30
                        )
                    }
                    .buttonStyle(
                        .bordered
                    )
                    .help(
                        "Stop the active context query."
                    )

                } else {
                    Button {
                        Task {
                            await sendContextQuery()
                        }
                    } label: {
                        Label(
                            "Send",
                            systemImage:
                                "paperplane.fill"
                        )
                        .frame(
                            minWidth: 72,
                            minHeight: 30
                        )
                    }
                    .buttonStyle(
                        .borderedProminent
                    )
                    .disabled(
                        meetingContextController
                            .prompt
                            .trimmingCharacters(
                                in:
                                    .whitespacesAndNewlines
                            )
                            .isEmpty
                    )
                }
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
    }

    var meetingContextConversationMarkdown:
        String
    {
        contextConversation
            .enumerated()
            .map { index, item in
                let heading =
                    item.isUser
                        ? "## You"
                        : "## Assistant"

                let turn =
                    "\(heading)\n\n\(item.content)"

                if index == 0 {
                    return turn
                }

                return
                    "────────────────────────\n\n\(turn)"
            }
            .joined(
                separator: "\n\n"
            )
    }

    @MainActor
    func toggleMeetingContext(
        _ meeting: Meeting
    ) {
        meetingContextController
            .toggleMeeting(
                id: meeting.id
            )
    }

    @MainActor
    func clearContextSelection() {
        meetingContextController
            .clearSelection()
    }

    @MainActor
    func buildSelectedContext()
        async
    {
        let runs = contextMeetingRuns

        await meetingContextController
            .buildContext(
                meetingRuns: runs
            )

        if meetingContextController
            .builtContext != nil {
            selectedWorkspaceTab =
                .context
        }
    }

    @MainActor
    func sendContextQuery()
        async
    {
        meetingContextController
            .startQuery()
    }
}
