import SwiftUI

extension MeetingsView {
    /// Dialogs and sheets for the session rail, kept out of the main
    /// view's long modifier chain so the compiler can type-check it.
    var sessionRailDialogs: some View {
        Color.clear
            .frame(width: 0, height: 0)
            .confirmationDialog(
                "Delete Session?",
                isPresented: Binding(
                    get: { pendingDeleteSession != nil },
                    set: { isPresented in
                        if !isPresented {
                            pendingDeleteSession = nil
                        }
                    }
                ),
                titleVisibility: .visible
            ) {
                Button("Delete Session", role: .destructive) {
                    let name = pendingDeleteSession
                    pendingDeleteSession = nil

                    if let name {
                        Task {
                            await deleteRailSession(name)
                        }
                    }
                }

                Button("Cancel", role: .cancel) {
                    pendingDeleteSession = nil
                }
            } message: {
                let name: String = pendingDeleteSession ?? ""
                let part1: String = "This permanently deletes the saved session “"
                let part2: String = "”, including its conversation history. The meetings themselves are not deleted."
                Text(part1 + name + part2)
            }
            .sheet(
                isPresented: Binding(
                    get: { renameSessionTarget != nil },
                    set: { isPresented in
                        if !isPresented {
                            renameSessionTarget = nil
                        }
                    }
                )
            ) {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Rename Session")
                        .font(.title2)
                        .fontWeight(.semibold)

                    TextField(
                        "Session name",
                        text: $renameSessionText
                    )
                    .textFieldStyle(.roundedBorder)

                    if let renameSessionError {
                        Text(renameSessionError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }

                    HStack {
                        Spacer()

                        Button("Cancel") {
                            renameSessionTarget = nil
                        }
                        .keyboardShortcut(.cancelAction)

                        Button("Rename") {
                            Task {
                                await renameRailSession()
                            }
                        }
                        .keyboardShortcut(.defaultAction)
                        .disabled(
                            renameSessionText
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
            .sheet(item: $dynamicEditorTarget) { target in
                DynamicSessionEditorSheet(
                    target: target
                ) { result in
                    Task {
                        await reloadSessionFilterChoices()
                        selectLibrary(.session(result.sessionName))
                    }
                }
            }
    }

    var libraryRail: some View {
        ScrollView {
            VStack(
                alignment: .leading,
                spacing: 2
            ) {
                libraryRows
                foldersSection
                dynamicSessionsSection
                fixedSessionsSection
            }
            .padding(10)
        }
        .background(
            Color(nsColor: .windowBackgroundColor)
        )
        .sheet(isPresented: folderSessionSheetBinding) {
            folderSessionSheet
        }
    }

    var libraryRows: some View {
        let recentCount: Int = meetings.filter {
            isRecent($0)
        }.count

        let unpublishedCount: Int = meetings.filter {
            !$0.isPublished
        }.count

        let filed: Set<String> = filedRuns

        let unfiledCount: Int = meetings.filter {
            !filed.contains($0.run)
        }.count

        let current: LibrarySelection = librarySelection

        return VStack(
            alignment: .leading,
            spacing: 2
        ) {
            libraryHeader

            takeOutOfFoldersTarget(
                key: "all",
                row: railRow(
                    title: "All Meetings",
                    icon: "tray.full",
                    count: meetings.count,
                    isSelected: current == .all,
                    isDropTarget: dropTargetKey == "all"
                ) {
                    selectLibrary(.all)
                }
            )

            if showRecentRow {
                railRow(
                    title: "Recent",
                    icon: "clock",
                    count: recentCount,
                    isSelected: current == .recent
                ) {
                    selectLibrary(.recent)
                }
                .help(
                    "Meetings from the last "
                        + String(recentDays)
                        + " days. Change this in Settings."
                )
            }

            if showUnpublishedRow {
                railRow(
                    title: "Unpublished",
                    icon: "tray.and.arrow.up",
                    count: unpublishedCount,
                    isSelected: current == .unpublished
                ) {
                    selectLibrary(.unpublished)
                }
            }

            if showUnfiledRow {
                takeOutOfFoldersTarget(
                    key: "unfiled",
                    row: railRow(
                        title: "Not in a Folder",
                        icon: "tray",
                        count: unfiledCount,
                        isSelected: current == .unfiled,
                        isDropTarget: dropTargetKey == "unfiled"
                    ) {
                        selectLibrary(.unfiled)
                    }
                )
            }
        }
    }

    /// Rows that take dropped meetings out of every folder.
    func takeOutOfFoldersTarget<Row: View>(
        key: String,
        row: Row
    ) -> some View {
        row.dropDestination(
            for: String.self
        ) { runs, _ in
            Task {
                await removeRunsFromAllFolders(
                    droppedRuns(runs)
                )
            }

            return true
        } isTargeted: { targeted in
            setDropTarget(key, targeted)
        }
    }

    var foldersSection: some View {
        let knownRuns: Set<String> = Set(meetings.map(\.run))

        return VStack(
            alignment: .leading,
            spacing: 2
        ) {
            railHeaderWithAdd(
                "FOLDERS",
                help: "New folder"
            ) {
                openCreateFolder(with: [])
            }

            if folders.isEmpty {
                railEmptyNote("No folders yet")
            }

            ForEach(railSort.sorted(folders, name: { $0.name })) { folder in
                folderRow(folder, knownRuns: knownRuns)
            }
        }
    }

    func folderRow(
        _ folder: MeetingFolder,
        knownRuns: Set<String>
    ) -> some View {
        let count: Int = folder.meetingRuns
            .filter { knownRuns.contains($0) }
            .count
        let key: String = "folder:" + folder.name
        let isSelected: Bool =
            meetingContextController.folderFilterName
                == folder.name

        return railRow(
            title: folder.name,
            icon: "folder",
            count: count,
            isSelected: isSelected,
            isDropTarget: dropTargetKey == key
        ) {
            selectLibrary(.folder(folder.name))
        }
        .contextMenu {
            Button("Make Session from Folder…") {
                beginFolderSession(folder)
            }

            Divider()

            Button("Rename…") {
                openRenameFolder(folder.name)
            }

            Button(
                "Delete Folder",
                role: .destructive
            ) {
                if confirmFolderDelete {
                    pendingDeleteFolder = folder.name
                } else {
                    Task {
                        await deleteFolder(folder.name)
                    }
                }
            }
        }
        .draggable(
            railOrderPayload(kind: "folder", name: folder.name)
        ) {
            Text(folder.name).font(.callout)
        }
        .dropDestination(
            for: String.self
        ) { runs, _ in
            if handleRailOrderDrop(
                runs,
                kind: "folder",
                onto: folder.name
            ) {
                return true
            }

            let dropped: [String] = droppedRuns(runs)

            if dropped.isEmpty {
                return false
            }

            Task {
                await addRunsToFolder(
                    folder.name,
                    dropped
                )
            }

            return true
        } isTargeted: { targeted in
            setDropTarget(key, targeted)
        }
    }

    var dynamicSessionsSection: some View {
        let sessions: [SavedSession] = allSessions.filter {
            $0.isDynamic
        }

        return VStack(
            alignment: .leading,
            spacing: 2
        ) {
            railHeaderWithAdd(
                "DYNAMIC SESSIONS",
                help: "New dynamic session"
            ) {
                dynamicEditorTarget =
                    DynamicEditorTarget(name: nil)
            }

            if sessions.isEmpty {
                railEmptyNote("No dynamic sessions yet")
            }

            ForEach(
                railSort.sorted(
                    sessions,
                    name: { $0.name },
                    manualOrder: sessionOrder.dynamic
                )
            ) { session in
                dynamicSessionRow(session)
            }
        }
    }

    func dynamicSessionRow(
        _ session: SavedSession
    ) -> some View {
        let key: String = "session:" + session.name

        return railRow(
            title: session.name,
            icon: "sparkle.magnifyingglass",
            count: session.meetingCount,
            isSelected: sessionFilterName == session.name,
            isDropTarget: dropTargetKey == key
        ) {
            selectLibrary(.session(session.name))
        }
        .draggable(
            railOrderPayload(kind: "dynamic", name: session.name)
        ) {
            Text(session.name).font(.callout)
        }
        .dropDestination(
            for: String.self
        ) { items, _ in
            handleRailOrderDrop(
                items,
                kind: "dynamic",
                onto: session.name
            )
        } isTargeted: { targeted in
            setDropTarget(key, targeted)
        }
        .contextMenu {
            sessionMenu(for: session)
        }
    }

    var fixedSessionsSection: some View {
        let sessions: [SavedSession] = allSessions.filter {
            !$0.isDynamic
        }

        return VStack(
            alignment: .leading,
            spacing: 2
        ) {
            railHeaderWithAdd(
                "FIXED SESSIONS",
                help: "New fixed session from the ticked meetings"
            ) {
                beginNewFixedSession()
            }

            if sessions.isEmpty {
                railEmptyNote("No fixed sessions yet")
            }

            ForEach(
                railSort.sorted(
                    sessions,
                    name: { $0.name },
                    manualOrder: sessionOrder.fixed
                )
            ) { session in
                fixedSessionRow(session)
            }
        }
    }

    func fixedSessionRow(
        _ session: SavedSession
    ) -> some View {
        let key: String = "session:" + session.name

        return railRow(
            title: session.name,
            icon: "bubble.left.and.bubble.right",
            count: session.meetingCount,
            isSelected: sessionFilterName == session.name,
            isDropTarget: dropTargetKey == key
        ) {
            selectLibrary(.session(session.name))
        }
        .draggable(
            railOrderPayload(kind: "fixed", name: session.name)
        ) {
            Text(session.name).font(.callout)
        }
        .dropDestination(
            for: String.self
        ) { runs, _ in
            if handleRailOrderDrop(
                runs,
                kind: "fixed",
                onto: session.name
            ) {
                return true
            }

            let dropped: [String] = droppedRuns(runs)

            if dropped.isEmpty {
                return false
            }

            Task {
                await addDroppedRuns(
                    dropped,
                    toSession: session.name
                )
            }

            return true
        } isTargeted: { targeted in
            setDropTarget(key, targeted)
        }
        .contextMenu {
            sessionMenu(for: session)
        }
    }

    var sessionFilterName: String {
        meetingContextController.sessionFilterName
    }

    @ViewBuilder
    func sessionMenu(
        for session: SavedSession
    ) -> some View {
        if session.isDynamic {
            Button("Edit Rules…") {
                dynamicEditorTarget =
                    DynamicEditorTarget(name: session.name)
            }

            Button("Refresh") {
                Task {
                    await refreshRailSession(session.name)
                }
            }

            Divider()
        }

        Button("Rename…") {
            renameSessionText = session.name
            renameSessionError = nil
            renameSessionTarget = session.name
        }

        Button("Delete Session…", role: .destructive) {
            pendingDeleteSession = session.name
        }
    }

    @MainActor
    func refreshRailSession(
        _ name: String
    ) async {
        do {
            let result = try await backend
                .refreshSession(name: name)

            await reloadSessionFilterChoices()

            if !showNotices {
                return
            }

            if result.isAlreadyCurrent {
                addToSessionTitle = "Already Up to Date"
                let total: Int = result.meetingCount
                let noun: String = total == 1 ? "meeting" : "meetings"
                addToSessionResult =
                    "“" + name + "” has \(total) " + noun + ". Nothing changed."
            } else {
                addToSessionTitle = "Session Refreshed"
                let total: Int = result.meetingCount
                let added: Int = result.added
                let removed: Int = result.removed
                var text: String = "“" + name + "” now has "
                text += String(total) + ". Added "
                text += String(added) + ", removed "
                text += String(removed) + "."
                addToSessionResult = text
            }
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    @MainActor
    func renameRailSession() async {
        guard let oldName = renameSessionTarget,
              !isRenamingSession
        else {
            return
        }

        let newName = renameSessionText.trimmingCharacters(
            in: .whitespacesAndNewlines
        )

        guard !newName.isEmpty else {
            renameSessionError = "Enter a session name."
            return
        }

        isRenamingSession = true
        renameSessionError = nil

        defer {
            isRenamingSession = false
        }

        do {
            let result = try await backend.renameSession(
                oldName: oldName,
                newName: newName
            )

            renameSessionTarget = nil

            let wasSelected = sessionFilterName == oldName

            await reloadSessionFilterChoices()

            if wasSelected {
                selectLibrary(.session(result.newName))
            }
        } catch {
            renameSessionError = error.localizedDescription
        }
    }

    @MainActor
    func deleteRailSession(
        _ name: String
    ) async {
        do {
            let result = try await backend
                .deleteSession(name: name)

            guard result.deleted else {
                addToSessionResult =
                    "The session was not deleted."
                return
            }

            if sessionFilterName == name {
                selectLibrary(.all)
            }

            await reloadSessionFilterChoices()
        } catch {
            addToSessionResult =
                error.localizedDescription
        }
    }

    func setDropTarget(
        _ key: String,
        _ targeted: Bool
    ) {
        if targeted {
            dropTargetKey = key
        } else if dropTargetKey == key {
            dropTargetKey = nil
        }
    }

    /// Dragging a ticked meeting drags every ticked meeting;
    /// otherwise just the one being dragged. Runs are joined by
    /// newlines so a single string payload can carry several.
    func dragPayload(
        for meeting: Meeting
    ) -> String {
        if contextMeetingIDs.contains(meeting.id),
           contextMeetingIDs.count > 1 {
            return contextMeetingRuns.joined(separator: "\n")
        }

        return meeting.run
    }

    func droppedRuns(
        _ payloads: [String]
    ) -> [String] {
        payloads
            .filter { !$0.hasPrefix(Self.railOrderPrefix) }
            .flatMap {
                $0.split(separator: "\n").map(String.init)
            }
    }

    @ViewBuilder
    func dragPreview(
        for meeting: Meeting
    ) -> some View {
        let count = contextMeetingIDs.contains(meeting.id)
            ? contextMeetingIDs.count
            : 1

        Text(
            count > 1
                ? "\(count) meetings"
                : meeting.title
        )
        .font(.callout)
        .lineLimit(1)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.accentColor.opacity(0.25))
        )
    }

    var railSort: RailSortOrder {
        RailSortOrder(rawValue: railSortRaw) ?? .alpha
    }

    var libraryHeader: some View {
        HStack {
            railHeader("LIBRARY")

            Spacer()

            Menu {
                Picker(
                    "Sort folders and sessions",
                    selection: $railSortRaw
                ) {
                    ForEach(RailSortOrder.allCases) { order in
                        Text(order.label).tag(order.rawValue)
                    }
                }
                .pickerStyle(.inline)
            } label: {
                Image(systemName: "arrow.up.arrow.down")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help("Sort folders and sessions")
            .padding(.top, 10)
            .padding(.trailing, 6)
        }
    }

    func railHeaderWithAdd(
        _ title: String,
        help: String,
        action: @escaping () -> Void
    ) -> some View {
        HStack {
            railHeader(title)

            Spacer()

            Button(action: action) {
                Image(systemName: "plus")
            }
            .buttonStyle(.borderless)
            .help(help)
            .padding(.top, 10)
            .padding(.trailing, 6)
        }
    }

    func railEmptyNote(
        _ text: String
    ) -> some View {
        Text(text)
            .font(.caption)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
    }

    /// A Fixed session is built from meetings, so the + needs some
    /// ticked first; then it reuses the Save as Session sheet.
    func beginNewFixedSession() {
        guard !contextMeetingIDs.isEmpty else {
            addToSessionTitle = "Select Meetings"
            addToSessionResult =
                "Tick the meetings you want in the session first, then click + again."
            return
        }

        saveContextSessionError = nil
        saveContextSessionName = ""
        isShowingSaveContextSessionSheet = true
    }

    func railHeader(
        _ title: String
    ) -> some View {
        Text(title)
            .font(.caption2)
            .fontWeight(.semibold)
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.top, 14)
            .padding(.bottom, 4)
    }

    func railRow(
        title: String,
        icon: String,
        count: Int,
        isSelected: Bool,
        isDropTarget: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon)
                    .frame(width: 16)
                    .foregroundStyle(
                        isSelected
                            ? Color.accentColor
                            : Color.secondary
                    )

                Text(title)
                    .lineLimit(1)
                    .fontWeight(
                        isSelected ? .semibold : .regular
                    )

                Spacer(minLength: 4)

                Text("\(count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(
                        isDropTarget
                            ? Color.accentColor.opacity(0.30)
                            : isSelected
                                ? Color.accentColor.opacity(0.18)
                                : Color.clear
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .stroke(
                        Color.accentColor,
                        lineWidth: isDropTarget ? 2 : 0
                    )
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}
