"""Regression coverage for private memory benchmark production-entrypoint parity.

All AI execution is mocked; fixtures contain synthetic data only.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.benchmark import memory_benchmark as benchmark


class MemoryBenchmarkProductionParityTests(unittest.TestCase):
    RUN_NAME = "2026-10-10_1135_AlexA1v1100726"
    SUMMARY = "Synthetic meeting summary."
    TRANSCRIPT = "[00:01] **Mic**\nI'll review.\n[00:02] **Remote**\nI'll follow up."
    PARTICIPANTS = [{"name": "Alex A", "speaker": "Remote"}]
    MEMORY = {
        "topics": [], "commitments": [], "decisions": [],
        "risks": [], "open_questions": [], "follow_ups": [],
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.case = self.root / "cases" / "synthetic-one-on-one"
        self.case.mkdir(parents=True)
        self.run_root = self.root / "runs"
        self.metadata = {
            "meeting_run": self.RUN_NAME,
            "display_title": "Alex A 1v1",
            "participants": self.PARTICIPANTS,
        }
        (self.case / "meeting_metadata.json").write_text(json.dumps(self.metadata))
        (self.case / "meeting_summary.md").write_text(self.SUMMARY)
        (self.case / "meeting_transcript_cleaned.md").write_text(self.TRANSCRIPT)
        (self.case / "expected_memory.json").write_text(json.dumps({
            "expected": {category: [] for category in benchmark.CATEGORY_CONFIG},
            "forbidden": {"owners": ["Remote", "Mic"]},
        }))
        self.source_before = {
            p.name: p.read_bytes() for p in self.case.iterdir()
        }

    def _mock_ai(self):
        return (
            patch("ai.set_memory_resolution_trace_enabled"),
            patch("ai.get_last_memory_resolution_diagnostics", return_value={"status": "verified"}),
            patch("ai.get_last_memory_resolution_trace", return_value={}),
        )

    def _assert_common_results(self, result, expected_mode):
        self.assertEqual(result["execution_mode"], expected_mode)
        self.assertEqual(result["meeting_label"], "Alex A 1v1")
        self.assertTrue(result["score"]["passed"])
        output = Path(result["output_dir"])
        for filename in (
            "actual_memory.json", "memory_trace.json", "processing_diagnostics.json",
            "benchmark_result.json", "benchmark_report.md",
        ):
            self.assertTrue((output / filename).exists(), filename)
        self.assertEqual(json.loads((output / "actual_memory.json").read_text()), self.MEMORY)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.case.iterdir()}, self.source_before
        )
        self.assertFalse((self.case / "meeting_memory.json").exists())

    def test_production_parity_calls_real_entrypoint_with_original_run_id_and_inputs(self):
        def fake_production(*, run_dir, meeting_summary, cleaned_transcript, participants):
            self.assertEqual(run_dir.name, self.RUN_NAME)
            self.assertEqual(run_dir.parent.name, "production_replay")
            self.assertTrue(run_dir.is_relative_to(self.run_root))
            self.assertEqual(meeting_summary, self.SUMMARY)
            self.assertEqual(cleaned_transcript, self.TRANSCRIPT)
            self.assertEqual(participants, self.PARTICIPANTS)
            self.assertFalse(run_dir.is_relative_to(self.case))
            memory_path = run_dir / "meeting_memory.json"
            memory_path.write_text(json.dumps(self.MEMORY))
            return memory_path

        mocks = self._mock_ai()
        with mocks[0], mocks[1], mocks[2], \
             patch("pipeline.run_meeting_memory", side_effect=fake_production) as production, \
             patch("ai.build_complete_meeting_memory") as direct:
            result = benchmark.run_case(self.case, self.run_root, production_parity=True)
        production.assert_called_once()
        direct.assert_not_called()
        self._assert_common_results(result, "production_memory_entrypoint")

    def test_direct_mode_remains_independent_and_uses_same_case_inputs(self):
        mocks = self._mock_ai()
        with mocks[0], mocks[1], mocks[2], \
             patch("ai.build_complete_meeting_memory", return_value=self.MEMORY) as direct, \
             patch("pipeline.run_meeting_memory") as production:
            result = benchmark.run_case(self.case, self.run_root, production_parity=False)
        direct.assert_called_once_with(
            meeting_label="Alex A 1v1", meeting_summary=self.SUMMARY,
            transcript=self.TRANSCRIPT, participants=self.PARTICIPANTS,
        )
        production.assert_not_called()
        self._assert_common_results(result, "direct_ai")

    def test_invalid_production_run_id_never_invokes_pipeline(self):
        metadata_path = self.case / "meeting_metadata.json"
        metadata = dict(self.metadata, meeting_run="../unsafe")
        metadata_path.write_text(json.dumps(metadata))
        with patch("ai.set_memory_resolution_trace_enabled"), \
             patch("pipeline.run_meeting_memory") as production:
            with self.assertRaisesRegex(ValueError, "safe meeting_run"):
                benchmark.run_case(self.case, self.run_root, production_parity=True)
        production.assert_not_called()


if __name__ == "__main__":
    unittest.main()
