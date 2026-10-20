import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import state_backup
from state_backup import (
    backup_state,
    list_snapshots,
    restore_state,
    sync_mirror,
)


class ExtrasBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.archive = root / "archive"
        self.project = root / "project"
        self.backups = root / "backups"
        self.mirror = root / "nas" / "Backups"
        (self.archive / "query_sessions").mkdir(parents=True)
        (self.project / "tools").mkdir(parents=True)
        (self.project / ".git" / "info").mkdir(parents=True)
        self.mirror.mkdir(parents=True)
        self.t0 = datetime(2026, 1, 1, 9, 0, 0)

    def put(self, base, relative, text):
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_backup(self, hours=0, **kwargs):
        return backup_state(
            self.archive,
            self.backups,
            project_dir=self.project,
            now=self.t0 + timedelta(hours=hours),
            **kwargs,
        )


class ProjectFileTests(ExtrasBase):
    def test_local_files_are_saved_under_project_prefix(self):
        self.put(self.project, ".git/info/exclude", "tools/mt\n")
        self.put(self.project, "tools/mt", "#!/bin/bash\n")
        self.put(self.project, "tools/bench_local.py", "x = 1\n")
        self.put(self.project, "release_audit.local.json", "{}")
        self.put(self.project, "tools/tracked_tool.py", "not saved")

        result = self.run_backup()

        snapshot = self.backups / result["snapshot"]
        saved = {
            str(path.relative_to(snapshot))
            for path in snapshot.rglob("*")
            if path.is_file() and path.name != "manifest.json"
        }
        self.assertEqual(
            saved,
            {
                "project/.git/info/exclude",
                "project/tools/mt",
                "project/tools/bench_local.py",
                "project/release_audit.local.json",
            },
        )

    def test_missing_archive_still_saves_local_files(self):
        self.put(self.project, "tools/mt", "x")
        result = backup_state(
            self.archive / "gone",
            self.backups,
            project_dir=self.project,
            now=self.t0,
        )
        self.assertEqual(result["status"], "created")

    def test_changing_a_local_file_makes_a_new_snapshot(self):
        self.put(self.project, "tools/mt", "one")
        self.run_backup()
        self.put(self.project, "tools/mt", "two")
        self.assertEqual(self.run_backup(hours=1)["status"], "created")

    def test_restore_puts_local_files_back_and_reports_changes(self):
        self.put(self.project, "tools/mt", "good")
        made = self.run_backup()
        self.put(self.project, "tools/mt", "broken")

        preview = restore_state(
            self.archive,
            self.backups,
            made["snapshot"],
            project_dir=self.project,
        )
        self.assertEqual(preview["details"][0]["change"], "differs")
        self.assertEqual((self.project / "tools/mt").read_text(), "broken")

        restore_state(
            self.archive,
            self.backups,
            made["snapshot"],
            project_dir=self.project,
            apply=True,
        )
        self.assertEqual((self.project / "tools/mt").read_text(), "good")

    def test_restore_refuses_paths_that_escape_the_folders(self):
        made = self.run_backup() if False else None
        snapshot = self.backups / "20260101-000000"
        snapshot.mkdir(parents=True)
        (snapshot / "manifest.json").write_text(
            json.dumps({"files": ["project/../evil.txt", "../evil2.txt"]})
        )
        result = restore_state(
            self.archive,
            self.backups,
            "20260101-000000",
            project_dir=self.project,
            apply=True,
        )
        self.assertEqual(
            [item["change"] for item in result["details"]],
            ["skipped", "skipped"],
        )
        self.assertFalse((self.project.parent / "evil.txt").exists())


class MirrorTests(ExtrasBase):
    def test_snapshots_are_copied_to_the_mirror(self):
        self.put(self.project, "tools/mt", "x")
        result = self.run_backup(mirror_dir=self.mirror)
        self.assertEqual(result["mirror"]["status"], "synced")
        self.assertEqual(
            [p.name for p in list_snapshots(self.mirror)],
            [result["snapshot"]],
        )

    def test_unchanged_run_catches_up_a_mirror_that_was_offline(self):
        self.put(self.project, "tools/mt", "x")
        first = self.run_backup(mirror_dir=self.mirror.parent / "offline")
        self.assertEqual(first["mirror"]["status"], "skipped")

        second = self.run_backup(hours=1, mirror_dir=self.mirror)
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(second["mirror"]["copied"], 1)

    def test_missing_mirror_folder_is_not_created(self):
        result = sync_mirror(self.backups, self.mirror.parent / "nope")
        self.assertEqual(result["status"], "skipped")
        self.assertFalse((self.mirror.parent / "nope").exists())

    def test_unmounted_volume_is_refused(self):
        with mock.patch("state_backup.os.path.ismount", return_value=False):
            result = sync_mirror(self.backups, Path("/Volumes/Gone/Backups"))
        self.assertEqual(result["status"], "skipped")
        self.assertIn("not connected", result["reason"])

    def test_off_when_not_configured(self):
        self.assertEqual(sync_mirror(self.backups, None)["status"], "off")

    def test_mirror_keeps_only_newest(self):
        for index in range(4):
            self.put(self.project, "tools/mt", str(index))
            self.run_backup(hours=index)
        sync_mirror(self.backups, self.mirror, keep=2)
        self.assertEqual(len(list_snapshots(self.mirror)), 2)

    def test_partial_copies_are_ignored(self):
        (self.mirror / ".partial-20260101-000000").mkdir()
        (self.mirror / ".partial-20260101-000000" / "manifest.json").write_text("{}")
        self.assertEqual(list_snapshots(self.mirror), [])

    def test_restore_can_use_a_snapshot_that_only_exists_on_the_mirror(self):
        self.put(self.project, "tools/mt", "good")
        made = self.run_backup(mirror_dir=self.mirror)
        for path in list(self.backups.iterdir()):
            import shutil
            shutil.rmtree(path)
        self.put(self.project, "tools/mt", "broken")

        restore_state(
            self.archive,
            self.backups,
            made["snapshot"],
            project_dir=self.project,
            mirror_dir=self.mirror,
            apply=True,
        )
        self.assertEqual((self.project / "tools/mt").read_text(), "good")


if __name__ == "__main__":
    unittest.main()
