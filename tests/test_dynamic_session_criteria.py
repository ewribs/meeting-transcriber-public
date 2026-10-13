import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import meeting_selector


class DynamicSessionCriteriaTests(unittest.TestCase):
    def _meeting(self, root: Path, run: str, title: str, participants: list[str]):
        meeting_dir = root / run
        meeting_dir.mkdir(parents=True, exist_ok=True)
        (meeting_dir / "meeting_memory.json").write_text(
            json.dumps({"topics": [{"topic": "Vendor Alpha", "summary": "Renewal planning"}]}),
            encoding="utf-8",
        )
        return {
            "meeting_run": run,
            "meeting_datetime": "2026-09-10T09:00:00",
            "display_title": title,
            "participants": participants,
            "location": str(meeting_dir),
            "publish_status": "Published",
            "is_published": True,
        }

    def test_person_only_criteria_allows_blank_title_and_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meetings = [
                self._meeting(root, "2026-09-10_0900_Alex", "Alex 1v1", ["Alex"]),
                self._meeting(root, "2026-09-10_1000_Jordan", "Jordan 1v1", ["Jordan"]),
            ]
            with patch.object(meeting_selector, "load_meeting_index", return_value=meetings):
                selected = meeting_selector.select_meetings(
                    person="Alex",
                    title=None,
                    topic=None,
                )
        self.assertEqual([m["display_title"] for m in selected], ["Alex 1v1"])

    def test_title_filter_is_optional_but_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meetings = [
                self._meeting(root, "2026-09-10_0900_Alex", "Alex 1v1", ["Alex"]),
                self._meeting(root, "2026-09-11_0900_AlexStaff", "Alex Staff", ["Alex"]),
            ]
            with patch.object(meeting_selector, "load_meeting_index", return_value=meetings):
                selected = meeting_selector.select_meetings(
                    person="Alex",
                    title="1v1",
                    topic=None,
                )
        self.assertEqual([m["display_title"] for m in selected], ["Alex 1v1"])

    def test_topic_filter_still_works_with_blank_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            meetings = [self._meeting(root, "2026-09-10_0900_Alex", "Alex 1v1", ["Alex"])]
            with patch.object(meeting_selector, "load_meeting_index", return_value=meetings):
                selected = meeting_selector.select_meetings(
                    person="Alex",
                    title=None,
                    topic="Vendor Alpha",
                )
        self.assertEqual(len(selected), 1)


if __name__ == "__main__":
    unittest.main()
