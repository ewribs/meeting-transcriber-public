import SwiftUI

/// Meetings preferences. Lives in its own view so a change here only
/// redraws this small tab, not the whole Preferences window.
struct MeetingsPreferencesTab: View {
    @AppStorage("meetings.recentDays")
    private var recentDays = 14

    @AppStorage("meetings.sortOrder")
    private var sortOrderRaw = "newest"

    @AppStorage("meetings.density")
    private var densityRaw = "normal"

    @AppStorage("meetings.railSort")
    private var railSortRaw = "alpha"

    @AppStorage("meetings.showRecentRow")
    private var showRecentRow = true

    @AppStorage("meetings.showUnpublishedRow")
    private var showUnpublishedRow = true

    @AppStorage("meetings.showUnfiledRow")
    private var showUnfiledRow = true

    @AppStorage("meetings.showNotices")
    private var showNotices = true

    @AppStorage("meetings.confirmFolderDelete")
    private var confirmFolderDelete = true

    @AppStorage("ask.showFavorites")
    private var showFavorites = true

    var body: some View {
        Form {
            Section("Meeting List") {
                Stepper(
                    value: $recentDays,
                    in: 1...365
                ) {
                    LabeledContent("“Recent” covers the last") {
                        Text(
                            recentDays == 1
                                ? "1 day"
                                : String(recentDays) + " days"
                        )
                    }
                }

                Picker(
                    "Sort meetings by",
                    selection: $sortOrderRaw
                ) {
                    ForEach(MeetingSortOrder.allCases) { order in
                        Text(order.label).tag(order.rawValue)
                    }
                }

                Picker(
                    "List density",
                    selection: $densityRaw
                ) {
                    ForEach(MeetingDensity.allCases) { option in
                        Text(option.label).tag(option.rawValue)
                    }
                }

                Text("Settings on this tab apply immediately; there is nothing to save.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Sidebar") {
                DeferredToggle(title: "Show Recent", stored: $showRecentRow)
                DeferredToggle(title: "Show Unpublished", stored: $showUnpublishedRow)
                DeferredToggle(title: "Show Not in a Folder", stored: $showUnfiledRow)

                Picker(
                    "Sort folders and sessions",
                    selection: $railSortRaw
                ) {
                    ForEach(RailSortOrder.allCases) { order in
                        Text(order.label).tag(order.rawValue)
                    }
                }

                Text("Dragging a folder or session into place switches this to Manual.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("Notices and Confirmations") {
                DeferredToggle(title: "Show notices (already added, session refreshed)", stored: $showNotices)

                DeferredToggle(title: "Confirm before deleting a folder", stored: $confirmFolderDelete)

                DeferredToggle(title: "Show prompt favorites in the Ask tab", stored: $showFavorites)
            }
        }
        .formStyle(.grouped)
    }

}

/// A toggle that animates immediately, then saves the setting on the next
/// run-loop turn so the rest of the app's redraw cannot stall the switch.
struct DeferredToggle: View {
    let title: String
    @Binding var stored: Bool
    @State private var local: Bool

    init(title: String, stored: Binding<Bool>) {
        self.title = title
        self._stored = stored
        self._local = State(initialValue: stored.wrappedValue)
    }

    var body: some View {
        Toggle(title, isOn: $local)
            .onChange(of: local) { _, newValue in
                DispatchQueue.main.async {
                    stored = newValue
                }
            }
    }
}
