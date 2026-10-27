import unittest

import ai
from memory_reconciliation import near_duplicate, stem_word


class StemTests(unittest.TestCase):
    def test_endings_collapse(self):
        self.assertEqual(stem_word("reply"), stem_word("replying"))
        self.assertEqual(stem_word("reply"), stem_word("replied"))
        self.assertEqual(stem_word("apply"), stem_word("applying"))
        self.assertEqual(stem_word("meeting"), stem_word("meet"))

    def test_plurals_work_as_before(self):
        self.assertEqual(stem_word("apps"), "app")
        self.assertEqual(stem_word("tools"), "tool")

    def test_short_words_are_left_alone(self):
        self.assertEqual(stem_word("bring"), "bring")
        self.assertEqual(stem_word("need"), "need")


class DuplicateTests(unittest.TestCase):
    def test_commitment_in_a_different_form_is_a_duplicate(self):
        self.assertTrue(near_duplicate(
            {"reply", "salesforce"}, [{"replying", "salesforce"}], threshold=0.75))

    def test_different_commitments_are_not(self):
        self.assertFalse(near_duplicate(
            {"reply", "salesforce"}, [{"send", "salesforce", "contract"}],
            threshold=0.75))

    def test_questions_with_a_different_verb_form_are_duplicates(self):
        self.assertTrue(ai._questions_are_near_duplicates(
            "Whether Casey was planning to apply for the role",
            "Whether Casey is interested in applying for the role"))

    def test_different_questions_are_kept(self):
        self.assertFalse(ai._questions_are_near_duplicates(
            "Whether the vendor will extend support",
            "Whether the vendor will lower pricing"))


if __name__ == "__main__":
    unittest.main()
