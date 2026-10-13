import unittest
from tools.benchmark.question_appeal_compare import retrieve_uncertainty_passages

class RetrievalTests(unittest.TestCase):
    def test_retrieves_uncertain_business_allocation(self):
        text=("# Meeting Transcript\n\n[00:01] **Remote**\n\nWe finished the deck.\n\n"
              "[00:02] **Remote**\n\nI don't know how much of the fund is earmarked for external work.\n\n"
              "[00:03] **Remote**\n\nWe will send the deck today.")
        result=retrieve_uncertainty_passages(text)
        self.assertEqual(len(result),1)
        self.assertIn('earmarked for external work',result[0])

    def test_ignores_ordinary_updates(self):
        self.assertEqual(retrieve_uncertainty_passages('[00:01] **Mic**\n\nDone.'),[])

    def test_caps_number_of_passages(self):
        text='\n\n'.join(f'[00:{i:02d}] **Remote**\n\nI am not sure about item {i}.' for i in range(20))
        self.assertEqual(len(retrieve_uncertainty_passages(text,max_passages=4)),4)

    def test_empty(self):
        self.assertEqual(retrieve_uncertainty_passages(''),[])
