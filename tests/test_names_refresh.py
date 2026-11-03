import json
import tempfile
import unittest
from pathlib import Path

import catch_up
import config
import names_refresh
import voice_service as vs

RUN = "2026-01-01_1000_Sample"


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def voices(**people):
    """Voice 'a' lasts 60 s, 'b' 30 s, 'c' 10 s. people maps id to a name or None."""
    seconds = {"a": 60, "b": 30, "c": 10}
    return {"version": vs.SPEAKERS_VERSION, "voices": [
        {"id": vid, "seconds": seconds[vid], "turns": 5,
         "status": "named" if people.get(vid) else "unknown",
         "person": people.get(vid) or ""} for vid in ("a", "b", "c")]}


def make_meeting(base, document):
    folder = base / RUN
    write(folder / "meeting_transcript.md", "transcript")
    write(folder / "meeting_transcript_cleaned.md", "cleaned")
    write(folder / "meeting_summary.md", "summary")
    write(folder / "meeting_memory.json", json.dumps({"commitments": []}))
    write(folder / "transcript" / "remote.vtt", "WEBVTT")
    write(folder / "speakers.json", json.dumps(document))
    return folder


class NamesFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.output, self.staging, self.backups = root / "o", root / "s", root / "b"
        self.folder = make_meeting(self.output, voices(a="Sam"))
        self.saved = config.NAMED_TRANSCRIPT
        config.NAMED_TRANSCRIPT = True

    def tearDown(self):
        config.NAMED_TRANSCRIPT = self.saved
        self.tmp.cleanup()

    def status(self):
        return names_refresh.status(self.folder, self.staging, self.backups)

    def rename(self, **people):
        write(self.folder / "speakers.json", json.dumps(voices(**people)))


class NamesRefreshTests(NamesFixture):
    def test_a_meeting_built_without_any_names_is_stale_once_voices_are_named(self):
        # No record of names used: it was built without names (voice recognition
        # could not run). Sam speaks 60% of it, so he counts as newly named.
        result = self.status()
        self.assertEqual((result["state"], result["people"]), ("stale", ["Sam"]))

    def test_no_record_and_no_named_voices_is_current(self):
        self.rename()
        self.assertEqual(self.status()["state"], "current")

    def test_no_record_and_only_a_brief_named_voice_is_current(self):
        write(self.folder / "speakers.json", json.dumps({
            "version": vs.SPEAKERS_VERSION, "voices": [
                {"id": "a", "seconds": 99, "turns": 5, "status": "unknown", "person": ""},
                {"id": "b", "seconds": 1, "turns": 1, "status": "named", "person": "Sam"}]}))
        self.assertEqual(self.status()["state"], "current")

    def test_nothing_changed_since_the_build_is_current(self):
        names_refresh.record_names_used(self.folder)
        self.assertEqual(self.status()["state"], "current")

    def test_naming_a_voice_that_spoke_a_lot_makes_it_stale(self):
        names_refresh.record_names_used(self.folder)
        self.rename(a="Sam", b="Dana")
        result = self.status()
        self.assertEqual(result["state"], "stale")
        self.assertEqual(result["people"], ["Dana"])
        self.assertAlmostEqual(result["share"], 0.3, places=2)

    def test_naming_a_voice_that_barely_spoke_is_not_worth_a_notice(self):
        write(self.folder / "speakers.json", json.dumps({
            "version": vs.SPEAKERS_VERSION, "voices": [
                {"id": "a", "seconds": 1000, "turns": 9, "status": "named", "person": "Sam"},
                {"id": "b", "seconds": 5, "turns": 1, "status": "unknown", "person": ""}]}))
        names_refresh.record_names_used(self.folder)
        write(self.folder / "speakers.json", json.dumps({
            "version": vs.SPEAKERS_VERSION, "voices": [
                {"id": "a", "seconds": 1000, "turns": 9, "status": "named", "person": "Sam"},
                {"id": "b", "seconds": 5, "turns": 1, "status": "named", "person": "Dana"}]}))
        self.assertEqual(self.status()["state"], "current")

    def test_changing_who_a_voice_is_makes_it_stale(self):
        names_refresh.record_names_used(self.folder)
        self.rename(a="Casey")
        self.assertEqual(self.status()["state"], "stale")

    def test_noise_voices_are_ignored(self):
        document = voices(a="Sam")
        document["voices"][2]["noise"] = True
        write(self.folder / "speakers.json", json.dumps(document))
        self.assertEqual(names_refresh._named_voices(document), {"a": "Sam"})

    def test_off_when_named_transcripts_are_off(self):
        config.NAMED_TRANSCRIPT = False
        self.assertEqual(self.status()["state"], "off")

    def test_off_when_the_meeting_cannot_be_rebuilt(self):
        (self.folder / "speakers.json").unlink()
        self.assertEqual(self.status()["state"], "off")

    def test_a_finished_rebuild_is_ready_and_discarding_it_clears_that(self):
        names_refresh.record_names_used(self.folder)
        write(self.staging / RUN / "status.json", json.dumps(
            {"state": "built", "old": {"commitments": 3}, "new": {"commitments": 2}}))
        result = self.status()
        self.assertEqual(result["state"], "ready")
        self.assertEqual(result["staged"]["new"], {"commitments": 2})
        self.assertTrue(names_refresh.discard(self.folder, self.staging))
        self.assertEqual(self.status()["state"], "current")

    def test_undo_is_offered_after_an_apply(self):
        self.assertFalse(self.status()["can_undo"])
        write(self.backups / RUN / "20260101-100000" / "record.json",
              json.dumps({"state": "applied", "entries": []}))
        self.assertTrue(self.status()["can_undo"])

    def test_stamp_all_stamps_once(self):
        self.assertEqual(names_refresh.stamp_all(self.output)["stamped"], 1)
        self.assertEqual(names_refresh.stamp_all(self.output)["had_one"], 1)
        self.assertEqual(self.status()["state"], "current")

    def test_apply_carries_the_new_stamp_over(self):
        def runner(work):
            for name in catch_up.REPLACED:
                write(work / name, "new")
            write(work / "meeting_metadata.json", "{}")
            names_refresh.record_names_used(work)
        self.rename(a="Sam", b="Dana")
        catch_up.rebuild(self.folder, self.staging, runner)
        catch_up.apply(self.folder, self.staging, self.backups, None,
                       export=lambda run: None)
        self.assertEqual(self.status()["state"], "current")
        catch_up.undo(self.folder, self.backups, None)
        self.assertFalse((self.folder / names_refresh.STAMP).exists())


CURRENT = """# Meeting Summary

## Executive Summary

Old words.

## Decisions
- Unidentified will provide a video on Friday.
- Reseller management goes live on Friday.

**Possible decisions (unconfirmed)**
- Vendors will be tested in a sandbox.

## Action Items
- Dana - See the release - Due date not identified

## Risks and Concerns

None identified.
"""

REBUILT = """# Meeting Summary

## Executive Summary

Completely new words.

## Decisions
- Reseller management goes live on Friday
- The team will focus on reporting.

**Possible decisions (unconfirmed)**
- Vendors will be tested in a sandbox.

## Action Items
- AlexH - Explain how it works - Due: Friday

## Risks and Concerns
- A new reseller may not be set up.
"""


class PreviewTests(NamesFixture):
    def staged(self, text):
        write(self.staging / RUN / "work" / "meeting_summary.md", text)

    def test_changes_list_only_what_differs_in_the_sections_people_act_on(self):
        result = names_refresh.summary_changes(CURRENT, REBUILT)
        text = result["changes"]
        self.assertIn("### Decisions", text)
        self.assertIn("**Added:** The team will focus on reporting.", text)
        self.assertIn("**Removed:** Unidentified will provide a video on Friday.", text)
        self.assertIn("**Added:** AlexH - Explain how it works", text)
        self.assertIn("**Removed:** Dana - See the release", text)
        self.assertIn("**Added:** A new reseller may not be set up.", text)
        self.assertNotIn("None identified", text)
        self.assertNotIn("new words", text)                 # the executive summary is not listed
        self.assertNotIn("sandbox", text)                   # unchanged lines are not listed
        self.assertNotIn("goes live on Friday", text)       # same line apart from a final period
        self.assertEqual((result["added"], result["removed"]), (3, 2))

    def test_identical_summaries_say_so(self):
        result = names_refresh.summary_changes(CURRENT, CURRENT)
        self.assertEqual((result["added"], result["removed"]), (0, 0))
        self.assertIn("No differences", result["changes"])

    def test_preview_reads_the_current_and_the_staged_summary(self):
        write(self.folder / "meeting_summary.md", CURRENT)
        self.staged(REBUILT)
        result = names_refresh.preview(self.folder, self.staging)
        self.assertEqual(result["current"], CURRENT)
        self.assertEqual(result["rebuilt"], REBUILT)
        self.assertEqual(result["added"], 3)

    def test_preview_without_a_rebuild_is_refused(self):
        with self.assertRaises(catch_up.CatchUpError):
            names_refresh.preview(self.folder, self.staging)

    def test_the_bridge_command_passes_it_through(self):
        from unittest import mock
        import backend_bridge
        write(self.folder / "meeting_summary.md", CURRENT)
        self.staged(REBUILT)
        with mock.patch.object(backend_bridge, "_meeting_run",
                               lambda run: (self.folder, None, None, None, None, None)), \
                mock.patch.object(backend_bridge, "_names_roots",
                                  lambda: (self.staging, self.backups)):
            result = backend_bridge.meeting_names_preview_payload(RUN)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["removed"], 2)


class ProgressTests(NamesFixture):
    def test_lines_become_plain_steps(self):
        pt = names_refresh.progress_text
        self.assertEqual(pt("Cleaning chunk 2/3..."), "Cleaning the transcript (part 2 of 3)")
        self.assertEqual(pt("Looking for action items (names pass)..."), "Finding action items")
        self.assertEqual(pt("Looking for decisions, risks and open questions (names pass)..."),
                         "Finding decisions, risks and open questions")
        self.assertEqual(pt("Summarizing complete transcript directly..."), "Writing the summary")
        self.assertEqual(pt("Fetching 11 files: 100%"), "")

    def test_the_tee_keeps_the_latest_step_and_passes_text_on(self):
        import io
        out = io.StringIO()
        path = self.staging / RUN / names_refresh.PROGRESS
        tee = names_refresh.ProgressTee(out, path)
        tee.write("Cleaning chunk 1/3...\nnoise\nLooking for action")
        self.assertEqual(path.read_text(), "Cleaning the transcript (part 1 of 3)")
        tee.write(" items (names pass)...\n")
        self.assertEqual(path.read_text(), "Finding action items")
        self.assertIn("noise", out.getvalue())

    def test_status_shows_the_step_while_a_rebuild_runs_and_not_when_ready(self):
        names_refresh.record_names_used(self.folder)
        write(self.staging / RUN / names_refresh.PROGRESS, "Writing the summary")
        self.assertEqual(self.status()["progress"], "Writing the summary")
        write(self.staging / RUN / "status.json", json.dumps({"state": "built"}))
        self.assertEqual(self.status()["progress"], "")

    def test_an_old_progress_file_is_ignored(self):
        import os
        import time
        path = self.staging / RUN / names_refresh.PROGRESS
        write(path, "Writing the summary")
        old = time.time() - names_refresh.PROGRESS_FRESH_SECONDS - 60
        os.utime(path, (old, old))
        self.assertEqual(self.status()["progress"], "")


class BridgeTests(NamesFixture):
    """The commands the app calls."""

    def setUp(self):
        super().setUp()
        from unittest import mock
        import backend_bridge
        self.bridge = backend_bridge
        for target, value in (
            ("_meeting_run", lambda run: (self.folder, self.output, None, None, None, None)),
            ("_names_roots", lambda: (self.staging, self.backups)),
        ):
            patch = mock.patch.object(backend_bridge, target, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_status_command_reports_the_state(self):
        names_refresh.record_names_used(self.folder)
        self.rename(a="Sam", b="Dana")
        result = self.bridge.meeting_names_status_payload(RUN)
        self.assertEqual((result["state"], result["people"]), ("stale", ["Dana"]))

    def test_rebuild_then_discard(self):
        from unittest import mock
        names_refresh.record_names_used(self.folder)
        self.rename(a="Sam", b="Dana")
        built = {"state": "built", "old": {"commitments": 1}, "new": {"commitments": 2}}

        def fake_rebuild(folder, staging):
            write(Path(staging) / folder.name / "status.json", json.dumps(built))
            return built

        with mock.patch.object(catch_up, "rebuild", side_effect=fake_rebuild):
            self.assertEqual(self.bridge.meeting_names_rebuild_payload(RUN)["state"], "ready")
        self.assertEqual(self.bridge.meeting_names_discard_payload(RUN)["state"], "stale")

    def test_a_failed_rebuild_raises_with_the_reason(self):
        from unittest import mock
        with mock.patch.object(catch_up, "rebuild",
                               return_value={"state": "failed", "reason": "model busy"}):
            with self.assertRaises(RuntimeError) as caught:
                self.bridge.meeting_names_rebuild_payload(RUN)
        self.assertIn("model busy", str(caught.exception))

    def test_apply_and_undo_refresh_the_dashboard(self):
        from unittest import mock
        with mock.patch.object(catch_up, "apply") as apply, \
                mock.patch.object(catch_up, "undo") as undo, \
                mock.patch.object(catch_up, "refresh_dashboard") as refresh:
            self.bridge.meeting_names_apply_payload(RUN)
            self.bridge.meeting_names_undo_payload(RUN)
        apply.assert_called_once()
        undo.assert_called_once()
        self.assertEqual(refresh.call_count, 2)

    def test_progress_lines_never_reach_stdout(self):
        import contextlib
        import io
        from unittest import mock
        built = {"state": "built", "old": {}, "new": {}}

        def noisy_rebuild(folder, staging):
            print("Looking for action items (names pass)...")
            write(Path(staging) / folder.name / "status.json", json.dumps(built))
            return built

        out = io.StringIO()
        with mock.patch.object(catch_up, "rebuild", side_effect=noisy_rebuild), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.bridge.meeting_names_rebuild_payload(RUN)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
