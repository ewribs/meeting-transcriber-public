import unittest

from memory_reconciliation import demote_rejected_risks


def _row(risk, reason="risk_evidence_not_supported", grounded=("a quote",)):
    return {"risk": risk, "reason": reason, "grounded_evidence": list(grounded)}


class PossibleRisksTests(unittest.TestCase):
    def test_weak_evidence_rejection_becomes_possible_risk(self):
        out = demote_rejected_risks(
            [_row("Uncertainty around the ten year term and its implications")],
            {"risks": [], "follow_ups": []})
        self.assertEqual(len(out["follow_ups"]), 1)
        self.assertTrue(out["follow_ups"][0].startswith("Possible risk (unconfirmed)"))

    def test_other_reasons_missing_quotes_and_duplicates_are_ignored(self):
        rows = [_row("Risk with another rejection reason here", reason="risk_length_invalid"),
                _row("Risk with no grounded quote at all here", grounded=()),
                _row("Existing retained risk about vendor support lapse")]
        final = {"risks": [{"risk": "Existing retained risk about vendor support lapse"}],
                 "follow_ups": []}
        self.assertEqual(demote_rejected_risks(rows, final)["follow_ups"], [])

    def test_limit_is_three(self):
        rows = [_row(f"Distinct concern topic{i}x detail{i}y exposure{i}z here") for i in range(8)]
        out = demote_rejected_risks(rows, {"risks": [], "follow_ups": []})
        self.assertEqual(len(out["follow_ups"]), 3)


if __name__ == "__main__":
    unittest.main()
