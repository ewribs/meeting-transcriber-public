"""Production meeting-title boundary regression tests (no model calls)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai
import pipeline
from metadata import get_display_title


class ProductionMeetingIdentityTests(unittest.TestCase):
    def test_sanitized_directory_becomes_resolvable_one_on_one_title(self):
        run_dir = Path("2026-10-10_1135_AlexA1v1100726")
        title = get_display_title(run_dir)
        self.assertEqual(title, "Alex A 1v1")
        transcript = "[00:01] **Mic**\nI'll check.\n[00:02] **Remote**\nI'll follow up."
        with patch.object(ai, "SELF_NAME", "Sam"), patch.object(ai, "SELF_SPEAKER_LABEL", "Mic"):
            mapping = ai._meeting_participant_identity_map(title, transcript)
        self.assertEqual(mapping, {"mic": "Sam", "remote": "Alex A"})

    def test_production_memory_uses_display_title_not_directory_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "2026-10-10_1135_AlexA1v1100726"
            run_dir.mkdir()
            with patch.object(pipeline, "build_complete_meeting_memory", return_value={"commitments": []}) as builder, \
                 patch.object(pipeline, "get_last_memory_resolution_diagnostics", return_value={}):
                result = pipeline.run_meeting_memory(
                    run_dir, "Summary", "[00:01] **Remote**\nI'll follow up.", []
                )
            self.assertEqual(result, run_dir / "meeting_memory.json")
            self.assertTrue(result.exists())
            self.assertEqual(builder.call_args.kwargs["meeting_label"], "Alex A 1v1")

    def test_non_one_on_one_title_does_not_invent_remote_identity(self):
        transcript = "[00:01] **Mic**\nI'll check.\n[00:02] **Remote**\nI'll follow up."
        with patch.object(ai, "SELF_NAME", "Sam"), patch.object(ai, "SELF_SPEAKER_LABEL", "Mic"):
            mapping = ai._meeting_participant_identity_map("Team Review", transcript)
        self.assertNotIn("remote", mapping)


if __name__ == "__main__":
    unittest.main()
