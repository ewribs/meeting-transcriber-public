import sys, unittest
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


if __name__ == "__main__":
    unittest.main()
