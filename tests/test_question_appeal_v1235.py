import unittest
from tools.benchmark.question_appeal_compare import discover_uncertainty_questions

class UnresolvedBusinessUncertaintyTests(unittest.TestCase):
    def test_recovers_uncertainty_statement(self):
        passage = "We still do not know how much of the budget is allocated to vendor expenses."
        def reviewer(prompt, schema):
            return {"questions": [{"question": "How much budget is allocated to vendor expenses?", "evidence_quote": passage}]}
        candidates, diag = discover_uncertainty_questions(passage, reviewer=reviewer)
        self.assertEqual(len(candidates), 1)
        self.assertFalse(diag['errors'])

    def test_rejects_unrelated_quote(self):
        transcript = "We still do not know how much of the budget is allocated to vendor expenses."
        def reviewer(prompt, schema):
            return {"questions": [{"question": "Who owns the contract approval?", "evidence_quote": transcript}]}
        candidates, diag = discover_uncertainty_questions(transcript, reviewer=reviewer)
        self.assertEqual(candidates, [])
        self.assertEqual(diag['rejected'][0]['reason'], 'question_evidence_mismatch')

    def test_rejects_fabricated_quote(self):
        transcript = "We still need to validate the budget amount."
        def reviewer(prompt, schema):
            return {"questions": [{"question": "What is the budget amount?", "evidence_quote": "We have not agreed upon the total budget amount."}]}
        candidates, diag = discover_uncertainty_questions(transcript, reviewer=reviewer)
        self.assertEqual(candidates, [])
        self.assertEqual(diag['rejected'][0]['reason'], 'no_exact_uncertainty_evidence')

    def test_fails_closed_when_context_exceeds_limit(self):
        candidates, diag = discover_uncertainty_questions('a' * 30, max_chars=5, reviewer=lambda p,s: self.fail('no inference'))
        self.assertEqual(candidates, [])
        self.assertTrue(diag['errors'])

if __name__ == '__main__': unittest.main()
