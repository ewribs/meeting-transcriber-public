import json
import tempfile
import unittest

from datetime import date
from pathlib import Path

from meeting_browser import (
    build_meeting_browser_entry,
    build_meeting_browser_entries,
    count_unpublished,
    meeting_matches_filters,
    sort_meeting_entries,
)


class MeetingBrowserTests(unittest.TestCase):
    def _meeting(self, root: Path, **overrides):
        run = root / "2026-09-14_1000_TestMeeting"
        run.mkdir(parents=True, exist_ok=True)
        data = {
            "meeting_run": run.name,
            "display_title": "Test Meeting",
            "publish_status": "Unpublished",
            "participants": ["Alex", "Jordan"],
            "location": str(run),
        }
        data.update(overrides)
        return data, run

    def test_entry_includes_topics_in_search_and_preview(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            meeting, run = self._meeting(Path(temp_dir))
            (run / "meeting_memory.json").write_text(
                json.dumps(
                    {
                        "topics": [
                            {
                                "topic_key": "cloud_provider_a",
                                "topic": "Cloud Provider A renewal",
                                "summary": "Commercial strategy",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            entry = build_meeting_browser_entry(meeting)

            self.assertIsNotNone(entry)
            self.assertEqual(
                entry.label,
                "2026-09-14 · Unpublished\nTest Meeting",
            )
            self.assertIn("cloud provider a renewal", entry.search_text)
            self.assertIn("commercial strategy", entry.search_text)
            self.assertIn("**Status:** Unpublished", entry.preview_markdown)
            self.assertIn("- Cloud Provider A renewal", entry.preview_markdown)

    def test_count_unpublished(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first, _ = self._meeting(root)
            second = dict(first)
            second["meeting_run"] = "2026-09-13_1000_Other"
            second["display_title"] = "Other"
            second["publish_status"] = "Published"

            entries = build_meeting_browser_entries([first, second])
            self.assertEqual(count_unpublished(entries), 1)

    def test_filters_search_status_and_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            meeting, _ = self._meeting(Path(temp_dir))
            entry = build_meeting_browser_entry(meeting)

            self.assertTrue(
                meeting_matches_filters(
                    entry,
                    search_text="alex",
                    status_filter="Unpublished",
                    date_filter="Last 7 days",
                    today=date(2026, 9, 14),
                )
            )
            self.assertFalse(
                meeting_matches_filters(
                    entry,
                    status_filter="Published",
                )
            )
            self.assertFalse(
                meeting_matches_filters(
                    entry,
                    date_filter="Custom range",
                    custom_from=date(2026, 9, 1),
                    custom_to=date(2026, 9, 10),
                )
            )

    def test_sort_modes(self):
        entries = []
        for run, title in [
            ("2026-09-12_1000_B", "Beta"),
            ("2026-09-14_1000_A", "Alpha"),
        ]:
            entry = build_meeting_browser_entry(
                {
                    "meeting_run": run,
                    "display_title": title,
                    "publish_status": "Published",
                }
            )
            entries.append(entry)

        self.assertEqual(
            [entry.title for entry in sort_meeting_entries(entries, "Newest first")],
            ["Alpha", "Beta"],
        )
        self.assertEqual(
            [entry.title for entry in sort_meeting_entries(entries, "Oldest first")],
            ["Beta", "Alpha"],
        )
        self.assertEqual(
            [entry.title for entry in sort_meeting_entries(entries, "Title A-Z")],
            ["Alpha", "Beta"],
        )


if __name__ == "__main__":
    unittest.main()
