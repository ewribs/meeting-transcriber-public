import Foundation

nonisolated struct GlobalSearchResult: Identifiable, Decodable, Sendable, Hashable {
    let id: String
    let kind: String
    let title: String
    let subtitle: String
    let date: String
    let snippet: String
    let score: Int
    let meetingRun: String
    let sessionName: String

    enum CodingKeys: String, CodingKey {
        case id
        case kind
        case title
        case subtitle
        case date
        case snippet
        case score
        case meetingRun = "meeting_run"
        case sessionName = "session_name"
    }

    var isMeeting: Bool { kind == "meeting" }
    var isSession: Bool { kind == "session" }
}

nonisolated struct GlobalSearchResponse: Decodable, Sendable {
    let schemaVersion: Int
    let query: String
    let meetings: [GlobalSearchResult]
    let sessions: [GlobalSearchResult]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case query
        case meetings
        case sessions
    }

    var totalCount: Int {
        meetings.count + sessions.count
    }
}
