import Combine
import Foundation

@MainActor
final class AppNavigationController: ObservableObject {
    enum Workspace: String, CaseIterable, Identifiable {
        case transcribe = "Transcribe"
        case meetings = "Meetings"
        case sessions = "Sessions"
        case search = "Search"

        var id: Self { self }

        var systemImage: String {
            switch self {
            case .transcribe:
                return "waveform"
            case .meetings:
                return "list.bullet.rectangle"
            case .sessions:
                return "bubble.left.and.bubble.right"
            case .search:
                return "magnifyingglass"
            }
        }
    }

    @Published var workspace: Workspace? = .transcribe

    @Published var searchQuery = ""
    @Published var searchResponse: GlobalSearchResponse?
    @Published var searchSelectedResultID: GlobalSearchResult.ID?

    @Published var requestedMeetingRun: String?
    @Published var requestedSessionName: String?

    func openMeeting(run: String) {
        requestedMeetingRun = run
        workspace = .meetings
    }

    func openSession(name: String) {
        requestedSessionName = name
        workspace = .sessions
    }
}
