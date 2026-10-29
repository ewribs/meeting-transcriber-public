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
    def test_a_meeting_built_before_names_were_tracked_is_unknown(self):
        self.assertEqual(self.status()["state"], "unknown")

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
