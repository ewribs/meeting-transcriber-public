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
    let progress: String?

    enum CodingKeys: String, CodingKey {
        case state
        case people
        case share
        case reason
        case staged
        case canUndo = "can_undo"
        case progress
    }
}

/// The rebuilt summary next to the current one, and what changed in the
/// decisions, action items, risks and open questions.
nonisolated struct MeetingNamesPreview: Decodable, Sendable, Equatable {
    let current: String
    let rebuilt: String
    let changes: String
    let added: Int
    let removed: Int
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
    @State private var stepText = ""
    @State private var pollTask: Task<Void, Never>?
    @State private var preview: MeetingNamesPreview?
    @State private var isLoadingPreview = false
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
        .sheet(
            isPresented: Binding(
                get: { preview != nil },
                set: { if !$0 { preview = nil } }
            )
        ) {
            if let preview {
                MeetingNamesPreviewSheet(
                    preview: preview,
                    onApply: {
                        self.preview = nil
                        perform(.apply)
                    },
                    onDiscard: {
                        self.preview = nil
                        perform(.discard)
                    }
                )
            }
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
                    VStack(alignment: .leading, spacing: 2) {
                        Text(workingText)
                            .font(.callout)
                        if !stepText.isEmpty {
                            Text(stepText)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
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
                    if isLoadingPreview {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Button("Preview…") { showPreview() }
                        .disabled(isLoadingPreview)
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

    private func showPreview() {
        isLoadingPreview = true
        Task {
            do {
                preview = try await backend.meetingNamesPreview(run: run)
            } catch {
                errorText = Self.friendly(error)
            }
            isLoadingPreview = false
        }
    }

    private func perform(_ command: MeetingNamesCommand) {
        errorText = nil
        resultText = nil
        canUndoNow = false
        isWorking = true
        stepText = ""
        canCancel = command == .rebuild
        pollTask?.cancel()
        if command == .rebuild {
            startPolling()
        }
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
            pollTask?.cancel()
            stepText = ""
            isWorking = false
        }
    }

    /// While a rebuild runs, asks every few seconds which step it is on. A separate
    /// backend instance is used so cancelling the rebuild never stops a check.
    private func startPolling() {
        let checker = BackendService()
        let runName = self.run
        pollTask = Task {
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 3_000_000_000)
                if Task.isCancelled { break }
                if let latest = try? await checker.meetingNames(.status, run: runName),
                   let step = latest.progress,
                   !step.isEmpty {
                    stepText = step
                }
            }
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


// MARK: - The preview sheet

/// Lets you read what a rebuild produced before it replaces anything.
struct MeetingNamesPreviewSheet: View {
    let preview: MeetingNamesPreview
    let onApply: () -> Void
    let onDiscard: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var mode: Mode = .changes

    private enum Mode: String, CaseIterable, Identifiable {
        case changes = "What changed"
        case rebuilt = "New summary"
        case current = "Current summary"

        var id: String { rawValue }
    }

    var body: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Preview of the update")
                    .font(.title3)
                    .fontWeight(.semibold)

                Text(headline)
                    .font(.callout)
                    .foregroundStyle(.secondary)

                Picker("View", selection: $mode) {
                    ForEach(Mode.allCases) { mode in
                        Text(mode.rawValue).tag(mode)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 440)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)

            Divider()

            ScrollView {
                MeetingMarkdownView(markdown: shownText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            HStack(spacing: 10) {
                Text("Applying saves the originals; Undo puts them back.")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                Button("Close") { dismiss() }
                Button("Discard", role: .destructive) { onDiscard() }
                Button("Apply") { onApply() }
                    .buttonStyle(.borderedProminent)
            }
            .padding(14)
        }
        .frame(minWidth: 760, minHeight: 560)
    }

    private var headline: String {
        "In decisions, action items, risks and open questions: \(preview.added) added, \(preview.removed) removed. Other sections are rewritten; see the new summary."
    }

    private var shownText: String {
        switch mode {
        case .changes: return preview.changes
        case .rebuilt: return preview.rebuilt
        case .current: return preview.current.isEmpty ? "No current summary." : preview.current
        }
    }
}
