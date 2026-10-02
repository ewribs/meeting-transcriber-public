//
//  Meeting_TranscriberTests.swift
//  Meeting TranscriberTests
//
//  Created for the Meeting Transcriber project.
//

import Foundation
import Testing
@testable import Meeting_Transcriber

struct Meeting_TranscriberTests {

    @Test func preferencesDecodeResolvedAutoProfile() throws {
        let json = #"""
        {
          "schema_version": 16,
          "settings": {
            "performance_profile": "Auto",
            "llm_backend": "auto",
            "output_dir": "/work",
            "archive_dir": "/archive",
            "recordings_dir": "/recordings",
            "llm_model": "qwen3:14b",
            "mlx_model": "Qwen/Qwen3-30B-A3B-MLX-6bit",
            "llm_context_size": 0,
            "llm_context_mode": "profile_default",
            "m4a_retention_days": 30,
            "archived_m4a_retention_days": 365
          },
          "backend_options": [
            {
              "value": "auto",
              "label": "Auto (Recommended)",
              "description": "Selects the best local backend for this Mac."
            }
          ],
          "resolved_llm_backend": {
            "requested_name": "auto",
            "resolved_name": "mlx",
            "effective_model": "Qwen/Qwen3-30B-A3B-MLX-6bit",
            "reason": "Auto selected MLX.",
            "mlx_available": true,
            "auto_eligible": true
          },
          "performance_profiles": [
            "Auto",
            "Conservative",
            "Balanced",
            "High Performance"
          ],
          "performance_profile_options": [
            {
              "name": "Auto",
              "description": "Automatically selects a profile from this Mac."
            }
          ],
          "hardware_profile": {
            "display_label": "Apple M5 Max · 36 GB",
            "chip_name": "Apple M5 Max",
            "memory_gb": 36,
            "performance_class": "Apple Silicon Max"
          },
          "resolved_performance_profile": {
            "requested_name": "Auto",
            "resolved_name": "High Performance",
            "context_size_tokens": 40960,
            "direct_token_budget": 32000,
            "chunk_source_token_budget": 7000,
            "chunk_overlap_tokens": 512,
            "hardware_label": "Apple M5 Max · 36 GB",
            "reason": "Auto selected High Performance.",
            "context_mode": "profile_default",
            "context_override_tokens": 0
          },
          "context_size_options": [
            {"label": "Profile default", "value": 0}
          ],
          "installed_models": ["qwen3:14b"],
          "model_status": "Installed",
          "archive_status": "Available",
          "model_discovery_error": null
        }
        """#

        let response = try JSONDecoder().decode(
            PreferencesResponse.self,
            from: Data(json.utf8)
        )

        #expect(response.settings.llmBackend == "auto")
        #expect(response.resolvedLLMBackend.resolvedName == "mlx")
        #expect(response.resolvedLLMBackend.autoEligible)
        #expect(response.settings.llmContextMode == "profile_default")
        #expect(response.hardwareProfile.memoryGB == 36)
        #expect(response.resolvedPerformanceProfile.requestedName == "Auto")
        #expect(response.resolvedPerformanceProfile.resolvedName == "High Performance")
        #expect(response.resolvedPerformanceProfile.contextMode == "profile_default")
    }
    @Test func sentenceCasesOpenQuestionAndRiskBulletsForDisplayOnly() {
        let markdown = #"""
        # Open Questions

        - why is Platform Beta still unresolved?

        # Risks & Concerns

        - we're still at risk of a single-instance failure.

        # Topics

        - lowercase topic text should remain unchanged.
        """#

        let normalized = MarkdownPresentationNormalizer.normalize(markdown)

        #expect(normalized.contains("- Why is Platform Beta still unresolved?"))
        #expect(normalized.contains("- We're still at risk of a single-instance failure."))
        #expect(normalized.contains("- lowercase topic text should remain unchanged."))
    }

    @Test func meetingDeleteOperationKeepsRecordingByDefaultPath() {
        #expect(!MeetingDeleteOperation.keepRecording.deletesManagedRecording)
        #expect(MeetingDeleteOperation.deleteRecording.deletesManagedRecording)
    }

    @Test func projectDirectoryResolverHonorsEnvironmentOverride() {
        let resolved = BackendService.resolveProjectDirectory(
            environment: [
                "MEETING_TRANSCRIBER_PROJECT_DIR": "/tmp/meeting-transcriber-test"
            ],
            supportDirectory: nil,
            homeDirectory: URL(fileURLWithPath: "/tmp/home", isDirectory: true)
        )

        #expect(resolved.path == "/tmp/meeting-transcriber-test")
    }

}
