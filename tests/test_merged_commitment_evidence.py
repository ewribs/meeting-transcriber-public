import unittest
from memory_reconciliation import enforce_commitment_evidence_integrity


class MergedCommitmentEvidenceTests(unittest.TestCase):
    def test_merged_explicit_promise_supports_verified_parent(self):
        memory = {'commitments': [{'owner': 'Alex A', 'action': 'Escalate an issue with Vendor Alpha',
                                   'evidence': "He is leading it, but I told him I'd get involved."}]}
        ledger = [
            {'disposition': 'candidate', 'event_type': 'commitment', 'owner': 'Alex A',
             'subject': 'escalate something with Vendor Alpha', 'evidence': memory['commitments'][0]['evidence']},
            {'disposition': 'merged', 'duplicate_of': 0, 'event_type': 'commitment',
             'owner': 'Alex A', 'subject': 'help escalate',
             'evidence': "I'll just get on a call. I'll help you escalate."},
        ]
        result = enforce_commitment_evidence_integrity(memory, ledger)
        self.assertEqual(len(result['commitments']), 1)
        self.assertEqual(result['commitments'][0]['evidence'], ledger[1]['evidence'])

    def test_different_owner_cannot_launder_evidence(self):
        memory = {'commitments': [{'owner': 'Alex A', 'action': 'Escalate an issue with Vendor Alpha',
                                   'evidence': 'He is leading it.'}]}
        ledger = [
            {'disposition': 'candidate', 'event_type': 'commitment', 'owner': 'Alex A',
             'subject': 'escalate something with Vendor Alpha', 'evidence': 'He is leading it.'},
            {'disposition': 'merged', 'duplicate_of': 0, 'event_type': 'commitment',
             'owner': 'Someone Else', 'subject': 'help escalate',
             'evidence': "I'll help you escalate."},
        ]
        self.assertEqual(enforce_commitment_evidence_integrity(memory, ledger)['commitments'], [])

    def test_discussion_without_promise_cannot_launder_evidence(self):
        memory = {'commitments': [{'owner': 'Alex A', 'action': 'Escalate an issue with Vendor Alpha',
                                   'evidence': 'He is leading it.'}]}
        ledger = [
            {'disposition': 'candidate', 'event_type': 'commitment', 'owner': 'Alex A',
             'subject': 'escalate something with Vendor Alpha', 'evidence': 'He is leading it.'},
            {'disposition': 'merged', 'duplicate_of': 0, 'event_type': 'commitment',
             'owner': 'Alex A', 'subject': 'help escalate',
             'evidence': 'We discussed how to escalate.'},
        ]
        self.assertEqual(enforce_commitment_evidence_integrity(memory, ledger)['commitments'], [])


if __name__ == '__main__':
    unittest.main()
