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


class UnknownsTests(CliTestCase):
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
        self.assertIn("identify-all --redo", out)
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
