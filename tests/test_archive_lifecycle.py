import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import archive
import cleanup_archived_m4as
import cleanup_old_m4as


REQUIRED_FILES = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


class ArchiveLifecycleTests(unittest.TestCase):
    def _make_complete_meeting(
        self,
        root: Path,
        name: str,
    ) -> Path:
        meeting = root / name
        meeting.mkdir(parents=True)
        for filename in REQUIRED_FILES:
            (meeting / filename).write_text(
                "test",
                encoding="utf-8",
            )
        return meeting

    def test_publish_archives_original_m4a_and_verifies_size(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            meetings_dir = root / "meetings"
            archive_dir = root / "archive"
            output_dir = root / "output"
            meetings_dir.mkdir()
            archive_dir.mkdir()
            output_dir.mkdir()

            source = meetings_dir / "Alex1v1090826.m4a"
            source.write_bytes(b"original-audio")

            run_dir = self._make_complete_meeting(
                output_dir,
                "2026-09-08_1159_Alex1v1090826",
            )

            with patch.object(
                archive,
                "MEETINGS_DIR",
                meetings_dir,
            ), patch.object(
                archive,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                destination = archive.archive_only(
                    run_dir
                )

                archived_source = (
                    destination
                    / "source"
                    / source.name
                )

                self.assertTrue(
                    archived_source.exists()
                )
                self.assertEqual(
                    archived_source.stat().st_size,
                    source.stat().st_size,
                )
                self.assertTrue(
                    archive.archived_source_is_verified(
                        source,
                        destination,
                    )
                )

    def test_local_m4a_not_eligible_without_verified_archived_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            meetings_dir = root / "meetings"
            archive_dir = root / "archive"
            meetings_dir.mkdir()
            archive_dir.mkdir()

            source = meetings_dir / "Alex1v1090826.m4a"
            source.write_bytes(b"original-audio")
            old_time = (
                datetime.now()
                - timedelta(days=40)
            ).timestamp()
            os.utime(source, (old_time, old_time))

            self._make_complete_meeting(
                archive_dir,
                "2026-09-08_1159_Alex1v1090826",
            )

            with patch.object(
                cleanup_old_m4as,
                "MEETINGS_DIR",
                meetings_dir,
            ), patch.object(
                cleanup_old_m4as,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                result = cleanup_old_m4as.cleanup_old_m4as(
                    days=30,
                    delete=False,
                )

            self.assertEqual(
                result["eligible"],
                [],
            )
            self.assertIn(
                "archived source M4A missing",
                result["skipped"][0][1],
            )

    def test_archived_m4a_forever_never_eligible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir) / "archive"
            archive_dir.mkdir()

            with patch.object(
                cleanup_archived_m4as,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                result = (
                    cleanup_archived_m4as
                    .cleanup_archived_m4as(
                        days=0,
                        delete=True,
                    )
                )

            self.assertTrue(result["forever"])
            self.assertEqual(result["deleted"], 0)

    def test_archived_m4a_cleanup_keeps_meeting_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_dir = root / "archive"
            archive_dir.mkdir()

            meeting = self._make_complete_meeting(
                archive_dir,
                "2026-01-01_0900_TestMeeting",
            )
            source_dir = meeting / "source"
            source_dir.mkdir()
            archived_m4a = source_dir / "TestMeeting.m4a"
            archived_m4a.write_bytes(b"audio")

            old_time = (
                datetime.now()
                - timedelta(days=400)
            ).timestamp()
            os.utime(
                archived_m4a,
                (old_time, old_time),
            )

            with patch.object(
                cleanup_archived_m4as,
                "ARCHIVE_DIR",
                archive_dir,
            ):
                result = (
                    cleanup_archived_m4as
                    .cleanup_archived_m4as(
                        days=365,
                        delete=True,
                    )
                )

            self.assertEqual(result["deleted"], 1)
            self.assertFalse(archived_m4a.exists())
            for filename in REQUIRED_FILES:
                self.assertTrue(
                    (meeting / filename).exists()
                )


if __name__ == "__main__":
    unittest.main()
