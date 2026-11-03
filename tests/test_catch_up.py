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


class ModelFailureTests(unittest.TestCase):
    def test_no_failures_is_fine(self):
        catch_up.check_model_failures([])

    def test_running_out_of_memory_says_so(self):
        with self.assertRaises(catch_up.CatchUpError) as caught:
            catch_up.check_model_failures(["[METAL] Insufficient Memory (0000008)", "again"])
        self.assertIn("ran out of memory", str(caught.exception))
        self.assertIn("2 model steps", str(caught.exception))
        self.assertIn("Nothing was changed", str(caught.exception))

    def test_any_other_failure_names_the_first_problem(self):
        with self.assertRaises(catch_up.CatchUpError) as caught:
            catch_up.check_model_failures(["model busy\nmore detail"])
        self.assertIn("1 model step failed (model busy)", str(caught.exception))

    def test_ask_llm_records_failures_only_when_asked(self):
        import ai
        from unittest import mock

        class Broken:
            def generate(self, *args, **kwargs):
                raise RuntimeError("[METAL] Insufficient Memory")

        with mock.patch.object(ai, "_get_llm_backend", return_value=Broken()):
            ai.LLM_FAILURES = None
            with self.assertRaises(RuntimeError):
                ai.ask_llm("hi")
            self.assertIsNone(ai.LLM_FAILURES)
            ai.LLM_FAILURES = []
            try:
                with self.assertRaises(RuntimeError):
                    ai.ask_llm("hi")
                self.assertEqual(len(ai.LLM_FAILURES), 1)
            finally:
                ai.LLM_FAILURES = None


class RefreshDashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.archive = self.root / "archive"
        self.folder = make_meeting(self.root / "output")

    def tearDown(self):
        self.tmp.cleanup()

    def test_refreshes_when_the_meeting_is_published(self):
        from unittest import mock
        make_meeting(self.archive)
        with mock.patch("voice_review.refresh_index", return_value=True) as refresh:
            self.assertTrue(catch_up.refresh_dashboard(self.archive, self.folder))
        refresh.assert_called_once_with(self.archive)

    def test_skips_a_meeting_that_is_not_published(self):
        from unittest import mock
        self.archive.mkdir()
        with mock.patch("voice_review.refresh_index") as refresh:
            self.assertFalse(catch_up.refresh_dashboard(self.archive, self.folder))
            self.assertFalse(catch_up.refresh_dashboard(None, self.folder))
        refresh.assert_not_called()

    def test_never_raises(self):
        from unittest import mock
        make_meeting(self.archive)
        with mock.patch("voice_review.refresh_index", side_effect=RuntimeError("boom")):
            self.assertFalse(catch_up.refresh_dashboard(self.archive, self.folder))

    def test_apply_all_refreshes_once_for_the_batch(self):
        from unittest import mock
        staging, backups = self.root / "staging", self.root / "backups"
        for name in ("2026-01-01_1000_One", "2026-01-02_1000_Two"):
            make_meeting(self.root / "output", name)
            make_meeting(self.archive, name)
            catch_up.rebuild(self.root / "output" / name, staging, fake_runner)
        logs = []
        with mock.patch("voice_review.refresh_index", return_value=True) as refresh:
            counts = catch_up.apply_all(self.root / "output", staging, backups, self.archive,
                                        export=fake_export, log=logs.append)
        self.assertEqual(counts["applied"], 2)
        refresh.assert_called_once_with(self.archive)
        self.assertIn("Refreshed the meeting index and dashboard.", logs)


QUOTE = "I will gather the cost information for the tools by Friday"


class KeepEarlierTests(unittest.TestCase):
    """A rebuild keeps firm action items the current summary already has."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.staging = root / "staging"
        self.folder = make_meeting(root / "output")

    def tearDown(self):
        self.tmp.cleanup()

    def old_memory(self, *commitments):
        write(self.folder / "meeting_memory.json", json.dumps({
            "commitments": list(commitments), "decisions": [], "open_questions": [], "risks": []}))

    def rebuilt(self, commitments=(), others=(), transcript=None):
        text = QUOTE if transcript is None else transcript

        def runner(work):
            write(work / "meeting_transcript_cleaned.md", "**Avery**\n\n" + text + "\n")
            write(work / "meeting_summary.md",
                  "## Executive Summary\n\nText.\n\n## Action Items\n\nNone identified.\n\n## Risks and Concerns\n\nNone identified.\n")
            write(work / "meeting_summary.html", "<p>x</p>")
            write(work / "meeting_memory.json", json.dumps({
                "commitments": list(commitments), "other_next_steps": list(others),
                "decisions": [], "open_questions": [], "risks": []}))

        status = catch_up.rebuild(self.folder, self.staging, runner)
        work = self.staging / RUN / "work"
        memory = json.loads((work / "meeting_memory.json").read_text(encoding="utf-8"))
        summary = (work / "meeting_summary.md").read_text(encoding="utf-8")
        return status, memory, summary

    def item(self, owner="Avery", action="Gather cost information for the tools", evidence=QUOTE):
        return {"owner": owner, "action": action, "due": "", "evidence": evidence, "status": "open"}

    def test_missed_item_is_put_back_and_shown_in_the_summary(self):
        self.old_memory(self.item())
        status, memory, summary = self.rebuilt()
        self.assertEqual(status["state"], "built")
        self.assertEqual(status["kept_earlier"], 1)
        self.assertEqual([c["owner"] for c in memory["commitments"]], ["Avery"])
        self.assertIn("- Avery - Gather cost information for the tools - Due date not identified", summary)
        self.assertNotIn("None identified.\n\n## Risks", summary)

    def test_item_the_rebuild_already_has_is_not_repeated(self):
        self.old_memory(self.item())
        status, memory, _summary = self.rebuilt(commitments=[
            self.item(action="Gather the cost information for the tools")])
        self.assertEqual(status["kept_earlier"], 0)
        self.assertEqual(len(memory["commitments"]), 1)

    def test_unconfirmed_copy_is_replaced_by_the_firm_item(self):
        self.old_memory(self.item())
        _status, memory, summary = self.rebuilt(
            others=["Avery - Gather cost information for the tools - Due date not identified"])
        self.assertEqual(memory["other_next_steps"], [])
        self.assertNotIn("Other next steps mentioned", summary)

    def test_other_unconfirmed_steps_stay(self):
        self.old_memory(self.item())
        _status, memory, summary = self.rebuilt(others=["Dana - Book the room for the review"])
        self.assertEqual(memory["other_next_steps"], ["Dana - Book the room for the review"])
        self.assertIn("Other next steps mentioned (unconfirmed)", summary)

    def test_item_whose_quote_is_gone_is_not_put_back(self):
        self.old_memory(self.item())
        status, memory, _summary = self.rebuilt(transcript="We talked about something else entirely today")
        self.assertEqual(status["kept_earlier"], 0)
        self.assertEqual(memory["commitments"], [])

    def test_a_quote_with_extra_words_added_in_the_middle_still_matches(self):
        self.old_memory(self.item(evidence="I'd say there's no harm in gathering the cost information."))
        status, _memory, _summary = self.rebuilt(
            transcript="I'd say there's, seems like there's no harm in gathering the cost information.")
        self.assertEqual(status["kept_earlier"], 1)

    def test_a_quote_only_in_the_raw_transcript_still_counts(self):
        self.old_memory(self.item())
        text = "We talked about something else entirely today"

        def runner(work):
            write(work / "meeting_transcript.md", "Avery: " + QUOTE)
            write(work / "meeting_transcript_cleaned.md", "**Avery**\n\n" + text + "\n")
            write(work / "meeting_summary.md", "## Action Items\n\nNone identified.\n")
            write(work / "meeting_summary.html", "<p>x</p>")
            write(work / "meeting_memory.json", json.dumps({
                "commitments": [], "other_next_steps": [], "decisions": [],
                "open_questions": [], "risks": []}))

        status = catch_up.rebuild(self.folder, self.staging, runner)
        self.assertEqual(status["kept_earlier"], 1)

    def test_items_without_a_named_owner_or_a_quote_are_not_put_back(self):
        self.old_memory(self.item(owner="Unknown"), self.item(owner="Remote"),
                        self.item(evidence=""))
        status, memory, _summary = self.rebuilt()
        self.assertEqual(status["kept_earlier"], 0)
        self.assertEqual(memory["commitments"], [])

    def test_a_quote_with_a_dropped_word_still_matches(self):
        self.old_memory(self.item(evidence="I will gather the cost information for the tools by um Friday"))
        status, _memory, _summary = self.rebuilt()
        self.assertEqual(status["kept_earlier"], 1)


if __name__ == "__main__":
    unittest.main()
