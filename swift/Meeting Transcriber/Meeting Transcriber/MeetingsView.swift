import SwiftUI

struct MeetingsView: View {
    @EnvironmentObject
    private var meetingContextController:
        MeetingContextController

    @EnvironmentObject
    private var navigation: AppNavigationController

    private enum MeetingWorkspaceTab:
        String,
        CaseIterable,
        Identifiable
    {
        case meeting = "Meeting"
        case context = "Context"

        var id: String {
            rawValue
        }
    }

    enum StatusFilter: String, CaseIterable, Identifiable {
        case all = "All statuses"
        case published = "Published"
        case unpublished = "Unpublished"

        var id: Self { self }
    }

    @State private var meetings: [Meeting] = []
    @State private var selectedMeetingID: Meeting.ID?

    @State private var selectedWorkspaceTab:
        MeetingWorkspaceTab = .meeting

    @State private var isLoading = false
    @State private var errorMessage: String?

    @State private var meetingDetail: MeetingDetail?
    @State private var isLoadingDetail = false
    @State private var detailErrorMessage: String?

    @State private var isPublishing = false
    @State private var showingPublishConfirmation = false
    @State private var publishErrorMessage: String?

    @State private var isDeletingMeeting = false
    @State private var showingDeleteConfirmation = false
    @State private var pendingDeletePlan: MeetingDeletePlanResponse?
    @State private var deleteErrorMessage: String?
    @State private var transcriptionQueueCleanupRequest:
        MeetingTranscriptionQueueCleanupRequest?

    @State private var isUnpublishing = false
    @State private var showingUnpublishConfirmation = false
    @State private var pendingUnpublishPlan: MeetingUnpublishPlanResponse?
    @State private var unpublishErrorMessage: String?
    @State private var unpublishSuccessMessage: String?

    @State private var isShowingContextMeetings = false

    @State private var isShowingSaveContextSessionSheet = false
    @State private var saveContextSessionName = ""
    @State private var isSavingContextSession = false
    @State private var saveContextSessionError: String?
    @State private var saveContextSessionResult: String?

    private let backend = BackendService()

    private var filteredMeetings: [Meeting] {
        meetings.filter { meeting in
            let matchesStatus: Bool

            switch statusFilter {
            case .all:
                matchesStatus = true
            case .published:
                matchesStatus = meeting.isPublished
            case .unpublished:
                matchesStatus = !meeting.isPublished
            }

            guard matchesStatus else {
                return false
            }

            let query = searchText
                .trimmingCharacters(in: .whitespacesAndNewlines)

            guard !query.isEmpty else {
                return true
            }

            return meeting.title.localizedCaseInsensitiveContains(query)
                || meeting.run.localizedCaseInsensitiveContains(query)
                || meeting.participants.contains {
                    $0.localizedCaseInsensitiveContains(query)
                }
        }
    }

    private var selectedMeeting: Meeting? {
        guard let selectedMeetingID else {
            return nil
        }

        return meetings.first {
            $0.id == selectedMeetingID
        }
    }

    private var contextMeetingIDs:
        Set<Meeting.ID>
    {
        meetingContextController
            .meetingIDs
    }

    private var builtContext:
        MeetingContextResponse?
    {
        meetingContextController
            .builtContext
    }

    private var contextConversation:
        [SessionConversationItem]
    {
        meetingContextController
            .conversation
    }

    private var isBuildingContext:
        Bool
    {
        meetingContextController
            .isBuildingContext
    }

    private var isRunningContextQuery:
        Bool
    {
        meetingContextController
            .isRunningQuery
    }

    private var contextErrorMessage:
        String?
    {
        meetingContextController
            .errorMessage
    }

    private var contextStatusMessage:
        String?
    {
        if !isRunningContextQuery,
           let preview =
            meetingContextController
                .planPreviewMessage {
            return preview
        }

        return meetingContextController
            .statusMessage
    }

    private var searchText:
        String
    {
        meetingContextController
            .searchText
    }

    private var statusFilter:
        StatusFilter
    {
        StatusFilter(
            rawValue:
                meetingContextController
                    .statusFilterRawValue
        ) ?? .all
    }

    private var statusFilterBinding:
        Binding<StatusFilter>
    {
        Binding(
            get: {
                statusFilter
            },
            set: { newValue in
                meetingContextController
                    .statusFilterRawValue =
                        newValue.rawValue
            }
        )
    }

    private var contextMeetingRuns:
        [String]
    {
        meetings
            .filter {
                contextMeetingIDs
                    .contains($0.id)
            }
            .map(\.run)
            .sorted()
    }

    private var contextSelectionCount:
        Int
    {
        contextMeetingIDs.count
    }

    var body: some View {
        GeometryReader { geometry in
            HSplitView {
                meetingListPane
                    .frame(
                        minWidth: 300,
                        idealWidth: 360,
                        maxWidth: 460,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )

                detailPane
                    .frame(
                        minWidth: 650,
                        idealWidth: 900,
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
        .background {
            MeetingTranscriptionQueueCleanupBridge(
                request: transcriptionQueueCleanupRequest
            )
            .frame(width: 0, height: 0)
        }
        .navigationTitle("Meetings")
        .task {
            await reloadMeetings()
        }
        .task(id: selectedMeetingID) {
            await reloadSelectedMeetingDetail()
        }
        .onChange(
            of: selectedMeetingID
        ) {
            if selectedMeetingID != nil {
                selectedWorkspaceTab =
                    .meeting
            }
        }
        .confirmationDialog(
            "Publish & Archive this meeting?",
            isPresented: $showingPublishConfirmation,
            titleVisibility: .visible
        ) {
            Button("Publish & Archive") {
                Task {
                    await publishSelectedMeeting()
                }
            }

            Button("Cancel", role: .cancel) {
            }
        } message: {
            Text(
                "This will run the existing Meeting Transcriber publish workflow, archive the meeting, refresh the dashboard/index, and apply configured cleanup rules."
            )
        }
        .alert(
            "Publish Failed",
            isPresented: Binding(
                get: {
                    publishErrorMessage != nil
                },
                set: { showing in
                    if !showing {
                        publishErrorMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                publishErrorMessage = nil
            }
        } message: {
            Text(
                publishErrorMessage
                    ?? "Unknown publish error"
            )
        }
        .confirmationDialog(
            "Delete this meeting?",
            isPresented: $showingDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button("Delete Meeting, Keep Recording") {
                Task {
                    await deleteSelectedMeeting(
                        operation: .keepRecording
                    )
                }
            }
            .keyboardShortcut(.defaultAction)

            Button("Delete Meeting and Recording", role: .destructive) {
                Task {
                    await deleteSelectedMeeting(
                        operation: .deleteRecording
                    )
                }
            }
            .disabled(
                !(pendingDeletePlan?.sourceFound == true
                    && pendingDeletePlan?.sourceIsManaged == true)
            )

            Button("Cancel", role: .cancel) {
                pendingDeletePlan = nil
            }
        } message: {
            if let plan = pendingDeletePlan {
                Text(deleteConfirmationMessage(plan))
            } else {
                Text("This meeting and its generated artifacts will be removed.")
            }
        }
        .alert(
            "Delete Failed",
            isPresented: Binding(
                get: { deleteErrorMessage != nil },
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
            Text(deleteErrorMessage ?? "Unknown delete error")
        }
        .confirmationDialog(
            "Unpublish this meeting?",
            isPresented: $showingUnpublishConfirmation,
            titleVisibility: .visible
        ) {
            Button(
                unpublishUsesPermanentArchiveDeletion
                    ? "Unpublish & Permanently Delete Archive"
                    : "Unpublish Meeting",
                role: .destructive
            ) {
                Task {
                    await unpublishSelectedMeeting()
                }
            }

            Button("Cancel", role: .cancel) {
                pendingUnpublishPlan = nil
            }
        } message: {
            if let plan = pendingUnpublishPlan {
                Text(unpublishConfirmationMessage(plan))
            } else {
                Text("This meeting will be removed from the published archive and returned to Unpublished status.")
            }
        }
        .alert(
            "Unpublish Failed",
            isPresented: Binding(
                get: { unpublishErrorMessage != nil },
                set: { showing in
                    if !showing {
                        unpublishErrorMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                unpublishErrorMessage = nil
            }
        } message: {
            Text(unpublishErrorMessage ?? "Unknown unpublish error")
        }
        .alert(
            "Meeting Unpublished",
            isPresented: Binding(
                get: { unpublishSuccessMessage != nil },
                set: { showing in
                    if !showing {
                        unpublishSuccessMessage = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                unpublishSuccessMessage = nil
            }
        } message: {
            Text(unpublishSuccessMessage ?? "The meeting was unpublished.")
        }
        .sheet(
            isPresented:
                $isShowingSaveContextSessionSheet
        ) {
            VStack(
                alignment: .leading,
                spacing: 16
            ) {
                Text("Save Meeting Context")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text(
                    "Save these meetings and the current conversation as a fixed Session."
                )
                .font(.caption)
                .foregroundStyle(.secondary)

                TextField(
                    "Session name",
                    text:
                        $saveContextSessionName
                )
                .textFieldStyle(.roundedBorder)

                if let saveContextSessionError {
                    Text(saveContextSessionError)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }

                HStack {
                    Spacer()

                    Button("Cancel") {
                        isShowingSaveContextSessionSheet = false
                    }
                    .keyboardShortcut(.cancelAction)
                    .disabled(isSavingContextSession)

                    Button("Save Session") {
                        Task {
                            await saveCurrentContextAsSession()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(
                        isSavingContextSession
                        || saveContextSessionName
                            .trimmingCharacters(
                                in: .whitespacesAndNewlines
                            )
                            .isEmpty
                    )
                }
            }
            .padding(24)
            .frame(width: 440)
        }
        .alert(
            "Session Saved",
            isPresented: Binding(
                get: {
                    saveContextSessionResult != nil
                },
                set: { showing in
                    if !showing {
                        saveContextSessionResult = nil
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                saveContextSessionResult = nil
            }
        } message: {
            Text(saveContextSessionResult ?? "")
        }
    }

    private var meetingListPane: some View {
        VStack(spacing: 0) {
            controls
                .padding(.horizontal, 12)
                .padding(.top, 10)
                .padding(.bottom, 8)

            Divider()

            Group {
                if isLoading && meetings.isEmpty {
                    ProgressView("Loading meetings…")
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity
                        )

                } else if let errorMessage,
                          meetings.isEmpty {
                    ContentUnavailableView {
                        Label(
                            "Unable to load meetings",
                            systemImage: "exclamationmark.triangle"
                        )
                    } description: {
                        Text(errorMessage)
                            .textSelection(.enabled)
                    } actions: {
                        Button("Try Again") {
                            Task {
                                await reloadMeetings()
                            }
                        }
                    }
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )

                } else if filteredMeetings.isEmpty {
                    ContentUnavailableView.search(
                        text: searchText
                    )
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity
                    )

                } else {
                    List(
                        filteredMeetings,
                        selection: $selectedMeetingID
                    ) { meeting in
                        MeetingRow(
                            meeting: meeting,
                            isInContext:
                                contextMeetingIDs
                                    .contains(
                                        meeting.id
                                    ),
                            toggleContext: {
                                toggleMeetingContext(
                                    meeting
                                )
                            }
                        )
                        .tag(meeting.id)
                    }
                    .listStyle(.inset)
                    .frame(
                        maxWidth: .infinity,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )
                }
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity,
                alignment: .topLeading
            )

            Divider()

            VStack(spacing: 8) {
                HStack {
                    Text(
                        "\(filteredMeetings.count) meeting\(filteredMeetings.count == 1 ? "" : "s")"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    Spacer()

                    if isLoading {
                        ProgressView()
                            .controlSize(.small)
                    }
                }

                HStack(spacing: 8) {
                    Text(
                        "Selected: \(contextSelectionCount)"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)

                    Spacer()

                    Button("Clear") {
                        clearContextSelection()
                    }
                    .disabled(
                        contextMeetingIDs.isEmpty
                        || isBuildingContext
                    )

                    Button {
                        Task {
                            await buildSelectedContext()
                        }
                    } label: {
                        if isBuildingContext {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text("Build Context")
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        contextMeetingIDs.isEmpty
                        || isBuildingContext
                    )
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .frame(
            maxWidth: .infinity,
            maxHeight: .infinity,
            alignment: .topLeading
        )
    }

    private var controls: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                Picker(
                    "Status",
                    selection: statusFilterBinding
                ) {
                    ForEach(StatusFilter.allCases) { status in
                        Text(status.rawValue)
                            .tag(status)
                    }
                }
                .labelsHidden()
                .frame(width: 150)

                Spacer()

                Button {
                    Task {
                        await reloadMeetings()
                    }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("Refresh meetings")
                .disabled(isLoading)
            }

            TextField(
                "Search meetings",
                text:
                    $meetingContextController
                        .searchText
            )
            .textFieldStyle(.roundedBorder)
        }
    }

    private var detailPane: some View {
        VStack(spacing: 0) {
            Picker(
                "Meetings workspace",
                selection:
                    $selectedWorkspaceTab
            ) {
                ForEach(
                    MeetingWorkspaceTab.allCases
                ) { tab in
                    Text(tab.rawValue)
                        .tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 300)
            .padding(.horizontal, 24)
            .padding(.vertical, 10)

            Divider()

            Group {
                switch selectedWorkspaceTab {
                case .meeting:
                    meetingWorkspace

                case .context:
                    contextWorkspace
                }
            }
            .frame(
                maxWidth: .infinity,
                maxHeight: .infinity
            )
        }
    }

    @ViewBuilder
    private var meetingWorkspace: some View {
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

    private var contextWorkspace: some View {
        VStack(spacing: 0) {
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
                                "Refresh Context",
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



    private var meetingContextComposer:
        some View
    {
        VStack(
            alignment: .leading,
            spacing: 10
        ) {
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

    private var meetingContextConversationMarkdown:
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
    private func toggleMeetingContext(
        _ meeting: Meeting
    ) {
        meetingContextController
            .toggleMeeting(
                id: meeting.id
            )
    }

    @MainActor
    private func clearContextSelection() {
        meetingContextController
            .clearSelection()
    }

    @MainActor
    private func buildSelectedContext()
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
    private func sendContextQuery()
        async
    {
        meetingContextController
            .startQuery()
    }

    @MainActor
    private func saveCurrentContextAsSession()
        async
    {
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
            saveContextSessionResult =
                "Saved “\(result.sessionName)” with \(result.meetingCount) meeting\(result.meetingCount == 1 ? "" : "s") and \(result.turnCount) conversation turn\(result.turnCount == 1 ? "" : "s")."

        } catch {
            saveContextSessionError =
                error.localizedDescription
        }
    }

    private func meetingHeader(
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

    private func meetingDocumentMarkdown(
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

    private func summaryContainsHeading(
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

    private func detailRow(
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

    private func formattedDate(_ rawDate: String) -> String {
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

    private func deleteConfirmationMessage(
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

    private func unpublishConfirmationMessage(
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
    private func prepareDeleteSelectedMeeting() async {
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
    private func deleteSelectedMeeting(
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

    private enum PublishedArchiveDisposition {
        case systemTrash
        case permanentDelete
    }

    private var unpublishUsesPermanentArchiveDeletion: Bool {
        guard let plan = pendingUnpublishPlan else {
            return false
        }
        return archiveRequiresPermanentDeletion(plan.archivePath)
    }

    private func archiveRequiresPermanentDeletion(_ path: String?) -> Bool {
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

    private func removePublishedArchive(
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
    private func prepareUnpublishSelectedMeeting() async {
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
    private func unpublishSelectedMeeting() async {
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
    private func publishSelectedMeeting() async {
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
    private func reloadSelectedMeetingDetail() async {
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

    @MainActor
    private func reloadMeetings() async {
        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            let loadedMeetings =
                try await backend.loadMeetings()

            meetings = loadedMeetings

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

private struct MeetingRow: View {
    let meeting: Meeting
    let isInContext: Bool
    let toggleContext: () -> Void

    var body: some View {
        HStack(
            alignment: .center,
            spacing: 10
        ) {
            Button(
                action: toggleContext
            ) {
                Image(
                    systemName:
                        isInContext
                            ? "checkmark.square.fill"
                            : "square"
                )
                .imageScale(.large)
            }
            .buttonStyle(.plain)
            .help(
                isInContext
                    ? "Remove from meeting context"
                    : "Add to meeting context"
            )

            VStack(
                alignment: .leading,
                spacing: 4
            ) {
                Text(meeting.title)
                    .fontWeight(.medium)
                    .lineLimit(1)

                HStack(spacing: 6) {
                    if !meeting.date.isEmpty {
                        Text(formattedDate(meeting.date))
                    }

                    if !meeting.participants.isEmpty {
                        Text("•")

                        Text(
                            meeting.participants.joined(
                                separator: ", "
                            )
                        )
                        .lineLimit(1)
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Spacer(minLength: 12)

            StatusBadge(
                status: meeting.status,
                isPublished: meeting.isPublished
            )
        }
        .padding(.vertical, 4)
    }

    private func formattedDate(_ rawDate: String) -> String {
        let input = DateFormatter()
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd"

        guard let date = input.date(from: rawDate) else {
            return rawDate
        }

        let output = DateFormatter()
        output.locale = Locale.current
        output.dateStyle = .medium
        output.timeStyle = .none

        return output.string(from: date)
    }
}

private struct StatusBadge: View {
    let status: String
    let isPublished: Bool

    var body: some View {
        Label(
            status,
            systemImage:
                isPublished
                    ? "checkmark.circle.fill"
                    : "clock.badge.exclamationmark"
        )
        .font(.caption)
        .foregroundStyle(
            isPublished
                ? .secondary
                : .primary
        )
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(
            Capsule()
                .fill(.quaternary)
        )
        .fixedSize()
    }
}

private struct MeetingTranscriptionQueueCleanupRequest: Equatable {
    let id = UUID()
    let run: String
    let sourcePath: String?
}

private struct MeetingTranscriptionQueueCleanupBridge: View {
    @EnvironmentObject
    private var transcriptionController: TranscriptionController

    let request: MeetingTranscriptionQueueCleanupRequest?

    var body: some View {
        Color.clear
            .onChange(of: request?.id) {
                guard let request else {
                    return
                }

                transcriptionController.removeMeetingReference(
                    run: request.run,
                    sourcePath: request.sourcePath
                )
            }
    }
}
