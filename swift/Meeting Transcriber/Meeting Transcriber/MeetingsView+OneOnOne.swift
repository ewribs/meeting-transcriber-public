import SwiftUI

/// One-step 1v1 sessions: a Dynamic session for one person whose
/// meetings have "1v1" in the title, covering all history.
extension MeetingsView {
    static let oneOnOneWord = "1v1"

    /// Right-click menu entry: one choice per participant of the meeting.
    @ViewBuilder
    func oneOnOneMenu(
        for meeting: Meeting
    ) -> some View {
        let people: [String] = meeting.participants.filter {
            !$0.trimmingCharacters(in: .whitespaces).isEmpty
        }

        if !people.isEmpty {
            Menu("Make 1v1 Session With") {
                ForEach(people, id: \.self) { person in
                    Button(person) {
                        Task {
                            await makeOneOnOneSession(with: person)
                        }
                    }
                }
            }
        }
    }

    @MainActor
    func makeOneOnOneSession(with person: String) async {
        let name: String = person + " " + Self.oneOnOneWord + "s"

        do {
            let result = try await backend.createDynamicSession(
                name: name,
                person: person,
                title: Self.oneOnOneWord,
                topic: "",
                historyLabel: "All history",
                rulesJSON: "{}"
            )

            await reloadSessionFilterChoices()
            selectLibrary(.session(result.sessionName))
        } catch {
            addToSessionTitle = "Couldn't Make 1v1 Session"
            addToSessionResult = oneOnOneErrorText(
                error,
                person: person,
                name: name
            )
        }
    }

    func oneOnOneErrorText(
        _ error: Error,
        person: String,
        name: String
    ) -> String {
        let text: String = error.localizedDescription

        if text.contains("DuplicateSessionNameError") {
            return "A session named “" + name + "” already exists."
        }

        if text.contains("NoMatchingMeetingsError") {
            return "No meetings with " + person
                + " have “" + Self.oneOnOneWord
                + "” in the title yet."
        }

        return text
    }
}
