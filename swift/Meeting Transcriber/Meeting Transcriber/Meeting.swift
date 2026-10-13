import Foundation

nonisolated func usableFilesystemPath(_ rawValue: String?) -> String? {
    guard let rawValue else {
        return nil
    }

    let value = rawValue.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !value.isEmpty else {
        return nil
    }

    let placeholderValues: Set<String> = [
        "n/a", "na", "none", "null", "unknown", "-"
    ]
    guard !placeholderValues.contains(value.lowercased()) else {
        return nil
    }

    return value
}

nonisolated struct MeetingTopic: Decodable, Sendable, Hashable {
    let name: String
    let status: String
    let summary: String
}

nonisolated struct Meeting: Identifiable, Decodable, Sendable {
    let id: String
    let run: String
    let title: String
    let date: String
    let status: String
    let isPublished: Bool
    let canPublish: Bool
    let participants: [String]

    enum CodingKeys: String, CodingKey {
        case id
        case run
        case title
        case date
        case status
        case isPublished = "is_published"
        case canPublish = "can_publish"
        case participants
    }

    var participantsText: String {
        participants.isEmpty
            ? "None identified"
            : participants.joined(separator: ", ")
    }
}

nonisolated struct MeetingsResponse: Decodable, Sendable {
    let schemaVersion: Int
    let meetings: [Meeting]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case meetings
    }
}

nonisolated struct MeetingCommitment: Decodable, Sendable, Hashable {
    let owner: String
    let action: String
    let status: String
}


nonisolated struct MeetingProcessingMetadata: Decodable, Sendable {
    let aiModel: String
    let profileDisplay: String
    let mode: String
    let contextSizeTokens: Int
    let estimatedPromptTokens: Int
    let whisperModel: String
    let whisperChunkMinutes: Int

    enum CodingKeys: String, CodingKey {
        case aiModel = "ai_model"
        case profileDisplay = "profile_display"
        case mode
        case contextSizeTokens = "context_size_tokens"
        case estimatedPromptTokens = "estimated_prompt_tokens"
        case whisperModel = "whisper_model"
        case whisperChunkMinutes = "whisper_chunk_minutes"
    }
}

nonisolated struct MeetingDetail: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let summary: String
    let topics: [MeetingTopic]
    let decisions: [String]
    let commitments: [MeetingCommitment]
    let openQuestions: [String]
    let followUps: [String]
    let processing: MeetingProcessingMetadata?
    let hasSummary: Bool
    let hasMemory: Bool

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case summary
        case topics
        case decisions
        case commitments
        case openQuestions = "open_questions"
        case followUps = "follow_ups"
        case processing
        case hasSummary = "has_summary"
        case hasMemory = "has_memory"
    }
}


nonisolated enum MeetingDeleteOperation: Sendable {
    case keepRecording
    case deleteRecording

    var deletesManagedRecording: Bool {
        switch self {
        case .keepRecording:
            return false
        case .deleteRecording:
            return true
        }
    }
}


nonisolated struct MeetingDeletePlanResponse: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let runPath: String
    let sourcePath: String?
    let sourceFound: Bool
    let sourceIsManaged: Bool
    let displayTitle: String
    let sessionReferenceCount: Int
    let sessionReferenceNames: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case runPath = "run_path"
        case sourcePath = "source_path"
        case sourceFound = "source_found"
        case sourceIsManaged = "source_is_managed"
        case displayTitle = "display_title"
        case sessionReferenceCount = "session_reference_count"
        case sessionReferenceNames = "session_reference_names"
    }
}

nonisolated struct FinalizeMeetingDeleteResponse: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let deleted: Bool
    let runPath: String
    let updatedSessionCount: Int
    let updatedSessions: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case deleted
        case runPath = "run_path"
        case updatedSessionCount = "updated_session_count"
        case updatedSessions = "updated_sessions"
    }
}

nonisolated struct MeetingUnpublishPlanResponse: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let archivePath: String
    let localRunPath: String
    let displayTitle: String
    let sessionReferenceCount: Int
    let sessionReferenceNames: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case archivePath = "archive_path"
        case localRunPath = "local_run_path"
        case displayTitle = "display_title"
        case sessionReferenceCount = "session_reference_count"
        case sessionReferenceNames = "session_reference_names"
    }
}

nonisolated struct FinalizeMeetingUnpublishResponse: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let unpublished: Bool
    let localRunPath: String
    let updatedSessionCount: Int
    let updatedSessions: [String]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case unpublished
        case localRunPath = "local_run_path"
        case updatedSessionCount = "updated_session_count"
        case updatedSessions = "updated_sessions"
    }
}


nonisolated struct PublishMeetingResponse: Decodable, Sendable {
    let schemaVersion: Int
    let run: String
    let status: String
    let archivedPath: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case run
        case status
        case archivedPath = "archived_path"
    }
}


nonisolated struct MeetingContextResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let meetingCount: Int
    let meetingRuns: [String]
    let meetingLabels: [String]
    let prepText: String

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case meetingCount =
            "meeting_count"
        case meetingRuns =
            "meeting_runs"
        case meetingLabels =
            "meeting_labels"
        case prepText =
            "prep_text"
    }
}


nonisolated struct MeetingContextQueryPlanResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let mode: String
    let estimatedPromptTokens: Int
    let directTokenBudget: Int
    let chunkSourceTokenBudget: Int
    let chunkCount: Int
    let inferenceCalls: Int
    let meetingCount: Int
    let hardwareLabel: String
    let profile: String
    let statusText: String

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case mode
        case estimatedPromptTokens =
            "estimated_prompt_tokens"
        case directTokenBudget =
            "direct_token_budget"
        case chunkSourceTokenBudget =
            "chunk_source_token_budget"
        case chunkCount =
            "chunk_count"
        case inferenceCalls =
            "inference_calls"
        case meetingCount =
            "meeting_count"
        case hardwareLabel =
            "hardware_label"
        case profile
        case statusText =
            "status_text"
    }
}


nonisolated struct MeetingContextQueryResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let assistantResponse: String
    let elapsedSeconds: Double
    let statusText: String
    let executionMode: String
    let inferenceCalls: Int

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case assistantResponse =
            "assistant_response"
        case elapsedSeconds =
            "elapsed_seconds"
        case statusText =
            "status_text"
        case executionMode =
            "execution_mode"
        case inferenceCalls =
            "inference_calls"
    }
}


nonisolated struct SaveMeetingContextSessionResponse:
    Decodable,
    Sendable
{
    let schemaVersion: Int
    let sessionName: String
    let meetingCount: Int
    let turnCount: Int

    enum CodingKeys:
        String,
        CodingKey
    {
        case schemaVersion =
            "schema_version"
        case sessionName =
            "session_name"
        case meetingCount =
            "meeting_count"
        case turnCount =
            "turn_count"
    }
}
