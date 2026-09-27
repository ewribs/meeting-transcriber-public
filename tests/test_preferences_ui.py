import tempfile
import unittest
from pathlib import Path

from preferences_ui import (
    archive_status_text,
    context_size_state,
    merge_model_choices,
    model_status_text,
    preferences_saved_message,
    selected_context_size,
    validate_preferences,
)


class PreferencesUITests(unittest.TestCase):
    def test_model_status_and_choice_merge(self):
        self.assertEqual(
            merge_model_choices(["qwen3:8b"], "custom:model"),
            ["qwen3:8b", "custom:model"],
        )
        self.assertEqual(
            model_status_text("qwen3:8b", ["qwen3:8b"], None),
            "Installed",
        )
        self.assertEqual(
            model_status_text("missing", ["qwen3:8b"], None),
            "Configured model not detected",
        )

    def test_archive_status(self):
        self.assertEqual(archive_status_text(""), "No archive folder configured")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(archive_status_text(tmp), "Available")
        self.assertEqual(
            archive_status_text("/definitely/not/a/mounted/path"),
            "Unavailable / not mounted",
        )

    def test_context_size_mapping(self):
        self.assertEqual(context_size_state(16384), (16384, 16384, False))
        self.assertEqual(context_size_state(24576), (24576, 24576, False))
        self.assertEqual(selected_context_size(-1, 24576), 24576)
        self.assertEqual(selected_context_size(8192, 24576), 8192)

    def test_preference_validation(self):
        error = validate_preferences("", "/tmp/archive", "qwen3:8b")
        self.assertEqual(error.title, "Storage Paths Required")
        error = validate_preferences("relative", "/tmp/archive", "qwen3:8b")
        self.assertEqual(error.title, "Invalid Output Folder")
        error = validate_preferences("/tmp/a", "/tmp/a", "qwen3:8b")
        self.assertEqual(error.title, "Storage Paths Must Differ")
        self.assertIsNone(validate_preferences("/tmp/a", "/tmp/b", "qwen3:8b"))

    def test_saved_message_reports_archive_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            message = preferences_saved_message(Path(tmp))
            self.assertIn("Archive is currently available.", message)
            self.assertIn("Restart Meeting Transcriber", message)


if __name__ == "__main__":
    unittest.main()
