//
//  Meeting_TranscriberApp.swift
//  Meeting Transcriber
//
//  Created for the Meeting Transcriber project.
//

import AppKit
import SwiftUI

/// Warns before quitting while a recording is being captured or is
/// still being encoded in the background, because quitting then
/// would lose it.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak static var recordingController: RecordingController?

    func applicationShouldTerminate(
        _ sender: NSApplication
    ) -> NSApplication.TerminateReply {
        guard let controller = Self.recordingController,
              controller.isRecording || controller.isFinalizing
        else {
            return .terminateNow
        }

        let alert = NSAlert()
        alert.alertStyle = .warning

        if controller.isRecording {
            alert.messageText = "A recording is in progress."
            alert.informativeText =
                "If you quit now, the recording in progress will be lost."
        } else {
            alert.messageText =
                "A recording is still being finished."
            alert.informativeText =
                "The recording is still being saved in the background. If you quit now, it will not be added to the transcription queue. Wait a minute or so, then quit."
        }

        alert.addButton(withTitle: "Keep Open")
        alert.addButton(withTitle: "Quit Anyway")

        return alert.runModal() == .alertSecondButtonReturn
            ? .terminateNow
            : .terminateCancel
    }
}

@main
struct Meeting_TranscriberApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self)
    private var appDelegate

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
                .onAppear {
                    AppDelegate.recordingController =
                        recordingController
                }
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

                    // Best-effort local copy of folders and saved sessions.
                    try? await BackendService().backupState()

                    // Finish any recording left unfinished by a crash or
                    // by quitting while it was still being encoded.
                    await recordingController.recoverPendingRecordings { path in
                        transcriptionController.addRecordingPaths([path])
                    }
                }
        }

        Settings {
            PreferencesView()
        }
    }
}
