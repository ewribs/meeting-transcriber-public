import unittest

from hardware_profile import (
    benchmark_informed_budget_factor,
)


class HardwareProfileTests(unittest.TestCase):

    def test_m2_pro_16gb_is_project_baseline(self):
        factor, performance_class = (
            benchmark_informed_budget_factor(
                "Apple M2 Pro",
                16,
            )
        )

        self.assertEqual(
            factor,
            1.0,
        )
        self.assertEqual(
            performance_class,
            "Apple Silicon Pro",
        )

    def test_max_with_more_memory_gets_modest_increase(self):
        factor, performance_class = (
            benchmark_informed_budget_factor(
                "Apple M2 Max",
                32,
            )
        )

        self.assertGreater(
            factor,
            1.0,
        )
        self.assertEqual(
            performance_class,
            "Apple Silicon Max",
        )

    def test_base_apple_silicon_chunks_sooner_than_pro_baseline(self):
        factor, _ = (
            benchmark_informed_budget_factor(
                "Apple M2",
                16,
            )
        )

        self.assertLess(
            factor,
            1.0,
        )

    def test_unknown_hardware_preserves_existing_behavior(self):
        factor, performance_class = (
            benchmark_informed_budget_factor(
                "Intel(R) Core(TM)",
                16,
            )
        )

        self.assertEqual(
            factor,
            1.0,
        )
        self.assertEqual(
            performance_class,
            "Generic",
        )


if __name__ == "__main__":
    unittest.main()
