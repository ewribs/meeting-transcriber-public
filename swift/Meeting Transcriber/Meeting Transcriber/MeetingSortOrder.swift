import Foundation

/// How the Meetings list is ordered. "Newest first" keeps the order the
/// backend returns; the others re-order that list.
enum MeetingSortOrder: String, CaseIterable, Identifiable {
    case newest
    case oldest
    case title

    var id: String {
        rawValue
    }

    var label: String {
        switch self {
        case .newest:
            return "Newest First"
        case .oldest:
            return "Oldest First"
        case .title:
            return "Title A–Z"
        }
    }

    func apply(to meetings: [Meeting]) -> [Meeting] {
        switch self {
        case .newest:
            return meetings
        case .oldest:
            return Array(meetings.reversed())
        case .title:
            return meetings.sorted { first, second in
                first.title.localizedStandardCompare(second.title)
                    == .orderedAscending
            }
        }
    }
}
