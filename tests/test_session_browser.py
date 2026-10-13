import json
import tempfile
import time
import unittest
from pathlib import Path

from session_browser import (
    format_session_criteria,
    load_session_browser_entries,
)


class SessionBrowserTests(unittest.TestCase):
    def test_load_entries_formats_fixed_and_dynamic_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixed = root / "Fixed Session.json"
            dynamic = root / "Alex.json"

            fixed.write_text(
                json.dumps({
                    "meeting_runs": ["a"],
                    "conversation_history": [
                        {"role": "user"},
                        {"role": "assistant"},
                    ],
                }),
                encoding="utf-8",
            )
            time.sleep(0.01)
            dynamic.write_text(
                json.dumps({
                    "meeting_runs": ["a", "b"],
                    "conversation_history": [],
                    "selection_criteria": {"person": "Alex"},
                }),
                encoding="utf-8",
            )

            entries = load_session_browser_entries(root)

            self.assertEqual([e.name for e in entries], ["Alex", "Fixed Session"])
            self.assertIn("Dynamic · 2 meetings · 0 turns", entries[0].label)
            self.assertIn("Fixed · 1 meeting · 1 turn", entries[1].label)
            self.assertTrue(entries[0].tooltip.startswith("Updated "))

    def test_invalid_json_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(load_session_browser_entries(root), [])

    def test_format_person_only_dynamic_criteria(self):
        lines = format_session_criteria({
            "person": "Alex",
            "title": None,
            "topic": None,
            "history_days": 30,
        })
        self.assertEqual(
            lines,
            [
                "CRITERIA",
                "--------",
                "Person: Alex",
                "Window: Last 30 days",
            ],
        )

    def test_format_custom_window_and_optional_fields(self):
        lines = format_session_criteria({
            "title": "1v1",
            "topic": "Vendor Alpha",
            "start_date": "2026-08-01",
            "end_date": "2026-09-14",
        })
        self.assertIn("Title contains: 1v1", lines)
        self.assertIn("Topic contains: Vendor Alpha", lines)
        self.assertIn("Window: 2026-08-01 to 2026-09-14", lines)


if __name__ == "__main__":
    unittest.main()
