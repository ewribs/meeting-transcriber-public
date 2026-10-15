import SwiftUI

/// "What changed since last time?" for the open session: compares its
/// two most recent meetings. Shown as the Changes tab in Meetings.
struct SessionChangesPanel: View {
    let session: SavedSession

    @State private var changes: SessionChangesResponse?
    @State private var isLoading = false
    @State private var loadError: String?

    private let backend = BackendService()

    var body: some View {
        content
            .task(id: session.name) {
                changes = nil
                loadError = nil
                await load(force: false)
            }
    }

    // MARK: - States

    @ViewBuilder
    private var content: some View {
        if isLoading {
            VStack(spacing: 10) {
                ProgressView()

                Text("Comparing the latest meetings…")
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let loadError {
            ContentUnavailableView {
                Label(
                    "Unable to compare meetings",
                    systemImage: "exclamationmark.triangle"
                )
            } description: {
                Text(loadError)
                    .textSelection(.enabled)
            } actions: {
                Button("Try Again") {
                    Task {
                        await load(force: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let changes {
            changesScroll(changes)
        } else {
            ContentUnavailableView {
                Label(
                    "Compare recent meetings",
                    systemImage: "arrow.left.arrow.right"
                )
            } description: {
                Text("Compare the two most recent meetings in this session.")
            } actions: {
                Button("What changed since last time?") {
                    Task {
                        await load(force: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    private func changesScroll(
        _ changes: SessionChangesResponse
    ) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if changes.available {
                    header(changes)

                    MeetingMarkdownView(markdown: changes.markdown)

                    Text(
                        String(
                            format: "Generated in %.1f sec",
                            changes.elapsedSeconds
                        )
                    )
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                } else {
                    ContentUnavailableView(
                        "Not enough meetings yet",
                        systemImage: "arrow.left.arrow.right",
                        description: Text(changes.markdown)
                    )
                    .frame(maxWidth: .infinity, minHeight: 260)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 24)
            .padding(.vertical, 18)
        }
    }

    private func header(
        _ changes: SessionChangesResponse
    ) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 3) {
                Text("What changed since last time?")
                    .font(.headline)

                if let generatedAt = formattedTimestamp(
                    changes.generatedAt
                ) {
                    Text("Last run: " + generatedAt)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let previous = changes.previousLabel,
                   let latest = changes.latestLabel {
                    Text("Compared: " + previous + "  →  " + latest)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if changes.isStale {
                    Label(
                        "New meetings available. Refresh to compare the latest.",
                        systemImage: "clock.badge.exclamationmark"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }
            }

            Spacer()

            Button {
                Task {
                    await load(force: true)
                }
            } label: {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .buttonStyle(.bordered)
        }
    }

    // MARK: - Actions

    @MainActor
    private func load(force: Bool) async {
        if isLoading {
            return
        }

        if changes != nil, !force {
            return
        }

        let name: String = session.name

        isLoading = true
        loadError = nil

        do {
            let loaded = try await backend.loadSessionChanges(
                name: name,
                force: force
            )

            if name == session.name {
                changes = loaded
            }
        } catch {
            if name == session.name {
                loadError = error.localizedDescription
            }
        }

        isLoading = false
    }

    private func formattedTimestamp(_ rawValue: String?) -> String? {
        guard let rawValue, !rawValue.isEmpty else {
            return nil
        }

        guard let date = ISO8601DateFormatter().date(from: rawValue) else {
            return rawValue
        }

        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}
