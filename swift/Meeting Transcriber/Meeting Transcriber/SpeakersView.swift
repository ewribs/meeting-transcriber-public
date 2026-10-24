import AppKit
import AVFoundation
import Combine
import SwiftUI

// MARK: - Data from the backend

/// A voice that keeps coming back across meetings but has no name yet.
nonisolated struct VoiceGroup: Decodable, Sendable, Identifiable, Equatable {
    let id: String
    let meetings: Int
    let voices: Int
    let minutes: Double
    let first: String
    let last: String
    let hints: [String]
    let loose: Bool
    let recent: [String]
    let status: String
}

nonisolated struct VoiceGroupStateResponse: Decodable, Sendable {
    let status: String
}

nonisolated struct VoiceGroupsResponse: Decodable, Sendable {
    let groups: [VoiceGroup]
    let people: [String]
}

nonisolated struct VoiceClip: Decodable, Sendable, Identifiable, Equatable {
    let path: String
    let meeting: String
    let seconds: Int

    var id: String { path }
}

nonisolated struct VoiceClipsResponse: Decodable, Sendable {
    let clips: [VoiceClip]
}

nonisolated struct VoiceRematch: Decodable, Sendable {
    let summary: String?
    let error: String?
}

nonisolated struct VoiceNameResult: Decodable, Sendable {
    let named: Int
    let meetings: Int
    let learned: Int
    let rematch: VoiceRematch?
}

// MARK: - Playing a clip

/// Plays one short clip at a time.
@MainActor
final class ClipPlayer: NSObject, ObservableObject, AVAudioPlayerDelegate {
    @Published var playingPath: String?

    private var player: AVAudioPlayer?
    private var knownFiles = Set<String>()

    override init() {
        super.init()

        // Quitting the app while clips exist should not leave them behind.
        NotificationCenter.default.addObserver(
            forName: NSApplication.willTerminateNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.purgeFiles()
            }
        }
    }

    /// Remember clips so they can be deleted when no longer needed.
    func remember(paths: [String]) {
        knownFiles.formUnion(paths)
    }

    /// Stop playing and delete every clip this player has been given.
    func purgeFiles() {
        stop()

        for path in knownFiles {
            try? FileManager.default.removeItem(atPath: path)
        }

        knownFiles.removeAll()
    }

    /// Starts the clip, or stops it if it is the one already playing.
    func toggle(path: String) {
        if playingPath == path {
            stop()
            return
        }

        stop()

        do {
            let newPlayer = try AVAudioPlayer(
                contentsOf: URL(fileURLWithPath: path)
            )
            newPlayer.delegate = self
            newPlayer.play()
            player = newPlayer
            playingPath = path
        } catch {
            playingPath = nil
        }
    }

    func stop() {
        player?.stop()
        player = nil
        playingPath = nil
    }

    nonisolated func audioPlayerDidFinishPlaying(
        _ player: AVAudioPlayer,
        successfully flag: Bool
    ) {
        Task { @MainActor in
            self.stop()
        }
    }
}

// MARK: - The Speakers workspace

/// Recurring unnamed voices, with clips to listen to and a place to name them.
struct SpeakersView: View {
    @State private var groups: [VoiceGroup] = []
    @State private var people: [String] = []
    @State private var isLoading = false
    @State private var hasLoaded = false
    @State private var errorMessage: String?
    @State private var message: String?
    @State private var recentMeetings: [RecentVoiceMeeting] = []
    @State private var voicesSheetTarget: VoiceSheetTarget?

    @StateObject private var player = ClipPlayer()

    private let backend = BackendService()

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            Divider()

            content
        }
        .navigationTitle("Speakers")
        .sheet(item: $voicesSheetTarget) { target in
            MeetingVoicesSheet(target: target) {
                Task {
                    await load()
                }
            }
        }
        .task {
            if !hasLoaded {
                // Remove any clips a crash or force-quit left behind.
                await backend.clearVoiceClips()
                await load()
            }
        }
        .onDisappear {
            player.purgeFiles()
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Speakers")
                    .font(.title2.weight(.semibold))

                Text("Voices that keep coming back but have no name yet. Listen first, then name the ones you are sure about.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if isLoading {
                ProgressView()
                    .controlSize(.small)
            }

            Menu("Name Voices in a Meeting") {
                if recentMeetings.isEmpty {
                    Text("No meetings with voice information yet")
                }

                ForEach(recentMeetings) { meeting in
                    Button(
                        "\(meeting.date)  \(meeting.title)"
                            + (meeting.unnamed > 0
                                ? "  (\(meeting.unnamed) unnamed)"
                                : "")
                    ) {
                        voicesSheetTarget = VoiceSheetTarget(
                            run: meeting.run,
                            title: meeting.title
                        )
                    }
                }
            }
            .fixedSize()

            Button("Refresh") {
                Task {
                    await load()
                }
            }
            .disabled(isLoading)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 14)
    }

    @ViewBuilder
    private var content: some View {
        if !hasLoaded && isLoading {
            VStack {
                Spacer()
                ProgressView("Looking through your meetings…")
                Spacer()
            }
            .frame(maxWidth: .infinity)
        } else if let errorMessage {
            VStack(alignment: .leading, spacing: 8) {
                Text(errorMessage)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)

                Button("Try Again") {
                    Task {
                        await load()
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 14) {
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

                    if activeGroups.isEmpty {
                        ContentUnavailableView(
                            "No recurring unnamed voices",
                            systemImage: "person.wave.2",
                            description: Text("Voices show up here after meetings have been analyzed and the same unnamed voice appears in more than one meeting.")
                        )
                        .padding(.top, 40)
                    }

                    ForEach(activeGroups) { group in
                        card(for: group)
                    }

                    if !hiddenGroups.isEmpty {
                        DisclosureGroup(
                            "Hidden for now (\(hiddenGroups.count))"
                        ) {
                            VStack(alignment: .leading, spacing: 14) {
                                ForEach(hiddenGroups) { group in
                                    card(for: group)
                                }
                            }
                            .padding(.top, 10)
                        }
                    }

                    if !ignoredGroups.isEmpty {
                        DisclosureGroup(
                            "Not tracked (\(ignoredGroups.count))"
                        ) {
                            VStack(alignment: .leading, spacing: 14) {
                                ForEach(ignoredGroups) { group in
                                    card(for: group)
                                }
                            }
                            .padding(.top, 10)
                        }
                    }
                }
                .padding(24)
            }
        }
    }

    /// Groups seen in the most meetings come first, then the most speech.
    private func sorted(_ items: [VoiceGroup]) -> [VoiceGroup] {
        items.sorted {
            if $0.meetings != $1.meetings {
                return $0.meetings > $1.meetings
            }

            return $0.minutes > $1.minutes
        }
    }

    private var activeGroups: [VoiceGroup] {
        sorted(groups.filter { $0.status == "active" })
    }

    private var hiddenGroups: [VoiceGroup] {
        sorted(groups.filter { $0.status == "hidden" })
    }

    private var ignoredGroups: [VoiceGroup] {
        sorted(groups.filter { $0.status == "ignored" })
    }

    private func card(for group: VoiceGroup) -> some View {
        SpeakerGroupCard(
            group: group,
            people: people,
            player: player,
            onNamed: { text in
                message = text

                Task {
                    await load()
                }
            },
            onChanged: {
                Task {
                    await load()
                }
            }
        )
    }

    @MainActor
    private func load() async {
        guard !isLoading else {
            return
        }

        isLoading = true
        defer {
            isLoading = false
            hasLoaded = true
        }

        do {
            let response = try await backend.loadVoiceGroups()
            groups = response.groups
            people = response.people
            recentMeetings =
                (try? await backend.loadRecentVoiceMeetings()) ?? []
            errorMessage = nil
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }
    }
}

// MARK: - One group

private struct SpeakerGroupCard: View {
    let group: VoiceGroup
    let people: [String]
    @ObservedObject var player: ClipPlayer
    let onNamed: (String) -> Void
    let onChanged: () -> Void

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
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text(
                    "\(group.meetings) meetings · \(Int(group.minutes.rounded())) min of speech"
                )
                .font(.headline)

                Spacer()

                Text(dateRange)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Text("Recent: " + group.recent.joined(separator: " · "))
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            if group.loose {
                Text("This group may mix more than one person. Listen carefully before naming it.")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }

            clipsSection

            Divider()

            if group.status == "active" {
                nameSection
            }

            setAsideSection

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
            "Name all \(group.voices) voices in this group as \(trimmedName)?",
            isPresented: $showConfirm,
            titleVisibility: .visible
        ) {
            Button("Name as \(trimmedName)") {
                Task {
                    await nameGroup()
                }
            }

            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This names the voice in \(group.meetings) meetings and teaches the app what \(trimmedName) sounds like.")
        }
    }

    private var dateRange: String {
        group.first == group.last
            ? group.first
            : group.first + " to " + group.last
    }

    private var setAsideSection: some View {
        HStack {
            if group.status == "active" {
                Button("Hide for Now") {
                    Task {
                        await setStatus("hide")
                    }
                }
                .help("Move this to Hidden. You can bring it back later.")

                Button("Don't Track") {
                    Task {
                        await setStatus("ignore")
                    }
                }
                .help("You don't care who this is. It stops showing up here.")
            } else {
                Text(
                    group.status == "hidden"
                        ? "Hidden for now."
                        : "Not tracked."
                )
                .font(.caption)
                .foregroundStyle(.secondary)

                Button("Bring Back") {
                    Task {
                        await setStatus("restore")
                    }
                }
            }

            Spacer()
        }
        .controlSize(.small)
    }

    @MainActor
    private func setStatus(_ action: String) async {
        errorMessage = nil
        player.stop()

        do {
            _ = try await backend.setVoiceGroupState(
                groupID: group.id,
                action: action
            )
            onChanged()
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }
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
            Text("No clips could be made. The audio for these meetings may no longer be available.")
                .font(.caption)
                .foregroundStyle(.secondary)
        } else {
            VStack(alignment: .leading, spacing: 6) {
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

                Text("Do the clips sound like the same person?")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var nameSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !group.hints.isEmpty {
                HStack {
                    Text("Title hints:")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    ForEach(group.hints, id: \.self) { hint in
                        Button(hint) {
                            name = hint
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }

            HStack {
                TextField("Who is this?", text: $name)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 260)
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

                Button("Name Group") {
                    showConfirm = true
                }
                .buttonStyle(.borderedProminent)
                .disabled(trimmedName.isEmpty || isNaming)

                if isNaming {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            Text("Skip it if you are not sure. A wrong name is worse than no name.")
                .font(.caption)
                .foregroundStyle(.secondary)
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
            let response = try await backend.makeVoiceClips(groupID: group.id)
            clips = response.clips
            player.remember(paths: response.clips.map(\.path))
            clipsLoaded = true
        } catch {
            errorMessage = voiceFriendlyMessage(error)
        }
    }

    @MainActor
    private func nameGroup() async {
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
            let result = try await backend.nameVoiceGroup(
                groupID: group.id,
                name: chosen
            )

            var text =
                "Named \(result.named) voices in \(result.meetings) meetings as \(chosen)."

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

/// The backend reports problems as a line of JSON with a "message".
/// Show just that sentence when it is there.
func voiceFriendlyMessage(_ error: Error) -> String {
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
