import SwiftUI

struct SearchView: View {
    @EnvironmentObject
    private var navigation: AppNavigationController

    @State private var isSearching = false
    @State private var errorMessage: String?

    @State private var meetingDetail: MeetingDetail?
    @State private var sessionDetail: SessionDetail?
    @State private var isLoadingDetail = false
    @State private var detailErrorMessage: String?

    private let backend = BackendService()

    private var selectedResult: GlobalSearchResult? {
        guard let selectedResultID = navigation.searchSelectedResultID,
              let response = navigation.searchResponse else {
            return nil
        }

        return (response.meetings + response.sessions).first {
            $0.id == selectedResultID
        }
    }

    var body: some View {
        GeometryReader { geometry in
            Group {
                if selectedResult == nil {
                    resultsPane
                        .frame(
                            maxWidth: .infinity,
                            maxHeight: .infinity,
                            alignment: .topLeading
                        )
                } else {
                    HSplitView {
                        resultsPane
                            .frame(
                                minWidth: 320,
                                idealWidth: 390,
                                maxWidth: 500,
                                maxHeight: .infinity,
                                alignment: .topLeading
                            )

                        detailPane
                            .frame(
                                minWidth: 620,
                                idealWidth: 900,
                                maxHeight: .infinity,
                                alignment: .topLeading
                            )
                    }
                }
            }
            .frame(
                width: geometry.size.width,
                height: geometry.size.height
            )
        }
        .navigationTitle("Search")
        .task(id: navigation.searchSelectedResultID) {
            await loadSelectedDetail()
        }
    }

    private var resultsPane: some View {
        VStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    TextField(
                        "Search meetings and sessions",
                        text: $navigation.searchQuery
                    )
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        Task { await runSearch() }
                    }

                    Button("Search") {
                        Task { await runSearch() }
                    }
                    .keyboardShortcut(.defaultAction)
                    .disabled(
                        navigation.searchQuery.trimmingCharacters(
                            in: .whitespacesAndNewlines
                        ).isEmpty || isSearching
                    )
                }

                if isSearching {
                    HStack(spacing: 8) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Searching local meeting history…")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else if let response = navigation.searchResponse {
                    Text(
                        "\(response.totalCount) result\(response.totalCount == 1 ? "" : "s")"
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                } else {
                    Text(
                        "Search Meetings and Sessions by title, people, summary, topics, decisions, questions, commitments, follow-ups, Session criteria, and saved Session content."
                    )
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }

                if let errorMessage {
                    Text(errorMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
            .padding(16)

            Divider()

            if let response = navigation.searchResponse, response.totalCount == 0 {
                ContentUnavailableView(
                    "No Results",
                    systemImage: "magnifyingglass",
                    description: Text(
                        "No Meetings or Sessions matched “\(response.query)”."
                    )
                )
            } else {
                List(selection: searchSelectionBinding) {
                    if let sessions = navigation.searchResponse?.sessions,
                       !sessions.isEmpty {
                        Section {
                            ForEach(sessions) { result in
                                resultRow(result)
                                    .tag(result.id)
                            }
                        } header: {
                            resultSectionHeader(
                                title: "Sessions",
                                count: sessions.count,
                                systemImage: "rectangle.stack.fill"
                            )
                        }
                    }

                    if let meetings = navigation.searchResponse?.meetings,
                       !meetings.isEmpty {
                        Section {
                            ForEach(meetings) { result in
                                resultRow(result)
                                    .tag(result.id)
                            }
                        } header: {
                            resultSectionHeader(
                                title: "Meetings",
                                count: meetings.count,
                                systemImage: "doc.text.fill"
                            )
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        }
    }


    private var searchSelectionBinding: Binding<GlobalSearchResult.ID?> {
        Binding(
            get: { navigation.searchSelectedResultID },
            set: { newValue in
                Task { @MainActor in
                    await Task.yield()
                    navigation.searchSelectedResultID = newValue
                }
            }
        )
    }

    private func resultRow(
        _ result: GlobalSearchResult
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(
                    systemName: result.isMeeting
                        ? "doc.text.fill"
                        : "rectangle.stack.fill"
                )
                .font(.body)
                .foregroundStyle(.secondary)

                Text(result.isMeeting ? "MEETING" : "SESSION")
                    .font(.caption2)
                    .fontWeight(.bold)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(
                        Capsule()
                            .fill(.quaternary)
                    )

                Text(result.title)
                    .fontWeight(.semibold)
                    .lineLimit(1)
            }

            if !result.subtitle.isEmpty {
                Text(result.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Text(result.snippet)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(.vertical, 4)
    }


    private func resultSectionHeader(
        title: String,
        count: Int,
        systemImage: String
    ) -> some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
            Text("\(title.uppercased()) (\(count))")
                .fontWeight(.bold)
        }
    }

    @ViewBuilder
    private var detailPane: some View {
        if let result = selectedResult {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(alignment: .center, spacing: 10) {
                            Label(
                                result.isMeeting ? "MEETING" : "SESSION",
                                systemImage: result.isMeeting
                                    ? "doc.text.fill"
                                    : "rectangle.stack.fill"
                            )
                            .font(.caption)
                            .fontWeight(.bold)
                            .foregroundStyle(.secondary)

                            Spacer()

                            Button {
                                openSelectedResult(result)
                            } label: {
                                Label(
                                    result.isMeeting
                                        ? "Open Meeting"
                                        : "Open Session",
                                    systemImage: "arrow.up.forward.app"
                                )
                                .lineLimit(1)
                                .fixedSize(horizontal: true, vertical: false)
                            }
                        }

                        Text(result.title)
                            .font(.title2)
                            .fontWeight(.semibold)

                        if !result.subtitle.isEmpty {
                            Text(result.subtitle)
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                    }

                    GroupBox("Why this matched") {
                        Text(result.snippet)
                            .frame(
                                maxWidth: .infinity,
                                alignment: .leading
                            )
                            .textSelection(.enabled)
                            .padding(.vertical, 4)
                    }

                    if isLoadingDetail {
                        ProgressView("Loading detail…")
                    }

                    if let detailErrorMessage {
                        Text(detailErrorMessage)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }

                    if result.isMeeting,
                       let meetingDetail {
                        MeetingMarkdownView(
                            markdown: meetingMarkdown(
                                detail: meetingDetail
                            )
                        )
                    } else if result.isSession,
                              let sessionDetail {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("Session Context")
                                .font(.headline)

                            SelectableStructuredTextView(
                                text: sessionDetail.prepText
                            )
                        }
                    }
                }
                .padding(24)
                .frame(
                    maxWidth: .infinity,
                    alignment: .topLeading
                )
            }
        } else {
            ContentUnavailableView(
                "Select a Search Result",
                systemImage: "magnifyingglass",
                description: Text(
                    "Search your local meeting history, then select a Meeting or Session to open its detail."
                )
            )
        }
    }

    private func runSearch() async {
        let cleaned = navigation.searchQuery.trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        guard !cleaned.isEmpty else { return }

        isSearching = true
        errorMessage = nil

        do {
            let result = try await backend.globalSearch(
                query: cleaned
            )
            navigation.searchResponse = result

            let ids = Set(
                (result.meetings + result.sessions).map(\.id)
            )
            if let selectedResultID = navigation.searchSelectedResultID,
               !ids.contains(selectedResultID) {
                navigation.searchSelectedResultID = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }

        isSearching = false
    }

    private func loadSelectedDetail() async {
        meetingDetail = nil
        sessionDetail = nil
        detailErrorMessage = nil

        guard let result = selectedResult else {
            return
        }

        isLoadingDetail = true

        do {
            if result.isMeeting {
                meetingDetail = try await backend.loadMeetingDetail(
                    run: result.meetingRun
                )
            } else if result.isSession {
                sessionDetail = try await backend.loadSessionDetail(
                    name: result.sessionName
                )
            }
        } catch {
            detailErrorMessage = error.localizedDescription
        }

        isLoadingDetail = false
    }

    private func openSelectedResult(
        _ result: GlobalSearchResult
    ) {
        if result.isMeeting {
            navigation.openMeeting(run: result.meetingRun)
        } else if result.isSession {
            navigation.openSession(name: result.sessionName)
        }
    }

    private func meetingMarkdown(
        detail: MeetingDetail
    ) -> String {
        var sections: [String] = []

        if detail.hasSummary, !detail.summary.isEmpty {
            sections.append("# Summary\n\n\(detail.summary)")
        }

        if !detail.commitments.isEmpty {
            let commitments = detail.commitments.map { item in
                let owner = item.owner.isEmpty
                    ? ""
                    : "**\(item.owner):** "
                let status = item.status.isEmpty
                    ? ""
                    : " (\(item.status))"
                return "- \(owner)\(item.action)\(status)"
            }
            .joined(separator: "\n\n")

            sections.append(
                "# Commitments\n\n\(commitments)"
            )
        }

        if !detail.topics.isEmpty {
            let topics = detail.topics.map { topic in
                let status = topic.status.isEmpty
                    ? ""
                    : " — \(topic.status)"
                return "## \(topic.name)\(status)\n\n\(topic.summary)"
            }
            .joined(separator: "\n\n")

            sections.append("# Topics\n\n\(topics)")
        }

        return sections.joined(separator: "\n\n")
    }
}
