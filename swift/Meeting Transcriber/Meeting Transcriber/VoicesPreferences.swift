import SwiftUI

/// What the voice tools report about themselves.
nonisolated struct VoiceStatus: Decodable, Sendable, Equatable {
    let ready: Bool
    let reason: String
    let peopleCount: Int
    let recent: [String]

    enum CodingKeys: String, CodingKey {
        case ready
        case reason
        case peopleCount = "people_count"
        case recent
    }

    static let empty = VoiceStatus(
        ready: false,
        reason: "",
        peopleCount: 0,
        recent: []
    )
}

nonisolated struct VoiceSettings: Decodable, Sendable {
    let enabled: Bool
    let updateParticipants: Bool
    let pendingDays: Int

    enum CodingKeys: String, CodingKey {
        case enabled
        case updateParticipants = "update_participants"
        case pendingDays = "pending_days"
    }
}

nonisolated struct VoiceSettingsResponse: Decodable, Sendable {
    let settings: VoiceSettings
    let status: VoiceStatus
}

/// The "Voices" tab of Preferences. Changes here apply immediately;
/// there is nothing to save.
struct VoicesPreferencesTab: View {
    @State private var enabled = false
    @State private var updateParticipants = true
    @State private var pendingDays = 180
    @State private var status = VoiceStatus.empty
    @State private var isLoaded = false
    @State private var isBusy = false
    @State private var errorMessage: String?

    private let backend = BackendService()

    var body: some View {
        Form {
            Section("Voice Recognition") {
                Text("After each transcription, Meeting Transcriber can recognize the voices on the call and replace “Remote” with real names. It runs on this Mac and adds roughly half a minute per meeting. If it fails, your transcript is not affected.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Toggle(
                    "Recognize voices after each transcription",
                    isOn: enabledBinding
                )
                .disabled(!isLoaded || isBusy)

                Toggle(
                    "List the people who spoke as the meeting’s participants",
                    isOn: participantsBinding
                )
                .disabled(!isLoaded || isBusy || !enabled)

                if !status.ready && !status.reason.isEmpty {
                    Text(status.reason)
                        .font(.caption)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                }
            }

            Section("Unnamed Voices") {
                Picker(
                    "Remember unnamed voices for",
                    selection: pendingDaysBinding
                ) {
                    Text("1 month").tag(30)
                    Text("3 months").tag(90)
                    Text("6 months").tag(180)
                    Text("1 year").tag(365)
                    Text("Never delete").tag(0)
                }
                .disabled(!isLoaded || isBusy)

                Text("Voices that have no name yet are remembered for this long, so the Speakers screen can match them across meetings. After that their fingerprint is deleted. Named people are not affected and are kept until you delete them.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Section("Status") {
                LabeledContent("People with a voice fingerprint") {
                    Text(String(status.peopleCount))
                        .foregroundStyle(.secondary)
                }

                if status.recent.isEmpty {
                    Text("No automatic runs yet.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Most recent runs")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    ForEach(
                        Array(status.recent.enumerated()),
                        id: \.offset
                    ) { _, line in
                        Text(line)
                            .font(.caption.monospaced())
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                Text("Voice fingerprints stay on this Mac. They are never saved in your meetings, exports or the project folder. To name new voices, use Terminal for now: python3 voice_cli.py unknowns")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .formStyle(.grouped)
        .task {
            await load()
        }
    }

    private var enabledBinding: Binding<Bool> {
        Binding(
            get: { enabled },
            set: { newValue in
                Task {
                    await save(
                        enabled: newValue,
                        updateParticipants: updateParticipants,
                        pendingDays: pendingDays
                    )
                }
            }
        )
    }

    private var participantsBinding: Binding<Bool> {
        Binding(
            get: { updateParticipants },
            set: { newValue in
                Task {
                    await save(
                        enabled: enabled,
                        updateParticipants: newValue,
                        pendingDays: pendingDays
                    )
                }
            }
        )
    }

    private var pendingDaysBinding: Binding<Int> {
        Binding(
            get: { pendingDays },
            set: { newValue in
                Task {
                    await save(
                        enabled: enabled,
                        updateParticipants: updateParticipants,
                        pendingDays: newValue
                    )
                }
            }
        )
    }

    @MainActor
    private func load() async {
        do {
            apply(try await backend.loadVoiceSettings())
            errorMessage = nil
        } catch {
            errorMessage = friendlyMessage(error)
        }

        isLoaded = true
    }

    @MainActor
    private func save(
        enabled newEnabled: Bool,
        updateParticipants newUpdate: Bool,
        pendingDays newDays: Int
    ) async {
        guard !isBusy else {
            return
        }

        isBusy = true
        errorMessage = nil

        defer {
            isBusy = false
        }

        do {
            apply(
                try await backend.saveVoiceSettings(
                    enabled: newEnabled,
                    updateParticipants: newUpdate,
                    pendingDays: newDays
                )
            )
        } catch {
            errorMessage = friendlyMessage(error)

            // Show what is really saved, not what was just clicked.
            if let current = try? await backend.loadVoiceSettings() {
                apply(current)
            }
        }
    }

    /// The backend reports problems as a line of JSON with a "message".
    /// Show just that sentence when it is there.
    private func friendlyMessage(_ error: Error) -> String {
        let text = error.localizedDescription

        if let start = text.firstIndex(of: "{"),
           let data = String(text[start...]).data(using: .utf8),
           let object = try? JSONSerialization.jsonObject(with: data),
           let dictionary = object as? [String: Any],
           let message = dictionary["message"] as? String,
           !message.isEmpty {
            return message
        }

        return text
    }

    private func apply(_ response: VoiceSettingsResponse) {
        enabled = response.settings.enabled
        updateParticipants = response.settings.updateParticipants
        pendingDays = response.settings.pendingDays
        status = response.status
    }
}
