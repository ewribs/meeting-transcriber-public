import SwiftUI

struct ContentView: View {
    @EnvironmentObject
    private var navigation: AppNavigationController

    private var workspaceSelectionBinding: Binding<AppNavigationController.Workspace?> {
        Binding(
            get: { navigation.workspace },
            set: { newValue in
                Task { @MainActor in
                    await Task.yield()
                    navigation.workspace = newValue
                }
            }
        )
    }

    var body: some View {
        NavigationSplitView {
            List(
                AppNavigationController.Workspace.allCases,
                selection: workspaceSelectionBinding
            ) { workspace in
                Label(
                    workspace.rawValue,
                    systemImage: workspace.systemImage
                )
                .tag(workspace)
            }
            .navigationTitle("Meeting Transcriber")
        } detail: {
            Group {
                switch navigation.workspace {
                case .transcribe:
                    TranscribeView()

                case .meetings:
                    MeetingsView()

                case .sessions:
                    SessionsView()

                case .search:
                    SearchView()

                case nil:
                    ContentUnavailableView(
                        "Select a workspace",
                        systemImage: "sidebar.left"
                    )
                }
            }
        }
        .frame(minWidth: 900, minHeight: 600)
    }
}

private struct PlaceholderView: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(spacing: 12) {
            Text(title)
                .font(.largeTitle)
                .fontWeight(.semibold)

            Text(subtitle)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(40)
    }
}

#Preview {
    ContentView()
        .environmentObject(
            AppNavigationController()
        )
}
