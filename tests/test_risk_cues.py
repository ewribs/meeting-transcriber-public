import unittest

import ai


class RiskCueTests(unittest.TestCase):
    def test_everyday_phrasing_is_accepted(self):
        cases = [
            ("Concern about getting the agreement done in 24 hours",
             ["I'm concerned about trying to get it done in 24 hours."]),
            ("Difficulty getting contractual approval from the vendor",
             ["I think we're going to have a hard time getting contractual approval from the vendor"]),
            ("Uncertainty around the year four forecast step affecting financial planning",
             ["one of the unknowns was that year four forecast step"]),
        ]
        for risk, quotes in cases:
            self.assertTrue(ai._risk_evidence_semantically_supports(risk, quotes), risk)

    def test_unrelated_quote_does_not_support_a_risk(self):
        self.assertFalse(ai._risk_evidence_semantically_supports(
            "Server outage will lose all customer data next quarter",
            ["we had lunch and talked about the weather today"]))
        self.assertFalse(ai._risk_evidence_semantically_supports(
            "Vendor cost overrun will cause financial loss for the project",
            ["I'm worried we will be late on the schedule for the offsite"]))


if __name__ == "__main__":
    unittest.main()
