import SwiftUI

private enum SessionWorkspaceTab: String, CaseIterable, Identifiable {
    case conversation = "Conversation"
    case context = "Context"

    var id: String { rawValue }
    case changes = "Changes"
}

struct SessionsView: View {
    @EnvironmentObject
    private var navigation: AppNavigationController

    @State private var sessions: [SavedSession] = []
    @State private var selectedSessionID: SavedSession.ID?
    @State private var searchText = ""
    @State private var isLoading = false
    @State private var errorMessage: String?

    @State private var isRefreshingSession = false
    @State private var refreshResultMessage: String?
    @State private var refreshErrorMessage: String?

    @State private var isShowingRenameSheet = false
    @State private var renameText = ""
    @State private var isRenamingSession = false
    @State private var renameErrorMessage: String?

    @State private var isShowingDeleteConfirmation = false
    @State private var isDeletingSession = false
    @State private var deleteErrorMessage: String?

    @State private var isShowingDynamicEditor = false
    @State private var dynamicEditorMode = "create"
    @State private var dynamicSessionName = ""
    @State private var dynamicPerson = ""
    @State private var dynamicTitle = ""
    @State private var dynamicTopic = ""
    @State private var dynamicHistoryOptions: [String] = []
    @State private var dynamicHistoryLabel = ""
    @State private var dynamicCustomRangeLabel: String?
    @State private var isLoadingDynamicEditor = false
    @State private var isSavingDynamicSession = false
    @State private var dynamicEditorErrorMessage: String?
    @State private var dynamicEditorResultMessage: String?

    @State private var sessionDetail: SessionDetail?
    @State private var isLoadingSessionDetail = false
    @State private var sessionDetailErrorMessage: String?

    @State private var sessionQueryText = ""
    @State private var sessionQueryMode = "normal"
    @State private var isRunningSessionQuery = false
    @State private var sessionQueryStatusMessage: String?
    @State private var sessionQueryErrorMessage: String?
    @State private var selectedWorkspaceTab: SessionWorkspaceTab = .conversation

    @State private var sessionChanges:
        SessionChangesResponse?

    @State private var isLoadingSessionChanges =
        false

    @State private var sessionChangesError:
        String?

    @State private var pendingSessionPrompt: String?

    private let backend = BackendService()

    private var filteredSessions: [SavedSession] {
        let query = searchText
            .trimmingCharacters(
                in: .whitespacesAndNewlines
            )

        guard !query.isEmpty else {
            return sessions
        }

        return sessions.filter { session in
            session.name.localizedCaseInsensitiveContains(
                query
            )
            || session.sessionType.localizedCaseInsensitiveContains(
                query
            )
            || session.criteria.contains {
                $0.localizedCaseInsensitiveContains(
                    query
                )
            }
        }
    }

    private var selectedSession: SavedSession? {
        guard let selectedSessionID else {
            return nil
        }

        return sessions.first {
            $0.id == selectedSessionID
        }
    }

    var body: some View {
        GeometryReader { geometry in
            HSplitView {
                listPane
                    .frame(
                        minWidth: 280,
                        idealWidth: 340,
                        maxWidth: 430,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )

                detailPane
                    .frame(
                        minWidth: 650,
                        idealWidth: 920,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )
            }
            .frame(
                width: geometry.size.width,
                height: geometry.size.height,
                alignment: .topLeading
            )
        }
        .navigationTitle("Sessions")
        .task {
            await reloadSessions()
        }
        .task(id: selectedSessionID) {
            await loadSelectedSessionDetail()
        }
        .sheet(
            isPresented: $isShowingRenameSheet
        ) {
            VStack(
                alignment: .leading,
                spacing: 16
            ) {
                Text("Rename Session")
                    .font(.title2)
                    .fontWeight(.semibold)

                TextField(
                    "Session name",
                    text: $renameText
                )
                .textFieldStyle(.roundedBorder)

                if let renameErrorMessage {
                    Text(renameErrorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }

                HStack {
                    Spacer()

                    Button("Cancel") {
                        isShowingRenameSheet = false
                    }
                    .keyboardShortcut(.cancelAction)

                    Button("Rename") {
                        Task {
                            await renameSelectedSession()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(
                        renameText
                            .trimmingCharacters(
                                in: .whitespacesAndNewlines
                            )
                            .isEmpty
                        || isRenamingSession
                    )
                }
            }
            .padding(24)
            .frame(width: 420)
        }
        .sheet(
            isPresented: $isShowingDynamicEditor
        ) {
            VStack(
                alignment: .leading,
                spacing: 18
            ) {
                HStack {
                    VStack(
                        alignment: .leading,
                        spacing: 4
                    ) {
                        Text(
                            dynamicEditorMode == "create"
                                ? "Create Dynamic Session"
                                : "Edit Dynamic Session"
                        )
                        .font(.title2)
                        .fontWeight(.semibold)

                        Text(
                            dynamicEditorMode == "create"
                                ? "Create a saved session that automatically selects meetings matching these criteria."
                                : "Update the saved criteria. Existing conversation history will be preserved."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }

                    Spacer()
                }

                Divider()

                Grid(
                    alignment: .leading,
                    horizontalSpacing: 14,
                    verticalSpacing: 12
                ) {
                    GridRow {
                        Text("Session name")
                            .foregroundStyle(.secondary)

                        TextField(
                            "Session name",
                            text: $dynamicSessionName
                        )
                        .textFieldStyle(.roundedBorder)
                        .disabled(
                            dynamicEditorMode == "edit"
                        )
                    }

                    GridRow {
                        Text("Person")
                            .foregroundStyle(.secondary)

                        TextField(
                            "Any person",
                            text: $dynamicPerson
                        )
                        .textFieldStyle(.roundedBorder)
                    }

                    GridRow {
                        Text("Title contains")
                            .foregroundStyle(.secondary)

                        TextField(
                            "Optional",
                            text: $dynamicTitle
                        )
                        .textFieldStyle(.roundedBorder)
                    }

                    GridRow {
                        Text("Topic contains")
                            .foregroundStyle(.secondary)

                        TextField(
                            "Optional",
                            text: $dynamicTopic
                        )
                        .textFieldStyle(.roundedBorder)
                    }

                    GridRow {
                        Text("History")
                            .foregroundStyle(.secondary)

                        Picker(
                            "History",
                            selection: $dynamicHistoryLabel
                        ) {
                            ForEach(
                                dynamicHistoryOptions,
                                id: \.self
                            ) { option in
                                Text(option)
                                    .tag(option)
                            }
                        }
                        .labelsHidden()
                        .frame(
                            maxWidth: .infinity,
                            alignment: .leading
                        )
                    }
                }

                if let dynamicCustomRangeLabel,
                   dynamicHistoryLabel
                    == dynamicCustomRangeLabel {
                    Label(
                        "This legacy saved date range will be preserved unless you choose a different history window.",
                        systemImage: "calendar.badge.clock"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                Text(
                    "Leave Person, Title, and Topic blank to ignore that criterion. A rolling history window can be used by itself."
                )
                .font(.caption)
                .foregroundStyle(.secondary)

                if let dynamicEditorErrorMessage {
                    Text(dynamicEditorErrorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }

                HStack {
                    if isSavingDynamicSession {
                        ProgressView()
                            .controlSize(.small)

                        Text(
                            dynamicEditorMode == "create"
                                ? "Creating…"
                                : "Saving changes…"
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }

                    Spacer()

                    Button("Cancel") {
                        isShowingDynamicEditor = false
                    }
                    .keyboardShortcut(.cancelAction)
                    .disabled(isSavingDynamicSession)

                    Button(
                        dynamicEditorMode == "create"
                            ? "Create"
                            : "Save Changes"
                    ) {
                        Task {
                            await saveDynamicSessionEditor()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(
                        isSavingDynamicSession
                        || dynamicSessionName
                            .trimmingCharacters(
                                in: .whitespacesAndNewlines
                            )
                            .isEmpty
                        || dynamicHistoryLabel.isEmpty
                    )
                }
            }
            .padding(24)
            .frame(width: 610)
        }
        .alert(
            "Dynamic Session",
            isPresented: Binding(
                get: {
                    dynamicEditorResultMessage != nil
                },
                set: { showing in
                    if !showing {
                        dynamicEditorResultMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                dynamicEditorResultMessage = nil
            }
        } message: {
            Text(
                dynamicEditorResultMessage ?? ""
            )
        }
        .confirmationDialog(
            "Delete Session?",
            isPresented: $isShowingDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button(
                "Delete Session",
                role: .destructive
            ) {
                Task {
                    await deleteSelectedSession()
                }
            }

            Button("Cancel", role: .cancel) {}
        } message: {
            if let selectedSession {
                Text(
                    "This will permanently delete the saved session “\(selectedSession.name)”. The meetings themselves will not be deleted."
                )
            }
        }
        .alert(
            "Delete Failed",
            isPresented: Binding(
                get: {
                    deleteErrorMessage != nil
                },
                set: { showing in
                    if !showing {
                        deleteErrorMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                deleteErrorMessage = nil
            }
        } message: {
            Text(
                deleteErrorMessage
                    ?? "Unknown delete error"
            )
        }
        .alert(
            "Session Refresh",
            isPresented: Binding(
                get: {
                    refreshResultMessage != nil
                },
                set: { showing in
                    if !showing {
                        refreshResultMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                refreshResultMessage = nil
            }
        } message: {
            Text(refreshResultMessage ?? "")
        }
        .alert(
            "Refresh Failed",
            isPresented: Binding(
                get: {
                    refreshErrorMessage != nil
                },
                set: { showing in
                    if !showing {
                        refreshErrorMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                refreshErrorMessage = nil
            }
        } message: {
            Text(
                refreshErrorMessage
                    ?? "Unknown refresh error"
            )
        }
    }

    private var listPane: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                TextField(
                    "Search sessions",
                    text: $searchText
                )
                .textFieldStyle(.roundedBorder)

                Button {
                    Task {
                        await beginCreateDynamicSession()
                    }
                } label: {
                    Image(systemName: "plus")
                }
                .buttonStyle(.borderless)
                .help("Create dynamic session")
                .disabled(
                    isLoadingDynamicEditor
                    || isSavingDynamicSession
                )

                Button {
                    Task {
                        await reloadSessions()
                    }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("Refresh sessions")
                .disabled(isLoading)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)

            Divider()

            Group {
                if isLoading && sessions.isEmpty {
                    ProgressView("Loading sessions…")
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity
                        )

                } else if let errorMessage,
                          sessions.isEmpty {
                    ContentUnavailableView {
                        Label(
                            "Unable to load sessions",
                            systemImage: "exclamationmark.triangle"
                        )
                    } description: {
                        Text(errorMessage)
                            .textSelection(.enabled)
                    } actions: {
                        Button("Try Again") {
                            Task {
                                await reloadSessions()
                            }
                        }
                    }
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )

                } else if filteredSessions.isEmpty {
                    ContentUnavailableView.search(
                        text: searchText
                    )
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )

                } else {
                    List(
                        filteredSessions,
                        selection: $selectedSessionID
                    ) { session in
                        SessionRow(session: session)
                            .tag(session.id)
                    }
                    .listStyle(.inset)
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )
                }
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )

            Divider()

            HStack {
                Text(
                    "\(filteredSessions.count) session\(filteredSessions.count == 1 ? "" : "s")"
                )
                .font(.caption)
                .foregroundStyle(.secondary)

                Spacer()

                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
        }
        .frame(
            maxWidth: .infinity,
            maxHeight: .infinity
        )
    }

    @ViewBuilder
    private var detailPane: some View {
        if let session = selectedSession {
            VStack(spacing: 0) {
                sessionHeader(session)

                Divider()

                Picker(
                    "Session workspace",
                    selection: $selectedWorkspaceTab
                ) {
                    ForEach(SessionWorkspaceTab.allCases) { tab in
                        Text(tab.rawValue)
                            .tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 430)
                .padding(.horizontal, 24)
                .padding(.vertical, 12)
                .onChange(
                    of: selectedWorkspaceTab
                ) {
                    if selectedWorkspaceTab
                        == .changes {
                        Task {
                            await loadSessionChanges()
                        }
                    }
                }

                Divider()

                Group {
                    if isLoadingSessionDetail {
                        VStack(spacing: 10) {
                            ProgressView()
                            Text("Resuming session context…")
                                .foregroundStyle(.secondary)
                        }
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity
                        )

                    } else if let sessionDetailErrorMessage {
                        ContentUnavailableView {
                            Label(
                                "Unable to resume session",
                                systemImage: "exclamationmark.triangle"
                            )
                        } description: {
                            Text(sessionDetailErrorMessage)
                                .textSelection(.enabled)
                        } actions: {
                            Button("Try Again") {
                                Task {
                                    await loadSelectedSessionDetail()
                                }
                            }
                        }
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity
                        )

                    } else if let detail = sessionDetail,
                              detail.sessionName == session.name {
                        switch selectedWorkspaceTab {
                        case .conversation:
                            conversationWorkspace(
                                session: session,
                                detail: detail
                            )

                        case .context:
                            contextWorkspace(
                                session: session,
                                detail: detail
                            )

                        case .changes:
                            changesWorkspace(
                                session: session
                            )
                        }

                    } else {
                        ProgressView()
                            .frame(
                                maxWidth: .infinity,
                                maxHeight: .infinity
                            )
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )

        } else {
            ContentUnavailableView(
                "Select a session",
                systemImage: "bubble.left.and.bubble.right",
                description: Text(
                    "Choose a saved session to view its details."
                )
            )
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )
        }
    }

    private func sessionHeader(
        _ session: SavedSession
    ) -> some View {
        VStack(
            alignment: .leading,
            spacing: 12
        ) {
            HStack(
                alignment: .center,
                spacing: 12
            ) {
                VStack(
                    alignment: .leading,
                    spacing: 4
                ) {
                    Text(session.name)
                        .font(.title2)
                        .fontWeight(.semibold)
                        .lineLimit(1)

                    Text(
                        "\(session.meetingCount) meeting\(session.meetingCount == 1 ? "" : "s") • \(session.turnCount) conversation turn\(session.turnCount == 1 ? "" : "s")"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                Spacer()

                SessionTypeBadge(
                    session: session
                )
            }

            HStack(spacing: 8) {
                if session.isDynamic {
                    Button {
                        Task {
                            await beginEditDynamicSession(
                                session
                            )
                        }
                    } label: {
                        Label(
                            "Edit Criteria",
                            systemImage: "slider.horizontal.3"
                        )
                    }
                    .buttonStyle(.bordered)
                    .disabled(
                        isLoadingDynamicEditor
                        || isSavingDynamicSession
                        || isRefreshingSession
                    )

                    Button {
                        Task {
                            await refreshSelectedSession()
                        }
                    } label: {
                        if isRefreshingSession {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Label(
                                "Refresh",
                                systemImage: "arrow.clockwise"
                            )
                        }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isRefreshingSession)
                }

                Spacer()

                Menu {
                    Button {
                        renameText = session.name
                        renameErrorMessage = nil
                        isShowingRenameSheet = true
                    } label: {
                        Label(
                            "Rename Session",
                            systemImage: "pencil"
                        )
                    }

                    Divider()

                    Button(
                        role: .destructive
                    ) {
                        isShowingDeleteConfirmation = true
                    } label: {
                        Label(
                            "Delete Session",
                            systemImage: "trash"
                        )
                    }
                } label: {
                    Label(
                        "More",
                        systemImage: "ellipsis.circle"
                    )
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                .disabled(
                    isRenamingSession
                    || isDeletingSession
                )
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
    }

    private func conversationWorkspace(
        session: SavedSession,
        detail: SessionDetail
    ) -> some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(
                        alignment: .leading,
                        spacing: 14
                    ) {
                        if detail.conversation.isEmpty
                            && pendingSessionPrompt == nil {
                            ContentUnavailableView(
                                "No conversation yet",
                                systemImage: "bubble.left",
                                description: Text(
                                    "Ask a question below to start this session conversation."
                                )
                            )
                            .frame(
                                maxWidth: .infinity,
                                minHeight: 220
                            )
                        } else {
                            if !detail.conversation.isEmpty {
                                MeetingMarkdownView(
                                    markdown: conversationMarkdown(
                                        detail.conversation
                                    )
                                )
                            }

                            if let pendingSessionPrompt {
                                Divider()

                                MeetingMarkdownView(
                                    markdown:
                                        "## You\n\n\(pendingSessionPrompt)"
                                )

                                HStack(spacing: 10) {
                                    ProgressView()
                                        .controlSize(.small)

                                    Text("Qwen is working…")
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }

                        Color.clear
                            .frame(height: 1)
                            .id("conversation-bottom")
                    }
                    .frame(
                        maxWidth: .infinity,
                        alignment: .leading
                    )
                    .padding(.horizontal, 24)
                    .padding(.vertical, 18)
                }
                .onAppear {
                    scrollConversationToBottom(
                        proxy,
                        animated: false
                    )
                }
                .onChange(
                    of: detail.conversation.count
                ) {
                    scrollConversationToBottom(
                        proxy,
                        animated: true
                    )
                }
                .onChange(
                    of: pendingSessionPrompt
                ) {
                    scrollConversationToBottom(
                        proxy,
                        animated: true
                    )
                }
            }

            Divider()

            sessionComposer(session)
        }
    }

    private func conversationMarkdown(
        _ items: [SessionConversationItem]
    ) -> String {
        items
            .map { item in
                let speaker =
                    item.isUser
                        ? "You"
                        : "Assistant"

                return
                    "## \(speaker)\n\n\(item.content)"
            }
            .joined(
                separator: "\n\n"
            )
    }

    private func sessionComposer(
        _ session: SavedSession
    ) -> some View {
        VStack(
            alignment: .leading,
            spacing: 10
        ) {
            PromptFavoritesBar(
                promptText:
                    $sessionQueryText,
                onSelect: { favorite in
                    sessionQueryMode =
                        favorite.category
                            == "changes"
                                ? "changes"
                                : "normal"
                }
            )

            Divider()

            HStack {
                Text("Ask this Session")
                    .font(.headline)

                Spacer()

                if let sessionQueryStatusMessage,
                   !isRunningSessionQuery {
                    Text(sessionQueryStatusMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            HStack(
                alignment: .bottom,
                spacing: 10
            ) {
                TextEditor(
                    text: $sessionQueryText
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
                .disabled(isRunningSessionQuery)

                Button {
                    Task {
                        await sendSessionQuery()
                    }
                } label: {
                    ZStack {
                        Label(
                            "Send",
                            systemImage:
                                "paperplane.fill"
                        )
                        .opacity(
                            isRunningSessionQuery
                                ? 0
                                : 1
                        )

                        if isRunningSessionQuery {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                    .frame(
                        minWidth: 72,
                        minHeight: 30
                    )
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(
                    .return,
                    modifiers: [.command]
                )
                .disabled(
                    isRunningSessionQuery
                    || sessionQueryText
                        .trimmingCharacters(
                            in: .whitespacesAndNewlines
                        )
                        .isEmpty
                )
            }

            if let sessionQueryErrorMessage {
                Text(sessionQueryErrorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            } else {
                Text("⌘↩ sends")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(.background)
    }

    private func changesWorkspace(
        session: SavedSession
    ) -> some View {
        Group {
            if isLoadingSessionChanges {
                VStack(spacing: 10) {
                    ProgressView()

                    Text(
                        "Loading Changes…"
                    )
                    .foregroundStyle(.secondary)
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )

            } else if let sessionChangesError {
                ContentUnavailableView {
                    Label(
                        "Unable to compare meetings",
                        systemImage:
                            "exclamationmark.triangle"
                    )
                } description: {
                    Text(sessionChangesError)
                        .textSelection(.enabled)
                } actions: {
                    Button("Try Again") {
                        Task {
                            await loadSessionChanges(
                                force: true
                            )
                        }
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )

            } else if let changes =
                sessionChanges {
                ScrollView {
                    VStack(
                        alignment: .leading,
                        spacing: 14
                    ) {
                        if changes.available {
                            HStack {
                                VStack(
                                    alignment: .leading,
                                    spacing: 3
                                ) {
                                    Text(
                                        "What changed since last time?"
                                    )
                                    .font(.headline)

                                    if let generatedAt =
                                        formattedChangesTimestamp(
                                            changes.generatedAt
                                        ) {
                                        Text(
                                            "Last Run: \(generatedAt)"
                                        )
                                        .font(.caption)
                                        .foregroundStyle(
                                            .secondary
                                        )
                                    }

                                    if let previous =
                                        changes.previousLabel,
                                       let latest =
                                        changes.latestLabel {
                                        Text(
                                            "Compared: \(previous)  →  \(latest)"
                                        )
                                        .font(.caption)
                                        .foregroundStyle(
                                            .secondary
                                        )
                                    }

                                    if changes.isStale {
                                        Label(
                                            "New meetings available",
                                            systemImage:
                                                "clock.badge.exclamationmark"
                                        )
                                        .font(.caption)
                                        .foregroundStyle(.orange)
                                    }
                                }

                                Spacer()

                                Button {
                                    Task {
                                        await loadSessionChanges(
                                            force: true
                                        )
                                    }
                                } label: {
                                    Label(
                                        "Refresh",
                                        systemImage:
                                            "arrow.clockwise"
                                    )
                                }
                                .buttonStyle(.bordered)
                            }

                            MeetingMarkdownView(
                                markdown:
                                    changes.markdown
                            )

                            Text(
                                String(
                                    format:
                                        "Generated in %.1f sec",
                                    changes.elapsedSeconds
                                )
                            )
                            .font(.caption2)
                            .foregroundStyle(.tertiary)

                        } else {
                            ContentUnavailableView(
                                "Not enough meetings yet",
                                systemImage:
                                    "arrow.left.arrow.right",
                                description: Text(
                                    changes.markdown
                                )
                            )
                            .frame(
                                maxWidth: .infinity,
                                minHeight: 260
                            )
                        }
                    }
                    .frame(
                        maxWidth: .infinity,
                        alignment: .leading
                    )
                    .padding(.horizontal, 24)
                    .padding(.vertical, 18)
                }

            } else {
                ContentUnavailableView {
                    Label(
                        "Compare recent meetings",
                        systemImage:
                            "arrow.left.arrow.right"
                    )
                } description: {
                    Text(
                        "Compare the two most recent meetings in this session."
                    )
                } actions: {
                    Button(
                        "What changed since last time?"
                    ) {
                        Task {
                            await loadSessionChanges(
                                force: true
                            )
                        }
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    maxHeight: .infinity
                )
            }
        }
    }

    @MainActor
    private func loadSessionChanges(
        force: Bool = false
    ) async {
        guard
            let session =
                selectedSession,
            !isLoadingSessionChanges
        else {
            return
        }

        if sessionChanges != nil,
           !force {
            return
        }

        isLoadingSessionChanges = true
        sessionChangesError = nil

        defer {
            isLoadingSessionChanges = false
        }

        do {
            sessionChanges =
                try await backend
                    .loadSessionChanges(
                        name: session.name,
                        force: force
                    )

        } catch {
            sessionChangesError =
                error.localizedDescription
        }
    }

    private func formattedChangesTimestamp(
        _ rawValue: String?
    ) -> String? {
        guard let rawValue, !rawValue.isEmpty else {
            return nil
        }

        let isoFormatter = ISO8601DateFormatter()
        guard let date = isoFormatter.date(
            from: rawValue
        ) else {
            return rawValue
        }

        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    private func contextWorkspace(
        session: SavedSession,
        detail: SessionDetail
    ) -> some View {
        ScrollView {
            VStack(
                alignment: .leading,
                spacing: 12
            ) {
                Text("Session Context")
                    .font(.headline)

                SelectableStructuredTextView(
                    text: contextDocumentText(
                        session: session,
                        detail: detail
                    )
                )
            }
            .frame(
                maxWidth: .infinity,
                alignment: .leading
            )
            .padding(24)
        }
    }

    private func contextDocumentText(
        session: SavedSession,
        detail: SessionDetail
    ) -> String {
        var sections: [String] = [
            detail.prepText,
        ]

        let criteriaText: String

        if session.criteria.isEmpty {
            criteriaText =
                session.isDynamic
                    ? "No criteria available"
                    : "Fixed/manual meeting selection"
        } else {
            criteriaText = session.criteria
                .map { "• \($0)" }
                .joined(separator: "\n")
        }

        sections.append(
            "CRITERIA\n--------\n\(criteriaText)"
        )

        if !session.tooltip.isEmpty {
            sections.append(
                "BROWSER DETAILS\n---------------\n\(session.tooltip)"
            )
        }

        sections.append(
            "SAVED SESSION FILE\n------------------\n\(session.path)"
        )

        return sections.joined(
            separator: "\n\n"
        )
    }

    private func scrollConversationToBottom(
        _ proxy: ScrollViewProxy,
        animated: Bool
    ) {
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(
                        "conversation-bottom",
                        anchor: .bottom
                    )
                }
            } else {
                proxy.scrollTo(
                    "conversation-bottom",
                    anchor: .bottom
                )
            }
        }
    }

    private func metric(
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

            Text(value)
                .font(.title3)
                .fontWeight(.semibold)
        }
    }

    @MainActor
    private func loadSelectedSessionDetail(
        resetQueryState: Bool = true
    ) async {
        sessionChanges = nil
        sessionChangesError = nil

        guard let selectedSession else {
            sessionDetail = nil
            sessionDetailErrorMessage = nil
            pendingSessionPrompt = nil
            return
        }

        let requestedID = selectedSession.id
        let requestedName = selectedSession.name

        if resetQueryState {
            sessionQueryText = ""
            sessionQueryMode = "normal"
            sessionQueryStatusMessage = nil
            sessionQueryErrorMessage = nil
            pendingSessionPrompt = nil
            selectedWorkspaceTab = .conversation
        }

        isLoadingSessionDetail = true
        sessionDetailErrorMessage = nil

        defer {
            if selectedSessionID == requestedID {
                isLoadingSessionDetail = false
            }
        }

        do {
            let detail =
                try await backend.loadSessionDetail(
                    name: requestedName
                )

            guard selectedSessionID == requestedID else {
                return
            }

            sessionDetail = detail

        } catch {
            guard selectedSessionID == requestedID else {
                return
            }

            sessionDetailErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func sendSessionQuery() async {
        guard let selectedSession,
              !isRunningSessionQuery
        else {
            return
        }

        let prompt = sessionQueryText
            .trimmingCharacters(
                in: .whitespacesAndNewlines
            )

        guard !prompt.isEmpty else {
            return
        }

        let requestedID = selectedSession.id
        let requestedName = selectedSession.name
        let activeQueryMode = sessionQueryMode

        selectedWorkspaceTab = .conversation
        pendingSessionPrompt = prompt
        sessionQueryText = ""
        isRunningSessionQuery = true
        sessionQueryStatusMessage = nil
        sessionQueryErrorMessage = nil

        defer {
            isRunningSessionQuery = false
        }

        do {
            let result =
                try await backend.runSessionQuery(
                    name: requestedName,
                    prompt: prompt,
                    queryMode: activeQueryMode
                )

            guard selectedSessionID == requestedID else {
                return
            }

            let elapsedText = String(
                format: "%.1fs",
                result.elapsedSeconds
            )

            await reloadSessions()

            guard selectedSessionID == requestedID else {
                return
            }

            await loadSelectedSessionDetail(
                resetQueryState: false
            )

            pendingSessionPrompt = nil
            sessionQueryMode = "normal"
            sessionQueryStatusMessage =
                "\(result.statusText) · \(elapsedText)"

        } catch {
            guard selectedSessionID == requestedID else {
                return
            }

            pendingSessionPrompt = nil
            sessionQueryText = prompt
            sessionQueryErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func beginCreateDynamicSession() async {
        guard !isLoadingDynamicEditor else {
            return
        }

        isLoadingDynamicEditor = true
        dynamicEditorErrorMessage = nil

        defer {
            isLoadingDynamicEditor = false
        }

        do {
            let editor =
                try await backend.loadDynamicSessionEditor()

            applyDynamicEditor(
                editor
            )
            dynamicSessionName = ""
            isShowingDynamicEditor = true

        } catch {
            dynamicEditorErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func beginEditDynamicSession(
        _ session: SavedSession
    ) async {
        guard session.isDynamic,
              !isLoadingDynamicEditor
        else {
            return
        }

        isLoadingDynamicEditor = true
        dynamicEditorErrorMessage = nil

        defer {
            isLoadingDynamicEditor = false
        }

        do {
            let editor =
                try await backend.loadDynamicSessionEditor(
                    name: session.name
                )

            applyDynamicEditor(
                editor
            )
            isShowingDynamicEditor = true

        } catch {
            dynamicEditorErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func applyDynamicEditor(
        _ editor: DynamicSessionEditorResponse
    ) {
        dynamicEditorMode = editor.mode
        dynamicSessionName = editor.sessionName
        dynamicPerson = editor.person
        dynamicTitle = editor.title
        dynamicTopic = editor.topic
        dynamicHistoryOptions =
            editor.historyOptions
        dynamicHistoryLabel =
            editor.selectedHistoryLabel
        dynamicCustomRangeLabel =
            editor.customRangeLabel
        dynamicEditorErrorMessage = nil
    }

    @MainActor
    private func saveDynamicSessionEditor() async {
        guard !isSavingDynamicSession else {
            return
        }

        let sessionName = dynamicSessionName
            .trimmingCharacters(
                in: .whitespacesAndNewlines
            )

        guard !sessionName.isEmpty else {
            dynamicEditorErrorMessage =
                "Enter a session name."
            return
        }

        isSavingDynamicSession = true
        dynamicEditorErrorMessage = nil

        defer {
            isSavingDynamicSession = false
        }

        do {
            let result: DynamicSessionChangeResponse

            if dynamicEditorMode == "create" {
                result =
                    try await backend.createDynamicSession(
                        name: sessionName,
                        person: dynamicPerson,
                        title: dynamicTitle,
                        topic: dynamicTopic,
                        historyLabel:
                            dynamicHistoryLabel
                    )
            } else {
                result =
                    try await backend.editDynamicSession(
                        name: sessionName,
                        person: dynamicPerson,
                        title: dynamicTitle,
                        topic: dynamicTopic,
                        historyLabel:
                            dynamicHistoryLabel
                    )
            }

            isShowingDynamicEditor = false

            await reloadSessions()

            if let session = sessions.first(
                where: {
                    $0.name == result.sessionName
                }
            ) {
                selectedSessionID =
                    session.id
            }

            if dynamicEditorMode == "create" {
                dynamicEditorResultMessage =
                    "Dynamic session created.\n\nMeetings: \(result.meetingCount)"
            } else {
                dynamicEditorResultMessage =
                    "Dynamic session updated.\n\nAdded: \(result.added)\nRemoved: \(result.removed)\nUnchanged: \(result.unchanged)\nMeetings: \(result.meetingCount)"
            }

        } catch {
            dynamicEditorErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func deleteSelectedSession() async {
        guard let selectedSession,
              !isDeletingSession
        else {
            return
        }

        isDeletingSession = true
        deleteErrorMessage = nil

        defer {
            isDeletingSession = false
        }

        do {
            let result =
                try await backend.deleteSession(
                    name: selectedSession.name
                )

            guard result.deleted else {
                deleteErrorMessage =
                    "The session was not deleted."
                return
            }

            selectedSessionID = nil
            await reloadSessions()

        } catch {
            deleteErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func renameSelectedSession() async {
        guard let selectedSession,
              !isRenamingSession
        else {
            return
        }

        let proposedName = renameText
            .trimmingCharacters(
                in: .whitespacesAndNewlines
            )

        guard !proposedName.isEmpty else {
            renameErrorMessage =
                "Enter a session name."
            return
        }

        isRenamingSession = true
        renameErrorMessage = nil

        defer {
            isRenamingSession = false
        }

        do {
            let result =
                try await backend.renameSession(
                    oldName: selectedSession.name,
                    newName: proposedName
                )

            isShowingRenameSheet = false

            await reloadSessions()

            if let renamedSession = sessions.first(
                where: {
                    $0.name == result.newName
                }
            ) {
                selectedSessionID =
                    renamedSession.id
            }

        } catch {
            renameErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func refreshSelectedSession() async {
        guard let selectedSession,
              selectedSession.isDynamic,
              !isRefreshingSession
        else {
            return
        }

        let selectedID = selectedSession.id

        isRefreshingSession = true
        refreshResultMessage = nil
        refreshErrorMessage = nil

        defer {
            isRefreshingSession = false
        }

        do {
            let result =
                try await backend.refreshSession(
                    name: selectedSession.name
                )

            await reloadSessions()
            selectedSessionID = selectedID

            if result.isAlreadyCurrent {
                refreshResultMessage =
                    "No meeting changes were found.\n\nUnchanged: \(result.unchanged)\nMeetings: \(result.meetingCount)"
            } else {
                refreshResultMessage =
                    "Session refreshed.\n\nAdded: \(result.added)\nRemoved: \(result.removed)\nUnchanged: \(result.unchanged)\nMeetings: \(result.meetingCount)"
            }

        } catch {
            refreshErrorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func reloadSessions() async {
        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            let loaded =
                try await backend.loadSessions()

            sessions = loaded

            if let requestedName = navigation.requestedSessionName,
               let requestedSession = loaded.first(
                    where: {
                        $0.name == requestedName
                            || $0.id == requestedName
                    }
               ) {
                selectedSessionID = requestedSession.id
                selectedWorkspaceTab = .conversation
                navigation.requestedSessionName = nil
            }

            if let selectedSessionID,
               !loaded.contains(
                    where: {
                        $0.id == selectedSessionID
                    }
               ) {
                self.selectedSessionID = nil
                sessionDetail = nil
                sessionDetailErrorMessage = nil
            }

        } catch {
            errorMessage =
                error.localizedDescription
        }
    }
}

private struct SessionRow: View {
    let session: SavedSession

    var body: some View {
        HStack(
            alignment: .center,
            spacing: 10
        ) {
            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text(session.name)
                    .fontWeight(.medium)
                    .lineLimit(1)

                Text(
                    "\(session.meetingCount) meeting\(session.meetingCount == 1 ? "" : "s") • \(session.turnCount) turn\(session.turnCount == 1 ? "" : "s")"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer(minLength: 12)

            SessionTypeBadge(
                session: session
            )
        }
        .padding(.vertical, 4)
        .help(session.tooltip)
    }
}

private struct SessionTypeBadge: View {
    let session: SavedSession

    var body: some View {
        Label(
            session.typeDisplayName,
            systemImage:
                session.isDynamic
                    ? "arrow.triangle.2.circlepath"
                    : "pin.fill"
        )
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(
            Capsule()
                .fill(.quaternary)
        )
        .fixedSize()
    }
}
