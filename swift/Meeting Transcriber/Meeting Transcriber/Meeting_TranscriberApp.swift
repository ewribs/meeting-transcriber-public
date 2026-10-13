//
//  Meeting_TranscriberApp.swift
//  Meeting Transcriber
//
//  Created for the Meeting Transcriber project.
//

import SwiftUI

@main
struct Meeting_TranscriberApp: App {
    @StateObject
    private var transcriptionController =
        TranscriptionController()

    @StateObject
    private var recordingController =
        RecordingController()

    @StateObject
    private var meetingContextController =
        MeetingContextController()

    @StateObject
    private var promptFavoritesController =
        PromptFavoritesController()

    @StateObject
    private var appNavigationController =
        AppNavigationController()


    @State
    private var didRunStartupMaintenance = false

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(
                    transcriptionController
                )
                .environmentObject(
                    recordingController
                )
                .environmentObject(
                    meetingContextController
                )
                .environmentObject(
                    promptFavoritesController
                )
                .environmentObject(
                    appNavigationController
                )
                .task {
                    guard !didRunStartupMaintenance else {
                        return
                    }

                    didRunStartupMaintenance = true

                    do {
                        try await BackendService()
                            .performStartupRetention()
                    } catch {
                        // Startup maintenance is deliberately non-fatal.
                        // The app should still open when the archive volume
                        // is unavailable or retention encounters an error.
                        print(
                            "Startup retention warning: \(error.localizedDescription)"
                        )
                    }
                }
        }

        Settings {
            PreferencesView()
        }
    }
}
