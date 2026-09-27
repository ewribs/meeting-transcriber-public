import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tools.maintenance.legacy_audio_audit import audit_legacy_audio
from cleanup_old_m4as import _looks_like_meeting_archive


REQUIRED = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


class LegacyAudioAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.meetings = self.root / "meetings"
        self.output = self.root / "output"
        self.archive = self.root / "archive"
        self.meetings.mkdir()
        self.output.mkdir()
        self.archive.mkdir()
        self.now = datetime(2026, 9, 14, 12, 0, 0)

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

    def test_active_wavs_are_separated_from_pilot_and_recycle(self):
        local = self.output / "run" / "audio" / "remote.wav"
        local.parent.mkdir(parents=True)
        local.write_bytes(b"1234")

        pilot = self.output / "Pilot Files" / "mic.wav"
        pilot.parent.mkdir(parents=True)
        pilot.write_bytes(b"12345")

        archived = self.archive / "2026-08-01_0900_Test" / "audio" / "mic.wav"
        archived.parent.mkdir(parents=True)
        archived.write_bytes(b"123456")

        recycle = self.archive / "#recycle" / "2026-08-01_0900_Test" / "audio" / "remote.wav"
        recycle.parent.mkdir(parents=True)
        recycle.write_bytes(b"1234567")

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            now=self.now,
        )

        self.assertEqual(len(result["output_meeting_wavs"]), 1)
        self.assertEqual(len(result["development_wavs"]), 1)
        self.assertEqual(len(result["active_archive_wavs"]), 1)
        self.assertEqual(len(result["nas_recycle_wavs"]), 1)
        self.assertEqual(result["totals"]["output_meeting_wavs"]["bytes"], 4)
        self.assertEqual(result["totals"]["development_wavs"]["bytes"], 5)
        self.assertEqual(result["totals"]["active_archive_wavs"]["bytes"], 6)
        self.assertEqual(result["totals"]["nas_recycle_wavs"]["bytes"], 7)
        self.assertEqual(result["totals"]["app_managed_reclaimable"]["bytes"], 10)

    def test_local_m4a_safe_only_with_complete_verified_archive(self):
        source = self.meetings / "Alex.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)

        meeting = self._complete_archive("2026-08-01_0900_Alex")
        source_dir = meeting / "source"
        source_dir.mkdir()
        archived = source_dir / source.name
        archived.write_bytes(source.read_bytes())

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )

        self.assertEqual(len(result["local_m4as_safe"]), 1)
        self.assertEqual(len(result["local_m4as_blocked"]), 0)

    def test_local_m4a_without_archived_source_is_blocked(self):
        source = self.meetings / "Alex.m4a"
        source.write_bytes(b"audio-data")
        self._old(source)
        self._complete_archive("2026-08-01_0900_Alex")

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            local_retention_days=30,
            now=self.now,
        )

        self.assertEqual(len(result["local_m4as_safe"]), 0)
        self.assertEqual(len(result["local_m4as_blocked"]), 1)
        self.assertIn("missing or size mismatch", result["local_m4as_blocked"][0]["reason"])

    def test_archived_m4a_retention_forever_reports_none(self):
        meeting = self._complete_archive("2026-01-01_0900_Test")
        source_dir = meeting / "source"
        source_dir.mkdir()
        archived = source_dir / "Test.m4a"
        archived.write_bytes(b"audio")
        self._old(archived, days=400)

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            archived_retention_days=0,
            now=self.now,
        )

        self.assertEqual(result["archived_m4as_eligible"], [])

    def test_archived_m4a_past_retention_is_reported(self):
        meeting = self._complete_archive("2025-01-01_0900_Test")
        source_dir = meeting / "source"
        source_dir.mkdir()
        archived = source_dir / "Test.m4a"
        archived.write_bytes(b"audio")
        self._old(archived, days=400)

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            archived_retention_days=365,
            now=self.now,
        )

        self.assertEqual(len(result["archived_m4as_eligible"]), 1)

    def test_recycle_source_m4as_do_not_participate_in_archive_retention(self):
        recycle = self.archive / "#recycle" / "2025-01-01_0900_Test" / "source"
        recycle.mkdir(parents=True)
        archived = recycle / "Test.m4a"
        archived.write_bytes(b"audio")
        self._old(archived, days=400)

        result = audit_legacy_audio(
            meetings_dir=self.meetings,
            output_dir=self.output,
            archive_dir=self.archive,
            archived_retention_days=365,
            now=self.now,
        )

        self.assertEqual(result["archived_m4as_eligible"], [])
        self.assertEqual(result["archived_m4as_blocked"], [])

    def test_archive_name_detection_is_not_hard_coded_to_2026(self):
        self.assertTrue(_looks_like_meeting_archive("2027-01-02_0900_Test"))
        self.assertTrue(_looks_like_meeting_archive("2025-12-31_2359_Test"))
        self.assertFalse(_looks_like_meeting_archive("OneNote_Import"))
        self.assertFalse(_looks_like_meeting_archive("#recycle"))


if __name__ == "__main__":
    unittest.main()
