import Foundation

/// Optional headers in the Meetings list. Grouping only changes how the
/// list is laid out; the meetings and their order inside a group are
/// whatever the sort order produced.
enum MeetingGrouping: String, CaseIterable, Identifiable {
    case none
    case month
    case person

    var id: String {
        rawValue
    }

    var label: String {
        switch self {
        case .none:
            return "No Grouping"
        case .month:
            return "By Month"
        case .person:
            return "By Person"
        }
    }

    func groups(from meetings: [Meeting]) -> [MeetingGroup] {
        switch self {
        case .none:
            return []
        case .month:
            return Self.monthGroups(meetings)
        case .person:
            return Self.personGroups(meetings)
        }
    }

    // MARK: - Month

    private static func monthGroups(
        _ meetings: [Meeting]
    ) -> [MeetingGroup] {
        var order: [String] = []
        var buckets: [String: [Meeting]] = [:]

        for meeting in meetings {
            let title: String = monthTitle(meeting.date)

            if buckets[title] == nil {
                order.append(title)
            }

            buckets[title, default: []].append(meeting)
        }

        return order.map { title in
            MeetingGroup(
                title: title,
                meetings: buckets[title] ?? []
            )
        }
    }

    private static func monthTitle(_ rawDate: String) -> String {
        let input = DateFormatter()
        input.locale = Locale(identifier: "en_US_POSIX")
        input.dateFormat = "yyyy-MM-dd"

        guard let date = input.date(from: rawDate) else {
            return "No Date"
        }

        let output = DateFormatter()
        output.locale = Locale.current
        output.dateFormat = "LLLL yyyy"

        return output.string(from: date)
    }

    // MARK: - Person

    /// A meeting appears under every participant, so a group meeting is
    /// listed once for each person in it.
    private static func personGroups(
        _ meetings: [Meeting]
    ) -> [MeetingGroup] {
        let none: String = "No Participants"
        var buckets: [String: [Meeting]] = [:]

        for meeting in meetings {
            if meeting.participants.isEmpty {
                buckets[none, default: []].append(meeting)
                continue
            }

            for person in meeting.participants {
                buckets[person, default: []].append(meeting)
            }
        }

        let people: [String] = buckets.keys
            .filter { $0 != none }
            .sorted {
                $0.localizedStandardCompare($1) == .orderedAscending
            }

        var titles: [String] = people

        if buckets[none] != nil {
            titles.append(none)
        }

        return titles.map { title in
            MeetingGroup(
                title: title,
                meetings: buckets[title] ?? []
            )
        }
    }
}

struct MeetingGroup: Identifiable {
    let title: String
    let meetings: [Meeting]

    var id: String {
        title
    }

    var headerText: String {
        title + " (" + String(meetings.count) + ")"
    }
}
