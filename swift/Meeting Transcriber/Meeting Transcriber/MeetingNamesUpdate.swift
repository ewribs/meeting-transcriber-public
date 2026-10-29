import SwiftUI

// MARK: - What the backend reports

nonisolated struct MeetingNamesStaged: Decodable, Sendable, Equatable {
    let old: [String: Int]?
    let new: [String: Int]?
}

/// Where one meeting stands after voices were named: "stale" means more
/// voices were named since the summary was made, "ready" means a rebuilt
/// copy is waiting to be applied or discarded.
nonisolated struct MeetingNamesStatus: Decodable, Sendable, Equatable {
    let state: String
    let people: [String]
    let share: Double
    let reason: String
    let staged: MeetingNamesStaged?
    let canUndo: Bool

    enum CodingKeys: String, CodingKey {
        case state
        case people
        case share
        case reason
        case staged
        case canUndo = "can_undo"
    }
}

nonisolated enum MeetingNamesCommand: String, Sendable {
    case status
    case rebuild
    case apply
    case discard
    case undo
}

// MARK: - The notice in the meeting pane

/// Shows nothing until it matters. After voices are named in a meeting, offers
/// to rebuild the transcript, action items and summary with the new names,
/// shows what changed, and applies it only when asked. The originals are saved
/// by the backend, so an applied update can be undone right after.
struct MeetingNamesBanner: View {
    let run: String
    /// Changes whenever voices may have been named, so the notice is re-checked.
    let refreshToken: Int
    /// Called after the meeting's files changed (apply or undo).
    let onChanged: () -> Void

    private let backend = BackendService()

    @State private var status: MeetingNamesStatus?
    @State private var isWorking = false
    @State private var workingText = ""
    @State private var canCancel = false
    @State private var resultText: String?
    @State private var canUndoNow = false
    @State private var errorText: String?
    @State private var checkNote: String?
    @State private var task: Task<Void, Never>?

    var body: some View {
        VStack(spacing: 0) {
            // An always-present anchor: SwiftUI does not run `.task` on an empty
            // view, and the notice below is empty until the check has run.
            Color.clear
                .frame(height: 0)
                .task(id: refreshToken) {
                    await refresh()
                }

            noticeContent
        }
    }

    @ViewBuilder
    private var noticeContent: some View {
            if let errorText {
                notice(tint: .red) {
                    Text(errorText)
                        .font(.callout)
                    Spacer()
                    Button("Dismiss") { self.errorText = nil }
                }
            } else if isWorking {
                notice(tint: .accentColor) {
                    ProgressView()
                        .controlSize(.small)
                    Text(workingText)
                        .font(.callout)
                    Spacer()
                    if canCancel {
                        Button("Cancel") { task?.cancel() }
                    }
                }
            } else if let resultText {
                notice(tint: .green) {
                    Text(resultText)
                        .font(.callout)
                    Spacer()
                    if canUndoNow {
                        Button("Undo") { perform(.undo) }
                    }
                    Button("Dismiss") {
                        self.resultText = nil
                        canUndoNow = false
                    }
                }
            } else if let status, status.state == "ready" {
                notice(tint: .accentColor) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Rebuilt with the new names. \(changeSummary(status))")
                            .font(.callout)
                        Text("Applying replaces the transcript, action items and summary. The originals are saved and can be undone.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Discard") { perform(.discard) }
                    Button("Apply") { perform(.apply) }
                        .buttonStyle(.borderedProminent)
                }
            } else if let status, status.state == "stale" {
                notice(tint: .orange) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("\(peopleText(status.people)) named after this summary was made.")
                            .font(.callout)
                        Text("Update the transcript, action items and summary with the new names? It takes a few minutes and you can keep working.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Update…") { perform(.rebuild) }
                        .buttonStyle(.borderedProminent)
                }
            } else if let checkNote {
                Text(checkNote)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
    }

    // MARK: Actions

    private func refresh() async {
        guard !isWorking else { return }
        do {
            status = try await backend.meetingNames(.status, run: run)
            checkNote = nil
        } catch {
            status = nil
            checkNote = "Could not check whether this meeting needs a names update: \(error.localizedDescription)"
        }
    }

    private func perform(_ command: MeetingNamesCommand) {
        errorText = nil
        resultText = nil
        canUndoNow = false
        isWorking = true
        canCancel = command == .rebuild
        switch command {
        case .rebuild:
            workingText = "Rebuilding with the new names. This takes a few minutes."
        case .apply:
            workingText = "Applying…"
        case .undo:
            workingText = "Putting the originals back…"
        default:
            workingText = "Working…"
        }
        task = Task {
            do {
                let updated = try await backend.meetingNames(command, run: run)
                status = updated
                switch command {
                case .apply:
                    resultText = "Updated with the new names."
                    canUndoNow = updated.canUndo
                    onChanged()
                case .undo:
                    resultText = "Put the original transcript and summary back."
                    onChanged()
                default:
                    break
                }
            } catch is CancellationError {
                status = try? await backend.meetingNames(.status, run: run)
            } catch {
                if Task.isCancelled {
                    status = try? await backend.meetingNames(.status, run: run)
                } else {
                    errorText = Self.friendly(error)
                }
            }
            isWorking = false
        }
    }

    // MARK: Wording

    /// The backend's failure text is a long log; show the part a person needs.
    private static func friendly(_ error: Error) -> String {
        let text = error.localizedDescription
        let lower = text.lowercased()
        if lower.contains("insufficient memory")
            || lower.contains("out of memory")
            || lower.contains("outofmemory") {
            return "The Mac ran out of memory while updating. Close other apps or wait for other processing to finish, then try again. Nothing was changed."
        }
        let lines = text
            .split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        if let last = lines.last,
           last.hasPrefix("{"),
           let data = last.data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = object["message"] as? String {
            return message
        }
        return lines.last ?? text
    }

    private func peopleText(_ people: [String]) -> String {
        switch people.count {
        case 0: return "Some voices were"
        case 1: return "\(people[0]) was"
        case 2: return "\(people[0]) and \(people[1]) were"
        default:
            return "\(people.dropLast().joined(separator: ", ")) and \(people.last ?? "") were"
        }
    }

    private static let countLabels: [(key: String, label: String)] = [
        ("commitments", "Action items"),
        ("unowned", "without an owner"),
        ("decisions", "decisions"),
        ("open_questions", "open questions"),
        ("risks", "risks"),
    ]

    private func changeSummary(_ status: MeetingNamesStatus) -> String {
        guard let old = status.staged?.old,
              let new = status.staged?.new else {
            return ""
        }
        let parts = Self.countLabels.compactMap { item -> String? in
            let before = old[item.key] ?? 0
            let after = new[item.key] ?? 0
            guard before != after else { return nil }
            return "\(item.label) \(before) → \(after)"
        }
        return parts.isEmpty
            ? "The item counts are unchanged."
            : parts.joined(separator: ", ") + "."
    }

    private func notice<Content: View>(
        tint: Color,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 10) {
                content()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(tint.opacity(0.12))

            Divider()
        }
    }
}
