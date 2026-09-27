import json
import tempfile
import unittest
from pathlib import Path

from meeting_selector import (
    load_meeting_index,
    select_meetings,
)


def write_completed_local(
    output_dir: Path,
    run_name: str,
    participants=None,
):
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True)
    metadata = {
        "meeting_run": run_name,
        "meeting_datetime": "2026-09-14T08:00:00",
        "display_title": "Test Meeting",
        "participants": participants or [],
        "artifacts": {"summary": True},
    }
    (run_dir / "meeting_metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    (run_dir / "meeting_memory.json").write_text(
        json.dumps({"topics": []}),
        encoding="utf-8",
    )
    return run_dir


class MeetingSelectorDiscoveryTests(unittest.TestCase):
    def test_completed_local_run_is_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            output = root / "output"
            archive.mkdir()
            output.mkdir()
            run = "2026-09-14_0800_GUITEST"
            local_dir = write_completed_local(
                output,
                run,
                [{"name": "Alex"}],
            )

            meetings = load_meeting_index(
                archive,
                output,
            )

            self.assertEqual(len(meetings), 1)
            self.assertEqual(
                meetings[0]["meeting_run"],
                run,
            )
            self.assertEqual(
                meetings[0]["publish_status"],
                "Unpublished",
            )
            self.assertFalse(
                meetings[0]["is_published"]
            )
            self.assertEqual(
                meetings[0]["participants"],
                ["Alex"],
            )
            self.assertEqual(
                Path(meetings[0]["location"]),
                local_dir,
            )

    def test_incomplete_local_run_is_hidden(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            output = root / "output"
            archive.mkdir()
            output.mkdir()
            run_dir = output / "2026-09-14_0800_PARTIAL"
            run_dir.mkdir()
            (run_dir / "meeting_metadata.json").write_text(
                json.dumps({
                    "meeting_run": run_dir.name,
                    "meeting_datetime": "2026-09-14T08:00:00",
                }),
                encoding="utf-8",
            )

            self.assertEqual(
                load_meeting_index(archive, output),
                [],
            )

    def test_published_copy_wins_over_local_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            output = root / "output"
            archive.mkdir()
            output.mkdir()
            run = "2026-09-14_0800_GUITEST"
            write_completed_local(output, run)
            archived_dir = archive / run
            archived_dir.mkdir()
            (archive / "meeting_index.json").write_text(
                json.dumps([
                    {
                        "meeting_run": run,
                        "meeting_datetime": "2026-09-14T08:00:00",
                        "display_title": "Published Test",
                        "participants": ["Alex"],
                        "location": str(archived_dir),
                    }
                ]),
                encoding="utf-8",
            )

            meetings = load_meeting_index(
                archive,
                output,
            )

            self.assertEqual(len(meetings), 1)
            self.assertEqual(
                meetings[0]["publish_status"],
                "Published",
            )
            self.assertTrue(
                meetings[0]["is_published"]
            )
            self.assertEqual(
                Path(meetings[0]["location"]),
                archived_dir,
            )

    def test_select_meetings_includes_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            output = root / "output"
            archive.mkdir()
            output.mkdir()
            write_completed_local(
                output,
                "2026-09-14_0800_GUITEST",
                [{"name": "Alex"}],
            )

            selected = select_meetings(
                person="Alex",
                archive_dir=archive,
                output_dir=output,
            )

            self.assertEqual(len(selected), 1)
            self.assertEqual(
                selected[0]["publish_status"],
                "Unpublished",
            )


if __name__ == "__main__":
    unittest.main()
