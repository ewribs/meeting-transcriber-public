import SwiftUI

/// The saved conversation for one session, shown in the Meetings
/// Context tab when a session is open and no meetings are ticked.
/// Questions are asked of the whole session and stored with it, so
/// the conversation is there again next time the session is opened.
struct SessionChatPanel: View {
    let session: SavedSession
    var meetings: [Meeting] = []
    let onChanged: () -> Void

    @AppStorage("ask.showFavorites") private var showFavorites = true
    @State private var detail: SessionDetail?
    @State private var isLoading = false
    @State private var loadError: String?
    @State private var queryText = ""
    @State private var queryMode = "normal"
    @State private var isRunning = false
    @State private var pendingPrompt: String?
    @State private var statusMessage: String?
    @State private var queryError: String?

    private let backend = BackendService()

    var body: some View {
        VStack(spacing: 0) {
            savedStrip
            conversationArea
            Divider()
            membersStrip
            composer
        }
        .task(id: session.name) {
            await load(reset: true)
        }
    }

    // MARK: - Pieces

    @ViewBuilder
    private var membersStrip: some View {
        if let detail {
            SessionMembersSection(
                detail: detail,
                meetings: meetings
            )

            Divider()
        }
    }

    private var savedStrip: some View {
        let count: Int = detail?.meetingCount ?? session.meetingCount
        let noun: String = count == 1 ? "meeting" : "meetings"
        let lead: String = "Asking about all " + String(count)
            + " " + noun + ". "
        let tail: String = "Questions and answers are saved in this session."

        return Text(lead + tail)
            .font(.caption)
            .foregroundStyle(Color.green)
            .frame(
                maxWidth: .infinity,
                alignment: .leading
            )
            .padding(.horizontal, 24)
            .padding(.vertical, 7)
            .background(Color.green.opacity(0.12))
    }

    @ViewBuilder
    private var conversationArea: some View {
        if let loadError {
            ContentUnavailableView {
                Label(
                    "Unable to open session",
                    systemImage: "exclamationmark.triangle"
                )
            } description: {
                Text(loadError)
                    .textSelection(.enabled)
            } actions: {
                Button("Try Again") {
                    Task {
                        await load(reset: false)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let detail {
            conversationScroll(detail)
        } else {
            VStack(spacing: 10) {
                ProgressView()
                Text("Resuming session context…")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func conversationScroll(
        _ detail: SessionDetail
    ) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    conversationBody(detail)

                    Color.clear
                        .frame(height: 1)
                        .id("conversation-bottom")
                }
                .frame(
                    maxWidth: .infinity,
                    alignment: .leading
                )
                .padding(.horizontal, 24)
                .padding(.vertical, 18)
            }
            .onAppear {
                scrollToBottom(proxy, animated: false)
            }
            .onChange(of: detail.conversation.count) {
                scrollToBottom(proxy, animated: true)
            }
            .onChange(of: pendingPrompt) {
                scrollToBottom(proxy, animated: true)
            }
        }
    }

    @ViewBuilder
    private func conversationBody(
        _ detail: SessionDetail
    ) -> some View {
        if detail.conversation.isEmpty && pendingPrompt == nil {
            ContentUnavailableView(
                "No conversation yet",
                systemImage: "bubble.left",
                description: Text(
                    "Ask a question below to start this session conversation."
                )
            )
            .frame(maxWidth: .infinity, minHeight: 220)
        } else {
            if !detail.conversation.isEmpty {
                MeetingMarkdownView(
                    markdown: markdown(detail.conversation)
                )
            }

            if let pendingPrompt {
                Divider()

                MeetingMarkdownView(
                    markdown: "## You\n\n" + pendingPrompt
                )

                HStack(spacing: 10) {
                    ProgressView()
                        .controlSize(.small)

                    Text("Qwen is working…")
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 10) {
            if showFavorites {
                PromptFavoritesBar(
                    promptText: $queryText,
                    onSelect: { favorite in
                        queryMode = favorite.category == "changes"
                            ? "changes"
                            : "normal"
                    }
                )

                Divider()
            }

            HStack {
                Text("Ask this Session")
                    .font(.headline)

                Spacer()

                if let statusMessage, !isRunning {
                    Text(statusMessage)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }

            HStack(alignment: .bottom, spacing: 10) {
                TextEditor(text: $queryText)
                    .font(.body)
                    .frame(minHeight: 58, maxHeight: 96)
                    .padding(5)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(.quaternary)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(.separator, lineWidth: 1)
                    )
                    .disabled(isRunning)

                sendButton
            }

            if let queryError {
                Text(queryError)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            } else {
                Text("⌘↩ sends")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
        .background(.background)
    }

    private var sendButton: some View {
        let isEmpty: Bool = queryText
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .isEmpty

        return Button {
            Task {
                await send()
            }
        } label: {
            ZStack {
                Label("Send", systemImage: "paperplane.fill")
                    .opacity(isRunning ? 0 : 1)

                if isRunning {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .frame(minWidth: 72, minHeight: 30)
        }
        .buttonStyle(.borderedProminent)
        .keyboardShortcut(.return, modifiers: [.command])
        .disabled(isRunning || isEmpty)
    }

    // MARK: - Actions

    @MainActor
    private func load(reset: Bool) async {
        let name: String = session.name

        if reset {
            detail = nil
            loadError = nil
            queryText = ""
            queryMode = "normal"
            pendingPrompt = nil
            statusMessage = nil
            queryError = nil
        }

        isLoading = true

        do {
            let loaded = try await backend.loadSessionDetail(
                name: name
            )

            if name == session.name {
                detail = loaded
                loadError = nil
            }
        } catch {
            if name == session.name {
                loadError = error.localizedDescription
            }
        }

        isLoading = false
    }

    @MainActor
    private func send() async {
        let prompt: String = queryText.trimmingCharacters(
            in: .whitespacesAndNewlines
        )

        if prompt.isEmpty || isRunning {
            return
        }

        let name: String = session.name
        let mode: String = queryMode

        pendingPrompt = prompt
        queryText = ""
        isRunning = true
        statusMessage = nil
        queryError = nil

        do {
            let result = try await backend.runSessionQuery(
                name: name,
                prompt: prompt,
                queryMode: mode
            )

            if name == session.name {
                await load(reset: false)

                let seconds: String = String(
                    format: "%.1fs",
                    result.elapsedSeconds
                )

                pendingPrompt = nil
                queryMode = "normal"
                statusMessage = result.statusText + " · " + seconds
            }

            onChanged()
        } catch {
            if name == session.name {
                pendingPrompt = nil
                queryText = prompt
                queryError = error.localizedDescription
            }
        }

        isRunning = false
    }

    private func markdown(
        _ items: [SessionConversationItem]
    ) -> String {
        var parts: [String] = []

        for item in items {
            let speaker: String = item.isUser ? "You" : "Assistant"
            parts.append("## " + speaker + "\n\n" + item.content)
        }

        return parts.joined(separator: "\n\n")
    }

    private func scrollToBottom(
        _ proxy: ScrollViewProxy,
        animated: Bool
    ) {
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.2)) {
                    proxy.scrollTo(
                        "conversation-bottom",
                        anchor: .bottom
                    )
                }
            } else {
                proxy.scrollTo(
                    "conversation-bottom",
                    anchor: .bottom
                )
            }
        }
    }
}
