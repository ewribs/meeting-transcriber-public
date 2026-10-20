import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import meeting_rename
from metadata import create_meeting_metadata, get_display_title


def make_run(root: Path, name: str, title: str) -> Path:
    run_dir = root / name
    run_dir.mkdir(parents=True)
    (run_dir / "meeting_metadata.json").write_text(
        json.dumps({"display_title": title, "meeting_run": name}),
        encoding="utf-8",
    )
    return run_dir


class DisplayTitleTests(unittest.TestCase):
    def title(self, text):
        return get_display_title(Path("2026-10-19_1321_" + text + "101926"))

    def test_acronym_followed_by_glued_connector(self):
        self.assertEqual(
            self.title("XYZandThirdParty"),
            "XYZ and Third Party",
        )

    def test_capitalized_connectors_are_not_split(self):
        self.assertEqual(self.title("AlphaForTheWin"), "Alpha For The Win")
        self.assertEqual(self.title("BrandNewTeam"), "Brand New Team")

    def test_existing_behaviour_kept(self):
        self.assertEqual(self.title("TeamSync1v1"), "Team Sync 1v1")


class RenameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.archive = root / "archive"
        self.output = root / "output"
        self.archive.mkdir()
        self.output.mkdir()

    def rename(self, run, title):
        with mock.patch("indexer.build_meeting_index") as index, \
                mock.patch("dashboard_generator.build_meeting_dashboard") as dash:
            result = meeting_rename.rename_meeting(
                run, title, archive_dir=self.archive, output_dir=self.output
            )
            return result, index, dash

    def read(self, folder, run):
        return json.loads((folder / run / "meeting_metadata.json").read_text())

    def test_unpublished_rename_changes_only_local_metadata(self):
        make_run(self.output, "run1", "Old")
        result, index, dash = self.rename("run1", "  New   name ")
        self.assertEqual(result["title"], "New name")
        self.assertFalse(result["published"])
        data = self.read(self.output, "run1")
        self.assertEqual(data["display_title"], "New name")
        self.assertTrue(data["title_custom"])
        index.assert_not_called()

    def test_published_rename_updates_both_copies_and_rebuilds_index(self):
        make_run(self.output, "run1", "Old")
        make_run(self.archive, "run1", "Old")
        result, index, dash = self.rename("run1", "New")
        self.assertTrue(result["published"])
        self.assertEqual(self.read(self.archive, "run1")["display_title"], "New")
        self.assertEqual(self.read(self.output, "run1")["display_title"], "New")
        index.assert_called_once()
        dash.assert_called_once()

    def test_rejects_empty_unknown_and_path_like_names(self):
        make_run(self.output, "run1", "Old")
        for run, title in [("run1", "   "), ("missing", "X"), ("../x", "X")]:
            with self.assertRaises(meeting_rename.MeetingRenameError):
                self.rename(run, title)

    def test_custom_title_survives_metadata_rebuild(self):
        run_dir = make_run(self.output, "2026-10-19_1321_XYZandThird101926", "Old")
        self.rename("2026-10-19_1321_XYZandThird101926", "My Title")
        create_meeting_metadata(run_dir)
        data = json.loads((run_dir / "meeting_metadata.json").read_text())
        self.assertEqual(data["display_title"], "My Title")

    def test_uncustomised_title_is_regenerated(self):
        run_dir = make_run(self.output, "2026-10-19_1321_XYZandThird101926", "Stale")
        create_meeting_metadata(run_dir)
        data = json.loads((run_dir / "meeting_metadata.json").read_text())
        self.assertEqual(data["display_title"], "XYZ and Third")


if __name__ == "__main__":
    unittest.main()
