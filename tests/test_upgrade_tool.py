import contextlib, io, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "maintenance"))
import upgrade_tool as u

SAMPLE = """
case-a: PASS (95.2s)
  commitments    P=0.80 R=0.90 matched=9/10 predicted=11
  risks          P=0.50 R=0.50 matched=1/2 predicted=2
  Trace: x
zip: FAIL (50.0s)
  commitments    P=0.10 R=0.10 matched=1/10 predicted=5
  FAIL: something
"""


class UpgradeToolTests(unittest.TestCase):
    def test_parse_and_compare(self):
        a = u.parse_benchmark_output(SAMPLE)
        self.assertTrue(a["case-a"]["passed"])
        self.assertEqual(a["case-a"]["categories"]["commitments"], (9, 10, 11))
        self.assertFalse(a["zip"]["passed"])
        b = u.parse_benchmark_output(SAMPLE.replace("case-a: PASS", "case-a: FAIL").replace("matched=9/10", "matched=7/10"))
        lines = u.compare_benchmarks(a, b)
        self.assertTrue(any("PASS -> FAIL" in l for l in lines))
        self.assertTrue(any("matched 9 -> 7" in l for l in lines))
        self.assertEqual(u.compare_benchmarks(a, a), [])

    def test_unittest_summary_and_hints(self):
        self.assertEqual(u.parse_unittest_summary("Ran 726 tests in 3s\n\nOK\n"), (726, True, []))
        self.assertEqual(u.parse_unittest_summary("FAIL: test_x (a.B)\nRan 3 tests\nFAILED (failures=1)"),
                         (3, False, ["test_x"]))
        self.assertIn("mlx-lm==0.31.3", u.rollback_hint("mlx-lm", "pip", "0.31.3"))

    def test_menu_text(self):
        rows = u.menu_rows(["mlx-lm", "ffmpeg", "ollama"],
                           {"mlx-lm": "0.31.3", "ffmpeg": "8.1", "ollama": None},
                           {"mlx-lm": "0.32.0"})
        text = u.format_menu(rows)
        self.assertIn("1) mlx-lm", text)
        self.assertIn("0.31.3 -> 0.32.0  UPDATE AVAILABLE", text)
        self.assertIn("8.1  up to date", text)
        self.assertIn("not installed", text)

    def test_default_cases_from_file_then_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "root" / "x").mkdir(parents=True)
            (d / "root" / "x" / "expected_memory.json").write_text("{}")
            (d / "root" / "nokey").mkdir()
            self.assertEqual(u.default_cases(d / "missing.txt", d / "root"), ["x"])
            (d / "list.txt").write_text("# note\nfirst\n\nsecond\n")
            self.assertEqual(u.default_cases(d / "list.txt", d / "root"), ["first", "second"])

    def test_audio_contract_parsing_and_latest_file(self):
        import json, os, tempfile
        good = json.dumps({"extraction_ok": True, "compatible": True, "message": "Compatible"})
        self.assertEqual(u.parse_audio_contract(good), (True, "Compatible"))
        bad = json.dumps({"extraction_ok": True, "compatible": False, "message": "Wrong layout"})
        self.assertEqual(u.parse_audio_contract(bad), (False, "Wrong layout"))
        self.assertFalse(u.parse_audio_contract("not json")[0])
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            self.assertIsNone(u.latest_recording(d))
            (d / "old.m4a").write_text("a")
            (d / "new.m4a").write_text("b")
            os.utime(d / "old.m4a", (1, 1))
            self.assertEqual(u.latest_recording(d).name, "new.m4a")


class VoiceCheckTests(unittest.TestCase):
    def test_off_means_nothing_to_check(self):
        self.assertIsNone(u.voice_check({"voice_recognition_enabled": False})[0])

    def test_on_without_an_environment_is_a_problem(self):
        self.assertFalse(u.voice_check({"voice_recognition_enabled": True, "voice_python": ""})[0])

    def test_on_with_a_missing_python_is_a_problem(self):
        ok, detail = u.voice_check({"voice_recognition_enabled": True,
                                    "voice_python": "/no/such/venv/bin/python"})
        self.assertFalse(ok)
        self.assertIn("does not exist", detail)

    def test_a_working_environment_passes(self):
        calls = []

        def runner(cmd, timeout=None, stdout_only=False):
            calls.append(cmd)
            return 0, "ok\n"

        ok, _detail = u.voice_check({"voice_recognition_enabled": True,
                                     "voice_python": sys.executable}, runner)
        self.assertTrue(ok)
        self.assertEqual(calls[0][0], sys.executable)

    def test_missing_packages_are_named(self):
        ok, detail = u.parse_voice_check("missing: torch, numpy\n")
        self.assertFalse(ok)
        self.assertIn("torch, numpy", detail)
        self.assertFalse(u.parse_voice_check("")[0])


class ModelCheckTests(unittest.TestCase):
    def test_parse_model_check(self):
        self.assertEqual(u.parse_model_check('noise\n{"text": "PINEAPPLE", "seconds": 4.2}\n'),
                         (True, "answered in 4.2s"))
        self.assertFalse(u.parse_model_check('{"text": "banana", "seconds": 1}')[0])
        self.assertFalse(u.parse_model_check("")[0])
        self.assertFalse(u.parse_model_check("not json")[0])


class TestEnvironmentTests(unittest.TestCase):
    def test_unit_tests_run_with_named_transcripts_forced_off(self):
        from unittest import mock
        calls = []

        def fake_run(cmd, timeout=None, stdout_only=False, env=None):
            calls.append((cmd, env))
            return 0, "Ran 1 tests in 0s\n\nOK\n"

        name = next(iter(u.COMPONENTS))
        with mock.patch.object(u, "_run", fake_run), mock.patch.dict(
                "os.environ", {"MT_NAMED_TRANSCRIPT": "1"}):
            with contextlib.redirect_stdout(io.StringIO()):
                u.run_checks(name, {})
        unit = [env for cmd, env in calls if "unittest" in cmd]
        self.assertEqual(unit[0]["MT_NAMED_TRANSCRIPT"], "0")


if __name__ == "__main__":
    unittest.main()
