import Foundation

nonisolated struct MeetingFolder: Identifiable, Decodable, Sendable {
    let name: String
    let meetingRuns: [String]

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name
        case meetingRuns = "meeting_runs"
    }
}

nonisolated struct MeetingFoldersResponse: Decodable, Sendable {
    let schemaVersion: Int
    let folders: [MeetingFolder]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case folders
    }
}
