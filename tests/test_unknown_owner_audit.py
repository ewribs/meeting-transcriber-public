"""The final audit keeps Unknown-owner commitments and does not duplicate them."""

import unittest

from memory_reconciliation import audit_final_memory_integrity

QUOTE = "I will update the process so every stage gate has an accountable lead."


def _ledger():
    return [{"event_type": "commitment", "owner": None, "lifecycle": "planned",
             "subject": "Update the stage gate process", "evidence": QUOTE}]


def _memory(owner):
    return {"commitments": [{"owner": owner, "action": "Update the stage gate process",
                             "evidence": QUOTE}],
            "follow_ups": []}


class UnknownOwnerAuditTests(unittest.TestCase):
    def test_unknown_owner_is_kept_once(self):
        memory, _ = audit_final_memory_integrity(_memory("Unknown"), _ledger(), QUOTE)
        self.assertEqual([c["owner"] for c in memory["commitments"]], ["Unknown"])
        self.assertEqual(memory["follow_ups"], [])

    def test_named_owner_on_unidentified_evidence_is_still_rejected(self):
        memory, audit = audit_final_memory_integrity(_memory("Pat"), _ledger(), QUOTE)
        self.assertEqual(memory["commitments"], [])
        self.assertTrue(any(a["reason"] == "unidentified_speaker_evidence" for a in audit))


if __name__ == "__main__":
    unittest.main()
