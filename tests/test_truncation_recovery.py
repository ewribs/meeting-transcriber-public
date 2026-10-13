import json
import unittest
from unittest import mock

import ai

EMPTY = json.dumps({"commitments": [], "decisions": [], "risks": [],
                    "open_questions": [], "follow_ups": []})


def _block(n):
    return f"[00:{n:02d}] **Remote**\n\n" + " ".join(f"word{n}x{i}" for i in range(120))


class TruncationRecoveryTests(unittest.TestCase):
    def test_split_helper(self):
        chunk = "\n\n".join(_block(i) for i in range(8))
        parts = ai._split_chunk_for_retry(chunk)
        self.assertEqual(len(parts), 2)
        self.assertEqual("\n\n".join(parts), chunk)
        self.assertEqual(ai._split_chunk_for_retry("short text"), [])

    def test_oversized_section_is_split_and_run_continues(self):
        transcript = "\n\n".join(_block(i) for i in range(8))
        calls = []

        def fake_ask(prompt, response_format=None, **kw):
            calls.append(len(prompt))
            if len(calls) == 1:
                raise RuntimeError("MLX response appears truncated at the generation token ceiling.")
            return EMPTY

        with mock.patch.object(ai, "ask_llm", side_effect=fake_ask):
            ai.extract_grounded_commitments_and_decisions(
                meeting_label="Test", transcript=transcript, participants=[], chunk_words=5000)
        self.assertEqual(len(calls), 3)  # whole chunk failed, then two halves

    def test_unsplittable_section_is_skipped_not_fatal(self):
        def fake_ask(prompt, response_format=None, **kw):
            raise RuntimeError("MLX response appears truncated at the generation token ceiling.")

        with mock.patch.object(ai, "ask_llm", side_effect=fake_ask):
            ai.extract_grounded_commitments_and_decisions(
                meeting_label="Test", transcript="[00:00] **Remote**\n\nshort", participants=[])

    def test_other_errors_still_raise(self):
        with mock.patch.object(ai, "ask_llm", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ai.extract_grounded_commitments_and_decisions(
                    meeting_label="Test", transcript="[00:00] **Remote**\n\nshort", participants=[])


if __name__ == "__main__":
    unittest.main()
