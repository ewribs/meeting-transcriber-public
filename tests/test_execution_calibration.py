import unittest

from execution_calibration import (
    get_execution_calibration,
)


def make_record(
    *,
    elapsed=30.0,
    prompt=4000,
    budget=6000,
):
    return {
        "mode": "direct",
        "profile": "Balanced",
        "model_name": "qwen3:8b",
        "context_size_tokens": 16384,
        "hardware_label": "Apple M2 Pro · 16 GB",
        "estimated_prompt_tokens": prompt,
        "direct_token_budget": budget,
        "elapsed_seconds": elapsed,
    }


class ExecutionCalibrationTests(unittest.TestCase):
    def test_fewer_than_five_samples_do_not_adjust(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[make_record()] * 4,
        )

        self.assertEqual(calibration.factor, 1.0)
        self.assertEqual(calibration.sample_count, 4)

    def test_small_prompts_do_not_count(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[
                make_record(prompt=1000)
                for _ in range(12)
            ],
        )

        self.assertEqual(calibration.factor, 1.0)
        self.assertEqual(calibration.sample_count, 0)

    def test_five_fast_samples_raise_budget_slightly(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[
                make_record(elapsed=15.0)
                for _ in range(5)
            ],
        )

        self.assertEqual(calibration.factor, 1.05)
        self.assertEqual(calibration.sample_count, 5)

    def test_ten_fast_samples_raise_budget_but_cap_at_ten_percent(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[
                make_record(elapsed=15.0)
                for _ in range(10)
            ],
        )

        self.assertEqual(calibration.factor, 1.10)

    def test_ten_slow_samples_lower_budget(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[
                make_record(elapsed=75.0)
                for _ in range(10)
            ],
        )

        self.assertEqual(calibration.factor, 0.90)

    def test_normal_median_stays_neutral(self):
        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[
                make_record(elapsed=30.0)
                for _ in range(10)
            ],
        )

        self.assertEqual(calibration.factor, 1.0)
        self.assertEqual(
            calibration.median_elapsed_seconds,
            30.0,
        )

    def test_different_hardware_does_not_mix(self):
        other = make_record(elapsed=10.0)
        other["hardware_label"] = "Apple M4 Max · 64 GB"

        calibration = get_execution_calibration(
            profile="Balanced",
            model_name="qwen3:8b",
            context_size_tokens=16384,
            hardware_label="Apple M2 Pro · 16 GB",
            records=[other] * 20,
        )

        self.assertEqual(calibration.sample_count, 0)
        self.assertEqual(calibration.factor, 1.0)


if __name__ == "__main__":
    unittest.main()
