import SwiftUI

// MARK: - Data from the backend

nonisolated struct MeetingVoiceSuggestion: Decodable, Sendable, Equatable {
    let person: String
    let score: Double
}

nonisolated struct MeetingVoice: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let label: String
    let seconds: Int
    let status: String
    let person: String?
    let via: String?
    let suggestion: MeetingVoiceSuggestion?
    let short: Bool
    let canLearn: Bool

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case seconds
        case status
        case person
        case via
        case suggestion
        case short
        case canLearn = "can_learn"
    }

    var isNamed: Bool { status == "named" }

    var lengthText: String {
        if seconds < 60 {
            return "\(seconds) sec"
        }

        let minutes = Double(seconds) / 60

        return String(format: "%.1f min", minutes)
    }
}

nonisolated struct MeetingVoicesResponse: Decodable, Sendable {
    let run: String
    let remoteSilent: Bool
    let voices: [MeetingVoice]
    let people: [String]

    enum CodingKeys: String, CodingKey {
        case run
        case remoteSilent = "remote_silent"
        case voices
        case people
    }
}

nonisolated struct MeetingVoiceNameResult: Decodable, Sendable {
    let named: Int
    let learned: Int
    let rematch: VoiceRematch?
}

nonisolated struct RecentVoiceMeeting: Decodable, Sendable, Identifiable, Equatable {
    let run: String
    let title: String
    let date: String
    let voices: Int
    let unnamed: Int

    var id: String { run }
}

nonisolated struct RecentVoiceMeetingsResponse: Decodable, Sendable {
    let meetings: [RecentVoiceMeeting]
}

/// What the "Voices in this meeting" sheet is opened for.
struct VoiceSheetTarget: Identifiable, Equatable {
    let run: String
    let title: String

    var id: String { run }
}

// MARK: - The sheet

/// Lists the voices in one meeting so any of them can be listened to and
/// named, even when the voice has not shown up in other meetings yet.
struct MeetingVoicesSheet: View {
    let target: VoiceSheetTarget
    let onChanged: () -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var voices: [MeetingVoice] = []
    @State private var people: [String] = []
    @State private var remoteSilent = false
    @State private var isLoading = true
    @State private var errorMessage: String?
    @State private var message: String?

    @StateObject private var player = ClipPlayer()

    private let backend = BackendService()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Voices in this meeting")
                        .font(.title3.weight(.semibold))

                    Text(target.title)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Spacer()

                Button("Done") {
                    player.purgeFiles()
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding(20)

            Divider()

            content
        }
        .frame(minWidth: 620, minHeight: 460)
        .task {
            await load()
        }
        .onDisappear {
            player.purgeFiles()
        }
    }

    @ViewBuilder
    private var content: some View {
        if isLoading {
            VStack {
                Spacer()
                ProgressView()
                Spacer()
            }
            .frame(maxWidth: .infinity)
        } else if let errorMessage, voices.isEmpty {
            Text(errorMessage)
                .foregroundStyle(.red)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else if remoteSilent {
            Text("The other people were not captured in this recording, so there are no voices to name.")
                .foregroundStyle(.secondary)
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if let message {
                        Text(message)
                            .font(.callout)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                Color.green.opacity(0.12),
                                in: RoundedRectangle(cornerRadius: 10)
                            )
                    }

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.callout)
                            .foregroundStyle(.red)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    ForEach(voices) { voice in
                        MeetingVoiceRow(
                            run: target.run,
                            voice: voice,
                            people: people,
                            player: player,
                            onNamed: { text in
                                message = text
                                errorMessage = nil
                                onChanged()

                                Task {
                                    await load()
                                }
                            }
                        )
                    }

                    Text("Only name voices you are sure about. Wrong names are hard to undo.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
            }
        }
    }

    @MainActor
    private func load() async {
        do {
            let response = try await backend.loadMeetingVoices(
                run: target.run
            )
            voices = response.voices
            people = response.people
            remoteSilent = response.remoteSilent
            errorMessage = nil
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }

        isLoading = false
    }
}

// MARK: - One voice

private struct MeetingVoiceRow: View {
    let run: String
    let voice: MeetingVoice
    let people: [String]
    @ObservedObject var player: ClipPlayer
    let onNamed: (String) -> Void

    @State private var clips: [VoiceClip] = []
    @State private var clipsLoaded = false
    @State private var isLoadingClips = false
    @State private var name = ""
    @State private var isNaming = false
    @State private var showConfirm = false
    @State private var errorMessage: String?

    private let backend = BackendService()

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Voice \(voice.label)")
                    .font(.headline)

                Text(voice.lengthText)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Spacer()

                if voice.isNamed, let person = voice.person {
                    Label(person, systemImage: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                }
            }

            clipsSection

            if !voice.isNamed {
                nameSection
            }

            if let errorMessage {
                Text(errorMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            Color.secondary.opacity(0.08),
            in: RoundedRectangle(cornerRadius: 10)
        )
        .confirmationDialog(
            "Name voice \(voice.label) as \(trimmedName)?",
            isPresented: $showConfirm,
            titleVisibility: .visible
        ) {
            Button("Name as \(trimmedName)") {
                Task {
                    await nameVoice()
                }
            }

            Button("Cancel", role: .cancel) {}
        } message: {
            Text(confirmText)
        }
    }

    private var confirmText: String {
        if voice.canLearn {
            return "This names the voice in this meeting and teaches the app what \(trimmedName) sounds like, so other meetings are checked too."
        }

        return "This voice has too little speech to learn from, so only this meeting is labeled."
    }

    @ViewBuilder
    private var clipsSection: some View {
        if !clipsLoaded {
            HStack {
                Button {
                    Task {
                        await loadClips()
                    }
                } label: {
                    Label("Listen", systemImage: "play.circle")
                }
                .disabled(isLoadingClips)

                if isLoadingClips {
                    ProgressView()
                        .controlSize(.small)
                }
            }
        } else if clips.isEmpty {
            Text("No clip could be made. The audio for this meeting may no longer be available.")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else {
            HStack(spacing: 14) {
                ForEach(Array(clips.enumerated()), id: \.element.id) { index, clip in
                    Button {
                        player.toggle(path: clip.path)
                    } label: {
                        Label(
                            "Clip \(index + 1) · \(clip.meeting)",
                            systemImage: player.playingPath == clip.path
                                ? "stop.circle.fill"
                                : "play.circle"
                        )
                    }
                    .buttonStyle(.borderless)
                }
            }
        }
    }

    private var nameSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            if voice.short || !voice.canLearn {
                Text("Short voice. There is too little speech to learn a reliable fingerprint, so naming it only labels this meeting.")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if let suggestion = voice.suggestion,
               suggestion.score >= 0.3 {
                HStack {
                    Text("Closest match, not confident:")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    Button(suggestion.person) {
                        name = suggestion.person
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                }
            }

            HStack {
                TextField("Who is this?", text: $name)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 240)
                    .onSubmit {
                        if !trimmedName.isEmpty {
                            showConfirm = true
                        }
                    }

                if !people.isEmpty {
                    Menu("Known people") {
                        ForEach(people, id: \.self) { person in
                            Button(person) {
                                name = person
                            }
                        }
                    }
                    .fixedSize()
                }

                Button("Name Voice") {
                    showConfirm = true
                }
                .buttonStyle(.borderedProminent)
                .disabled(trimmedName.isEmpty || isNaming)

                if isNaming {
                    ProgressView()
                        .controlSize(.small)
                }
            }
        }
    }

    @MainActor
    private func loadClips() async {
        guard !isLoadingClips else {
            return
        }

        isLoadingClips = true
        errorMessage = nil
        defer {
            isLoadingClips = false
        }

        do {
            let response = try await backend.makeMeetingVoiceClips(
                run: run,
                voiceID: voice.id
            )
            clips = response.clips
            player.remember(paths: response.clips.map(\.path))
            clipsLoaded = true
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }
    }

    @MainActor
    private func nameVoice() async {
        guard !isNaming, !trimmedName.isEmpty else {
            return
        }

        isNaming = true
        errorMessage = nil
        player.stop()
        defer {
            isNaming = false
        }

        let chosen = trimmedName

        do {
            let result = try await backend.nameMeetingVoice(
                run: run,
                voiceID: voice.id,
                name: chosen
            )

            var text = "Named voice \(voice.label) as \(chosen)."

            if let summary = result.rematch?.summary {
                text += " " + summary
            } else if result.rematch?.error != nil {
                text += " The quick re-check of your other meetings did not finish. You can run: python3 voice_cli.py rematch"
            }

            onNamed(text)
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }
    }
}
