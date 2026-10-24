import Darwin
import Foundation

enum BackendError: LocalizedError {
    case projectNotFound(String)
    case pythonNotFound(String)
    case bridgeNotFound(String)
    case launchFailed(String)
    case backendFailed(Int32, String)
    case invalidOutput(String)

    var errorDescription: String? {
        switch self {
        case .projectNotFound(let path):
            return "Meeting Transcriber project was not found at \(path)"

        case .pythonNotFound(let path):
            return "Python virtual environment was not found at \(path)"

        case .bridgeNotFound(let path):
            return "Backend bridge was not found at \(path)"

        case .launchFailed(let message):
            return "Unable to launch backend: \(message)"

        case .backendFailed(let code, let message):
            return "Backend exited with status \(code): \(message)"

        case .invalidOutput(let message):
            return "Backend returned invalid data: \(message)"
        }
    }
}


nonisolated private final class BackendProcessHandle:
    @unchecked Sendable
{
    private let lock = NSLock()
    private var process: Process?
    private var cancellationRequested = false

    func begin() {
        lock.lock()
        cancellationRequested = false
        lock.unlock()
    }

    func set(
        _ process: Process
    ) {
        lock.lock()
        self.process = process
        let shouldCancel = cancellationRequested
        lock.unlock()

        if shouldCancel {
            terminate(process)
        }
    }

    func clear(
        _ candidate: Process
    ) {
        lock.lock()

        if process === candidate {
            process = nil
        }

        lock.unlock()
    }

    func cancel() {
        lock.lock()
        cancellationRequested = true
        let candidate = process
        lock.unlock()

        guard let candidate else {
            return
        }

        terminate(candidate)
    }

    private func terminate(
        _ candidate: Process
    ) {
        guard candidate.isRunning else {
            return
        }

        candidate.terminate()

        DispatchQueue.global(
            qos: .userInitiated
        ).asyncAfter(
            deadline: .now() + 1.0
        ) {
            if candidate.isRunning {
                kill(
                    candidate
                        .processIdentifier,
                    SIGKILL
                )
            }
        }
    }
}


nonisolated struct BackendService: Sendable {
    private struct InstallConfig: Decodable {
        let projectDir: String

        enum CodingKeys: String, CodingKey {
            case projectDir = "project_dir"
        }
    }

    private let projectDirectory: URL
    private let processHandle =
        BackendProcessHandle()

    init() {
        self.projectDirectory =
            Self.resolveProjectDirectory()
    }

    static func resolveProjectDirectory(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        supportDirectory: URL? = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser
    ) -> URL {
        if let override = environment[
            "MEETING_TRANSCRIBER_PROJECT_DIR"
        ]?.trimmingCharacters(
            in: .whitespacesAndNewlines
        ), !override.isEmpty {
            return URL(
                fileURLWithPath:
                    (override as NSString)
                        .expandingTildeInPath,
                isDirectory: true
            )
        }

        if let configURL = supportDirectory?
            .appendingPathComponent(
                "Meeting Transcriber",
                isDirectory: true
            )
            .appendingPathComponent(
                "install.json"
            ),
            let data = try? Data(
                contentsOf: configURL
            ),
            let config = try? JSONDecoder()
                .decode(
                    InstallConfig.self,
                    from: data
                ),
            !config.projectDir
                .trimmingCharacters(
                    in: .whitespacesAndNewlines
                )
                .isEmpty
        {
            return URL(
                fileURLWithPath:
                    (config.projectDir as NSString)
                        .expandingTildeInPath,
                isDirectory: true
            )
        }

        return homeDirectory
            .appendingPathComponent(
                "Projects/meeting-transcriber",
                isDirectory: true
            )
    }

    func backupState() async throws {
        _ = try await runBridge(
            arguments: [
                "backup-state"
            ]
        )
    }

    func runBackupNow() async throws -> BackupRunResponse {
        let data = try await runBridge(
            arguments: [
                "backup-state"
            ]
        )

        do {
            return try JSONDecoder().decode(
                BackupRunResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadBackupSettings() async throws -> BackupSettingsResponse {
        let data = try await runBridge(
            arguments: [
                "backup-settings"
            ]
        )

        do {
            return try JSONDecoder().decode(
                BackupSettingsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func saveBackupSettings(
        mirrorDir: String,
        keepLocal: Int,
        keepMirror: Int
    ) async throws -> BackupSettingsResponse {
        let data = try await runBridge(
            arguments: [
                "save-backup-settings",
                mirrorDir,
                String(keepLocal),
                String(keepMirror),
            ]
        )

        do {
            return try JSONDecoder().decode(
                BackupSettingsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadVoiceGroups() async throws -> VoiceGroupsResponse {
        let data = try await runBridge(
            arguments: [
                "voice-groups"
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceGroupsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    /// Deletes any leftover listening clips. Best effort: a failure here is
    /// not worth showing.
    func clearVoiceClips() async {
        _ = try? await runBridge(
            arguments: [
                "voice-clips-clear"
            ]
        )
    }

    func loadMeetingVoices(
        run: String
    ) async throws -> MeetingVoicesResponse {
        let data = try await runBridge(
            arguments: [
                "voice-meeting",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingVoicesResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func makeMeetingVoiceClips(
        run: String,
        voiceID: String
    ) async throws -> VoiceClipsResponse {
        let data = try await runBridge(
            arguments: [
                "voice-meeting-clips",
                run,
                voiceID,
                "3",
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceClipsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func nameMeetingVoice(
        run: String,
        voiceID: String,
        name: String
    ) async throws -> MeetingVoiceNameResult {
        let data = try await runBridge(
            arguments: [
                "voice-meeting-name",
                run,
                voiceID,
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingVoiceNameResult.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func changeMeetingVoice(
        run: String,
        voiceID: String,
        name: String
    ) async throws -> MeetingVoiceChangeResult {
        let data = try await runBridge(
            arguments: [
                "voice-meeting-change",
                run,
                voiceID,
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingVoiceChangeResult.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadRecentVoiceMeetings() async throws -> [RecentVoiceMeeting] {
        let data = try await runBridge(
            arguments: [
                "voice-recent-meetings"
            ]
        )

        do {
            return try JSONDecoder().decode(
                RecentVoiceMeetingsResponse.self,
                from: data
            ).meetings
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func setVoiceGroupState(
        groupID: String,
        action: String
    ) async throws -> VoiceGroupStateResponse {
        let data = try await runBridge(
            arguments: [
                "voice-group-state",
                groupID,
                action,
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceGroupStateResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func makeVoiceClips(
        groupID: String
    ) async throws -> VoiceClipsResponse {
        let data = try await runBridge(
            arguments: [
                "voice-group-clips",
                groupID,
                "3",
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceClipsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func nameVoiceGroup(
        groupID: String,
        name: String
    ) async throws -> VoiceNameResult {
        let data = try await runBridge(
            arguments: [
                "voice-name-group",
                groupID,
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceNameResult.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadVoiceSettings() async throws -> VoiceSettingsResponse {
        let data = try await runBridge(
            arguments: [
                "voice-settings"
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceSettingsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func saveVoiceSettings(
        enabled: Bool,
        updateParticipants: Bool,
        pendingDays: Int
    ) async throws -> VoiceSettingsResponse {
        let data = try await runBridge(
            arguments: [
                "save-voice-settings",
                enabled ? "on" : "off",
                updateParticipants ? "on" : "off",
                String(pendingDays),
            ]
        )

        do {
            return try JSONDecoder().decode(
                VoiceSettingsResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    /// Re-evaluates the rules of every Dynamic session and saves the new
    /// member lists. Best effort; callers ignore failures.
    /// Changes how a meeting's title is shown. The meeting's folder name
    /// (its ID) is never changed.
    func renameMeeting(
        run: String,
        title: String
    ) async throws {
        _ = try await runBridge(
            arguments: [
                "rename-meeting",
                run,
                title,
            ]
        )
    }

    func refreshAllSessions() async throws {
        _ = try await runBridge(
            arguments: [
                "refresh-all-sessions"
            ]
        )
    }

    func performStartupRetention() async throws {
        _ = try await runBridge(
            arguments: [
                "startup-retention"
            ]
        )
    }

    func loadPreferences()
        async throws
        -> PreferencesResponse
    {
        let data = try await runBridge(
            arguments: [
                "preferences"
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    PreferencesResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func previewLLMBackend(
        llmBackend: String
    ) async throws
        -> ResolvedLLMBackend
    {
        let data = try await runBridge(
            arguments: [
                "preview-llm-backend",
                llmBackend,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    ResolvedLLMBackend.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func previewPerformanceProfile(
        performanceProfile: String,
        llmContextSize: Int
    ) async throws
        -> ResolvedPerformanceProfile
    {
        let data = try await runBridge(
            arguments: [
                "preview-performance-profile",
                performanceProfile,
                String(llmContextSize),
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    ResolvedPerformanceProfile.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func savePreferences(
        performanceProfile: String,
        llmBackend: String,
        outputDir: String,
        archiveDir: String,
        recordingsDir: String,
        llmModel: String,
        llmContextSize: Int,
        m4aRetentionDays: Int,
        archivedM4aRetentionDays: Int
    ) async throws
        -> SavePreferencesResponse
    {
        let data = try await runBridge(
            arguments: [
                "save-preferences",
                performanceProfile,
                llmBackend,
                outputDir,
                archiveDir,
                recordingsDir,
                llmModel,
                String(
                    llmContextSize
                ),
                String(
                    m4aRetentionDays
                ),
                String(
                    archivedM4aRetentionDays
                ),
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    SavePreferencesResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func inspectAudioContract(
        path: String
    ) async throws -> AudioContractResponse {
        let data = try await runBridge(
            arguments: [
                "audio-contract",
                path,
            ]
        )

        do {
            return try JSONDecoder().decode(
                AudioContractResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func finalizeAudioRecording(
        sourcePath: String,
        outputPath: String,
        sampleRate: Int,
        channels: Int
    ) async throws -> AudioContractResponse {
        let data = try await runBridge(
            arguments: [
                "finalize-audio-recording",
                sourcePath,
                outputPath,
                String(sampleRate),
                String(channels),
            ]
        )

        do {
            return try JSONDecoder().decode(
                AudioContractResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func globalSearch(
        query: String,
        scopeKind: String = "",
        scopeName: String = ""
    ) async throws -> GlobalSearchResponse {
        var arguments: [String] = [
            "global-search",
            query,
        ]

        if scopeKind == "folder" {
            arguments.append("--scope-folder")
            arguments.append(scopeName)
        } else if scopeKind == "session" {
            arguments.append("--scope-session")
            arguments.append(scopeName)
        }

        let data = try await runBridge(
            arguments: arguments
        )

        do {
            return try JSONDecoder().decode(
                GlobalSearchResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadMeetings() async throws -> [Meeting] {
        let data = try await runBridge(
            arguments: ["meetings"]
        )

        do {
            return try JSONDecoder()
                .decode(
                    MeetingsResponse.self,
                    from: data
                )
                .meetings
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func buildMeetingContext(
        meetingRuns: [String]
    ) async throws
        -> MeetingContextResponse
    {
        let runsData = try JSONSerialization.data(
            withJSONObject:
                meetingRuns
        )

        let runsJSON = String(
            data: runsData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                "meeting-context",
                runsJSON,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    MeetingContextResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func saveMeetingContextSession(
        name: String,
        meetingRuns: [String],
        conversation:
            [SessionConversationItem]
    ) async throws
        -> SaveMeetingContextSessionResponse
    {
        let runsData = try JSONSerialization.data(
            withJSONObject:
                meetingRuns
        )

        let runsJSON = String(
            data: runsData,
            encoding: .utf8
        ) ?? "[]"

        let historyObject =
            conversation.map {
                [
                    "role": $0.role,
                    "content": $0.content,
                ]
            }

        let historyData =
            try JSONSerialization.data(
                withJSONObject:
                    historyObject
            )

        let historyJSON = String(
            data: historyData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                "save-meeting-context-session",
                name,
                runsJSON,
                historyJSON,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    SaveMeetingContextSessionResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func planMeetingContextQuery(
        meetingRuns: [String],
        prompt: String,
        conversation:
            [SessionConversationItem],
        queryMode: String = "normal"
    ) async throws
        -> MeetingContextQueryPlanResponse
    {
        let runsData =
            try JSONSerialization.data(
                withJSONObject:
                    meetingRuns
            )

        let runsJSON = String(
            data: runsData,
            encoding: .utf8
        ) ?? "[]"

        let historyObject =
            conversation.map {
                [
                    "role": $0.role,
                    "content": $0.content,
                ]
            }

        let historyData =
            try JSONSerialization.data(
                withJSONObject:
                    historyObject
            )

        let historyJSON = String(
            data: historyData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                "meeting-context-query-plan",
                runsJSON,
                prompt,
                historyJSON,
                queryMode,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    MeetingContextQueryPlanResponse
                        .self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func queryMeetingContext(
        meetingRuns: [String],
        prompt: String,
        conversation:
            [SessionConversationItem],
        queryMode: String = "normal"
    ) async throws
        -> MeetingContextQueryResponse
    {
        let runsData = try JSONSerialization.data(
            withJSONObject:
                meetingRuns
        )

        let runsJSON = String(
            data: runsData,
            encoding: .utf8
        ) ?? "[]"

        let historyObject =
            conversation.map {
                [
                    "role": $0.role,
                    "content": $0.content,
                ]
            }

        let historyData =
            try JSONSerialization.data(
                withJSONObject:
                    historyObject
            )

        let historyJSON = String(
            data: historyData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                "meeting-context-query",
                runsJSON,
                prompt,
                historyJSON,
                queryMode,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    MeetingContextQueryResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadPromptFavorites()
        async throws
        -> [PromptFavorite]
    {
        let data = try await runBridge(
            arguments: [
                "favorite-prompts"
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    PromptFavoritesResponse.self,
                    from: data
                )
                .favorites
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func savePromptFavorites(
        customFavorites:
            [PromptFavorite]
    ) async throws
        -> [PromptFavorite]
    {
        let payload =
            customFavorites.map {
                [
                    "id": $0.id,
                    "title": $0.title,
                    "prompt": $0.prompt,
                ]
            }

        let payloadData =
            try JSONSerialization.data(
                withJSONObject:
                    payload
            )

        let payloadJSON = String(
            data: payloadData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                "save-favorite-prompts",
                payloadJSON,
            ]
        )

        do {
            return try JSONDecoder()
                .decode(
                    PromptFavoritesResponse.self,
                    from: data
                )
                .favorites
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadMeetingDetail(
        run: String
    ) async throws -> MeetingDetail {
        let data = try await runBridge(
            arguments: [
                "meeting-detail",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingDetail.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadSessionChanges(
        name: String,
        force: Bool = false
    ) async throws
        -> SessionChangesResponse
    {
        var arguments = [
            "session-changes",
            name,
        ]
        if force {
            arguments.append("--force")
        }

        let data = try await runBridge(
            arguments: arguments
        )

        do {
            return try JSONDecoder()
                .decode(
                    SessionChangesResponse.self,
                    from: data
                )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadSessions() async throws -> [SavedSession] {
        let data = try await runBridge(
            arguments: ["sessions"]
        )

        do {
            return try JSONDecoder()
                .decode(
                    SessionsResponse.self,
                    from: data
                )
                .sessions
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func runSessionQuery(
        name: String,
        prompt: String,
        queryMode: String = "normal"
    ) async throws -> SessionQueryResponse {
        let data = try await runBridge(
            arguments: [
                "session-query",
                name,
                prompt,
                queryMode,
            ]
        )

        do {
            return try JSONDecoder().decode(
                SessionQueryResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadSessionDetail(
        name: String
    ) async throws -> SessionDetail {
        let data = try await runBridge(
            arguments: [
                "session-detail",
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                SessionDetail.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadDynamicSessionEditor(
        name: String? = nil
    ) async throws -> DynamicSessionEditorResponse {
        var arguments = ["session-editor"]

        if let name {
            arguments.append(name)
        }

        let data = try await runBridge(
            arguments: arguments
        )

        do {
            return try JSONDecoder().decode(
                DynamicSessionEditorResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func createDynamicSession(
        name: String,
        person: String,
        title: String,
        topic: String,
        historyLabel: String,
        rulesJSON: String
    ) async throws -> DynamicSessionChangeResponse {
        let data = try await runBridge(
            arguments: [
                "create-dynamic-session",
                name,
                person,
                title,
                topic,
                historyLabel,
                rulesJSON,
            ]
        )

        do {
            return try JSONDecoder().decode(
                DynamicSessionChangeResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func editDynamicSession(
        name: String,
        person: String,
        title: String,
        topic: String,
        historyLabel: String,
        rulesJSON: String
    ) async throws -> DynamicSessionChangeResponse {
        let data = try await runBridge(
            arguments: [
                "edit-dynamic-session",
                name,
                person,
                title,
                topic,
                historyLabel,
                rulesJSON,
            ]
        )

        do {
            return try JSONDecoder().decode(
                DynamicSessionChangeResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func previewCriteria(
        person: String,
        title: String,
        topic: String,
        historyLabel: String,
        rulesJSON: String
    ) async throws -> CriteriaPreviewResponse {
        let data = try await runBridge(
            arguments: [
                "preview-criteria",
                person,
                title,
                topic,
                historyLabel,
                rulesJSON,
            ]
        )

        do {
            return try JSONDecoder().decode(
                CriteriaPreviewResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func deleteSession(
        name: String
    ) async throws -> DeleteSessionResponse {
        let data = try await runBridge(
            arguments: [
                "delete-session",
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                DeleteSessionResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func renameSession(
        oldName: String,
        newName: String
    ) async throws -> RenameSessionResponse {
        let data = try await runBridge(
            arguments: [
                "rename-session",
                oldName,
                newName,
            ]
        )

        do {
            return try JSONDecoder().decode(
                RenameSessionResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func refreshSession(
        name: String
    ) async throws -> RefreshSessionResponse {
        let data = try await runBridge(
            arguments: [
                "refresh-session",
                name,
            ]
        )

        do {
            return try JSONDecoder().decode(
                RefreshSessionResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func addMeetingsToSession(
        name: String,
        meetingRuns: [String]
    ) async throws -> SessionMembershipResponse {
        try await changeSessionMembership(
            command: "add-session-meetings",
            name: name,
            meetingRuns: meetingRuns
        )
    }

    func removeMeetingsFromSession(
        name: String,
        meetingRuns: [String]
    ) async throws -> SessionMembershipResponse {
        try await changeSessionMembership(
            command: "remove-session-meetings",
            name: name,
            meetingRuns: meetingRuns
        )
    }

    private func changeSessionMembership(
        command: String,
        name: String,
        meetingRuns: [String]
    ) async throws -> SessionMembershipResponse {
        let runsData = try JSONSerialization.data(
            withJSONObject: meetingRuns
        )

        let runsJSON = String(
            data: runsData,
            encoding: .utf8
        ) ?? "[]"

        let data = try await runBridge(
            arguments: [
                command,
                name,
                runsJSON,
            ]
        )

        do {
            return try JSONDecoder().decode(
                SessionMembershipResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func reorderFolders(
        names: [String]
    ) async throws -> [MeetingFolder] {
        let json: String = try Self.jsonList(names)
        return try await runFolderCommand(
            ["reorder-folders", json]
        )
    }

    func loadSessionOrder() async throws -> SessionOrder {
        try await runSessionOrderCommand(["session-order"])
    }

    func saveSessionOrder(
        kind: String,
        names: [String]
    ) async throws -> SessionOrder {
        let json: String = try Self.jsonList(names)
        return try await runSessionOrderCommand(
            ["save-session-order", kind, json]
        )
    }

    private static func jsonList(
        _ names: [String]
    ) throws -> String {
        let data = try JSONSerialization.data(
            withJSONObject: names
        )

        return String(data: data, encoding: .utf8) ?? "[]"
    }

    private func runSessionOrderCommand(
        _ arguments: [String]
    ) async throws -> SessionOrder {
        let data = try await runBridge(
            arguments: arguments
        )

        do {
            return try JSONDecoder().decode(
                SessionOrder.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func loadFolders() async throws -> [MeetingFolder] {
        try await runFolderCommand(["folders"])
    }

    func createFolder(
        name: String
    ) async throws -> [MeetingFolder] {
        try await runFolderCommand(["create-folder", name])
    }

    func renameFolder(
        oldName: String,
        newName: String
    ) async throws -> [MeetingFolder] {
        try await runFolderCommand(
            ["rename-folder", oldName, newName]
        )
    }

    func deleteFolder(
        name: String
    ) async throws -> [MeetingFolder] {
        try await runFolderCommand(["delete-folder", name])
    }

    func addMeetingsToFolder(
        name: String,
        meetingRuns: [String]
    ) async throws -> [MeetingFolder] {
        try await runFolderCommand(
            [
                "add-folder-meetings",
                name,
                try encodeRunsJSON(meetingRuns),
            ]
        )
    }

    func removeMeetingsFromFolder(
        name: String,
        meetingRuns: [String]
    ) async throws -> [MeetingFolder] {
        try await runFolderCommand(
            [
                "remove-folder-meetings",
                name,
                try encodeRunsJSON(meetingRuns),
            ]
        )
    }

    private func encodeRunsJSON(
        _ runs: [String]
    ) throws -> String {
        let data = try JSONSerialization.data(
            withJSONObject: runs
        )

        return String(
            data: data,
            encoding: .utf8
        ) ?? "[]"
    }

    private func runFolderCommand(
        _ arguments: [String]
    ) async throws -> [MeetingFolder] {
        let data = try await runBridge(
            arguments: arguments
        )

        do {
            return try JSONDecoder().decode(
                MeetingFoldersResponse.self,
                from: data
            ).folders
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func meetingDeletePlan(
        run: String
    ) async throws -> MeetingDeletePlanResponse {
        let data = try await runBridge(
            arguments: [
                "meeting-delete-plan",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingDeletePlanResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func finalizeMeetingDelete(
        run: String
    ) async throws -> FinalizeMeetingDeleteResponse {
        let data = try await runBridge(
            arguments: [
                "finalize-meeting-delete",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                FinalizeMeetingDeleteResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func meetingUnpublishPlan(
        run: String
    ) async throws -> MeetingUnpublishPlanResponse {
        let data = try await runBridge(
            arguments: [
                "meeting-unpublish-plan",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                MeetingUnpublishPlanResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func finalizeMeetingUnpublish(
        run: String
    ) async throws -> FinalizeMeetingUnpublishResponse {
        let data = try await runBridge(
            arguments: [
                "finalize-meeting-unpublish",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                FinalizeMeetingUnpublishResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func publishMeeting(
        run: String
    ) async throws -> PublishMeetingResponse {
        let data = try await runBridge(
            arguments: [
                "publish-meeting",
                run,
            ]
        )

        do {
            return try JSONDecoder().decode(
                PublishMeetingResponse.self,
                from: data
            )
        } catch {
            throw invalidOutput(
                data,
                error: error
            )
        }
    }

    func cancelActiveProcess() {
        processHandle.cancel()
    }

    private func runBridge(
        arguments: [String]
    ) async throws -> Data {
        try Task.checkCancellation()
        processHandle.begin()

        return try await withTaskCancellationHandler(
            operation: {
                let data = try await Task.detached(
                    priority: .userInitiated
                ) {
                    try runBridgeSynchronously(
                        arguments: arguments
                    )
                }.value

                try Task.checkCancellation()
                return data
            },
            onCancel: {
                processHandle.cancel()
            }
        )
    }

    private func runBridgeSynchronously(
        arguments: [String]
    ) throws -> Data {
        let fileManager = FileManager.default

        let pythonURL = projectDirectory
            .appendingPathComponent(
                ".venv/bin/python"
            )

        let bridgeURL = projectDirectory
            .appendingPathComponent(
                "backend_bridge.py"
            )

        guard fileManager.fileExists(
            atPath: projectDirectory.path
        ) else {
            throw BackendError.projectNotFound(
                projectDirectory.path
            )
        }

        guard fileManager.isExecutableFile(
            atPath: pythonURL.path
        ) else {
            throw BackendError.pythonNotFound(
                pythonURL.path
            )
        }

        guard fileManager.fileExists(
            atPath: bridgeURL.path
        ) else {
            throw BackendError.bridgeNotFound(
                bridgeURL.path
            )
        }

        let process = Process()

        process.executableURL = pythonURL
        process.arguments = [
            bridgeURL.path
        ] + arguments
        process.currentDirectoryURL =
            projectDirectory

        var environment =
            ProcessInfo.processInfo.environment

        let preferredPaths = [
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]

        let existingPath =
            environment["PATH"]
            ?? ""

        let mergedPath =
            (
                preferredPaths
                + existingPath
                    .split(
                        separator: ":"
                    )
                    .map(String.init)
            )
            .reduce(
                into: [String]()
            ) {
                paths,
                candidate in

                if !candidate.isEmpty,
                   !paths.contains(
                        candidate
                   ) {
                    paths.append(
                        candidate
                    )
                }
            }
            .joined(
                separator: ":"
            )

        environment["PATH"] =
            mergedPath

        process.environment =
            environment

        let stdout = Pipe()
        let stderr = Pipe()

        process.standardOutput = stdout
        process.standardError = stderr

        do {
            try process.run()
        } catch {
            throw BackendError.launchFailed(
                error.localizedDescription
            )
        }

        processHandle.set(
            process
        )

        defer {
            processHandle.clear(
                process
            )
        }

        let stdoutData =
            stdout.fileHandleForReading
                .readDataToEndOfFile()

        let stderrData =
            stderr.fileHandleForReading
                .readDataToEndOfFile()

        process.waitUntilExit()

        if process.terminationStatus != 0 {
            let stderrText =
                String(
                    data: stderrData,
                    encoding: .utf8
                ) ?? "Unknown backend error"

            throw BackendError.backendFailed(
                process.terminationStatus,
                stderrText
            )
        }

        return stdoutData
    }

    private func invalidOutput(
        _ data: Data,
        error: Error
    ) -> BackendError {
        let rawOutput =
            String(
                data: data,
                encoding: .utf8
            ) ?? "<non-text output>"

        return .invalidOutput(
            "\(error.localizedDescription)\n\n\(rawOutput)"
        )
    }
}
