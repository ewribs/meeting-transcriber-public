"""The final integrity pass keeps commitments whose owner is honestly Unknown."""

import unittest

from memory_reconciliation import finalize_evidence_bound_memory


class UnknownOwnerFinalPassTests(unittest.TestCase):
    EVIDENCE = "We will update the process so every stage gate has an accountable lead."

    def _memory(self, owner):
        return {
            "commitments": [
                {
                    "owner": owner,
                    "action": "Update the process for stage gates and accountability",
                    "evidence": self.EVIDENCE,
                }
            ]
        }

    def _ledger(self, owner):
        return [{"owner": owner, "subject": "stage gate process", "evidence": self.EVIDENCE}]

    def test_unknown_owner_commitment_is_kept(self):
        result = finalize_evidence_bound_memory(self._memory("Unknown"), self._ledger(None), "")
        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(result["commitments"][0]["owner"], "Unknown")

    def test_named_owner_not_supported_by_evidence_is_still_dropped(self):
        result = finalize_evidence_bound_memory(self._memory("Pat"), self._ledger(None), "")
        self.assertEqual(result["commitments"], [])

    def test_named_owner_supported_by_evidence_is_kept(self):
        result = finalize_evidence_bound_memory(self._memory("Pat"), self._ledger("Pat"), "")
        self.assertEqual(len(result["commitments"]), 1)


if __name__ == "__main__":
    unittest.main()
