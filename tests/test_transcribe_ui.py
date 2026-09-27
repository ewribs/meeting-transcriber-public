import unittest
from pathlib import Path

from transcribe_ui import (
    queue_action_state,
    queue_completion_detail,
    queue_rows,
    source_summary,
    workflow_complete,
    workflow_running,
)


class TranscribeUiTests(unittest.TestCase):
    def test_queue_rows_include_status_and_error(self):
        rows = queue_rows([
            {
                "source_path": Path("/tmp/Alex.m4a"),
                "status": "Publish Failed",
                "error": "NAS unavailable",
            }
        ])
        self.assertEqual(rows[0][0], "1. Alex.m4a — Publish Failed")
        self.assertEqual(rows[0][1], "NAS unavailable")

    def test_queue_actions_respect_selection_status_and_activity(self):
        entries = [
            {"status": "Ready to Publish"},
            {"status": "Publish Failed"},
        ]
        state = queue_action_state(entries, 0, active=False)
        self.assertTrue(state.remove_selected)
        self.assertTrue(state.clear_completed)
        self.assertTrue(state.retry_failed)

        active_state = queue_action_state(entries, 0, active=True)
        self.assertFalse(active_state.remove_selected)
        self.assertFalse(active_state.clear_completed)
        self.assertFalse(active_state.retry_failed)

    def test_source_summary_describes_current_paths(self):
        input_text, summary = source_summary(
            Path("/meetings/Test.m4a"),
            output_dir=Path("/output"),
            archive_dir=Path("/archive"),
        )
        self.assertEqual(input_text, "/meetings/Test.m4a")
        self.assertIn("Current source: Test.m4a", summary)
        self.assertIn("Working folder: /output", summary)
        self.assertIn("Archive folder: /archive", summary)

    def test_workflow_text_reflects_auto_publish_and_failures(self):
        self.assertIn(
            "automatic after each transcription",
            workflow_running(auto_publish=True),
        )
        self.assertIn(
            "remain Unpublished",
            workflow_running(auto_publish=False),
        )
        self.assertIn(
            "complete with failures",
            workflow_complete(
                auto_publish=True,
                transcription_failures=1,
                publish_failures=0,
            ),
        )

    def test_completion_detail_preserves_existing_wording(self):
        detail = queue_completion_detail(
            auto_publish=True,
            successes=2,
            transcription_failures=1,
            published=1,
            publish_failures=1,
        )
        self.assertEqual(
            detail,
            "Queue complete: 2 transcribed, 1 published, 1 transcription "
            "failure(s), 1 publish failure(s).",
        )


if __name__ == "__main__":
    unittest.main()
