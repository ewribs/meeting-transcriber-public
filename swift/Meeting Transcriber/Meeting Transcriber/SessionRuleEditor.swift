import SwiftUI

enum SessionRuleKind: String, CaseIterable, Identifiable {
    case person = "Person is"
    case people = "Person is any of"
    case titleContains = "Title contains"
    case titleExcludes = "Title does not contain"
    case topicContains = "Topic contains"
    case topicExcludes = "Topic does not contain"

    var id: String { rawValue }

    var placeholder: String {
        switch self {
        case .people:
            return "Name, Name, Name"
        case .person:
            return "Name"
        default:
            return "Text"
        }
    }
}

struct SessionRuleRow: Identifiable, Equatable {
    let id = UUID()
    var kind: SessionRuleKind
    var value: String
}

struct SessionRuleArguments {
    let person: String
    let title: String
    let topic: String
    let rulesJSON: String
}

extension Array where Element == SessionRuleRow {
    private func trimmedValue(
        _ kind: SessionRuleKind
    ) -> String {
        (first { $0.kind == kind }?.value ?? "")
            .trimmingCharacters(
                in: .whitespacesAndNewlines
            )
    }

    func bridgeArguments(
        matchAny: Bool
    ) -> SessionRuleArguments {
        var rules: [String: String] = [:]

        if matchAny {
            rules["match"] = "any"
        }

        let pairs: [(String, SessionRuleKind)] = [
            ("people", .people),
            ("exclude_title", .titleExcludes),
            ("exclude_topic", .topicExcludes),
        ]

        for (key, kind) in pairs {
            let value = trimmedValue(kind)

            if !value.isEmpty {
                rules[key] = value
            }
        }

        let data =
            (try? JSONSerialization.data(
                withJSONObject: rules
            )) ?? Data("{}".utf8)

        return SessionRuleArguments(
            person: trimmedValue(.person),
            title: trimmedValue(.titleContains),
            topic: trimmedValue(.topicContains),
            rulesJSON: String(
                data: data,
                encoding: .utf8
            ) ?? "{}"
        )
    }

    static func rows(
        from editor: DynamicSessionEditorResponse
    ) -> [SessionRuleRow] {
        var rows: [SessionRuleRow] = []

        func add(
            _ kind: SessionRuleKind,
            _ value: String?
        ) {
            let text = (value ?? "")
                .trimmingCharacters(
                    in: .whitespacesAndNewlines
                )

            if !text.isEmpty {
                rows.append(
                    SessionRuleRow(
                        kind: kind,
                        value: text
                    )
                )
            }
        }

        add(.person, editor.person)
        add(.people, editor.people?.joined(separator: ", "))
        add(.titleContains, editor.title)
        add(.titleExcludes, editor.excludeTitle)
        add(.topicContains, editor.topic)
        add(.topicExcludes, editor.excludeTopic)

        return rows
    }
}

struct SessionRuleEditorView: View {
    @Binding var name: String
    let isNameEditable: Bool
    @Binding var rows: [SessionRuleRow]
    @Binding var matchAny: Bool
    let historyOptions: [String]
    @Binding var historyLabel: String
    let customRangeLabel: String?

    @State private var preview: CriteriaPreviewResponse?
    @State private var previewError: String?
    @State private var isLoadingPreview = false

    private let backend = BackendService()

    private var usesSavedRange: Bool {
        customRangeLabel != nil
            && historyLabel == customRangeLabel
    }

    private var unusedKinds: [SessionRuleKind] {
        SessionRuleKind.allCases.filter { kind in
            !rows.contains { $0.kind == kind }
        }
    }

    private var previewKey: String {
        (matchAny ? "any|" : "all|") + historyLabel + "|" + rows
            .map { "\($0.kind.rawValue)=\($0.value)" }
            .joined(separator: "|")
    }

    var body: some View {
        VStack(
            alignment: .leading,
            spacing: 14
        ) {
            VStack(
                alignment: .leading,
                spacing: 5
            ) {
                Text("NAME")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)

                TextField(
                    "Session name",
                    text: $name
                )
                .textFieldStyle(.roundedBorder)
                .disabled(!isNameEditable)
            }

            HStack(spacing: 10) {
                Text("DATES")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)

                Picker(
                    "Dates",
                    selection: $historyLabel
                ) {
                    ForEach(
                        historyOptions,
                        id: \.self
                    ) { option in
                        Text(option)
                            .tag(option)
                    }
                }
                .labelsHidden()
                .frame(width: 260)

                Spacer()
            }

            if usesSavedRange {
                Label(
                    "This legacy saved date range is kept unless you choose a different option. The preview below ignores it.",
                    systemImage: "calendar.badge.clock"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            VStack(
                alignment: .leading,
                spacing: 6
            ) {
                rulesHeader

                VStack(spacing: 0) {
                    if rows.isEmpty {
                        Text("No rules yet. Use Add Rule.")
                            .foregroundStyle(.secondary)
                            .frame(
                                maxWidth: .infinity,
                                alignment: .leading
                            )
                            .padding(10)
                    }

                    ForEach($rows) { $row in
                        HStack(spacing: 8) {
                            Text(row.kind.rawValue)
                                .frame(
                                    width: 170,
                                    alignment: .leading
                                )

                            TextField(
                                row.kind.placeholder,
                                text: $row.value
                            )
                            .textFieldStyle(.roundedBorder)

                            Button {
                                rows.removeAll {
                                    $0.id == row.id
                                }
                            } label: {
                                Image(
                                    systemName: "minus.circle"
                                )
                            }
                            .buttonStyle(.borderless)
                            .help("Remove this rule")
                        }
                        .padding(.horizontal, 10)
                        .padding(.vertical, 6)

                        Divider()
                    }
                }
                .background(
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color(nsColor: .controlBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.secondary.opacity(0.25))
                )

                Menu("Add Rule") {
                    ForEach(unusedKinds) { kind in
                        Button(kind.rawValue) {
                            rows.append(
                                SessionRuleRow(
                                    kind: kind,
                                    value: ""
                                )
                            )
                        }
                    }
                }
                .fixedSize()
                .disabled(unusedKinds.isEmpty)
            }

            previewBox
        }
        .task(id: previewKey) {
            try? await Task.sleep(
                nanoseconds: 400_000_000
            )

            if Task.isCancelled {
                return
            }

            await refreshPreview()
        }
    }

    private var rulesHeader: some View {
        let note: String = matchAny
            ? "A meeting needs to match at least one of the Person, Title and Topic rules. The “does not contain” rules and the dates still apply to every meeting."
            : "A meeting must match every rule."

        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Text("RULES")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)

                Picker("Match", selection: $matchAny) {
                    Text("All rules").tag(false)
                    Text("Any rule").tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 190)

                Spacer()
            }

            Text(note)
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var previewBox: some View {
        VStack(
            alignment: .leading,
            spacing: 6
        ) {
            HStack {
                Text("Preview")
                    .fontWeight(.semibold)

                Spacer()

                if isLoadingPreview {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if let previewError {
                Text(previewError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            } else if let preview {
                if !preview.hasCriteria {
                    Text("Add a rule or choose a date window to see which meetings match.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if preview.matchCount == 0 {
                    Text("No meetings match these rules yet. A session can't be saved until at least one does.")
                        .font(.caption)
                        .foregroundStyle(.orange)
                } else {
                    Text(
                        "\(preview.matchCount) meeting\(preview.matchCount == 1 ? "" : "s") match"
                    )
                    .foregroundStyle(.green)

                    ForEach(preview.meetings.prefix(5)) { meeting in
                        Text("• \(meeting.title)")
                            .font(.caption)
                            .lineLimit(1)
                    }

                    if preview.matchCount > 5 {
                        Text(
                            "and \(preview.matchCount - 5) more"
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text("Checking…")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(
            maxWidth: .infinity,
            alignment: .leading
        )
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color.secondary.opacity(0.25))
        )
    }

    @MainActor
    private func refreshPreview() async {
        let arguments = rows.bridgeArguments(matchAny: matchAny)
        let label = usesSavedRange
            ? "All history"
            : historyLabel

        isLoadingPreview = true

        defer {
            isLoadingPreview = false
        }

        do {
            let result = try await backend.previewCriteria(
                person: arguments.person,
                title: arguments.title,
                topic: arguments.topic,
                historyLabel: label,
                rulesJSON: arguments.rulesJSON
            )

            if Task.isCancelled {
                return
            }

            preview = result
            previewError = nil
        } catch {
            if Task.isCancelled {
                return
            }

            previewError = error.localizedDescription
        }
    }
}
