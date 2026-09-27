import unittest

from hardware_profile import HardwareProfile
from query.execution import (
    build_execution_metadata,
    choose_execution_plan,
    chunk_meeting_sources,
    estimate_tokens,
    get_execution_profile,
    infer_model_parameter_billions,
)


def _meeting(index: int, body_size: int = 400):
    meeting_run = (
        f"2026-01-{index:02d}_Meeting{index}"
    )

    memory = {
        "topics": [
            {
                "topic_key": f"topic-{index}",
                "topic": f"Topic {index}",
                "summary": "x" * body_size,
            }
        ],
        "decisions": [],
        "open_questions": [],
        "follow_ups": [],
        "commitments": [],
    }

    selected = {
        "meeting_run": meeting_run,
        "display_title": f"Meeting {index}",
        "relevance_weight": 1,
    }

    return (meeting_run, memory), selected


class QueryExecutionTests(unittest.TestCase):

    def test_manual_profiles_use_centralized_runtime_budgets(self):
        conservative = get_execution_profile(
            "Conservative",
            model_name="qwen3:8b",
        )
        balanced = get_execution_profile(
            "Balanced",
            model_name="qwen3:8b",
        )
        high = get_execution_profile(
            "High Performance",
            model_name="qwen3:8b",
        )

        self.assertEqual(conservative.direct_token_budget, 9000)
        self.assertEqual(conservative.context_size_tokens, 16384)
        self.assertEqual(balanced.direct_token_budget, 18000)
        self.assertEqual(balanced.context_size_tokens, 24576)
        self.assertEqual(high.direct_token_budget, 32000)
        self.assertEqual(high.context_size_tokens, 40960)
        self.assertLess(
            conservative.direct_token_budget,
            balanced.direct_token_budget,
        )
        self.assertLess(
            balanced.direct_token_budget,
            high.direct_token_budget,
        )

    def test_legacy_aggressive_alias_maps_to_high_performance(self):
        profile = get_execution_profile(
            "Aggressive",
            model_name="qwen3:8b",
        )

        self.assertEqual(profile.name, "High Performance")
        self.assertEqual(profile.resolved_name, "High Performance")
        self.assertEqual(profile.direct_token_budget, 32000)

    def test_context_override_caps_direct_budget_with_reserve(self):
        profile = get_execution_profile(
            "High Performance",
            context_size_tokens=8192,
            model_name="qwen3:8b",
        )

        self.assertEqual(profile.direct_token_budget, 6144)
        self.assertEqual(profile.context_size_tokens, 8192)
        self.assertEqual(profile.context_reserve_tokens, 2048)

    def test_model_size_is_inferred_from_common_ollama_tags(self):
        self.assertEqual(
            infer_model_parameter_billions(
                "qwen3:8b"
            ),
            8.0,
        )
        self.assertEqual(
            infer_model_parameter_billions(
                "qwen2.5:14b-instruct"
            ),
            14.0,
        )
        self.assertIsNone(
            infer_model_parameter_billions(
                "custom-model"
            )
        )

    def test_eight_b_model_preserves_balanced_budget(self):
        profile = get_execution_profile(
            "Balanced",
            model_name="qwen3:8b",
        )

        self.assertEqual(profile.direct_token_budget, 18000)
        self.assertEqual(profile.model_budget_factor, 1.0)
        self.assertEqual(profile.model_parameter_billions, 8.0)

    def test_fourteen_b_model_reduces_practical_budget(self):
        profile = get_execution_profile(
            "Balanced",
            model_name="qwen3:14b",
        )

        self.assertEqual(profile.direct_token_budget, 15300)
        self.assertEqual(profile.chunk_source_token_budget, 4250)
        self.assertEqual(profile.model_budget_factor, 0.85)

    def test_hardware_factor_is_metadata_not_second_budget_multiplier(self):
        profile = get_execution_profile(
            "Balanced",
            model_name="qwen3:8b",
            hardware_label="Apple M5 Max · 36 GB",
            hardware_performance_class="Apple Silicon Max",
            hardware_budget_factor=1.30,
        )

        self.assertEqual(profile.direct_token_budget, 18000)
        self.assertEqual(profile.hardware_budget_factor, 1.30)
        self.assertEqual(
            profile.hardware_performance_class,
            "Apple Silicon Max",
        )

    def test_unknown_model_size_preserves_profile_budget(self):
        profile = get_execution_profile(
            "Balanced",
            model_name="custom-model",
        )

        self.assertEqual(profile.direct_token_budget, 18000)
        self.assertIsNone(profile.model_parameter_billions)

    def test_context_reserve_scales_with_large_context(self):
        profile = get_execution_profile(
            "High Performance",
            model_name="qwen3:8b",
        )

        self.assertEqual(profile.context_reserve_tokens, 8192)
        self.assertEqual(profile.direct_token_budget, 32000)

    def test_unknown_execution_profile_is_rejected(self):
        with self.assertRaises(ValueError):
            get_execution_profile("Turbo Potato")

    def test_auto_planner_chunks_on_16gb_but_stays_direct_on_36gb(self):
        m2 = HardwareProfile(
            system="Darwin",
            architecture="arm64",
            chip_name="Apple M2 Pro",
            memory_bytes=16 * (1024 ** 3),
            memory_gb=16,
            performance_class="Apple Silicon Pro",
            budget_factor=1.0,
        )
        studio = HardwareProfile(
            system="Darwin",
            architecture="arm64",
            chip_name="Apple M5 Max",
            memory_bytes=36 * (1024 ** 3),
            memory_gb=36,
            performance_class="Apple Silicon Max",
            budget_factor=1.0,
        )

        conservative = get_execution_profile(
            "Auto",
            model_name="qwen3:8b",
            hardware_profile=m2,
        )
        high = get_execution_profile(
            "Auto",
            model_name="qwen3:8b",
            hardware_profile=studio,
        )

        prompt = "x" * 40000  # ~10,000 estimated tokens
        m2_plan = choose_execution_plan(
            prompt,
            can_chunk=True,
            direct_token_budget=conservative.direct_token_budget,
        )
        studio_plan = choose_execution_plan(
            prompt,
            can_chunk=True,
            direct_token_budget=high.direct_token_budget,
        )

        self.assertEqual(conservative.resolved_name, "Conservative")
        self.assertEqual(high.resolved_name, "High Performance")
        self.assertEqual(m2_plan.mode, "chunked")
        self.assertEqual(studio_plan.mode, "direct")

    def test_estimate_tokens_is_dependency_free_and_nonzero(self):
        self.assertGreater(
            estimate_tokens("hello world"),
            0,
        )

    def test_small_prompt_uses_direct_mode(self):
        plan = choose_execution_plan(
            "small prompt",
            can_chunk=True,
            direct_token_budget=100,
        )

        self.assertEqual(
            plan.mode,
            "direct",
        )

    def test_large_prompt_uses_chunked_mode_when_sources_available(self):
        plan = choose_execution_plan(
            "x" * 5000,
            can_chunk=True,
            direct_token_budget=100,
        )

        self.assertEqual(
            plan.mode,
            "chunked",
        )

    def test_large_prompt_stays_direct_when_chunking_is_unavailable(self):
        plan = choose_execution_plan(
            "x" * 5000,
            can_chunk=False,
            direct_token_budget=100,
        )

        self.assertEqual(
            plan.mode,
            "direct",
        )

    def test_direct_execution_metadata_reports_one_pass(self):
        plan = choose_execution_plan(
            "small prompt",
            can_chunk=True,
            direct_token_budget=100,
        )

        metadata = build_execution_metadata(
            plan
        )

        self.assertEqual(
            metadata["profile"],
            "Auto",
        )
        self.assertEqual(
            metadata["mode"],
            "direct",
        )
        self.assertEqual(
            metadata["inference_calls"],
            1,
        )

    def test_chunked_execution_metadata_counts_synthesis_pass(self):
        plan = choose_execution_plan(
            "x" * 5000,
            can_chunk=True,
            direct_token_budget=100,
        )

        metadata = build_execution_metadata(
            plan,
            chunk_count=3,
        )

        self.assertEqual(
            metadata["mode"],
            "chunked",
        )
        self.assertEqual(
            metadata["chunk_count"],
            3,
        )
        self.assertEqual(
            metadata["inference_calls"],
            4,
        )

    def test_meeting_chunks_preserve_order_and_do_not_mutate_selection(self):
        memories = []
        selected = []

        for index in range(1, 6):
            memory, item = _meeting(index)
            memories.append(memory)
            selected.append(item)

        original = [
            dict(item)
            for item in selected
        ]

        chunks = chunk_meeting_sources(
            memories,
            selected,
            chunk_source_token_budget=250,
        )

        flattened_runs = [
            run
            for chunk_memories, _ in chunks
            for run, _ in chunk_memories
        ]

        self.assertEqual(
            flattened_runs,
            [run for run, _ in memories],
        )
        self.assertEqual(
            selected,
            original,
        )
        self.assertGreater(
            len(chunks),
            1,
        )


if __name__ == "__main__":
    unittest.main()
