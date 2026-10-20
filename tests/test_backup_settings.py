import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import app_settings
import backend_bridge
import state_backup


class BackupSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings_path = self.root / "settings.json"
        self.backup_root = self.root / "project" / "local_backups"
        self.backup_root.mkdir(parents=True)

        patches = [
            mock.patch.object(app_settings, "SETTINGS_PATH", self.settings_path),
            mock.patch.object(
                state_backup,
                "default_paths",
                return_value=(self.root / "archive", self.backup_root),
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_defaults(self):
        payload = backend_bridge.backup_settings_payload()
        self.assertEqual(payload["settings"]["keep_local"], 20)
        self.assertEqual(payload["settings"]["keep_mirror"], 60)
        self.assertEqual(payload["settings"]["mirror_dir"], "")
        self.assertEqual(payload["status"]["mirror_state"], "off")
        self.assertEqual(payload["status"]["last_backup"], "")

    def test_save_round_trip(self):
        nas = self.root / "nas"
        nas.mkdir()
        payload = backend_bridge.save_backup_settings_payload(str(nas), 30, 100)
        self.assertEqual(payload["settings"]["mirror_dir"], str(nas))
        self.assertEqual(payload["settings"]["keep_local"], 30)
        self.assertEqual(payload["settings"]["keep_mirror"], 100)
        self.assertEqual(payload["status"]["mirror_state"], "ready")
        saved = json.loads(self.settings_path.read_text())
        self.assertEqual(saved["backup_keep_mirror"], 100)

    def test_other_settings_are_kept(self):
        app_settings.save_app_settings({"llm_model": "keep-me"})
        backend_bridge.save_backup_settings_payload("", 5, 5)
        self.assertEqual(app_settings.load_app_settings()["llm_model"], "keep-me")

    def test_offline_folder_can_still_be_saved(self):
        payload = backend_bridge.save_backup_settings_payload(
            "/Volumes/NotMountedNas/Backups", 20, 60
        )
        self.assertEqual(payload["status"]["mirror_state"], "unavailable")

    def test_rejects_bad_values(self):
        for args in [
            ("relative/path", 20, 60),
            (str(self.backup_root / "inside"), 20, 60),
            ("", 0, 60),
            ("", 20, 501),
        ]:
            with self.assertRaises(ValueError, msg=str(args)):
                backend_bridge.save_backup_settings_payload(*args)

    def test_keeps_come_from_settings_and_ignore_bad_values(self):
        app_settings.save_app_settings(
            {"backup_keep_local": 7, "backup_keep_mirror": "oops"}
        )
        self.assertEqual(state_backup.default_keeps(), (7, 60))

    def test_status_reports_last_backup(self):
        snapshot = self.backup_root / "20261020-104400"
        snapshot.mkdir()
        (snapshot / "manifest.json").write_text(json.dumps({"files": ["a", "b"]}))
        status = state_backup.backup_status(self.backup_root, None)
        self.assertEqual(status["last_backup"], "Oct 20, 2026 10:44 AM")
        self.assertEqual(status["last_file_count"], 2)
        self.assertEqual(status["snapshot_count"], 1)

    def test_backup_state_payload_uses_configured_keeps(self):
        app_settings.save_app_settings({"backup_keep_local": 3})
        with mock.patch.object(state_backup, "backup_state") as run, \
                mock.patch.object(state_backup, "default_project_dir",
                                  return_value=self.root):
            run.return_value = {"status": "unchanged"}
            backend_bridge.backup_state_payload()
        self.assertEqual(run.call_args.kwargs["keep"], 3)
        self.assertEqual(run.call_args.kwargs["mirror_keep"], 60)


if __name__ == "__main__":
    unittest.main()
