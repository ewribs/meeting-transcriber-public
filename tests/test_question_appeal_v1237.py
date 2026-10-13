import unittest
from tools.benchmark.question_appeal_compare import retrieve_uncertainty_passages, discover_uncertainty_questions

TRANSCRIPT = """[19:53] **Remote**
The search funding for these domains may create demand for software and consulting.

[20:17] **Remote**
We are trying to get access to how much of that is earmarked for third party spend.

[21:00] **Remote**
Let's look at the forecast next week.
"""

class ContextAwareUncertaintyTests(unittest.TestCase):
    def test_neighbor_turn_keeps_antecedent(self):
        snippets = retrieve_uncertainty_passages(TRANSCRIPT)
        relevant = [x for x in snippets if 'how much of that' in x]
        self.assertTrue(relevant)
        self.assertIn('search funding', relevant[0])

    def test_model_sees_context_and_candidate_still_needs_evidence(self):
        seen = []
        def reviewer(prompt, schema):
            seen.append(prompt)
            return {'questions': [{'question':'How much search funding is earmarked for third party spend?', 'evidence_quote':'We are trying to get access to how much of that is earmarked for third party spend.'}]}
        found, diag = discover_uncertainty_questions(TRANSCRIPT, reviewer=reviewer)
        self.assertIn('search funding', seen[0]); self.assertEqual(1, len(found))
        self.assertEqual([], diag['errors'])

    def test_unrelated_claim_still_rejected(self):
        def reviewer(prompt, schema):
            return {'questions':[{'question':'What is the renewal deadline for Vendor Alpha?', 'evidence_quote':'We are trying to get access to how much of that is earmarked for third party spend.'}]}
        found, diag=discover_uncertainty_questions(TRANSCRIPT, reviewer=reviewer)
        self.assertEqual([], found)
        self.assertEqual('question_evidence_mismatch', diag['rejected'][0]['reason'])
