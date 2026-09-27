import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ai
from meeting_detail_service import load_meeting_detail
from metadata import create_meeting_metadata


class TranscribeSummaryPlanningTests(unittest.TestCase):
    def _profile(self, budget: int):
        return SimpleNamespace(
            name="Auto",
            resolved_name="High Performance",
            direct_token_budget=budget,
            chunk_source_token_budget=7000,
            chunk_overlap_tokens=512,
            llm_call_timeout_seconds=150,
            context_size_tokens=40960,
        )

    def test_short_transcript_uses_direct(self):
        with patch(
            "ai.get_execution_profile",
            return_value=self._profile(32000),
        ):
            plan = ai.plan_meeting_summary_execution(
                "A normal meeting transcript. " * 100
            )

        self.assertEqual(plan["mode"], "direct")
        self.assertLessEqual(
            plan["estimated_prompt_tokens"],
            plan["direct_token_budget"],
        )

    def test_large_transcript_falls_back_to_chunked(self):
        with patch(
            "ai.get_execution_profile",
            return_value=self._profile(1000),
        ):
            plan = ai.plan_meeting_summary_execution(
                "substantial meeting content " * 3000
            )

        self.assertEqual(plan["mode"], "chunked")
        self.assertGreater(
            plan["estimated_prompt_tokens"],
            plan["direct_token_budget"],
        )

    def test_processing_runtime_is_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "2026-09-26_1021_Test"
            run_dir.mkdir()
            runtime = {
                "ai_model": "qwen3:14b",
                "profile_display": "Auto → High Performance",
                "profile_requested": "Auto",
                "profile_resolved": "High Performance",
                "mode": "Direct",
                "context_size_tokens": 40960,
                "estimated_prompt_tokens": 10449,
                "direct_token_budget": 27200,
                "whisper_model": "medium.en",
                "whisper_chunk_minutes": 5,
            }
            (run_dir / "processing_runtime.json").write_text(
                json.dumps(runtime),
                encoding="utf-8",
            )
            (run_dir / "meeting_summary.md").write_text(
                "# Meeting Summary\n\nTest.",
                encoding="utf-8",
            )

            metadata_path = create_meeting_metadata(run_dir)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["processing"]["ai_model"], "qwen3:14b")
            self.assertEqual(metadata["processing"]["mode"], "Direct")

            detail = load_meeting_detail({"location": str(run_dir)})
            self.assertEqual(detail["processing"]["ai_model"], "qwen3:14b")
            self.assertEqual(
                detail["processing"]["profile_display"],
                "Auto → High Performance",
            )
            self.assertEqual(detail["processing"]["whisper_model"], "medium.en")


if __name__ == "__main__":
    unittest.main()
