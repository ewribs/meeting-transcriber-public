import Combine
import Foundation

@MainActor
final class MeetingContextController:
    ObservableObject
{
    @Published
    var meetingIDs: Set<String> = []

    @Published
    var builtContext:
        MeetingContextResponse?

    @Published
    var conversation:
        [SessionConversationItem] = []

    @Published
    var prompt = "" {
        didSet {
            schedulePlanPreview()
        }
    }

    @Published
    var queryMode = "normal" {
        didSet {
            schedulePlanPreview()
        }
    }

    @Published
    private(set) var planPreviewMessage: String?

    @Published
    var isBuildingContext = false

    @Published
    var isRunningQuery = false

    @Published
    var errorMessage: String?

    @Published
    var statusMessage: String?

    @Published
    var searchText = ""

    @Published
    var statusFilterRawValue =
        "All statuses"

    private let backend =
        BackendService()

    private let planPreviewBackend =
        BackendService()

    private var queryTask:
        Task<Void, Never>?

    private var planPreviewTask:
        Task<Void, Never>?

    func toggleMeeting(
        id: String
    ) {
        guard !isRunningQuery else {
            return
        }

        if meetingIDs.contains(id) {
            meetingIDs.remove(id)
        } else {
            meetingIDs.insert(id)
        }

        invalidateBuiltContext()
    }

    func clearSelection() {
        guard !isRunningQuery else {
            return
        }

        meetingIDs.removeAll()
        builtContext = nil
        conversation = []
        prompt = ""
        queryMode = "normal"
        statusMessage = nil
        planPreviewMessage = nil
        errorMessage = nil
        cancelPlanPreview()
    }

    func buildContext(
        meetingRuns: [String]
    ) async {
        guard
            !meetingRuns.isEmpty,
            !isBuildingContext,
            !isRunningQuery
        else {
            return
        }

        isBuildingContext = true
        errorMessage = nil

        defer {
            isBuildingContext = false
        }

        do {
            builtContext =
                try await backend
                    .buildMeetingContext(
                        meetingRuns:
                            meetingRuns
                    )

            conversation = []
            statusMessage =
                "Context ready"
            schedulePlanPreview()

        } catch {
            errorMessage =
                error.localizedDescription
        }
    }

    func startQuery() {
        guard
            queryTask == nil,
            !isRunningQuery,
            let builtContext
        else {
            return
        }

        let trimmedPrompt =
            prompt.trimmingCharacters(
                in:
                    .whitespacesAndNewlines
            )

        guard !trimmedPrompt.isEmpty else {
            return
        }

        let priorConversation =
            conversation

        cancelPlanPreview()

        conversation.append(
            SessionConversationItem(
                role: "user",
                content: trimmedPrompt
            )
        )

        prompt = ""
        errorMessage = nil
        statusMessage =
            activeStatusText(
                for: queryMode
            )
        isRunningQuery = true

        let meetingRuns =
            builtContext.meetingRuns

        let activeQueryMode =
            queryMode

        queryTask = Task {
            defer {
                isRunningQuery = false
                queryTask = nil
            }

            do {
                if activeQueryMode
                    == "synthesis" {
                    let plan =
                        try await backend
                            .planMeetingContextQuery(
                                meetingRuns:
                                    meetingRuns,
                                prompt:
                                    trimmedPrompt,
                                conversation:
                                    priorConversation,
                                queryMode:
                                    activeQueryMode
                            )

                    if Task.isCancelled {
                        throw CancellationError()
                    }

                    statusMessage =
                        plan.statusText
                }

                let response =
                    try await backend
                        .queryMeetingContext(
                            meetingRuns:
                                meetingRuns,
                            prompt:
                                trimmedPrompt,
                            conversation:
                                priorConversation,
                            queryMode:
                                activeQueryMode
                        )

                conversation.append(
                    SessionConversationItem(
                        role: "assistant",
                        content:
                            response
                                .assistantResponse
                    )
                )

                statusMessage =
                    response.statusText
                queryMode = "normal"

            } catch is CancellationError {
                statusMessage =
                    "Query canceled"

            } catch {
                if Task.isCancelled {
                    statusMessage =
                        "Query canceled"
                } else {
                    errorMessage =
                        error.localizedDescription
                    statusMessage = nil
                }
            }
        }
    }

    func cancelQuery() {
        guard isRunningQuery else {
            return
        }

        statusMessage =
            "Canceling query…"

        queryTask?.cancel()
        backend.cancelActiveProcess()
    }

    private func schedulePlanPreview() {
        cancelPlanPreview()

        guard
            !isBuildingContext,
            !isRunningQuery,
            queryMode == "synthesis",
            let builtContext
        else {
            return
        }

        let trimmedPrompt =
            prompt.trimmingCharacters(
                in: .whitespacesAndNewlines
            )

        guard !trimmedPrompt.isEmpty else {
            return
        }

        let meetingRuns =
            builtContext.meetingRuns
        let priorConversation =
            conversation

        planPreviewTask = Task {
            do {
                try await Task.sleep(
                    nanoseconds: 350_000_000
                )

                try Task.checkCancellation()

                let plan =
                    try await planPreviewBackend
                        .planMeetingContextQuery(
                            meetingRuns:
                                meetingRuns,
                            prompt:
                                trimmedPrompt,
                            conversation:
                                priorConversation,
                            queryMode:
                                "synthesis"
                        )

                try Task.checkCancellation()

                guard
                    queryMode == "synthesis",
                    prompt.trimmingCharacters(
                        in: .whitespacesAndNewlines
                    ) == trimmedPrompt,
                    builtContext.meetingRuns
                        == meetingRuns
                else {
                    return
                }

                planPreviewMessage =
                    plan.statusText

            } catch is CancellationError {
                return

            } catch {
                // Planning is advisory. Keep the composer usable
                // even if a preview cannot be produced.
                return
            }
        }
    }

    private func cancelPlanPreview() {
        planPreviewTask?.cancel()
        planPreviewTask = nil
        planPreviewMessage = nil
        planPreviewBackend
            .cancelActiveProcess()
    }

    private func activeStatusText(
        for mode: String
    ) -> String {
        switch mode {
        case "synthesis":
            return "Planning Boss Prep…"
        case "changes":
            return "Comparing latest two meetings…"
        default:
            return "Qwen is working…"
        }
    }

    private func invalidateBuiltContext() {
        cancelPlanPreview()
        builtContext = nil
        conversation = []
        statusMessage = nil
        errorMessage = nil
    }
}
