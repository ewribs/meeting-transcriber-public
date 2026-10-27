import tempfile
import unittest
from pathlib import Path

import ai
from tools.refactor import llm_replay as lr
from tools.refactor import memory_golden as mg


class FakeReal:
    def __init__(self):
        self.calls = 0

    def __call__(self, prompt, response_format=None, *, timeout_seconds=None):
        self.calls += 1
        return f"answer to {prompt}"


class ReplayTests(unittest.TestCase):
    def test_record_then_replay_returns_the_same_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            real = FakeReal()
            recorder = lr.Replayer(lr.Recording(path), "record", real=real)
            self.assertEqual(recorder("one"), "answer to one")
            self.assertEqual(recorder("one"), "answer to one")      # not asked twice
            self.assertEqual(real.calls, 1)
            replayer = lr.Replayer(lr.Recording(path).load(), "replay")
            self.assertEqual(replayer("one"), "answer to one")

    def test_replay_stops_on_a_prompt_that_was_never_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            replayer = lr.Replayer(lr.Recording(Path(tmp) / "r.json"), "replay")
            with self.assertRaises(lr.MissingRecording):
                replayer("new prompt")

    def test_the_answer_format_is_part_of_the_key(self):
        self.assertNotEqual(lr.prompt_key("p", {"a": 1}), lr.prompt_key("p", {"a": 2}))
        self.assertEqual(lr.prompt_key("p", {"b": 1, "a": 2}), lr.prompt_key("p", {"a": 2, "b": 1}))

    def test_record_needs_the_real_function(self):
        with self.assertRaises(ValueError):
            lr.Replayer(lr.Recording(Path("x")), "record")

    def test_installed_swaps_and_restores_ask_llm(self):
        original = ai.ask_llm
        with tempfile.TemporaryDirectory() as tmp:
            with lr.installed(Path(tmp) / "r.json", "replay") as replayer:
                self.assertIs(ai.ask_llm, replayer)
            self.assertIs(ai.ask_llm, original)

    def test_installed_restores_even_after_an_error(self):
        original = ai.ask_llm
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                with lr.installed(Path(tmp) / "r.json", "replay"):
                    raise RuntimeError("boom")
        self.assertIs(ai.ask_llm, original)


class DiffTests(unittest.TestCase):
    def test_equal_results_have_no_differences(self):
        self.assertEqual(mg.diff_text({"a": [1, 2]}, {"a": [1, 2]}), [])

    def test_changes_are_shown(self):
        lines = mg.diff_text({"a": [1]}, {"a": [2]})
        self.assertTrue(any(line.startswith("-") and "1" in line for line in lines))
        self.assertTrue(any(line.startswith("+") and "2" in line for line in lines))

    def test_long_differences_are_cut(self):
        lines = mg.diff_text({"a": list(range(300))}, {"a": list(range(1, 301))}, limit=10)
        self.assertEqual(len(lines), 11)
        self.assertIn("more lines", lines[-1])


class EnvironmentTests(unittest.TestCase):
    def test_unstamped_recording_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            problem = mg.environment_problem("run", Path(tmp))
            self.assertIn("stamp", problem)

    def test_same_environment_is_accepted_and_a_different_one_is_not(self):
        original = mg.environment
        try:
            mg.environment = lambda: {"backend": "mlx", "profile": "High"}
            with tempfile.TemporaryDirectory() as tmp:
                mg.stamp("run", Path(tmp))
                self.assertIsNone(mg.environment_problem("run", Path(tmp)))
                mg.environment = lambda: {"backend": "ollama", "profile": "High"}
                problem = mg.environment_problem("run", Path(tmp))
                self.assertIn("backend", problem)
                self.assertIn("not be comparable", problem)
        finally:
            mg.environment = original

    def test_compare_refuses_when_the_environment_differs(self):
        original = mg.environment
        try:
            with tempfile.TemporaryDirectory() as tmp:
                store = Path(tmp) / "store"
                store.mkdir()
                run = Path(tmp) / "2026-01-01_0900_Sync"
                run.mkdir()
                (store / f"{run.name}.memory.json").write_text("{}", encoding="utf-8")
                (store / f"{run.name}.replay.json").write_text("{}", encoding="utf-8")
                mg.environment = lambda: {"backend": "mlx"}
                mg.stamp(run.name, store)
                mg.environment = lambda: {"backend": "ollama"}
                with self.assertRaises(mg.GoldenError):
                    mg.compare(run, store)
        finally:
            mg.environment = original


class MissingInputsTests(unittest.TestCase):
    def test_compare_without_a_recording_explains_what_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "2026-01-01_0900_Sync"
            run.mkdir()
            with self.assertRaises(mg.GoldenError) as caught:
                mg.compare(run, Path(tmp) / "store")
            self.assertIn("record", str(caught.exception))

    def test_build_needs_a_cleaned_transcript_and_a_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "2026-01-01_0900_Sync"
            run.mkdir()
            with self.assertRaises(mg.GoldenError):
                mg.build_memory(run, Path(tmp) / "scratch")


if __name__ == "__main__":
    unittest.main()
