import unittest

import ai


class WordFormMatchTests(unittest.TestCase):
    def test_cancel_cancelled_counts(self):
        self.assertTrue(ai._decision_is_supported(
            "To cancel the meeting",
            "Decision made. Alicia, get that meeting cancelled, and then we can move on"))

    def test_unrelated_evidence_still_fails(self):
        self.assertFalse(ai._decision_is_supported(
            "To cancel the meeting",
            "Decision made. We will lunch on Friday somewhere nice"))

    def test_helper(self):
        self.assertEqual(ai._count_matching_word_forms({"cancel", "meeting"}, {"cancelled", "meeting"}), 2)
        self.assertEqual(ai._count_matching_word_forms({"cut"}, {"cutting"}), 0)


if __name__ == "__main__":
    unittest.main()
