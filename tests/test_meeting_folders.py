import json
import tempfile
import unittest
from pathlib import Path

from meeting_folders import (
    DuplicateFolderError,
    FolderError,
    FolderNotFoundError,
    add_meetings,
    create_folder,
    delete_folder,
    load_folders,
    remove_meetings,
    rename_folder,
)


class MeetingFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "meeting_folders.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_means_no_folders(self):
        self.assertEqual(load_folders(self.path), [])

    def test_create_and_reload(self):
        create_folder(self.path, "  Pat   notes ")
        self.assertEqual(
            load_folders(self.path),
            [{"name": "Pat notes", "meeting_runs": []}],
        )

    def test_names_are_validated_and_unique_ignoring_case(self):
        create_folder(self.path, "Pat")
        with self.assertRaises(DuplicateFolderError):
            create_folder(self.path, "pat")
        with self.assertRaises(FolderError):
            create_folder(self.path, "   ")
        with self.assertRaises(FolderError):
            create_folder(self.path, "x" * 81)

    def test_add_is_idempotent_and_allows_many_folders(self):
        create_folder(self.path, "A")
        create_folder(self.path, "B")
        add_meetings(self.path, "A", ["r1", "r2", "r1"])
        add_meetings(self.path, "a", ["r2", "r3"])
        add_meetings(self.path, "B", ["r1"])
        folders = {f["name"]: f["meeting_runs"] for f in load_folders(self.path)}
        self.assertEqual(folders["A"], ["r1", "r2", "r3"])
        self.assertEqual(folders["B"], ["r1"])

    def test_remove_meetings(self):
        create_folder(self.path, "A")
        add_meetings(self.path, "A", ["r1", "r2"])
        remove_meetings(self.path, "A", ["r1", "nope"])
        self.assertEqual(load_folders(self.path)[0]["meeting_runs"], ["r2"])

    def test_rename_keeps_meetings_and_rejects_duplicates(self):
        create_folder(self.path, "A")
        create_folder(self.path, "B")
        add_meetings(self.path, "A", ["r1"])
        rename_folder(self.path, "A", "Alpha")
        rename_folder(self.path, "Alpha", "ALPHA")  # case-only change is fine
        with self.assertRaises(DuplicateFolderError):
            rename_folder(self.path, "ALPHA", "b")
        self.assertEqual(load_folders(self.path)[0]["meeting_runs"], ["r1"])
        self.assertEqual(load_folders(self.path)[0]["name"], "ALPHA")

    def test_delete_removes_only_the_folder(self):
        create_folder(self.path, "A")
        create_folder(self.path, "B")
        delete_folder(self.path, "A")
        self.assertEqual([f["name"] for f in load_folders(self.path)], ["B"])
        with self.assertRaises(FolderNotFoundError):
            delete_folder(self.path, "A")

    def test_unreadable_file_is_never_overwritten(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(FolderError):
            load_folders(self.path)
        with self.assertRaises(FolderError):
            create_folder(self.path, "A")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_wrong_shape_is_unreadable_too(self):
        self.path.write_text(json.dumps({"folders": [{"nope": 1}]}))
        with self.assertRaises(FolderError):
            load_folders(self.path)

    def test_no_temp_files_left_behind(self):
        create_folder(self.path, "A")
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name != self.path.name]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()


class FolderBridgeTests(unittest.TestCase):
    def test_commands_round_trip_through_the_bridge(self):
        from unittest import mock

        import backend_bridge

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("config.ARCHIVE_DIR", Path(tmp)):
                self.assertEqual(backend_bridge.folders_payload()["folders"], [])
                backend_bridge.create_folder_payload("Pat")
                result = backend_bridge.add_folder_meetings_payload(
                    "Pat", json.dumps(["r1", "r2"])
                )
                self.assertEqual(result["schema_version"], 14)
                self.assertEqual(result["folders"][0]["meeting_runs"], ["r1", "r2"])
                result = backend_bridge.remove_folder_meetings_payload(
                    "Pat", json.dumps(["r1"])
                )
                self.assertEqual(result["folders"][0]["meeting_runs"], ["r2"])
                result = backend_bridge.rename_folder_payload("Pat", "Pat 1v1")
                self.assertEqual(result["folders"][0]["name"], "Pat 1v1")
                result = backend_bridge.delete_folder_payload("Pat 1v1")
                self.assertEqual(result["folders"], [])

    def test_empty_selection_is_rejected(self):
        from unittest import mock

        import backend_bridge

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("config.ARCHIVE_DIR", Path(tmp)):
                backend_bridge.create_folder_payload("Pat")
                with self.assertRaises(ValueError):
                    backend_bridge.add_folder_meetings_payload("Pat", "[]")
                with self.assertRaises(ValueError):
                    backend_bridge.add_folder_meetings_payload("Pat", "nope")

    def test_cli_lists_folders(self):
        from unittest import mock
        import io
        from contextlib import redirect_stdout

        import backend_bridge

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("config.ARCHIVE_DIR", Path(tmp)):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = backend_bridge.main(["create-folder", "Pat"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(buffer.getvalue())["folders"][0]["name"], "Pat")
