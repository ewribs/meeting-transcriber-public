import unittest
from provenance_audit import audit_final_provenance

class FinalProvenanceAuditTests(unittest.TestCase):
    def test_verified_decision_exact_evidence(self):
        row = {'decision': 'Use board template', 'evidence': 'Let us use that template'}
        got = audit_final_provenance({'decisions': [row]}, {'decisions': [row]})
        self.assertEqual(got[0]['verification_status'], 'verified')

    def test_recovered_question_not_mislabeled(self):
        got = audit_final_provenance({'open_questions': ['What is the budget?']},
                                     {'_verified_open_questions': []})
        self.assertEqual(got[0]['verification_status'], 'not_verified')
        self.assertEqual(got[0]['origin'], 'post_verification_or_legacy')

    def test_changed_evidence_does_not_inherit_verification(self):
        verified = {'decisions': [{'decision': 'Use template', 'evidence': 'Use template for board'}]}
        final = {'decisions': [{'decision': 'Use template', 'evidence': 'Maybe use template'}]}
        self.assertEqual(audit_final_provenance(final, verified)[0]['verification_status'], 'not_verified')

    def test_recovery_clue_is_not_verification(self):
        item = 'Who approves the work?'
        audit = [{'section': 'open_questions', 'value': item, 'disposition': 'recovered', 'reason': 'grounded_question'}]
        got = audit_final_provenance({'open_questions': [item]}, {}, audit)
        self.assertEqual(got[0]['recovery_clues'], ['grounded_question'])
        self.assertEqual(got[0]['verification_status'], 'not_verified')

if __name__ == '__main__':
    unittest.main()
