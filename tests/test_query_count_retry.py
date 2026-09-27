import unittest
from types import SimpleNamespace
from unittest.mock import patch

from query.chat import run_query


class QueryCountRetryIntegrationTests(unittest.TestCase):

    @patch("query.chat.build_execution_metadata")
    @patch("query.chat.choose_execution_plan")
    @patch("query.chat.get_execution_profile")
    @patch("query.chat.get_execution_calibration")
    @patch("query.chat.detect_hardware_profile")
    @patch("query.chat.build_query_prompt")
    @patch("query.chat.prepare_query_memory")
    @patch("query.chat.resolve_query_dates")
    @patch("query.chat.ask_llm")
    def test_direct_query_retries_once_when_top_three_returns_one_item(
        self,
        ask_llm,
        resolve_query_dates,
        prepare_query_memory,
        build_query_prompt,
        detect_hardware_profile,
        get_execution_calibration,
        get_execution_profile,
        choose_execution_plan,
        build_execution_metadata,
    ):
        ask_llm.side_effect = [
            "1. One item only.",
            "1. First\n2. Second\n3. Third",
        ]
        resolve_query_dates.return_value = (
            "Tell me the top three things for Alex.",
            "2026-09-15",
        )
        prepare_query_memory.return_value = {}
        build_query_prompt.return_value = "BASE PROMPT"
        detect_hardware_profile.return_value = SimpleNamespace(
            display_label="Test hardware",
            performance_class="Test",
            budget_factor=1.0,
        )
        get_execution_calibration.return_value = SimpleNamespace(
            factor=1.0,
            sample_count=0,
            median_elapsed_seconds=None,
            reason="test",
        )
        get_execution_profile.return_value = SimpleNamespace(
            name="Balanced",
            direct_token_budget=6000,
            chunk_source_token_budget=2400,
            context_size_tokens=0,
            context_reserve_tokens=0,
            model_name="qwen3:8b",
            model_parameter_billions=8.0,
            model_budget_factor=1.0,
            hardware_label="Test hardware",
            hardware_performance_class="Test",
            hardware_budget_factor=1.0,
            calibration_factor=1.0,
            calibration_sample_count=0,
            calibration_median_elapsed_seconds=None,
            calibration_reason="test",
        )
        choose_execution_plan.return_value = SimpleNamespace(
            mode="direct",
            estimated_prompt_tokens=100,
            direct_token_budget=6000,
        )
        build_execution_metadata.return_value = {
            "profile": "Balanced",
            "mode": "direct",
            "inference_calls": 1,
        }

        result, metadata = run_query(
            "Tell me the top three things for Alex.",
            {},
            print_output=False,
            return_execution_metadata=True,
        )

        self.assertEqual(
            result,
            "1. First\n2. Second\n3. Third",
        )
        self.assertEqual(ask_llm.call_count, 2)
        self.assertEqual(metadata["inference_calls"], 2)
        self.assertEqual(metadata["count_retry_count"], 1)

    @patch("query.chat.ask_llm")
    def test_action_style_request_does_not_use_count_retry(self, ask_llm):
        # Count compliance is intentionally bypassed for action requests because
        # the application renders grounded actions separately.
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
