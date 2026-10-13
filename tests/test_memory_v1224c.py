"""Sanitized v12.24c explicit unresolved-question recovery regressions."""
import unittest
from ai import _recover_explicit_tbd_questions


class ExplicitTBDQuestionTests(unittest.TestCase):
    def test_explicit_unresolved_question(self):
        transcript = "[00:51] **Remote**\nWho will own the service transition? It's TBD on the org chart."
        self.assertEqual(_recover_explicit_tbd_questions(transcript),
                         ["Who will own the service transition?"])

    def test_discussion_example_not_recovered(self):
        transcript = "[01:00] **Remote**\nHow do teams think about annual budgets? We cover that in training."
        self.assertEqual(_recover_explicit_tbd_questions(transcript), [])

    def test_tbd_in_next_turn_is_not_enough(self):
        transcript = ("[01:00] **Mic**\nWho will own the service transition?\n"
                      "[01:05] **Remote**\nA separate unrelated topic is TBD.")
        self.assertEqual(_recover_explicit_tbd_questions(transcript), [])

    def test_no_duplicates(self):
        transcript = ("[00:51] **Remote**\nWho will own the service transition? It's TBD.\n"
                      "[01:00] **Remote**\nWho will own the service transition? Still undecided.")
        self.assertEqual(len(_recover_explicit_tbd_questions(transcript)), 1)


if __name__ == "__main__":
    unittest.main()
