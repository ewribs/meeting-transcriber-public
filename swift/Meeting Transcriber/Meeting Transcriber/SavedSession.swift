import Foundation

nonisolated struct SavedSession: Identifiable, Decodable, Sendable {
    let id: String
    let name: String
    let label: String
    let tooltip: String
    let sessionType: String
    let meetingCount: Int
    let turnCount: Int
    let criteria: [String]
    let path: String

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case label
        case tooltip
        case sessionType = "session_type"
        case meetingCount = "meeting_count"
        case turnCount = "turn_count"
        case criteria
        case path
    }

    var isDynamic: Bool {
        sessionType.caseInsensitiveCompare(
            "Dynamic"
        ) == .orderedSame
    }

    var typeDisplayName: String {
        isDynamic ? "Dynamic" : "Fixed"
    }
}

nonisolated struct SessionsResponse: Decodable, Sendable {
    let schemaVersion: Int
    let sessions: [SavedSession]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessions
    }
}


nonisolated struct RefreshSessionResponse: Decodable, Sendable {
    let schemaVersion: Int
    let sessionName: String
    let result: String
    let added: Int
    let removed: Int
    let unchanged: Int
    let meetingCount: Int

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionName = "session_name"
        case result
        case added
        case removed
        case unchanged
        case meetingCount = "meeting_count"
    }

    var isAlreadyCurrent: Bool {
        result == "already_current"
    }
}


nonisolated struct RenameSessionResponse: Decodable, Sendable {
    let schemaVersion: Int
    let oldName: String
    let newName: String
    let renamed: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case oldName = "old_name"
        case newName = "new_name"
        case renamed
    }
}


nonisolated struct DeleteSessionResponse: Decodable, Sendable {
    let schemaVersion: Int
    let sessionName: String
    let deleted: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionName = "session_name"
        case deleted
    }
}


nonisolated struct DynamicSessionEditorResponse: Decodable, Sendable {
    let schemaVersion: Int
    let mode: String
    let sessionName: String
    let person: String
    let title: String
    let topic: String
    let historyOptions: [String]
    let selectedHistoryLabel: String
    let customRangeLabel: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case mode
        case sessionName = "session_name"
        case person
        case title
        case topic
        case historyOptions = "history_options"
        case selectedHistoryLabel =
            "selected_history_label"
        case customRangeLabel =
            "custom_range_label"
    }
}


nonisolated struct DynamicSessionChangeResponse: Decodable, Sendable {
    let schemaVersion: Int
    let sessionName: String
    let added: Int
    let removed: Int
    let unchanged: Int
    let meetingCount: Int

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionName = "session_name"
        case added
        case removed
        case unchanged
        case meetingCount = "meeting_count"
    }
}


nonisolated struct SessionConversationItem: Identifiable, Decodable, Sendable {
    let role: String
    let content: String

    var id: String {
        "\(role)-\(content)"
    }

    var isUser: Bool {
        role == "user"
    }
}


nonisolated struct SessionDetail: Decodable, Sendable {
    let schemaVersion: Int
    let sessionName: String
    let meetingCount: Int
    let turnCount: Int
    let meetingRuns: [String]
    let prepText: String
    let conversation: [SessionConversationItem]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionName = "session_name"
        case meetingCount = "meeting_count"
        case turnCount = "turn_count"
        case meetingRuns = "meeting_runs"
        case prepText = "prep_text"
        case conversation
    }
}


nonisolated struct SessionQueryResponse: Decodable, Sendable {
    let schemaVersion: Int
    let sessionName: String
    let assistantResponse: String
    let turnCount: Int
    let elapsedSeconds: Double
    let statusText: String
    let executionMode: String
    let inferenceCalls: Int

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessionName = "session_name"
        case assistantResponse =
            "assistant_response"
        case turnCount = "turn_count"
        case elapsedSeconds =
            "elapsed_seconds"
        case statusText = "status_text"
        case executionMode =
            "execution_mode"
        case inferenceCalls =
            "inference_calls"
    }
}


nonisolated struct SessionChangesResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let sessionName: String
    let available: Bool
    let previousRun: String?
    let previousLabel: String?
    let latestRun: String?
    let latestLabel: String?
    let markdown: String
    let elapsedSeconds: Double
    let generatedAt: String?
    let isCached: Bool
    let isStale: Bool
    let currentPreviousRun: String?
    let currentPreviousLabel: String?
    let currentLatestRun: String?
    let currentLatestLabel: String?

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case sessionName =
            "session_name"
        case available
        case previousRun =
            "previous_run"
        case previousLabel =
            "previous_label"
        case latestRun =
            "latest_run"
        case latestLabel =
            "latest_label"
        case markdown
        case elapsedSeconds =
            "elapsed_seconds"
        case generatedAt =
            "generated_at"
        case isCached =
            "is_cached"
        case isStale =
            "is_stale"
        case currentPreviousRun =
            "current_previous_run"
        case currentPreviousLabel =
            "current_previous_label"
        case currentLatestRun =
            "current_latest_run"
        case currentLatestLabel =
            "current_latest_label"
    }
}
