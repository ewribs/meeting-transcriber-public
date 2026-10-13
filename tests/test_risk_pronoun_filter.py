import unittest

import ai


def clean(risk, evidence="x different quote"):
    memory = {"commitments": [], "decisions": [], "open_questions": [], "follow_ups": [],
              "risks": [{"risk": risk, "evidence": evidence}]}
    return ai._high_performance_memory_quality_cleanup(memory)["risks"]


class RiskPronounFilterTests(unittest.TestCase):
    def test_keeps_specific_risk_with_pronoun_inside(self):
        self.assertEqual(len(clean("Concern about trying to get it done in 24 hours")), 1)

    def test_keeps_risk_with_relative_that(self):
        self.assertEqual(len(clean("Risk that the vendor raises prices at renewal")), 1)

    def test_drops_risk_starting_with_bare_pronoun(self):
        self.assertEqual(clean("It could become a real problem for the team next quarter"), [])

    def test_drops_short_vague_risk(self):
        self.assertEqual(clean("That stuff is risky"), [])

    def test_still_drops_risk_equal_to_evidence(self):
        text = "Concern about trying to get it done in 24 hours"
        self.assertEqual(clean(text, evidence=text), [])


if __name__ == "__main__":
    unittest.main()
