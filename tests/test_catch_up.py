import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import catch_up

RUN = "2026-01-01_1000_Sample"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_meeting(base, name=RUN, old="old"):
    folder = base / name
    write(folder / "meeting_transcript.md", "transcript")
    write(folder / "meeting_transcript.html", "<p>t</p>")
    write(folder / "meeting_transcript_cleaned.md", f"cleaned {old}")
    write(folder / "meeting_summary.md", f"summary {old}")
    write(folder / "meeting_summary.html", f"<p>summary {old}</p>")
    write(folder / "meeting_memory.json", json.dumps({
        "commitments": [{"owner": "Unknown", "action": "a"}], "decisions": [],
        "open_questions": [], "risks": []}))
    write(folder / "meeting_metadata.json", json.dumps({
        "display_title": "My title", "title_custom": True,
        "participants": [{"name": "Old Name"}]}))
    write(folder / "speakers.json", "{}")
    write(folder / "transcript" / "remote.vtt", "WEBVTT")
    write(folder / "exports" / f"OneNote_{name}.html", "<p>old export</p>")
    return folder


def fake_runner(work):
    write(work / "meeting_transcript_cleaned.md", "cleaned new")
    write(work / "meeting_summary.md", "summary new")
    write(work / "meeting_summary.html", "<p>summary new</p>")
    write(work / "meeting_memory.json", json.dumps({
        "commitments": [{"owner": "Sam", "action": "a"}, {"owner": "Dana", "action": "b"}],
        "decisions": [], "open_questions": [], "risks": []}))
    metadata = json.loads((work / "meeting_metadata.json").read_text(encoding="utf-8"))
    metadata["participants"] = [{"name": "Sam"}, {"name": "Dana"}]
    metadata["display_title"] = "RESET BY PIPELINE"
    write(work / "meeting_metadata.json", json.dumps(metadata))


def fake_export(run_dir):
    write(run_dir / "exports" / f"OneNote_{run_dir.name}.html", "<p>new export</p>")


class CatchUpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.output, self.archive = root / "output", root / "archive"
        self.staging, self.backups = root / "staging", root / "backups"
        self.folder = make_meeting(self.output)
        self.twin = make_meeting(self.archive)

    def tearDown(self):
        self.tmp.cleanup()

    def built(self):
        return catch_up.rebuild(self.folder, self.staging, fake_runner)

    def apply(self, when=None):
        return catch_up.apply(self.folder, self.staging, self.backups, self.archive,
                              now=when, export=fake_export)

    def text(self, path):
        return path.read_text(encoding="utf-8")

    def test_rebuild_reports_old_and_new_and_leaves_the_meeting_alone(self):
        status = self.built()
        self.assertEqual(status["state"], "built")
        self.assertEqual(status["old"]["unowned"], 1)
        self.assertEqual(status["new"]["unowned"], 0)
        self.assertEqual(status["new"]["commitments"], 2)
        self.assertEqual(self.text(self.folder / "meeting_summary.md"), "summary old")

    def test_a_meeting_without_voice_information_is_skipped(self):
        (self.folder / "speakers.json").unlink()
        status = self.built()
        self.assertEqual(status["state"], "skipped")
        self.assertIn("voice", status["reason"])
        self.assertFalse((self.staging / RUN).exists())

    def test_a_failed_rebuild_leaves_nothing_behind(self):
        def broken(work):
            raise RuntimeError("model crashed")
        status = catch_up.rebuild(self.folder, self.staging, broken)
        self.assertEqual(status["state"], "failed")
        self.assertIn("model crashed", status["reason"])
        self.assertFalse((self.staging / RUN).exists())

    def test_a_rebuild_that_misses_a_file_fails(self):
        def partial(work):
            write(work / "meeting_summary.md", "x")
        self.assertEqual(catch_up.rebuild(self.folder, self.staging, partial)["state"], "failed")

    def test_apply_replaces_the_files_and_only_the_participants(self):
        self.built()
        result = self.apply()
        self.assertTrue(result["archive"])
        for base in (self.folder, self.twin):
            self.assertEqual(self.text(base / "meeting_summary.md"), "summary new")
            self.assertEqual(self.text(base / "meeting_transcript_cleaned.md"), "cleaned new")
            metadata = json.loads(self.text(base / "meeting_metadata.json"))
            self.assertEqual([p["name"] for p in metadata["participants"]], ["Sam", "Dana"])
            self.assertEqual(metadata["display_title"], "My title")
            self.assertTrue(metadata["title_custom"])
        self.assertEqual(self.text(self.folder / "exports" / f"OneNote_{RUN}.html"), "<p>new export</p>")
        self.assertEqual(self.text(self.twin / "exports" / f"OneNote_{RUN}.html"), "<p>new export</p>")
        self.assertEqual(self.text(self.folder / "meeting_transcript.md"), "transcript")

    def test_apply_needs_a_rebuild_first(self):
        with self.assertRaises(catch_up.CatchUpError):
            self.apply()

    def test_undo_puts_everything_back(self):
        self.built()
        self.apply(datetime(2026, 1, 2, 3, 4, 5))
        catch_up.undo(self.folder, self.backups, self.archive)
        for base in (self.folder, self.twin):
            self.assertEqual(self.text(base / "meeting_summary.md"), "summary old")
            metadata = json.loads(self.text(base / "meeting_metadata.json"))
            self.assertEqual([p["name"] for p in metadata["participants"]], ["Old Name"])
        self.assertEqual(self.text(self.folder / "exports" / f"OneNote_{RUN}.html"), "<p>old export</p>")
        with self.assertRaises(catch_up.CatchUpError):
            catch_up.undo(self.folder, self.backups, self.archive)

    def test_a_meeting_without_an_archived_copy_is_fine(self):
        import shutil
        shutil.rmtree(self.twin)
        self.built()
        self.assertFalse(self.apply()["archive"])

    def test_undo_removes_a_file_that_did_not_exist_before(self):
        (self.folder / "exports" / f"OneNote_{RUN}.html").unlink()
        self.built()
        self.apply()
        catch_up.undo(self.folder, self.backups, self.archive)
        self.assertFalse((self.folder / "exports" / f"OneNote_{RUN}.html").exists())


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.output, self.archive = root / "output", root / "archive"
        self.staging, self.backups = root / "staging", root / "backups"
        for name in ("2026-01-01_1000_Old", "2026-01-02_1000_Mid", "2026-01-03_1000_New"):
            make_meeting(self.output, name)
        # one meeting that cannot be caught up
        (self.output / "2026-01-02_1000_Mid" / "speakers.json").unlink()

    def tearDown(self):
        self.tmp.cleanup()

    def test_newest_first_and_unusable_meetings_are_skipped(self):
        lines = []
        counts = catch_up.rebuild_all(self.output, self.staging, fake_runner, log=lines.append)
        self.assertEqual(counts["built"], 2)
        self.assertEqual(counts["skipped"], 1)
        self.assertTrue(lines[0].startswith("2026-01-03_1000_New"))

    def test_a_second_run_skips_what_is_done_and_limit_stops_early(self):
        catch_up.rebuild_all(self.output, self.staging, fake_runner, limit=1, log=lambda _l: None)
        counts = catch_up.rebuild_all(self.output, self.staging, fake_runner, log=lambda _l: None)
        self.assertEqual(counts["already"], 1)
        self.assertEqual(counts["built"], 1)

    def test_one_failure_does_not_stop_the_rest(self):
        def sometimes_fails(work):
            if "New" in str(work):
                raise RuntimeError("model down")
            fake_runner(work)
        counts = catch_up.rebuild_all(self.output, self.staging, sometimes_fails,
                                      log=lambda _l: None)
        self.assertEqual(counts["failed"], 1)
        self.assertEqual(counts["built"], 1)

    def test_apply_all_applies_only_rebuilt_meetings_once(self):
        catch_up.rebuild_all(self.output, self.staging, fake_runner, log=lambda _l: None)
        first = catch_up.apply_all(self.output, self.staging, self.backups, self.archive,
                                   export=fake_export, log=lambda _l: None)
        second = catch_up.apply_all(self.output, self.staging, self.backups, self.archive,
                                    export=fake_export, log=lambda _l: None)
        self.assertEqual(first["applied"], 2)
        self.assertEqual(second["applied"], 0)
        self.assertEqual((self.output / "2026-01-03_1000_New" / "meeting_summary.md")
                         .read_text(encoding="utf-8"), "summary new")


class RetidyTests(unittest.TestCase):
    def test_only_decisions_and_risks_change_and_nothing_is_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            write(work / "meeting_summary.md",
                  "# Meeting Summary\n\n## Key Themes\n\n- keep this\n\n## Decisions\n\n"
                  "- Morgan asked the vendor to extend the licence.\n\n## Action Items\n\nx\n\n"
                  "## Risks and Concerns\n\n- Price may rise.\n- The price could rise.\n\n"
                  "## Open Questions\n\nNone identified.\n\n## Topics\n\nNone identified.\n")
            write(work / "meeting_memory.json", json.dumps({
                "decisions": [{"decision": "Morgan asked the vendor to extend the licence."}],
                "risks": [{"risk": "Price may rise."}, {"risk": "The price could rise."}],
                "commitments": [], "open_questions": []}))
            self.assertTrue(catch_up.retidy(work))
            text = (work / "meeting_summary.md").read_text(encoding="utf-8")
            self.assertEqual(text.count("## Decisions"), 1)
            self.assertIn("- keep this", text)
            self.assertIn("**Possible decisions (unconfirmed)**\n\n- Morgan asked", text)
            self.assertEqual(text.count("rise"), 1)
            self.assertFalse(catch_up.retidy(work))


class TidyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.output, self.staging = root / "output", root / "staging"
        make_meeting(self.output, "2026-01-03_1000_New")
        catch_up.rebuild_all(self.output, self.staging, fake_runner, log=lambda _l: None)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_changed_meeting_is_marked_to_be_applied_again(self):
        name = "2026-01-03_1000_New"
        status = json.loads((self.staging / name / "status.json").read_text())
        status["state"] = "applied"
        (self.staging / name / "status.json").write_text(json.dumps(status))
        counts = catch_up.tidy_all(self.output, self.staging, tidy=lambda work: True,
                                   log=lambda _l: None)
        self.assertEqual(counts["changed"], 1)
        self.assertEqual(catch_up.staged_state(self.staging, name), "built")

    def test_an_unchanged_meeting_stays_applied(self):
        name = "2026-01-03_1000_New"
        status = json.loads((self.staging / name / "status.json").read_text())
        status["state"] = "applied"
        (self.staging / name / "status.json").write_text(json.dumps(status))
        counts = catch_up.tidy_all(self.output, self.staging, tidy=lambda work: False,
                                   log=lambda _l: None)
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual(catch_up.staged_state(self.staging, name), "applied")


if __name__ == "__main__":
    unittest.main()
