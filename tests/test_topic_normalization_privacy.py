import unittest

from ai import normalize_topic_key


class TopicNormalizationPrivacyTests(unittest.TestCase):
    def test_explicit_generic_rules_are_applied(self):
        rules = (("vendor_alpha_renewal", ("vendor alpha", "alpha renewal")),)
        self.assertEqual(
            normalize_topic_key(
                "renewal",
                "Vendor Alpha Renewal",
                canonical_rules=rules,
            ),
            "vendor_alpha_renewal",
        )

    def test_empty_rules_fall_back_to_generic_key_normalization(self):
        self.assertEqual(
            normalize_topic_key(
                "Quarterly Planning",
                "Quarterly Planning",
                canonical_rules=(),
            ),
            "quarterly_planning",
        )


if __name__ == "__main__":
    unittest.main()
