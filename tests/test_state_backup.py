import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from state_backup import (
    backup_state,
    list_snapshots,
    restore_state,
)


class StateBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.archive = root / "archive"
        self.backups = root / "backups"
        (self.archive / "query_sessions").mkdir(parents=True)
        self.t0 = datetime(2026, 1, 1, 9, 0, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative, text):
        path = self.archive / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_skips_when_archive_missing(self):
        result = backup_state(
            self.archive / "nope", self.backups, now=self.t0
        )
        self.assertEqual(result["status"], "skipped")
        self.assertFalse(self.backups.exists())

    def test_skips_when_nothing_to_back_up(self):
        result = backup_state(self.archive, self.backups, now=self.t0)
        self.assertEqual(result["status"], "skipped")

    def test_creates_snapshot_with_folders_and_sessions(self):
        self._write("meeting_folders.json", "[]")
        self._write("query_sessions/Alpha.json", "{}")

        result = backup_state(self.archive, self.backups, now=self.t0)

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["files"], 2)
        snapshot = self.backups / result["snapshot"]
        self.assertTrue((snapshot / "meeting_folders.json").is_file())
        self.assertTrue(
            (snapshot / "query_sessions" / "Alpha.json").is_file()
        )

    def test_unchanged_state_makes_no_new_snapshot(self):
        self._write("meeting_folders.json", "[]")
        backup_state(self.archive, self.backups, now=self.t0)

        result = backup_state(
            self.archive, self.backups, now=self.t0 + timedelta(hours=1)
        )

        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(len(list_snapshots(self.backups)), 1)

    def test_change_makes_new_snapshot(self):
        self._write("meeting_folders.json", "[]")
        backup_state(self.archive, self.backups, now=self.t0)
        self._write("meeting_folders.json", '[{"name": "A"}]')

        result = backup_state(
            self.archive, self.backups, now=self.t0 + timedelta(hours=1)
        )

        self.assertEqual(result["status"], "created")
        self.assertEqual(len(list_snapshots(self.backups)), 2)

    def test_keeps_only_newest_snapshots(self):
        for index in range(5):
            self._write("meeting_folders.json", json.dumps([index]))
            backup_state(
                self.archive,
                self.backups,
                now=self.t0 + timedelta(hours=index),
                keep=3,
            )

        names = [path.name for path in list_snapshots(self.backups)]
        self.assertEqual(len(names), 3)
        self.assertEqual(names, sorted(names))

    def test_unfinished_snapshot_is_ignored(self):
        (self.backups / "20260101-000000").mkdir(parents=True)
        self.assertEqual(list_snapshots(self.backups), [])

    def test_restore_is_dry_run_by_default(self):
        self._write("meeting_folders.json", '["old"]')
        made = backup_state(self.archive, self.backups, now=self.t0)
        self._write("meeting_folders.json", '["new"]')

        result = restore_state(
            self.archive, self.backups, made["snapshot"]
        )

        self.assertFalse(result["applied"])
        self.assertEqual(
            (self.archive / "meeting_folders.json").read_text(),
            '["new"]',
        )

    def test_restore_apply_restores_and_keeps_current_copy(self):
        self._write("meeting_folders.json", '["old"]')
        made = backup_state(self.archive, self.backups, now=self.t0)
        self._write("meeting_folders.json", '["new"]')

        result = restore_state(
            self.archive, self.backups, made["snapshot"], apply=True
        )

        self.assertTrue(result["applied"])
        self.assertEqual(
            (self.archive / "meeting_folders.json").read_text(),
            '["old"]',
        )
        # The "new" state was saved as its own snapshot before restoring.
        self.assertEqual(len(list_snapshots(self.backups)), 2)

    def test_restore_unknown_name_raises(self):
        with self.assertRaises(FileNotFoundError):
            restore_state(self.archive, self.backups, "missing")


if __name__ == "__main__":
    unittest.main()
