import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tools.maintenance.repair_legacy_audio_archives import (
    apply_legacy_archive_repairs,
    plan_legacy_archive_repairs,
)


REQUIRED = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


class LegacyAudioRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meetings = self.root / "meetings"
        self.archive = self.root / "archive"
        self.meetings.mkdir()
        self.archive.mkdir()
        self.now = datetime(2026, 10, 5, 12, 0, 0)

    def tearDown(self):
        self.temp.cleanup()

    def _old(self, path: Path, days: int = 60):
        stamp = (self.now - timedelta(days=days)).timestamp()
        os.utime(path, (stamp, stamp))

    def _complete_archive(self, name: str) -> Path:
        meeting = self.archive / name
        meeting.mkdir()
        for filename in REQUIRED:
            (meeting / filename).write_text("ok", encoding="utf-8")
        return meeting

    def test_single_complete_legacy_archive_is_repairable(self):
        source = self.meetings / "MeetingAlpha.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)
        meeting = self._complete_archive("2026-08-01_0900_MeetingAlpha")

        plan = plan_legacy_archive_repairs(
            meetings_dir=self.meetings,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )

        self.assertEqual(len(plan["repairable"]), 1)
        self.assertEqual(plan["repairable"][0]["meeting"], meeting)
        self.assertEqual(plan["blocked"], [])

    def test_apply_copies_and_hash_verifies_without_deleting_local(self):
        source = self.meetings / "MeetingAlpha.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)
        meeting = self._complete_archive("2026-08-01_0900_MeetingAlpha")

        plan = plan_legacy_archive_repairs(
            meetings_dir=self.meetings,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )
        result = apply_legacy_archive_repairs(plan)

        destination = meeting / "source" / source.name
        self.assertTrue(source.exists())
        self.assertEqual(destination.read_bytes(), source.read_bytes())
        self.assertEqual(len(result["repaired"]), 1)
        self.assertEqual(result["failed"], [])

    def test_multiple_archives_remain_blocked(self):
        source = self.meetings / "MeetingAlpha.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)
        self._complete_archive("2026-08-01_0900_MeetingAlpha")
        self._complete_archive("2026-08-02_0900_MeetingAlpha")

        plan = plan_legacy_archive_repairs(
            meetings_dir=self.meetings,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )

        self.assertEqual(plan["repairable"], [])
        self.assertEqual(len(plan["blocked"]), 1)
        self.assertIn("multiple matching archives", plan["blocked"][0]["reason"])

    def test_existing_mismatched_archived_source_is_not_overwritten(self):
        source = self.meetings / "MeetingAlpha.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)
        meeting = self._complete_archive("2026-08-01_0900_MeetingAlpha")
        destination = meeting / "source" / source.name
        destination.parent.mkdir()
        destination.write_bytes(b"wrong")

        plan = plan_legacy_archive_repairs(
            meetings_dir=self.meetings,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )

        self.assertEqual(plan["repairable"], [])
        self.assertEqual(len(plan["blocked"]), 1)
        self.assertIn("refusing to overwrite", plan["blocked"][0]["reason"])
        self.assertEqual(destination.read_bytes(), b"wrong")


if __name__ == "__main__":
    unittest.main()
