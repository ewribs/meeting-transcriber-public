import contextlib
import io
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import voice_cli
import voice_profiles as vp
import voice_service as vs

DIM = 32


def unit(seed):
    rng = random.Random(seed)
    return vp.normalize([rng.gauss(0, 1) for _ in range(DIM)])


def prints(base, count=20, seed=0):
    rng = random.Random(seed)
    return [vp.normalize([x + rng.gauss(0, 0.15) for x in base]) for _ in range(count)]


ALEX, SAM, STRANGER = unit(1), unit(2), unit(4)


def voice(voice_id, base, seconds, seed=0):
    return {"voice_id": voice_id, "seconds": seconds,
            "turns": [[0.0, seconds]], "fingerprints": prints(base, seed=seed)}


def payload(*voices, silent=False):
    return {"version": 1, "models": {}, "duration_seconds": 600.0,
            "remote_mean_db": -30.0, "remote_silent": silent,
            "seconds_taken": 1.0, "voices": list(voices)}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.voices = self.root / "voices"
        self.output = self.root / "output"
        self.meetings = self.root / "meetings"
        self.archive = self.root / "archive"
        for folder in (self.output, self.meetings, self.archive):
            folder.mkdir()
        self.payloads = {}
        self.asked = []

    def worker(self, audio):
        return self.payloads[Path(audio).name]

    def run_cli(self, *argv, answer="y"):
        out = io.StringIO()

        def ask(prompt):
            self.asked.append(prompt)
            return answer

        with contextlib.redirect_stdout(out):
            code = voice_cli.main(
                list(argv), worker=self.worker, voices_dir=self.voices,
                dirs=(self.output, self.meetings, self.archive), ask=ask,
            )
        return code, out.getvalue()

    def add_recording(self, name, result, folder=None):
        path = (folder or self.meetings) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        self.payloads[name] = result
        return path

    def store(self):
        return vp.VoiceStore.load(self.voices / "profiles.json")


class PeopleAndEnrollTests(CliTestCase):
    def test_empty_people_list(self):
        code, out = self.run_cli("people")
        self.assertEqual(code, 0)
        self.assertIn("No voice profiles yet", out)

    def test_enroll_learns_people_and_remembers_what_it_used(self):
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.add_recording("Alex1v1100526.m4a", payload(voice("V0", ALEX, 900, seed=1)))
        self.add_recording("Sam1v1100526.m4a", payload(voice("V0", SAM, 900)))
        code, out = self.run_cli("enroll")
        self.assertEqual(code, 0)
        self.assertIn("Learned from 3 recordings", out)
        self.assertEqual(self.store().find("Alex").enrollments, 2)
        self.assertEqual(oct((self.voices / "profiles.json").stat().st_mode & 0o777), "0o600")

        code, out = self.run_cli("enroll")
        self.assertIn("Nothing new to learn", out)

        code, out = self.run_cli("people")
        self.assertIn("Alex", out)
        self.assertIn("Sam", out)

    def test_declining_learns_nothing(self):
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        code, out = self.run_cli("enroll", answer="n")
        self.assertEqual(code, 1)
        self.assertIn("Cancelled", out)
        self.assertEqual(self.store().people(), [])

    def test_yes_flag_does_not_ask(self):
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")
        self.assertEqual(self.asked, [])

    def test_bad_recordings_are_skipped_and_reported(self):
        self.add_recording("Alex1v1092126.m4a", payload(silent=True))
        self.add_recording("Sam1v1100526.m4a", payload(voice("V0", SAM, 900)))
        code, out = self.run_cli("enroll", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("skipped Alex1v1092126.m4a", out)
        self.assertIn("Learned from 1 recordings, skipped 1", out)
        self.assertIsNone(self.store().find("Alex"))

    def test_archive_recordings_are_included(self):
        self.add_recording(
            "Alex1v1081926.m4a", payload(voice("V0", ALEX, 900)),
            folder=self.archive / "2026-08-19_1000_Alex1v1081926" / "source",
        )
        code, out = self.run_cli("enroll", "--yes")
        self.assertIn("Learned from 1 recordings", out)
        code, out = self.run_cli("enroll", "--yes", "--no-archive")
        self.assertIn("No one-on-one recordings found", out)

    def test_delete_removes_the_person_and_what_was_used(self):
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")
        code, out = self.run_cli("people", "--delete", "alex")
        self.assertEqual(code, 0)
        self.assertEqual(self.store().people(), [])
        code, out = self.run_cli("enroll", "--yes")
        self.assertIn("Learned from 1 recordings", out)

    def test_delete_unknown_person(self):
        code, out = self.run_cli("people", "--delete", "nobody")
        self.assertEqual(code, 1)

    def test_enroll_without_a_voice_environment_explains(self):
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        out = io.StringIO()
        with mock.patch.object(voice_cli, "_voice_python", return_value=None), \
                contextlib.redirect_stdout(out):
            code = voice_cli.main(
                ["enroll", "--yes"], voices_dir=self.voices,
                dirs=(self.output, self.meetings, self.archive),
            )
        self.assertEqual(code, 2)
        self.assertIn("set-python", out.getvalue())


class MeetingTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")
        self.run_name = "2026-10-20_1353_GroupCall102026"
        self.run_dir = self.output / self.run_name
        (self.run_dir / "audio").mkdir(parents=True)
        (self.run_dir / "audio" / "remote.wav").write_bytes(b"")
        self.payloads["remote.wav"] = payload(
            voice("SPEAKER_00", ALEX, 300),
            voice("SPEAKER_01", STRANGER, 120, seed=3),
        )

    def test_identify_show_and_confirm(self):
        code, out = self.run_cli("identify", self.run_name, "--expect", "Alex, Jordan")
        self.assertEqual(code, 0)
        self.assertIn("Alex  (matched)", out)
        self.assertIn("unknown", out)
        self.assertIn("may be Jordan", out)
        self.assertTrue((self.run_dir / "speakers.json").exists())

        code, out = self.run_cli("show", self.run_name)
        self.assertIn("may be Jordan", out)

        code, out = self.run_cli("confirm", self.run_name, "--accept-hint")
        self.assertEqual(code, 0)
        self.assertIn("Named voice 01 as Jordan and learned", out)
        self.assertIsNotNone(self.store().find("Jordan").centroid)

        code, out = self.run_cli("show", self.run_name)
        self.assertIn("Jordan  (confirmed by you)", out)
        self.assertNotIn("may be", out)

    def test_confirm_with_explicit_voice_and_name(self):
        self.run_cli("identify", self.run_name)
        code, out = self.run_cli("confirm", self.run_name, "Jordan", "--voice", "01")
        self.assertEqual(code, 0)
        self.assertEqual(self.store().find("Jordan").enrollments, 1)

    def test_confirm_errors(self):
        code, out = self.run_cli("confirm", self.run_name, "Jordan", "--voice", "01")
        self.assertEqual(code, 1)
        self.assertIn("identify", out)
        self.run_cli("identify", self.run_name)
        code, out = self.run_cli("confirm", self.run_name, "Jordan", "--voice", "99")
        self.assertEqual(code, 2)
        code, out = self.run_cli("confirm", self.run_name, "--accept-hint")
        self.assertEqual(code, 1)
        code, out = self.run_cli("confirm", self.run_name)
        self.assertEqual(code, 2)

    def test_identify_reports_missing_meeting_and_audio(self):
        code, out = self.run_cli("identify", "no-such-meeting")
        self.assertEqual(code, 2)
        empty = self.output / "2026-10-21_0900_Empty102126"
        empty.mkdir()
        code, out = self.run_cli("identify", empty.name)
        self.assertEqual(code, 2)
        self.assertIn("--audio", out)

    def test_silent_remote_is_explained(self):
        self.payloads["remote.wav"] = payload(silent=True)
        code, out = self.run_cli("identify", self.run_name)
        self.assertEqual(code, 0)
        self.assertIn("not captured", out)
        self.assertEqual(list((self.voices / "pending").glob("*")), [])

    def test_meeting_can_be_given_as_a_path(self):
        code, out = self.run_cli("identify", str(self.run_dir))
        self.assertEqual(code, 0)


class IdentifyAllTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")

    def make_run(self, name, result=None, root=None):
        folder = (root or self.output) / name
        (folder / "audio").mkdir(parents=True)
        if result is not None:
            (folder / "audio" / "remote.wav").write_bytes(b"")
            self.payloads["remote.wav"] = result
        return folder

    def test_processes_new_meetings_and_skips_finished_and_audioless(self):
        done = self.make_run("2026-10-01_0900_Done", payload(voice("SPEAKER_00", ALEX, 300)))
        vs.write_speakers(done, {"version": 1, "voices": []})
        self.make_run("2026-10-02_0900_NoAudio")
        fresh = self.make_run("2026-10-03_0900_Fresh", payload(
            voice("SPEAKER_00", ALEX, 300), voice("SPEAKER_01", STRANGER, 120, seed=3)))
        code, out = self.run_cli("identify-all")
        self.assertEqual(code, 0)
        self.assertIn("2 meetings to look at", out)
        self.assertIn("no audio, skipped", out)
        self.assertIn("2 voices, 1 named", out)
        self.assertIn("1 analyzed, 1 without audio, 0 failed", out)
        self.assertEqual(vs.read_speakers(fresh)["voices"][0]["person"], "Alex")
        self.assertEqual(vs.read_speakers(done)["voices"], [])

    def test_running_again_has_nothing_to_do(self):
        self.make_run("2026-10-03_0900_Fresh", payload(voice("SPEAKER_00", ALEX, 300)))
        self.run_cli("identify-all")
        code, out = self.run_cli("identify-all")
        self.assertIn("Nothing to do", out)

    def test_redo_and_limit(self):
        for day in ("01", "02", "03"):
            self.make_run(f"2026-10-{day}_0900_M{day}", payload(voice("SPEAKER_00", ALEX, 300)))
        code, out = self.run_cli("identify-all", "--limit", "2")
        self.assertIn("2 meetings to look at", out)
        self.assertIn("2026-10-03_0900_M03", out)
        self.assertNotIn("M01", out)
        code, out = self.run_cli("identify-all", "--redo", "--limit", "1")
        self.assertIn("1 meetings to look at", out)

    def test_silent_remote_is_recorded_so_it_is_not_retried(self):
        folder = self.make_run("2026-10-03_0900_Quiet", payload(silent=True))
        code, out = self.run_cli("identify-all")
        self.assertIn("remote not captured", out)
        self.assertTrue((folder / "speakers.json").exists())

    def test_failures_do_not_stop_the_run(self):
        self.make_run("2026-10-03_0900_Bad", payload())
        good = self.make_run("2026-10-02_0900_Good", payload(voice("SPEAKER_00", ALEX, 300)))
        # Both folders use the same file name, so tell them apart by folder.
        def by_folder(audio):
            if Path(audio).parent.parent.name.endswith("Bad"):
                raise vs.VoiceServiceError("boom")
            return self.payloads["remote.wav"]

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = voice_cli.main(
                ["identify-all"], worker=by_folder, voices_dir=self.voices,
                dirs=(self.output, self.meetings, self.archive),
            )
        self.assertEqual(code, 0)
        self.assertIn("failed (boom)", out.getvalue())
        self.assertIn("1 analyzed, 0 without audio, 1 failed", out.getvalue())
        self.assertTrue((good / "speakers.json").exists())

    def test_archive_meetings_are_included_once(self):
        archived = self.make_run(
            "2026-08-01_0900_Old", payload(voice("SPEAKER_00", ALEX, 300)), root=self.archive)
        code, out = self.run_cli("identify-all")
        self.assertIn("1 meetings to look at", out)
        self.assertTrue((archived / "speakers.json").exists())
        code, out = self.run_cli("identify-all", "--no-archive", "--redo")
        self.assertIn("Nothing to do", out)

    def test_meeting_whose_audio_is_only_in_the_archive_is_analyzed(self):
        run = self.make_run("2026-08-01_0900_Older")          # no local audio
        archived = self.archive / run.name / "source"
        archived.mkdir(parents=True)
        (archived / "Older.m4a").write_bytes(b"")
        self.payloads["Older.m4a"] = payload(voice("SPEAKER_00", ALEX, 300))
        code, out = self.run_cli("identify-all")
        self.assertIn("1 analyzed, 0 without audio", out)
        self.assertEqual(vs.read_speakers(run)["voices"][0]["person"], "Alex")

    def test_redo_keeps_names_the_user_confirmed(self):
        run = self.make_run("2026-10-03_0900_Fresh", payload(
            voice("SPEAKER_00", ALEX, 300), voice("SPEAKER_01", STRANGER, 120, seed=3)))
        self.run_cli("identify-all")
        self.run_cli("confirm", run.name, "Jordan", "--voice", "01")
        self.store_path = self.voices / "profiles.json"
        (self.voices / "profiles.json").unlink()          # even without the profile
        code, out = self.run_cli("identify-all", "--redo")
        self.assertEqual(code, 1)                          # no profiles: nothing runs
        self.run_cli("enroll", "--yes", "--no-archive")
        self.run_cli("identify-all", "--redo")
        document = vs.read_speakers(run)
        self.assertEqual(document["voices"][1]["person"], "Jordan")
        self.assertEqual(document["voices"][1]["via"], "user")

    def test_needs_profiles_first(self):
        fresh_voices = self.root / "empty"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = voice_cli.main(
                ["identify-all"], worker=self.worker, voices_dir=fresh_voices,
                dirs=(self.output, self.meetings, self.archive),
            )
        self.assertEqual(code, 1)
        self.assertIn("enroll", out.getvalue())


class ParticipantsNewTests(CliTestCase):
    def setUp(self):
        super().setUp()
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")
        self.name = "2026-10-01_0900_AlexSync100126"
        folder = self.output / self.name
        (folder / "audio").mkdir(parents=True)
        (folder / "audio" / "remote.wav").write_bytes(b"")
        self.result = payload(voice("SPEAKER_00", ALEX, 300, seed=7))
        self.write_metadata(folder, [{"name": "Mentioned", "confidence": "high"}])
        self.twin = self.archive / self.name
        self.twin.mkdir()
        self.write_metadata(self.twin, [{"name": "Mentioned", "confidence": "high"}])

    def worker(self, audio):
        named = self.payloads.get(Path(audio).name)
        return named or self.result

    def write_metadata(self, folder, participants):
        import json
        (folder / "meeting_metadata.json").write_text(
            json.dumps({"title": "t", "participants": participants}), encoding="utf-8")

    def names(self, folder):
        import json
        data = json.loads((folder / "meeting_metadata.json").read_text(encoding="utf-8"))
        return [p["name"] for p in data["participants"]]

    def test_dry_run_changes_nothing(self):
        self.run_cli("identify-all")
        code, out = self.run_cli("participants-new")
        self.assertEqual(code, 0)
        self.assertIn("Dry run", out)
        self.assertEqual(self.names(self.output / self.name), ["Mentioned"])
        self.assertEqual(self.names(self.twin), ["Mentioned"])

    def test_apply_updates_both_the_output_and_the_published_copy(self):
        self.run_cli("identify-all")
        code, out = self.run_cli("participants-new", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self.names(self.output / self.name), ["Alex"])
        self.assertEqual(self.names(self.twin), ["Alex"])

    def test_restore_puts_back_both(self):
        self.run_cli("identify-all")
        self.run_cli("participants-new", "--apply")
        code, out = self.run_cli("participants-new", "--restore")
        self.assertEqual(code, 0)
        self.assertEqual(self.names(self.output / self.name), ["Mentioned"])
        self.assertEqual(self.names(self.twin), ["Mentioned"])

    def test_meetings_without_voice_data_are_left_alone(self):
        code, out = self.run_cli("participants-new", "--apply")
        self.assertEqual(self.names(self.output / self.name), ["Mentioned"])

    def speaker_names(self, folder):
        import json
        data = json.loads((folder / "speakers.json").read_text(encoding="utf-8"))
        return [v["person"] for v in data["voices"]]

    def test_identify_all_also_updates_the_published_copy(self):
        self.run_cli("identify-all")
        self.assertEqual(self.speaker_names(self.twin), ["Alex"])

    def test_confirm_also_updates_the_published_copy(self):
        self.run_cli("identify-all")
        code, out = self.run_cli("confirm", self.name, "Sam", "--voice", "00")
        self.assertEqual(code, 0)
        self.assertEqual(self.speaker_names(self.output / self.name), ["Sam"])
        self.assertEqual(self.speaker_names(self.twin), ["Sam"])

    def test_identify_leaves_unpublished_meetings_without_a_copy(self):
        import shutil
        shutil.rmtree(self.twin)
        code, out = self.run_cli("identify", self.name)
        self.assertEqual(code, 0)
        self.assertFalse(self.twin.exists())


class UnknownsFixture(CliTestCase):
    """Three meetings share one unnamed voice; three others do not."""


    def setUp(self):
        super().setUp()
        self.by_folder = {}
        self.add_recording("Alex1v1092126.m4a", payload(voice("V0", ALEX, 900)))
        self.run_cli("enroll", "--yes")
        # Three meetings share one unnamed voice; three others do not.
        for day, title in (("01", "JordanSync"), ("02", "PlanJordan"), ("03", "JordanAndAlex")):
            self.add_meeting(f"2026-10-{day}_0900_{title}10{day}26", with_jordan=True, seed=int(day))
        for day, title in (("04", "BudgetPlan"), ("05", "TeamReview"), ("06", "Roadmap")):
            self.add_meeting(f"2026-10-{day}_0900_{title}10{day}26", with_jordan=False, seed=int(day))
        self.run_cli("identify-all")

    def worker(self, audio):
        named = self.payloads.get(Path(audio).name)
        return named or self.by_folder[Path(audio).parent.parent.name]

    def add_meeting(self, name, with_jordan, seed):
        folder = self.output / name
        (folder / "audio").mkdir(parents=True)
        (folder / "audio" / "remote.wav").write_bytes(b"")
        voices = [voice("SPEAKER_00", ALEX, 300, seed=seed)]
        if with_jordan:
            voices.append(voice("SPEAKER_01", STRANGER, 120, seed=seed + 50))
        self.by_folder[name] = payload(*voices)
        return folder


class UnknownsTests(UnknownsFixture):
    def test_lists_the_recurring_voice_with_title_hints(self):
        code, out = self.run_cli("unknowns")
        self.assertEqual(code, 0)
        self.assertIn("1 recurring unnamed voices", out)
        self.assertIn("Group 1: 3 meetings", out)
        self.assertIn("Jordan (3 of 3)", out)
        self.assertIn("--name 1 NAME", out)

    def test_a_voice_in_only_one_meeting_is_not_listed(self):
        self.add_meeting("2026-10-07_0900_OneOff100726", with_jordan=False, seed=7)
        self.by_folder["2026-10-07_0900_OneOff100726"]["voices"].append(
            voice("SPEAKER_01", unit(99), 120)
        )
        self.run_cli("identify-all")
        code, out = self.run_cli("unknowns")
        self.assertIn("1 recurring unnamed voices", out)

    def test_minimum_meetings_filter(self):
        code, out = self.run_cli("unknowns", "--min-meetings", "5")
        self.assertIn("No voice appears in 5 or more meetings", out)

    def test_naming_a_group_names_every_meeting_and_learns_the_person(self):
        code, out = self.run_cli("unknowns", "--name", "1", "Jordan")
        self.assertEqual(code, 0)
        self.assertIn("Named 3 voices in 3 meetings as Jordan", out)
        self.assertIn("Updated", out)
        self.assertEqual(self.store().find("Jordan").enrollments, 3)
        document = vs.read_speakers(self.output / "2026-10-02_0900_PlanJordan100226")
        self.assertEqual(document["voices"][1]["person"], "Jordan")

        code, out = self.run_cli("unknowns")
        self.assertIn("No unnamed voices to group", out)

    def test_declining_names_nobody(self):
        code, out = self.run_cli("unknowns", "--name", "1", "Jordan", answer="n")
        self.assertEqual(code, 1)
        self.assertIsNone(self.store().find("Jordan"))

    def test_bad_group_numbers_are_refused(self):
        for bad in ("0", "9", "x", "-1"):
            code, out = self.run_cli("unknowns", "--name", bad, "Jordan")
            self.assertEqual(code, 2, bad)
        self.assertIsNone(self.store().find("Jordan"))

    def test_nothing_analyzed_yet(self):
        empty = self.root / "empty_voices"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = voice_cli.main(
                ["unknowns"], worker=self.worker, voices_dir=empty,
                dirs=(self.root / "no_output", self.meetings, self.archive),
            )
        self.assertEqual(code, 0)
        self.assertIn("identify-all", out.getvalue())


class ReviewTests(UnknownsFixture):
    """The shared review logic that the app uses."""

    def groups(self):
        import voice_review
        runs, groups = voice_review.build_groups(
            self.output, self.archive, self.voices / "pending", self.store())
        return voice_review, runs, groups

    def test_group_has_a_stable_id_and_readable_facts(self):
        review, runs, groups = self.groups()
        self.assertEqual(len(groups), 1)
        info = review.describe_group(groups[0])
        self.assertEqual(info["meetings"], 3)
        self.assertEqual(info["hints"], ["Jordan"])
        self.assertEqual(len(info["id"]), 12)
        self.assertEqual(info["first"], "2026-10-01")
        self.assertEqual(info["last"], "2026-10-03")
        self.assertEqual(info["recent"][0], "JordanAndAlex1003" + "26")
        _, _, again = self.groups()
        self.assertEqual(review.group_id(again[0]), info["id"])

    def test_unknown_group_id_is_refused(self):
        review, runs, groups = self.groups()
        with self.assertRaises(review.ReviewError):
            review.find_group(groups, "nope")

    def test_clips_come_from_different_meetings_and_old_ones_are_removed(self):
        review, runs, groups = self.groups()
        clips_dir = self.root / "clips"
        clips_dir.mkdir()
        (clips_dir / "stale.wav").write_bytes(b"x")
        made = []

        def clipper(audio, start, length, out):
            made.append(out)
            Path(out).write_bytes(b"wav")

        clips = review.make_group_clips(
            groups[0], runs, self.meetings, self.archive, clips_dir,
            count=2, clipper=clipper)
        self.assertEqual(len(clips), 2)
        self.assertEqual(len({c["meeting"] for c in clips}), 2)
        self.assertFalse((clips_dir / "stale.wav").exists())
        self.assertTrue(all(Path(c["path"]).exists() for c in clips))

    def test_naming_a_group_names_all_and_mirrors(self):
        review, runs, groups = self.groups()
        store = self.store()
        result = review.name_group(
            groups[0], runs, "  Jordan  ", store, self.voices / "pending", self.archive)
        store.save(self.voices / "profiles.json")
        self.assertEqual(result["named"], 3)
        self.assertEqual(result["meetings"], 3)
        self.assertIsNotNone(self.store().find("Jordan"))

    def test_bad_names_are_refused(self):
        review, runs, groups = self.groups()
        for bad in ("", "   ", "x" * 61):
            with self.assertRaises(review.ReviewError):
                review.name_group(groups[0], runs, bad, self.store(),
                                  self.voices / "pending", self.archive)
        self.assertIsNone(self.store().find("Jordan"))


class ReviewBridgeTests(UnknownsFixture):
    """The three commands the app calls."""

    def setUp(self):
        super().setUp()
        import voice_service
        import backend_bridge
        self.bridge = backend_bridge
        store = self.store()
        self.context = (self.output, self.meetings, self.archive,
                        self.voices / "pending", store)
        patches = [
            mock.patch.object(backend_bridge, "_voice_review_context",
                              side_effect=lambda: self.context[:4] + (self.store(),)),
            mock.patch.object(voice_service, "STORE_PATH", self.voices / "profiles.json"),
            mock.patch("voice_review.CLIPS_DIR", self.root / "clips"),
            mock.patch("voice_review.STATE_PATH", self.root / "review_state.json"),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_groups_payload_lists_the_group_and_known_people(self):
        payload = self.bridge.voice_groups_payload()
        self.assertEqual(len(payload["groups"]), 1)
        self.assertEqual(payload["groups"][0]["hints"], ["Jordan"])
        self.assertEqual(payload["people"], ["Alex"])

    def test_naming_through_the_app_command(self):
        key = self.bridge.voice_groups_payload()["groups"][0]["id"]
        result = self.bridge.voice_name_group_payload(key, "Jordan")
        self.assertEqual(result["named"], 3)
        self.assertEqual(result["meetings"], 3)
        self.assertEqual(self.store().find("Jordan").enrollments, 3)
        self.assertEqual(self.bridge.voice_groups_payload()["groups"], [])

    def test_a_stale_group_id_is_refused_and_nothing_changes(self):
        with self.assertRaises(ValueError):
            self.bridge.voice_name_group_payload("stale", "Jordan")
        self.assertIsNone(self.store().find("Jordan"))

    def test_clips_command_passes_the_group_and_limits_the_count(self):
        import voice_review
        key = self.bridge.voice_groups_payload()["groups"][0]["id"]
        fake = [{"path": "/x/1.wav", "meeting": "A", "seconds": 10}]
        with mock.patch.object(voice_review, "make_group_clips",
                               return_value=fake) as made:
            payload = self.bridge.voice_group_clips_payload(key, 99)
        self.assertEqual(payload["clips"], fake)
        self.assertEqual(made.call_args.kwargs["count"], 6)
        self.assertEqual(len(made.call_args.args[0].members), 3)

    def first_group(self):
        return self.bridge.voice_groups_payload()["groups"][0]

    def test_groups_start_active(self):
        self.assertEqual(self.first_group()["status"], "active")

    def test_hide_ignore_and_restore(self):
        key = self.first_group()["id"]
        for action, expected in (("hide", "hidden"), ("ignore", "ignored"),
                                 ("restore", "active")):
            result = self.bridge.voice_group_state_payload(key, action)
            self.assertEqual(result["status"], expected)
            self.assertEqual(self.first_group()["status"], expected)
            self.assertEqual(self.first_group()["id"], key)

    def test_state_file_holds_no_fingerprints_and_is_private(self):
        import json, os, stat
        key = self.first_group()["id"]
        self.bridge.voice_group_state_payload(key, "ignore")
        path = self.root / "review_state.json"
        data = json.loads(path.read_text())
        self.assertEqual(set(data), {"version", "hidden", "ignored"})
        self.assertEqual(len(data["ignored"]), 3)
        self.assertTrue(all("|" in k for k in data["ignored"]))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_a_group_shows_again_when_it_gains_a_voice(self):
        import voice_review
        key = self.first_group()["id"]
        self.bridge.voice_group_state_payload(key, "hide")
        _runs, groups = voice_review.build_groups(
            self.output, self.archive, self.voices / "pending", self.store())
        state = voice_review.load_state()
        extra = {"x|9"}
        self.assertEqual(voice_review.group_status(groups[0], state), "hidden")
        state["hidden"] -= {sorted(voice_review.member_keys(groups[0]))[0]}
        self.assertEqual(voice_review.group_status(groups[0], state), "active")
        self.assertTrue(extra.isdisjoint(state["hidden"]))

    def test_unknown_action_and_stale_group_are_refused(self):
        key = self.first_group()["id"]
        with self.assertRaises(ValueError):
            self.bridge.voice_group_state_payload(key, "delete")
        with self.assertRaises(ValueError):
            self.bridge.voice_group_state_payload("stale", "hide")

    def test_a_damaged_state_file_is_treated_as_empty(self):
        (self.root / "review_state.json").write_text("{not json")
        self.assertEqual(self.first_group()["status"], "active")

    def test_clips_clear_removes_only_wav_files(self):
        clips = self.root / "clips"
        clips.mkdir()
        (clips / "a_1.wav").write_bytes(b"x")
        (clips / "a_2.wav").write_bytes(b"x")
        (clips / "keep.txt").write_text("x")
        self.assertEqual(self.bridge.voice_clips_clear_payload()["removed"], 2)
        self.assertEqual([p.name for p in clips.iterdir()], ["keep.txt"])
        self.assertEqual(self.bridge.voice_clips_clear_payload()["removed"], 0)

    def test_naming_reports_the_quick_recheck(self):
        key = self.first_group()["id"]
        result = self.bridge.voice_name_group_payload(key, "Jordan")
        self.assertIn("summary", result["rematch"])

    RUN = "2026-10-01_0900_JordanSync100126"

    def voice_of(self, run, voice_id):
        import voice_service
        document = voice_service.read_speakers(self.output / run)
        return next(v for v in document["voices"] if v["id"] == voice_id)

    def test_meeting_voices_lists_each_voice(self):
        payload = self.bridge.voice_meeting_payload(self.RUN)
        by_id = {v["id"]: v for v in payload["voices"]}
        self.assertEqual(by_id["SPEAKER_00"]["person"], "Alex")
        self.assertEqual(by_id["SPEAKER_01"]["status"], "unknown")
        self.assertFalse(by_id["SPEAKER_01"]["short"])
        self.assertTrue(by_id["SPEAKER_01"]["can_learn"])
        self.assertEqual(payload["voices"][0]["id"], "SPEAKER_00")
        self.assertEqual(payload["people"], ["Alex"])

    def test_a_path_is_not_a_meeting(self):
        for bad in ("../x", "a/b", "", ".."):
            with self.assertRaises(ValueError):
                self.bridge.voice_meeting_payload(bad)

    def test_naming_one_voice_names_it_and_rechecks_other_meetings(self):
        import voice_review
        with mock.patch.object(voice_review, "_participants_setting",
                               return_value=False):
            result = self.bridge.voice_meeting_name_payload(
                self.RUN, "SPEAKER_01", "Jordan")
        self.assertEqual(result["named"], 1)
        self.assertEqual(self.voice_of(self.RUN, "SPEAKER_01")["person"], "Jordan")
        self.assertEqual(self.voice_of(self.RUN, "SPEAKER_01")["via"], "user")
        self.assertIn("summary", result["rematch"])
        # The same voice in another meeting is now recognized.
        other = "2026-10-02_0900_PlanJordan100226"
        self.assertEqual(self.voice_of(other, "SPEAKER_01")["person"], "Jordan")

    def test_naming_needs_a_name_and_a_real_voice(self):
        with self.assertRaises(ValueError):
            self.bridge.voice_meeting_name_payload(self.RUN, "SPEAKER_01", "  ")
        with self.assertRaises(ValueError):
            self.bridge.voice_meeting_name_payload(self.RUN, "SPEAKER_77", "Jordan")
        self.assertEqual(self.voice_of(self.RUN, "SPEAKER_01")["status"], "unknown")

    def test_meeting_clips_come_from_that_voice_only(self):
        import voice_review
        made = []

        def fake_clipper(audio, start, length, out):
            made.append((start, length))
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"x")

        with mock.patch.object(voice_review.voice_sources, "make_clip",
                               fake_clipper), \
             mock.patch.object(voice_review, "make_voice_clips",
                               wraps=voice_review.make_voice_clips):
            folder = self.output / self.RUN
            clips = voice_review.make_voice_clips(
                folder, "SPEAKER_01", self.meetings, self.archive,
                self.root / "clips", clipper=fake_clipper)
        self.assertTrue(clips)
        self.assertTrue(all(c["meeting"].startswith("at ") for c in clips))
        self.assertTrue(all(Path(c["path"]).exists() for c in clips))
        with self.assertRaises(voice_review.ReviewError):
            voice_review.make_voice_clips(
                folder, "SPEAKER_77", self.meetings, self.archive,
                self.root / "clips", clipper=fake_clipper)

    def test_naming_in_the_app_rebuilds_the_published_index(self):
        import voice_review
        with mock.patch.object(voice_review, "_participants_setting",
                               return_value=True), \
             mock.patch.object(voice_review, "refresh_index",
                               return_value=True) as refreshed:
            result = self.bridge.voice_meeting_name_payload(
                self.RUN, "SPEAKER_01", "Jordan")
        refreshed.assert_called_once()
        self.assertTrue(result["rematch"]["index_refreshed"])

    def test_the_index_is_left_alone_when_participants_are_not_managed(self):
        import voice_review
        with mock.patch.object(voice_review, "_participants_setting",
                               return_value=False), \
             mock.patch.object(voice_review, "refresh_index") as refreshed:
            self.bridge.voice_meeting_name_payload(
                self.RUN, "SPEAKER_01", "Jordan")
        refreshed.assert_not_called()

    def test_refresh_index_never_raises(self):
        import voice_review
        self.assertFalse(voice_review.refresh_index(self.root / "nowhere"))

    def test_recent_meetings_lists_newest_first_with_counts(self):
        meetings = self.bridge.voice_recent_meetings_payload()["meetings"]
        self.assertEqual(meetings[0]["run"], "2026-10-06_0900_Roadmap100626")
        sync = next(m for m in meetings if m["run"] == self.RUN)
        self.assertEqual((sync["voices"], sync["unnamed"]), (2, 1))

    def test_clips_command_refuses_a_stale_group(self):
        with self.assertRaises(ValueError):
            self.bridge.voice_group_clips_payload("stale")


class SetPythonTests(CliTestCase):
    def test_missing_path_is_refused(self):
        code, out = self.run_cli("set-python", "/no/such/python")
        self.assertEqual(code, 2)

    def test_saves_the_path(self):
        fake = self.root / "python"
        fake.write_text("")
        with mock.patch("app_settings.update_app_setting") as save:
            code, out = self.run_cli("set-python", str(fake))
        self.assertEqual(code, 0)
        save.assert_called_once_with("voice_python", str(fake))


if __name__ == "__main__":
    unittest.main()
