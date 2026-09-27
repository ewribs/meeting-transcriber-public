import unittest

from hardware_profile import HardwareProfile
from performance_profile import (
    auto_profile_name,
    performance_profile_options,
    resolve_performance_profile,
)


def _hardware(chip: str, memory_gb: int, performance_class: str) -> HardwareProfile:
    return HardwareProfile(
        system="Darwin",
        architecture="arm64",
        chip_name=chip,
        memory_bytes=memory_gb * (1024 ** 3),
        memory_gb=memory_gb,
        performance_class=performance_class,
        budget_factor=1.0,
    )


class PerformanceProfileTests(unittest.TestCase):

    def test_profile_options_explain_auto_and_manual_modes(self):
        options = {
            item["name"]: item["description"]
            for item in performance_profile_options()
        }
        self.assertIn("detected unified memory", options["Auto"])
        self.assertIn("smaller direct contexts", options["Conservative"])
        self.assertIn("middle ground", options["Balanced"])
        self.assertIn("largest direct contexts", options["High Performance"])

    def test_auto_m2_pro_16gb_resolves_conservative(self):
        hardware = _hardware(
            "Apple M2 Pro",
            16,
            "Apple Silicon Pro",
        )

        name, _ = auto_profile_name(hardware)
        resolved = resolve_performance_profile(
            "Auto",
            hardware=hardware,
        )

        self.assertEqual(name, "Conservative")
        self.assertEqual(resolved.resolved_name, "Conservative")
        self.assertEqual(resolved.context_size_tokens, 16384)
        self.assertEqual(resolved.direct_token_budget, 9000)
        self.assertEqual(resolved.llm_call_timeout_seconds, 240)

    def test_auto_m5_max_36gb_resolves_high_performance(self):
        hardware = _hardware(
            "Apple M5 Max",
            36,
            "Apple Silicon Max",
        )

        resolved = resolve_performance_profile(
            "Auto",
            hardware=hardware,
        )

        self.assertEqual(resolved.resolved_name, "High Performance")
        self.assertEqual(resolved.context_size_tokens, 40960)
        self.assertEqual(resolved.direct_token_budget, 32000)
        self.assertEqual(resolved.llm_call_timeout_seconds, 150)

    def test_auto_m4_16gb_remains_conservative(self):
        hardware = _hardware(
            "Apple M4",
            16,
            "Apple Silicon",
        )

        resolved = resolve_performance_profile(
            "Auto",
            hardware=hardware,
        )

        self.assertEqual(resolved.resolved_name, "Conservative")

    def test_manual_profile_overrides_auto_choice(self):
        hardware = _hardware(
            "Apple M5 Max",
            36,
            "Apple Silicon Max",
        )

        resolved = resolve_performance_profile(
            "Conservative",
            hardware=hardware,
        )

        self.assertEqual(resolved.requested_name, "Conservative")
        self.assertEqual(resolved.resolved_name, "Conservative")
        self.assertEqual(resolved.context_size_tokens, 16384)

    def test_context_override_clamps_direct_budget_to_usable_context(self):
        hardware = _hardware(
            "Apple M5 Max",
            36,
            "Apple Silicon Max",
        )

        resolved = resolve_performance_profile(
            "Auto",
            context_size_override=16384,
            hardware=hardware,
        )

        self.assertEqual(resolved.resolved_name, "High Performance")
        self.assertEqual(resolved.context_size_tokens, 16384)
        self.assertEqual(resolved.direct_token_budget, 13108)

    def test_context_override_does_not_change_profile_tier(self):
        hardware = _hardware(
            "Apple M5 Max",
            36,
            "Apple Silicon Max",
        )

        resolved = resolve_performance_profile(
            "Auto",
            context_size_override=32768,
            hardware=hardware,
        )

        self.assertEqual(resolved.resolved_name, "High Performance")
        self.assertEqual(resolved.context_size_tokens, 32768)


if __name__ == "__main__":
    unittest.main()
