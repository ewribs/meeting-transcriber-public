import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend_bridge
from meeting_folders import create_folder, load_folders, reorder_folders
from sidebar_order import SidebarOrderError, load_order, save_order
from state_backup import backup_state, list_snapshots


class ReorderFoldersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "meeting_folders.json"
        for name in ("Charlie", "Alpha", "Bravo"):
            create_folder(self.path, name)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self):
        return [folder["name"] for folder in load_folders(self.path)]

    def test_reorders_to_the_given_order(self):
        reorder_folders(self.path, ["Alpha", "Bravo", "Charlie"])
        self.assertEqual(self.names(), ["Alpha", "Bravo", "Charlie"])

    def test_unlisted_folders_follow_in_existing_order(self):
        reorder_folders(self.path, ["Bravo"])
        self.assertEqual(self.names(), ["Bravo", "Charlie", "Alpha"])

    def test_unknown_and_repeated_names_are_ignored(self):
        reorder_folders(self.path, ["Nope", "Alpha", "alpha", "Bravo"])
        self.assertEqual(self.names(), ["Alpha", "Bravo", "Charlie"])

    def test_members_are_untouched(self):
        folders = load_folders(self.path)
        folders[0]["meeting_runs"] = ["r1", "r2"]
        from meeting_folders import _save

        _save(self.path, folders)
        reorder_folders(self.path, ["Alpha", "Bravo", "Charlie"])
        charlie = [f for f in load_folders(self.path) if f["name"] == "Charlie"][0]
        self.assertEqual(charlie["meeting_runs"], ["r1", "r2"])


class SidebarOrderFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sidebar_order.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_means_no_order(self):
        self.assertEqual(load_order(self.path), {"dynamic": [], "fixed": []})

    def test_unreadable_file_means_no_order(self):
        self.path.write_text("not json")
        self.assertEqual(load_order(self.path), {"dynamic": [], "fixed": []})

    def test_save_keeps_the_other_kind(self):
        save_order(self.path, "dynamic", ["B", "A"])
        save_order(self.path, "fixed", ["Z"])
        self.assertEqual(
            load_order(self.path), {"dynamic": ["B", "A"], "fixed": ["Z"]}
        )

    def test_names_are_cleaned_and_deduplicated(self):
        order = save_order(self.path, "fixed", [" A ", "A", "", "B"])
        self.assertEqual(order["fixed"], ["A", "B"])

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(SidebarOrderError):
            save_order(self.path, "other", ["A"])


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.folders = root / "meeting_folders.json"
        self.order = root / "sidebar_order.json"
        patches = [
            mock.patch.object(
                backend_bridge, "_folders_file", return_value=self.folders
            ),
            mock.patch.object(
                backend_bridge,
                "_session_order_file",
                return_value=self.order,
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reorder_folders_payload(self):
        for name in ("B", "A"):
            create_folder(self.folders, name)
        payload = backend_bridge.reorder_folders_payload(json.dumps(["A", "B"]))
        self.assertEqual([f["name"] for f in payload["folders"]], ["A", "B"])

    def test_reorder_folders_rejects_bad_json(self):
        with self.assertRaises(ValueError):
            backend_bridge.reorder_folders_payload("{")

    def test_session_order_round_trip(self):
        saved = backend_bridge.save_session_order_payload(
            "dynamic", json.dumps(["B", "A"])
        )
        self.assertEqual(saved["dynamic"], ["B", "A"])
        self.assertEqual(
            backend_bridge.session_order_payload()["dynamic"], ["B", "A"]
        )

    def test_session_order_rejects_non_list(self):
        with self.assertRaises(ValueError):
            backend_bridge.save_session_order_payload("fixed", "{}")


class BackupIncludesOrderTests(unittest.TestCase):
    def test_order_file_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            archive.mkdir()
            (archive / "sidebar_order.json").write_text("{}")
            result = backup_state(archive, Path(tmp) / "backups")
            self.assertEqual(result["status"], "created")
            snapshot = list_snapshots(Path(tmp) / "backups")[0]
            self.assertTrue((snapshot / "sidebar_order.json").is_file())


if __name__ == "__main__":
    unittest.main()
