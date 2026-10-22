import tempfile
import unittest
from pathlib import Path

import voice_auto
import voice_service as vs
from tests.test_voice_service import (
    PERSON_A, STRANGER, payload, voice_json, store_with_a_and_b,
)


class RunVoiceStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.run_dir = root / "2026-01-01_1000_Meeting"
        self.run_dir.mkdir()
        self.audio = root / "Meeting.m4a"
        self.audio.write_bytes(b"x")
        self.store_path = root / "profiles.json"
        self.pending = root / "pending"
        self.log_path = root / "auto.log"
        store_with_a_and_b().save(self.store_path)
        self.settings = {"voice_recognition_enabled": True, "voice_python": "py"}

    def tearDown(self):
        self.tmp.cleanup()

    def step(self, settings=None, audio="default", analyzer=None):
        return voice_auto.run_voice_step(
            self.run_dir,
            self.audio if audio == "default" else audio,
            self.settings if settings is None else settings,
            store_path=self.store_path,
            pending_dir=self.pending,
            log_path=self.log_path,
            analyzer=analyzer,
        )

    def good(self, audio):
        return payload(voice_json("V0", PERSON_A, 300),
                       voice_json("V1", STRANGER, 120, seed=3))

    def test_outcomes_are_logged_but_off_is_not(self):
        self.step({}, analyzer=self.good)
        self.assertFalse(self.log_path.exists())
        self.step(analyzer=self.good)
        self.step(audio=None, analyzer=self.good)
        lines = voice_auto.recent_log(5, self.log_path)
        self.assertEqual(len(lines), 2)
        self.assertIn(self.run_dir.name, lines[0])
        self.assertIn("done:", lines[0])
        self.assertTrue(lines[1].endswith("no audio"))

    def test_log_keeps_only_recent_lines(self):
        for i in range(voice_auto.LOG_KEEP_LINES + 20):
            voice_auto.log_status(f"run{i}", "done", self.log_path)
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), voice_auto.LOG_KEEP_LINES)
        self.assertIn(f"run{voice_auto.LOG_KEEP_LINES + 19}", lines[-1])

    def test_log_problems_never_raise(self):
        voice_auto.log_status("run", "done", self.run_dir)  # a folder, not a file
        self.assertEqual(voice_auto.recent_log(3, self.tmp.name + "/missing"), [])

    def test_off_by_default_does_nothing(self):
        called = []
        status = self.step({}, analyzer=lambda a: called.append(a))
        self.assertEqual(status, "off")
        self.assertEqual(called, [])
        self.assertIsNone(vs.read_speakers(self.run_dir))

    def test_writes_speakers_and_reports_counts(self):
        status = self.step(analyzer=self.good)
        self.assertTrue(status.startswith("done: 1 of 2 voices named"))
        document = vs.read_speakers(self.run_dir)
        self.assertEqual(document["voices"][0]["person"], "Person A")
        self.assertTrue((self.pending / (self.run_dir.name + ".json")).exists()
                        or any(self.pending.iterdir()))

    def test_missing_audio(self):
        self.assertEqual(self.step(audio=None, analyzer=self.good), "no audio")
        self.assertEqual(
            self.step(audio=Path("/nonexistent.m4a"), analyzer=self.good), "no audio")

    def test_not_set_up_without_python(self):
        self.assertEqual(self.step({"voice_recognition_enabled": True}), "not set up")

    def test_no_profiles_yet(self):
        self.store_path.unlink()
        self.assertEqual(self.step(analyzer=self.good), "no profiles yet")

    def test_failure_never_raises(self):
        def boom(audio):
            raise vs.VoiceServiceError("worker crashed")
        status = self.step(analyzer=boom)
        self.assertTrue(status.startswith("skipped:"))
        self.assertIn("worker crashed", status)

    def test_unexpected_error_never_raises(self):
        def boom(audio):
            raise RuntimeError("anything")
        self.assertTrue(self.step(analyzer=boom).startswith("skipped:"))

    def test_corrupt_profiles_never_raise(self):
        self.store_path.write_text("not json", encoding="utf-8")
        self.assertTrue(self.step(analyzer=self.good).startswith("skipped:"))

    def test_silent_remote_is_reported(self):
        silent = lambda a: payload(silent=True)
        self.assertEqual(self.step(analyzer=silent),
                         "done: remote audio was not captured")
        self.assertFalse(self.pending.exists() and any(self.pending.iterdir()))

    def write_metadata(self, folder, names):
        import json
        (folder / "meeting_metadata.json").write_text(json.dumps({
            "title": "t",
            "participants": [{"name": n, "confidence": "high"} for n in names],
        }), encoding="utf-8")

    def read_names(self, folder):
        import json
        data = json.loads((folder / "meeting_metadata.json").read_text(encoding="utf-8"))
        return [p["name"] for p in data["participants"]]

    def test_participants_follow_the_voices(self):
        self.write_metadata(self.run_dir, ["Mentioned"])
        twin = self.run_dir.parent / "archive" / self.run_dir.name
        twin.mkdir(parents=True)
        self.write_metadata(twin, ["Mentioned"])
        status = voice_auto.run_voice_step(
            self.run_dir, self.audio, self.settings,
            store_path=self.store_path, pending_dir=self.pending,
            log_path=self.log_path, archive_dir=twin.parent, analyzer=self.good)
        self.assertIn("participants updated", status)
        self.assertEqual(self.read_names(self.run_dir), ["Person A"])
        self.assertEqual(self.read_names(twin), ["Person A"])

    def test_participants_can_be_left_alone(self):
        self.write_metadata(self.run_dir, ["Mentioned"])
        settings = dict(self.settings, voice_update_participants=False)
        status = self.step(settings=settings, analyzer=self.good)
        self.assertNotIn("participants", status)
        self.assertEqual(self.read_names(self.run_dir), ["Mentioned"])

    def test_missing_metadata_does_not_break_the_step(self):
        status = self.step(analyzer=self.good)
        self.assertTrue(status.startswith("done:"))
        self.assertIn("participants not updated", status)

    def test_silent_remote_keeps_the_old_participants(self):
        self.write_metadata(self.run_dir, ["Mentioned"])
        self.step(analyzer=lambda a: payload(silent=True))
        self.assertEqual(self.read_names(self.run_dir), ["Mentioned"])

    def test_user_confirmations_survive(self):
        self.step(analyzer=self.good)
        document = vs.read_speakers(self.run_dir)
        document["voices"][1].update(
            {"status": "named", "via": "user",
             "person_id": "person-z", "person": "Person Z"})
        vs.write_speakers(self.run_dir, document)
        self.step(analyzer=self.good)
        self.assertEqual(vs.read_speakers(self.run_dir)["voices"][1]["person"],
                         "Person Z")


class AutoCommandTests(unittest.TestCase):
    def setUp(self):
        import app_settings
        self.app_settings = app_settings
        self.tmp = tempfile.TemporaryDirectory()
        self.old = app_settings.SETTINGS_PATH
        app_settings.SETTINGS_PATH = Path(self.tmp.name) / "settings.json"
        self.voices = Path(self.tmp.name) / "voices"
        self.voices.mkdir()

    def tearDown(self):
        self.app_settings.SETTINGS_PATH = self.old
        self.tmp.cleanup()

    def run_cli(self, *args):
        import io
        from contextlib import redirect_stdout
        import voice_cli
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = voice_cli.main(list(args), voices_dir=self.voices)
        return code, buffer.getvalue()

    def test_status_shows_recent_runs(self):
        voice_auto.log_status("run-one", "done: 2 of 3 voices named",
                              self.voices / "auto.log")
        code, out = self.run_cli("auto")
        self.assertIn("run-one", out)
        self.assertIn("Most recent runs", out)

    def test_status_defaults_to_off(self):
        code, out = self.run_cli("auto")
        self.assertEqual(code, 0)
        self.assertIn("off", out)

    def test_on_needs_python_and_profiles(self):
        code, out = self.run_cli("auto", "on")
        self.assertEqual(code, 2)
        self.assertIn("set-python", out)
        self.app_settings.update_app_setting("voice_python", "/bin/python3")
        code, out = self.run_cli("auto", "on")
        self.assertEqual(code, 2)
        self.assertIn("No voice profiles", out)

    def test_on_then_off(self):
        self.app_settings.update_app_setting("voice_python", "/bin/python3")
        store_with_a_and_b().save(self.voices / "profiles.json")
        code, out = self.run_cli("auto", "on")
        self.assertEqual(code, 0)
        self.assertIn("ON", out)
        self.assertTrue(self.app_settings.load_app_settings()["voice_recognition_enabled"])
        code, out = self.run_cli("auto", "off")
        self.assertIn("off", out)
        self.assertFalse(self.app_settings.load_app_settings()["voice_recognition_enabled"])


if __name__ == "__main__":
    unittest.main()
