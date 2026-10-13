import unittest

from memory_reconciliation import finalize_evidence_bound_memory


def _memory(evidence, supporting=None):
    item = {"owner": "Jordan", "action": "Coordinate with the vendor to set up a call",
            "status": "open", "evidence": evidence}
    if supporting:
        item["supporting_evidence"] = supporting
    return {"commitments": [item], "follow_ups": [], "open_questions": []}


class NamedOwnerAssignmentTests(unittest.TestCase):
    def test_assignment_that_names_the_owner_is_kept(self):
        quote = "Jordan, why don't you take the lead on getting something set up for the four of us?"
        ledger = [{"evidence": quote, "owner": "Sam", "subject": "set up a call"}]
        out = finalize_evidence_bound_memory(_memory(quote), ledger, quote)
        self.assertEqual(len(out["commitments"]), 1)

    def test_quote_from_someone_else_not_naming_owner_is_dropped(self):
        quote = "We should probably get something set up for the four of us."
        ledger = [{"evidence": quote, "owner": "Sam", "subject": "set up a call"}]
        out = finalize_evidence_bound_memory(_memory(quote), ledger, quote)
        self.assertEqual(out["commitments"], [])


if __name__ == "__main__":
    unittest.main()
