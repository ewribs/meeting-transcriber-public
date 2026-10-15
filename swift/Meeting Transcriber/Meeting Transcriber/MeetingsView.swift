import SwiftUI

struct MeetingsView: View {
    @EnvironmentObject
    var meetingContextController:
        MeetingContextController

    @EnvironmentObject
    var navigation: AppNavigationController

    enum MeetingWorkspaceTab:
        String,
        CaseIterable,
        Identifiable
    {
        case meeting = "Meeting"
        case context = "Ask"
        case changes = "Changes"

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

    enum FolderSheetMode: Identifiable {
        case create
        case rename(String)

        var id: String {
            switch self {
            case .create:
                return "create"
            case .rename(let name):
                return "rename-\(name)"
            }
        }

        var title: String {
            switch self {
            case .create:
                return "New Folder"
            case .rename:
                return "Rename Folder"
            }
        }

        var buttonTitle: String {
            switch self {
            case .create:
                return "Create"
            case .rename:
                return "Rename"
            }
        }
    }

    @State var meetings: [Meeting] = []
    @State var selectedMeetingID: Meeting.ID?

    @State var selectedWorkspaceTab:
        MeetingWorkspaceTab = .meeting

    @State var isLoading = false
    @State var errorMessage: String?

    @State var meetingDetail: MeetingDetail?
    @State var isLoadingDetail = false
    @State var detailErrorMessage: String?

    @State var isPublishing = false
    @State var showingPublishConfirmation = false
    @State var publishErrorMessage: String?

    @State var isDeletingMeeting = false
    @State var showingDeleteConfirmation = false
    @State var pendingDeletePlan: MeetingDeletePlanResponse?
    @State var deleteErrorMessage: String?
    @State var transcriptionQueueCleanupRequest:
        MeetingTranscriptionQueueCleanupRequest?

    @State var isUnpublishing = false
    @State var showingUnpublishConfirmation = false
    @State var pendingUnpublishPlan: MeetingUnpublishPlanResponse?
    @State var unpublishErrorMessage: String?
    @State var unpublishSuccessMessage: String?

    @State var isShowingContextMeetings = false

    @State var isShowingSaveContextSessionSheet = false
    @State var saveContextSessionName = ""
    @State var isSavingContextSession = false
    @State var saveContextSessionError: String?
    @State var saveContextSessionResult: String?

    @State var addToSessionResult: String?
    @State var addToSessionTitle = "Couldn't Complete"

    static let defaultAlertTitle = "Couldn't Complete"
    @State var allSessions: [SavedSession] = []
    @State var folders: [MeetingFolder] = []
    @State var folderSheet: FolderSheetMode?
    @State var dropTargetKey: String?
    @AppStorage("meetings.recentDays") var recentDays = 14
    @AppStorage("meetings.sortOrder") var sortOrderRaw = "newest"
    @AppStorage("meetings.groupBy") var groupByRaw = "none"
    @AppStorage("meetings.railSort") var railSortRaw = "alpha"
    @State var sessionOrder = SessionOrder.empty
    @AppStorage("meetings.showRecentRow") var showRecentRow = true
    @AppStorage("meetings.showUnpublishedRow") var showUnpublishedRow = true
    @AppStorage("meetings.showUnfiledRow") var showUnfiledRow = true
    @AppStorage("meetings.showNotices") var showNotices = true
    @AppStorage("meetings.confirmFolderDelete") var confirmFolderDelete = true
    @AppStorage("ask.showFavorites") var showFavorites = true
    @State var dynamicEditorTarget: DynamicEditorTarget?
    @State var sessionRefreshedRuns: Set<String> = []
    @State var pendingDeleteSession: String?
    @State var renameSessionTarget: String?
    @State var renameSessionText = ""
    @State var renameSessionError: String?
    @State var isRenamingSession = false
    @State var folderSessionSource: String?
    @State var folderSessionName = ""
    @State var folderSessionError: String?
    @State var isMakingFolderSession = false
    @State var folderNameText = ""
    @State var folderErrorMessage: String?
    @State var isSavingFolder = false
    @State var pendingDeleteFolder: String?
    @State var pendingFolderRuns: [String] = []

    let backend = BackendService()

    var sortOrder: MeetingSortOrder {
        MeetingSortOrder(rawValue: sortOrderRaw) ?? .newest
    }

    var filteredMeetings: [Meeting] {
        sortOrder.apply(to: matchingMeetings)
    }

    var matchingMeetings: [Meeting] {
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

            if let runs = sessionFilterRuns,
               !runs.contains(meeting.run) {
                return false
            }

            if meetingContextController.showRecentOnly,
               !isRecent(meeting) {
                return false
            }

            if let runs = folderFilterRuns,
               !runs.contains(meeting.run) {
                return false
            }

            if meetingContextController.showUnfiledOnly,
               filedRuns.contains(meeting.run) {
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

    /// Every meeting that is in at least one folder.
    var filedRuns: Set<String> {
        Set(folders.flatMap(\.meetingRuns))
    }

    static let isoDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    func isRecent(
        _ meeting: Meeting
    ) -> Bool {
        guard let day = Self.isoDayFormatter.date(
            from: String(meeting.date.prefix(10))
        ) else {
            return false
        }

        let limit: Double = Double(recentDays) * 86_400

        return Date().timeIntervalSince(day) <= limit
    }

    enum LibrarySelection: Equatable {
        case all
        case recent
        case unpublished
        case unfiled
        case folder(String)
        case session(String)
    }

    var librarySelection: LibrarySelection {
        if let folder = folderFilterFolder {
            return .folder(folder.name)
        }

        if let session = sessionFilterSession {
            return .session(session.name)
        }

        if meetingContextController.showRecentOnly {
            return .recent
        }

        if meetingContextController.showUnfiledOnly {
            return .unfiled
        }

        if statusFilter == .unpublished {
            return .unpublished
        }

        return .all
    }

    var libraryTitle: String {
        switch librarySelection {
        case .all:
            return "All Meetings"
        case .recent:
            return "Recent"
        case .unpublished:
            return "Unpublished"
        case .unfiled:
            return "Not in a Folder"
        case .folder(let name):
            return name
        case .session(let name):
            return name
        }
    }

    func selectLibrary(
        _ selection: LibrarySelection
    ) {
        meetingContextController.sessionFilterName = ""
        meetingContextController.folderFilterName = ""
        meetingContextController.showRecentOnly = false
        meetingContextController.showUnfiledOnly = false
        meetingContextController.statusFilterRawValue =
            StatusFilter.all.rawValue

        switch selection {
        case .all:
            break
        case .recent:
            meetingContextController.showRecentOnly = true
        case .unpublished:
            meetingContextController.statusFilterRawValue =
                StatusFilter.unpublished.rawValue
        case .unfiled:
            meetingContextController.showUnfiledOnly = true
        case .folder(let name):
            meetingContextController.folderFilterName = name
        case .session(let name):
            meetingContextController.sessionFilterName = name
        }
    }

    var folderFilterFolder: MeetingFolder? {
        let name = meetingContextController
            .folderFilterName

        guard !name.isEmpty else {
            return nil
        }

        return folders.first {
            $0.name == name
        }
    }

    var folderFilterRuns: Set<String>? {
        guard let folder = folderFilterFolder else {
            return nil
        }

        return Set(folder.meetingRuns)
    }

    var sessionFilterSession: SavedSession? {
        let name = meetingContextController
            .sessionFilterName

        guard !name.isEmpty else {
            return nil
        }

        return allSessions.first {
            $0.name == name
        }
    }

    var sessionFilterRuns: Set<String>? {
        guard let session = sessionFilterSession else {
            return nil
        }

        return Set(session.meetingRuns ?? [])
    }

    var sessionFilterNote: String {
        if folderFilterFolder != nil {
            return " in this folder"
        }

        guard let session = sessionFilterSession else {
            return ""
        }

        return session.isDynamic
            ? " in this session (as of its last refresh)"
            : " in this session"
    }

    var selectedMeeting: Meeting? {
        guard let selectedMeetingID else {
            return nil
        }

        return meetings.first {
            $0.id == selectedMeetingID
        }
    }

    var contextMeetingIDs:
        Set<Meeting.ID>
    {
        meetingContextController
            .meetingIDs
    }

    var builtContext:
        MeetingContextResponse?
    {
        meetingContextController
            .builtContext
    }

    var contextConversation:
        [SessionConversationItem]
    {
        meetingContextController
            .conversation
    }

    var isBuildingContext:
        Bool
    {
        meetingContextController
            .isBuildingContext
    }

    var isRunningContextQuery:
        Bool
    {
        meetingContextController
            .isRunningQuery
    }

    var contextErrorMessage:
        String?
    {
        meetingContextController
            .errorMessage
    }

    var contextStatusMessage:
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

    var searchText:
        String
    {
        meetingContextController
            .searchText
    }

    var statusFilter:
        StatusFilter
    {
        StatusFilter(
            rawValue:
                meetingContextController
                    .statusFilterRawValue
        ) ?? .all
    }

    var contextMeetingRuns:
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

    var autoBuildKey: String {
        selectedWorkspaceTab.rawValue
            + "|"
            + contextMeetingIDs.sorted().joined(separator: ",")
    }

    var contextSelectionCount:
        Int
    {
        contextMeetingIDs.count
    }

    var body: some View {
        bodyPart4
    }

    var bodyPart1: some View {
        GeometryReader { geometry in
            HSplitView {
                libraryRail
                    .frame(
                        minWidth: 170,
                        idealWidth: 210,
                        maxWidth: 260,
                        maxHeight: .infinity,
                        alignment: .topLeading
                    )

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
        .task(id: autoBuildKey) {
            await autoBuildContextIfNeeded()
        }
        .onChange(
            of: selectedMeetingID
        ) {
            if selectedMeetingID != nil {
                selectedWorkspaceTab =
                    .meeting
            }
        }
    }

    var bodyPart2: some View {
        bodyPart1
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
    }

    var bodyPart3: some View {
        bodyPart2
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
        .sheet(item: $folderSheet) { mode in
            VStack(
                alignment: .leading,
                spacing: 16
            ) {
                Text(mode.title)
                    .font(.title2)
                    .fontWeight(.semibold)

                if case .create = mode,
                   !pendingFolderRuns.isEmpty {
                    Text(
                        "The \(pendingFolderRuns.count) selected meeting\(pendingFolderRuns.count == 1 ? "" : "s") will be added to it."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                TextField(
                    "Folder name",
                    text: $folderNameText
                )
                .textFieldStyle(.roundedBorder)

                if let folderErrorMessage {
                    Text(folderErrorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }

                HStack {
                    Spacer()

                    Button("Cancel") {
                        pendingFolderRuns = []
                        folderSheet = nil
                    }
                    .keyboardShortcut(.cancelAction)
                    .disabled(isSavingFolder)

                    Button(mode.buttonTitle) {
                        Task {
                            await saveFolderSheet()
                        }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(
                        isSavingFolder
                        || folderNameText
                            .trimmingCharacters(
                                in: .whitespacesAndNewlines
                            )
                            .isEmpty
                    )
                }
            }
            .padding(24)
            .frame(width: 380)
        }
    }

    var bodyPart4: some View {
        bodyPart3
        .confirmationDialog(
            "Delete Folder?",
            isPresented: Binding(
                get: {
                    pendingDeleteFolder != nil
                },
                set: { isPresented in
                    if !isPresented {
                        pendingDeleteFolder = nil
                    }
                }
            ),
            titleVisibility: .visible
        ) {
            Button(
                "Delete Folder",
                role: .destructive
            ) {
                if let name = pendingDeleteFolder {
                    Task {
                        await deleteFolder(name)
                    }
                }
            }

            Button("Cancel", role: .cancel) {
                pendingDeleteFolder = nil
            }
        } message: {
            Text(
                "The folder “\(pendingDeleteFolder ?? "")” will be deleted. The meetings in it are not deleted."
            )
        }
        .alert(
            addToSessionTitle,
            isPresented: Binding(
                get: {
                    addToSessionResult != nil
                },
                set: { isPresented in
                    if !isPresented {
                        addToSessionResult = nil
                        addToSessionTitle =
                            Self.defaultAlertTitle
                    }
                }
            )
        ) {
            Button("OK", role: .cancel) {
                addToSessionResult = nil
                addToSessionTitle = Self.defaultAlertTitle
            }
        } message: {
            Text(addToSessionResult ?? "")
        }
        .background(sessionRailDialogs)
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

    var meetingListPane: some View {
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
                    meetingListView
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
                HStack(spacing: 4) {
                    Text(
                        "\(filteredMeetings.count) meeting\(filteredMeetings.count == 1 ? "" : "s")\(sessionFilterNote)"
                            + (
                                contextSelectionCount > 0
                                    ? " · \(contextSelectionCount) selected"
                                    : ""
                            )
                    )

                    if contextSelectionCount > 0 {
                        Text("·")

                        Button("Clear") {
                            clearContextSelection()
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(Color.accentColor)
                        .disabled(isBuildingContext)
                    }

                    Spacer()

                    if isLoading {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)

                HStack(spacing: 8) {
                    Spacer()

                    addToMenu

                    Button {
                        selectedWorkspaceTab = .context
                    } label: {
                        if isBuildingContext {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text(askButtonTitle)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(askButtonDisabled)
                    .help("Open the Ask tab and ask questions")
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

    var addToMenu: some View {
        Menu("Add to") {
            Section("Folder") {
                ForEach(sortedFolders) { folder in
                    Button(folder.name) {
                        Task {
                            await addRunsToFolder(
                                folder.name,
                                contextMeetingRuns
                            )
                        }
                    }
                }

                Button("New Folder…") {
                    openCreateFolder(
                        with: contextMeetingRuns
                    )
                }
            }

            Section("Session") {
                ForEach(sortedFixedSessions) { session in
                    Button(session.name) {
                        Task {
                            await addDroppedRuns(
                                contextMeetingRuns,
                                toSession: session.name
                            )
                        }
                    }
                }

                Button("New Session…") {
                    saveContextSessionError = nil
                    saveContextSessionName = ""
                    isShowingSaveContextSessionSheet = true
                }
            }
        }
        .fixedSize()
        .disabled(
            contextMeetingIDs.isEmpty
            || isBuildingContext
        )
    }

    var controls: some View {
        VStack(spacing: 8) {
            HStack(spacing: 8) {
                Text(libraryTitle)
                    .font(.headline)
                    .lineLimit(1)

                Spacer()

                Menu {
                    Picker("Sort by", selection: $sortOrderRaw) {
                        ForEach(MeetingSortOrder.allCases) { order in
                            Text(order.label).tag(order.rawValue)
                        }
                    }
                    .pickerStyle(.inline)

                    Picker("Group by", selection: $groupByRaw) {
                        ForEach(MeetingGrouping.allCases) { option in
                            Text(option.label).tag(option.rawValue)
                        }
                    }
                    .pickerStyle(.inline)
                } label: {
                    Image(systemName: "arrow.up.arrow.down")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help("Sort and group meetings")

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

    /// With a session open and nothing ticked, the button asks the
    /// whole session; otherwise it asks about the ticked meetings.
    var asksWholeSession: Bool {
        sessionFilterSession != nil && contextMeetingIDs.isEmpty
    }

    var askButtonTitle: String {
        asksWholeSession ? "Ask This Session" : "Ask About These"
    }

    var askButtonDisabled: Bool {
        if asksWholeSession {
            return false
        }

        return contextMeetingIDs.isEmpty || isBuildingContext
    }

    /// Builds the context automatically after "Ask About These",
    /// but only when nothing is built yet, so it never wipes a
    /// conversation that is already in progress.
    @MainActor
    func autoBuildContextIfNeeded() async {
        let onContextTab: Bool = selectedWorkspaceTab == .context
        let hasSelection: Bool = !contextMeetingIDs.isEmpty
        let hasBuilt: Bool = builtContext != nil

        if !onContextTab || !hasSelection || hasBuilt {
            return
        }

        try? await Task.sleep(nanoseconds: 500_000_000)

        if Task.isCancelled {
            return
        }

        let stillOnContextTab: Bool =
            selectedWorkspaceTab == .context
        let stillNotBuilt: Bool = builtContext == nil
        let busy: Bool =
            isBuildingContext || isRunningContextQuery

        if !stillOnContextTab || !stillNotBuilt || busy {
            return
        }

        await buildSelectedContext()
    }
}


struct MeetingRow: View {
    let meeting: Meeting
    let isInContext: Bool
    let toggleContext: () -> Void

    @AppStorage("meetings.density") private var densityRaw = "normal"

    private var density: MeetingDensity {
        MeetingDensity(rawValue: densityRaw) ?? .normal
    }

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
                spacing: density.lineSpacing
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
                .font(density.detailFont)
                .foregroundStyle(.secondary)
            }

            Spacer(minLength: 12)

            StatusBadge(
                status: meeting.status,
                isPublished: meeting.isPublished
            )
        }
        .padding(.vertical, density.rowPadding)
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

struct StatusBadge: View {
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

struct MeetingTranscriptionQueueCleanupRequest: Equatable {
    let id = UUID()
    let run: String
    let sourcePath: String?
}

struct MeetingTranscriptionQueueCleanupBridge: View {
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
