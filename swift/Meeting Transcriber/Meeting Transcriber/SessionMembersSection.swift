import SwiftUI

/// A collapsed strip under the session conversation. Opening it shows
/// which meetings the session contains and the context document the
/// assistant is given, so it is clear what questions are answered from.
struct SessionMembersSection: View {
    let detail: SessionDetail
    let meetings: [Meeting]

    @State private var isExpanded = false
    @State private var showsContext = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header

            if isExpanded {
                expandedContent
            }
        }
        .background(.background)
    }

    // MARK: - Pieces

    private var title: String {
        let count: Int = detail.meetingRuns.count
        let noun: String = count == 1 ? "meeting" : "meetings"
        return "Meetings in this session (" + String(count)
            + " " + noun + ")"
    }

    private var header: some View {
        Button {
            isExpanded.toggle()
        } label: {
            HStack(spacing: 6) {
                Image(
                    systemName: isExpanded
                        ? "chevron.down"
                        : "chevron.right"
                )
                .font(.caption2)
                .frame(width: 10)

                Text(title)
                    .font(.caption)
                    .fontWeight(.semibold)

                Spacer()
            }
            .foregroundStyle(.secondary)
            .contentShape(Rectangle())
            .padding(.horizontal, 24)
            .padding(.vertical, 7)
        }
        .buttonStyle(.plain)
    }

    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: 8) {
            ScrollView {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(detail.meetingRuns, id: \.self) { run in
                        Text(label(for: run))
                            .font(.caption)
                            .lineLimit(1)
                            .truncationMode(.tail)
                    }
                }
                .frame(
                    maxWidth: .infinity,
                    alignment: .leading
                )
            }
            .frame(maxHeight: 130)

            contextToggle

            if showsContext {
                ScrollView {
                    Text(detail.prepText)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(
                            maxWidth: .infinity,
                            alignment: .leading
                        )
                        .padding(8)
                }
                .frame(maxHeight: 180)
                .background(
                    RoundedRectangle(cornerRadius: 6)
                        .fill(.quaternary)
                )
            }
        }
        .padding(.horizontal, 24)
        .padding(.bottom, 10)
    }

    private var contextToggle: some View {
        Button {
            showsContext.toggle()
        } label: {
            let verb: String = showsContext ? "Hide" : "Show"
            Text(verb + " the context document sent to the assistant")
                .font(.caption)
        }
        .buttonStyle(.link)
    }

    private func label(for run: String) -> String {
        for meeting in meetings where meeting.run == run {
            return meeting.date + "  ·  " + meeting.title
        }

        return run
    }
}
