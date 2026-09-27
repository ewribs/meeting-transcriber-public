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
        }

        Settings {
            PreferencesView()
        }
    }
}
