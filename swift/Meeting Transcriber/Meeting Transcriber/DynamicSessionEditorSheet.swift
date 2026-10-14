import SwiftUI

/// Identifies one request to open the Dynamic session editor:
/// `name == nil` creates a new session, otherwise it edits that one.
struct DynamicEditorTarget: Identifiable {
    let id = UUID()
    let name: String?
}

/// Self-contained create/edit sheet for Dynamic sessions. It loads
/// the editor state itself, saves through the backend, and reports
/// the saved session back through `onSaved`.
struct DynamicSessionEditorSheet: View {
    let target: DynamicEditorTarget
    let onSaved: (DynamicSessionChangeResponse) -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var isLoading = true
    @State private var isSaving = false
    @State private var mode = "create"
    @State private var name = ""
    @State private var rules: [SessionRuleRow] = []
    @State private var historyOptions: [String] = []
    @State private var historyLabel = ""
    @State private var customRangeLabel: String?
    @State private var errorMessage: String?

    private let backend = BackendService()

    private var isCreating: Bool {
        mode == "create"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                Text(
                    isCreating
                        ? "Create Dynamic Session"
                        : "Edit Dynamic Session"
                )
                .font(.title2)
                .fontWeight(.semibold)

                Text(
                    isCreating
                        ? "Create a saved session that automatically selects meetings matching these criteria."
                        : "Update the saved criteria. Existing conversation history will be preserved."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Divider()

            if isLoading {
                ProgressView()
                    .controlSize(.small)
                    .frame(
                        maxWidth: .infinity,
                        minHeight: 120
                    )
            } else {
                SessionRuleEditorView(
                    name: $name,
                    isNameEditable: isCreating,
                    rows: $rules,
                    historyOptions: historyOptions,
                    historyLabel: $historyLabel,
                    customRangeLabel: customRangeLabel
                )
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }

            HStack {
                if isSaving {
                    ProgressView()
                        .controlSize(.small)

                    Text(
                        isCreating
                            ? "Creating…"
                            : "Saving changes…"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                Spacer()

                Button("Cancel") {
                    dismiss()
                }
                .keyboardShortcut(.cancelAction)
                .disabled(isSaving)

                Button(isCreating ? "Create" : "Save Changes") {
                    Task {
                        await save()
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(
                    isLoading
                    || isSaving
                    || name
                        .trimmingCharacters(
                            in: .whitespacesAndNewlines
                        )
                        .isEmpty
                    || historyLabel.isEmpty
                )
            }
        }
        .padding(24)
        .frame(width: 680)
        .task {
            await load()
        }
    }

    @MainActor
    private func load() async {
        do {
            let editor = try await backend
                .loadDynamicSessionEditor(name: target.name)

            mode = editor.mode
            name = target.name == nil ? "" : editor.sessionName
            rules = [SessionRuleRow].rows(from: editor)
            historyOptions = editor.historyOptions
            historyLabel = editor.selectedHistoryLabel
            customRangeLabel = editor.customRangeLabel
            isLoading = false
        } catch {
            isLoading = false
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func save() async {
        guard !isSaving else {
            return
        }

        let sessionName = name.trimmingCharacters(
            in: .whitespacesAndNewlines
        )

        guard !sessionName.isEmpty else {
            errorMessage = "Enter a session name."
            return
        }

        isSaving = true
        errorMessage = nil

        defer {
            isSaving = false
        }

        let arguments = rules.bridgeArguments

        do {
            let result: DynamicSessionChangeResponse

            if isCreating {
                result = try await backend.createDynamicSession(
                    name: sessionName,
                    person: arguments.person,
                    title: arguments.title,
                    topic: arguments.topic,
                    historyLabel: historyLabel,
                    rulesJSON: arguments.rulesJSON
                )
            } else {
                result = try await backend.editDynamicSession(
                    name: sessionName,
                    person: arguments.person,
                    title: arguments.title,
                    topic: arguments.topic,
                    historyLabel: historyLabel,
                    rulesJSON: arguments.rulesJSON
                )
            }

            onSaved(result)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
