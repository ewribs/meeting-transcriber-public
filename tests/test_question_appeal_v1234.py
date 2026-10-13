import unittest
from tools.benchmark.question_appeal_compare import question_quote_matches_claim
class EvidenceAlignedAppealTests(unittest.TestCase):
    def test_rejects_nearby_wrong_question(self):
        self.assertFalse(question_quote_matches_claim("When is the 90-day notice period for the Vendor Gamma agreements?", "when's the, how long is the blanket"))
    def test_contract_owner(self):
        self.assertTrue(question_quote_matches_claim("Who's signing contracts in the alpha model?", "when we get in the alpha model, who's signing contracts?"))
    def test_search_funding(self):
        self.assertTrue(question_quote_matches_claim("How much search funding is earmarked for third-party spend?", "how much search funding is earmarked for third party spend?"))
    def test_empty(self):
        self.assertFalse(question_quote_matches_claim("Who approves supplier contracts?", ""))
