import AppKit
import SwiftUI

struct PreferencesView: View {
    @State private var performanceProfile =
        "Auto"

    @State private var outputDir = ""
    @State private var archiveDir = ""
    @State private var recordingsDir = ""
    @State private var llmModel = ""
    @State private var llmContextSize = 0
    @State private var m4aRetentionDays = 30
    @State private var archivedM4aRetentionDays =
        365

    @State private var performanceProfiles:
        [String] = []

    @State private var performanceProfileOptions:
        [PerformanceProfileOption] = []

    @State private var hardwareProfile:
        HardwareProfileSummary?

    @State private var resolvedPerformanceProfile:
        ResolvedPerformanceProfile?

    @State private var contextSizeOptions:
        [ContextSizeOption] = []

    @State private var installedModels:
        [String] = []

    @State private var modelStatus =
        "Checking…"

    @State private var archiveStatus =
        "Checking…"

    @State private var isLoading = false
    @State private var isSaving = false

    @State private var errorMessage:
        String?

    @State private var savedMessage:
        String?

    @State private var runtimePreviewGeneration = 0

    private let backend =
        BackendService()

    private var selectedProfileDescription: String? {
        performanceProfileOptions
            .first {
                $0.name == performanceProfile
            }?
            .description
    }

    var body: some View {
        Form {
            Section("Storage") {
                pathRow(
                    label:
                        "Working folder",
                    value:
                        $outputDir,
                    buttonTitle:
                        "Choose…"
                ) {
                    chooseFolder(
                        binding:
                            $outputDir
                    )
                }

                pathRow(
                    label:
                        "Archive folder",
                    value:
                        $archiveDir,
                    buttonTitle:
                        "Choose…"
                ) {
                    chooseFolder(
                        binding:
                            $archiveDir
                    )
                }

                pathRow(
                    label:
                        "Recordings folder",
                    value:
                        $recordingsDir,
                    buttonTitle:
                        "Choose…"
                ) {
                    chooseFolder(
                        binding:
                            $recordingsDir
                    )
                }

                Text(
                    "Add Recordings… opens here by default. You can still browse elsewhere."
                )
                .font(.caption)
                .foregroundStyle(.secondary)

                LabeledContent(
                    "Archive status"
                ) {
                    Text(archiveStatus)
                        .foregroundStyle(
                            archiveStatus
                                == "Available"
                                ? .green
                                : .secondary
                        )
                }
            }

            Section("Local AI") {
                HStack {
                    Picker(
                        "Ollama model",
                        selection:
                            $llmModel
                    ) {
                        ForEach(
                            installedModels,
                            id: \.self
                        ) { model in
                            Text(model)
                                .tag(model)
                        }
                    }
                    .frame(
                        minWidth: 260
                    )

                    Button {
                        Task {
                            await loadPreferences(
                                preserveEdits:
                                    true
                            )
                        }
                    } label: {
                        Label(
                            "Refresh Models",
                            systemImage:
                                "arrow.clockwise"
                        )
                    }
                    .disabled(isLoading)
                }

                LabeledContent(
                    "Model status"
                ) {
                    Text(modelStatus)
                        .foregroundStyle(
                            modelStatus
                                == "Installed"
                                ? .green
                                : .secondary
                        )
                }

                Picker(
                    "Performance profile",
                    selection:
                        $performanceProfile
                ) {
                    ForEach(
                        performanceProfiles,
                        id: \.self
                    ) { profile in
                        Text(profile)
                            .tag(profile)
                    }
                }
                .frame(
                    maxWidth: 360
                )

                if let profileDescription =
                    selectedProfileDescription
                {
                    Text(profileDescription)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(
                            horizontal: false,
                            vertical: true
                        )
                }

                if let hardware = hardwareProfile {
                    LabeledContent(
                        "Detected hardware"
                    ) {
                        VStack(
                            alignment: .trailing,
                            spacing: 2
                        ) {
                            Text(hardware.displayLabel)
                                .fontWeight(.medium)

                            if !hardware.performanceClass.isEmpty {
                                Text(hardware.performanceClass)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                if let resolved =
                    resolvedPerformanceProfile
                {
                    LabeledContent(
                        "Effective profile"
                    ) {
                        Text(
                            resolved.requestedName == "Auto"
                                ? "Auto → \(resolved.resolvedName)"
                                : resolved.resolvedName
                        )
                        .fontWeight(.semibold)
                    }

                    LabeledContent(
                        "Context mode"
                    ) {
                        VStack(
                            alignment: .trailing,
                            spacing: 2
                        ) {
                            Text(
                                resolved.contextMode == "override"
                                    ? "Override"
                                    : "Profile default"
                            )
                            .fontWeight(.medium)

                            Text(
                                "\(resolved.contextSizeTokens.formatted()) tokens"
                            )
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                    }

                    LabeledContent(
                        "Direct budget"
                    ) {
                        Text(
                            "\(resolved.directTokenBudget.formatted()) tokens"
                        )
                    }

                    Text(resolved.reason)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(
                            horizontal: false,
                            vertical: true
                        )
                }

                Picker(
                    "Context override",
                    selection:
                        $llmContextSize
                ) {
                    ForEach(
                        contextSizeOptions
                    ) { option in
                        Text(option.label)
                            .tag(
                                option.value
                            )
                    }
                }
                .frame(
                    maxWidth: 360
                )

                Text(
                    "Leave Context override at Profile default unless you are intentionally testing a specific context window. Manual performance profiles stay fixed; Auto re-evaluates this Mac and selects the appropriate tier."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Section("Audio Retention") {
                Stepper(
                    value:
                        $m4aRetentionDays,
                    in: 0...3650
                ) {
                    LabeledContent(
                        "Local M4A retention"
                    ) {
                        Text(
                            retentionText(
                                m4aRetentionDays
                            )
                        )
                    }
                }

                Stepper(
                    value:
                        $archivedM4aRetentionDays,
                    in: 0...3650
                ) {
                    LabeledContent(
                        "Archived M4A retention"
                    ) {
                        Text(
                            retentionText(
                                archivedM4aRetentionDays
                            )
                        )
                    }
                }

                Text(
                    "0 days means Forever for archived recordings."
                )
                .font(.caption)
                .foregroundStyle(
                    .secondary
                )
            }

            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                        .textSelection(
                            .enabled
                        )
                }
            }

            Section {
                HStack {
                    if isLoading
                        || isSaving {
                        ProgressView()
                            .controlSize(
                                .small
                            )
                    }

                    Spacer()

                    Button("Reload") {
                        Task {
                            await loadPreferences(
                                preserveEdits:
                                    false
                            )
                        }
                    }
                    .disabled(
                        isLoading
                        || isSaving
                    )

                    Button("Save") {
                        Task {
                            await save()
                        }
                    }
                    .buttonStyle(
                        .borderedProminent
                    )
                    .disabled(
                        isLoading
                        || isSaving
                    )
                }
            }
        }
        .formStyle(.grouped)
        .padding(12)
        .frame(
            width: 720,
            height: 650
        )
        .onChange(of: performanceProfile) { _, _ in
            Task {
                await refreshResolvedRuntimePreview()
            }
        }
        .onChange(of: llmContextSize) { _, _ in
            Task {
                await refreshResolvedRuntimePreview()
            }
        }
        .task {
            await loadPreferences(
                preserveEdits:
                    false
            )
        }
        .alert(
            "Preferences Saved",
            isPresented: Binding(
                get: {
                    savedMessage != nil
                },
                set: { showing in
                    if !showing {
                        savedMessage = nil
                    }
                }
            )
        ) {
            Button(
                "OK",
                role: .cancel
            ) {
                savedMessage = nil
            }
        } message: {
            Text(
                savedMessage ?? ""
            )
        }
    }

    @ViewBuilder
    private func pathRow(
        label: String,
        value: Binding<String>,
        buttonTitle: String,
        choose:
            @escaping () -> Void
    ) -> some View {
        HStack {
            TextField(
                label,
                text: value
            )

            Button(
                buttonTitle,
                action: choose
            )
        }
    }

    @MainActor
    private func loadPreferences(
        preserveEdits: Bool
    ) async {
        guard !isLoading else {
            return
        }

        isLoading = true
        errorMessage = nil

        defer {
            isLoading = false
        }

        do {
            let response =
                try await backend
                    .loadPreferences()

            performanceProfiles =
                response
                    .performanceProfiles

            performanceProfileOptions =
                response
                    .performanceProfileOptions

            hardwareProfile =
                response
                    .hardwareProfile

            resolvedPerformanceProfile =
                response
                    .resolvedPerformanceProfile

            contextSizeOptions =
                response
                    .contextSizeOptions

            installedModels =
                response
                    .installedModels

            modelStatus =
                response
                    .modelStatus

            archiveStatus =
                response
                    .archiveStatus

            if !preserveEdits {
                performanceProfile =
                    response
                        .settings
                        .performanceProfile

                outputDir =
                    response
                        .settings
                        .outputDir

                archiveDir =
                    response
                        .settings
                        .archiveDir

                recordingsDir =
                    response
                        .settings
                        .recordingsDir

                llmModel =
                    response
                        .settings
                        .llmModel

                llmContextSize =
                    response
                        .settings
                        .llmContextSize

                m4aRetentionDays =
                    response
                        .settings
                        .m4aRetentionDays

                archivedM4aRetentionDays =
                    response
                        .settings
                        .archivedM4aRetentionDays
            } else if
                !installedModels
                    .contains(
                        llmModel
                    ),
                !llmModel.isEmpty
            {
                installedModels.append(
                    llmModel
                )
            }

        } catch {
            errorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func refreshResolvedRuntimePreview() async {
        guard !performanceProfile.isEmpty else {
            return
        }

        runtimePreviewGeneration += 1
        let generation = runtimePreviewGeneration

        do {
            let preview = try await backend
                .previewPerformanceProfile(
                    performanceProfile: performanceProfile,
                    llmContextSize: llmContextSize
                )

            guard generation == runtimePreviewGeneration else {
                return
            }

            resolvedPerformanceProfile = preview
        } catch {
            guard generation == runtimePreviewGeneration else {
                return
            }
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func save() async {
        guard !isSaving else {
            return
        }

        isSaving = true
        errorMessage = nil

        defer {
            isSaving = false
        }

        do {
            let response =
                try await backend
                    .savePreferences(
                        performanceProfile:
                            performanceProfile,
                        outputDir:
                            outputDir,
                        archiveDir:
                            archiveDir,
                        recordingsDir:
                            recordingsDir,
                        llmModel:
                            llmModel,
                        llmContextSize:
                            llmContextSize,
                        m4aRetentionDays:
                            m4aRetentionDays,
                        archivedM4aRetentionDays:
                            archivedM4aRetentionDays
                    )

            savedMessage =
                response.message

            await loadPreferences(
                preserveEdits: false
            )

        } catch {
            errorMessage =
                error.localizedDescription
        }
    }

    @MainActor
    private func chooseFolder(
        binding:
            Binding<String>
    ) {
        let panel =
            NSOpenPanel()

        panel.canChooseFiles =
            false

        panel.canChooseDirectories =
            true

        panel.allowsMultipleSelection =
            false

        panel.prompt = "Choose"

        let current =
            binding
                .wrappedValue

        if !current.isEmpty {
            panel.directoryURL =
                URL(
                    fileURLWithPath:
                        current,
                    isDirectory:
                        true
                )
        }

        guard let parentWindow =
            NSApp.keyWindow
                ?? NSApp.mainWindow
        else {
            panel.begin {
                response in

                guard
                    response == .OK,
                    let selected =
                        panel.url
                else {
                    return
                }

                Task {
                    @MainActor in
                    binding.wrappedValue =
                        selected.path
                }
            }

            return
        }

        panel.beginSheetModal(
            for: parentWindow
        ) {
            response in

            guard
                response == .OK,
                let selected =
                    panel.url
            else {
                return
            }

            Task {
                @MainActor in
                binding.wrappedValue =
                    selected.path
            }
        }
    }

    private func retentionText(
        _ days: Int
    ) -> String {
        if days == 0 {
            return "Forever"
        }

        return
            "\(days) day"
            + (days == 1 ? "" : "s")
    }
}
