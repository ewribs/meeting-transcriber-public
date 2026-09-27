from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import publisher


REQUIRED = publisher.REQUIRED_PUBLISH_ARTIFACTS


class PublisherRecoveryTests(unittest.TestCase):
    def _make_run(self, root: Path):
        run_dir = root / "2026-09-21_1334_TestMeeting"
        run_dir.mkdir()
        for name in REQUIRED:
            (run_dir / name).write_text("content-" + name, encoding="utf-8")
        exports = run_dir / "exports"
        exports.mkdir()
        (exports / "OneNote_Test.html").write_text("note", encoding="utf-8")
        return run_dir

    def _make_verified_archive(self, run_dir: Path, archive_dir: Path, source: Path):
        destination = archive_dir / run_dir.name
        shutil = __import__("shutil")
        shutil.copytree(run_dir, destination)
        source_dir = destination / "source"
        source_dir.mkdir()
        shutil.copy2(source, source_dir / source.name)
        return destination

    def test_existing_verified_archive_resumes_remaining_publish_steps(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            meetings_dir = root / "meetings"
            archive_dir.mkdir()
            meetings_dir.mkdir()
            run_dir = self._make_run(root)
            source = meetings_dir / "TestMeeting.m4a"
            source.write_bytes(b"audio")
            archived = self._make_verified_archive(run_dir, archive_dir, source)

            with patch.object(publisher, "ARCHIVE_DIR", archive_dir), patch.object(
                publisher, "find_source_m4a", return_value=source
            ), patch.object(
                publisher, "archived_source_is_verified", return_value=True
            ), patch.object(
                publisher, "archive_only"
            ) as archive_only, patch.object(
                publisher, "copy_onenote_export"
            ) as onenote, patch.object(
                publisher, "build_meeting_index", return_value=archive_dir / "index.json"
            ) as indexer, patch.object(
                publisher, "build_meeting_dashboard"
            ) as dashboard, patch.object(
                publisher, "remove_wavs"
            ) as remove_wavs:
                result = publisher.publish_meeting(run_dir)

            self.assertEqual(result, archived)
            archive_only.assert_not_called()
            onenote.assert_called_once_with(run_dir)
            indexer.assert_called_once_with(archive_dir)
            dashboard.assert_called_once()
            self.assertEqual(remove_wavs.call_count, 2)

    def test_existing_unverified_archive_is_not_overwritten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            meetings_dir = root / "meetings"
            archive_dir.mkdir()
            meetings_dir.mkdir()
            run_dir = self._make_run(root)
            source = meetings_dir / "TestMeeting.m4a"
            source.write_bytes(b"audio")
            archived = archive_dir / run_dir.name
            archived.mkdir()

            with patch.object(publisher, "ARCHIVE_DIR", archive_dir), patch.object(
                publisher, "find_source_m4a", return_value=source
            ), patch.object(
                publisher, "archive_only"
            ) as archive_only:
                with self.assertRaises(FileExistsError) as ctx:
                    publisher.publish_meeting(run_dir)

            archive_only.assert_not_called()
            self.assertIn("cannot be safely resumed", str(ctx.exception))

    def test_existing_archive_with_missing_source_repairs_and_resumes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            meetings_dir = root / "meetings"
            archive_dir.mkdir()
            meetings_dir.mkdir()
            run_dir = self._make_run(root)
            source = meetings_dir / "TestMeeting.m4a"
            source.write_bytes(b"audio")

            shutil = __import__("shutil")
            archived = archive_dir / run_dir.name
            shutil.copytree(run_dir, archived)

            with patch.object(publisher, "ARCHIVE_DIR", archive_dir), patch.object(
                publisher, "find_source_m4a", return_value=source
            ), patch.object(
                publisher, "copy_onenote_export"
            ) as onenote, patch.object(
                publisher, "build_meeting_index", return_value=archive_dir / "index.json"
            ) as indexer, patch.object(
                publisher, "build_meeting_dashboard"
            ) as dashboard, patch.object(
                publisher, "remove_wavs"
            ) as remove_wavs:
                result = publisher.publish_meeting(run_dir)

            archived_source = archived / "source" / source.name
            self.assertEqual(result, archived)
            self.assertTrue(archived_source.exists())
            self.assertEqual(archived_source.read_bytes(), b"audio")
            onenote.assert_called_once_with(run_dir)
            indexer.assert_called_once_with(archive_dir)
            dashboard.assert_called_once()
            self.assertEqual(remove_wavs.call_count, 2)

    def test_existing_archive_with_mismatched_source_repairs_and_resumes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            meetings_dir = root / "meetings"
            archive_dir.mkdir()
            meetings_dir.mkdir()
            run_dir = self._make_run(root)
            source = meetings_dir / "TestMeeting.m4a"
            source.write_bytes(b"correct-audio")

            shutil = __import__("shutil")
            archived = archive_dir / run_dir.name
            shutil.copytree(run_dir, archived)
            source_dir = archived / "source"
            source_dir.mkdir()
            (source_dir / source.name).write_bytes(b"bad")

            with patch.object(publisher, "ARCHIVE_DIR", archive_dir), patch.object(
                publisher, "find_source_m4a", return_value=source
            ), patch.object(
                publisher, "copy_onenote_export"
            ), patch.object(
                publisher, "build_meeting_index", return_value=archive_dir / "index.json"
            ), patch.object(
                publisher, "build_meeting_dashboard"
            ), patch.object(
                publisher, "remove_wavs"
            ):
                result = publisher.publish_meeting(run_dir)

            self.assertEqual(result, archived)
            self.assertEqual(
                (source_dir / source.name).read_bytes(),
                b"correct-audio",
            )

    def test_existing_archive_with_core_mismatch_still_refuses_recovery(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_dir = root / "archive"
            meetings_dir = root / "meetings"
            archive_dir.mkdir()
            meetings_dir.mkdir()
            run_dir = self._make_run(root)
            source = meetings_dir / "TestMeeting.m4a"
            source.write_bytes(b"audio")

            shutil = __import__("shutil")
            archived = self._make_verified_archive(run_dir, archive_dir, source)
            (archived / "meeting_summary.md").write_text(
                "different-size-content",
                encoding="utf-8",
            )

            with patch.object(publisher, "ARCHIVE_DIR", archive_dir), patch.object(
                publisher, "find_source_m4a", return_value=source
            ), patch.object(
                publisher, "archive_source_m4a"
            ) as repair_source:
                with self.assertRaises(FileExistsError) as ctx:
                    publisher.publish_meeting(run_dir)

            repair_source.assert_not_called()
            self.assertIn("cannot be safely resumed", str(ctx.exception))



if __name__ == "__main__":
    unittest.main()
