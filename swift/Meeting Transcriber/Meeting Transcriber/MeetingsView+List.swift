import SwiftUI

extension MeetingsView {
    var grouping: MeetingGrouping {
        MeetingGrouping(rawValue: groupByRaw) ?? .none
    }

    var meetingListView: some View {
        List(selection: $selectedMeetingID) {
            if grouping == .none {
                ForEach(filteredMeetings) { meeting in
                    meetingListRow(meeting)
                }
            } else {
                ForEach(grouping.groups(from: filteredMeetings)) { group in
                    Section(group.headerText) {
                        ForEach(group.meetings) { meeting in
                            meetingListRow(meeting)
                        }
                    }
                }
            }
        }
        .listStyle(.inset)
    }

    func meetingListRow(_ meeting: Meeting) -> some View {
        let isTicked: Bool = contextMeetingIDs.contains(meeting.id)

        return MeetingRow(
            meeting: meeting,
            isInContext: isTicked,
            toggleContext: {
                // Ticking a row also selects it so the
                // detail pane follows the click.
                selectedMeetingID = meeting.id
                toggleMeetingContext(meeting)
            }
        )
        .tag(meeting.id)
        .draggable(dragPayload(for: meeting)) {
            dragPreview(for: meeting)
        }
        .contextMenu {
            Button("Rename…") {
                openRenameMeeting(meeting)
            }

            Divider()

            meetingFolderMenu(for: meeting)
        }
    }
}
