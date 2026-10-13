import unittest
from ai import _explicit_scoped_template_decisions, _validate_resolved_decision

class ScopedDecisionTests(unittest.TestCase):
    def test_adopt_template_for_scoped_work(self):
        transcript = "Anything that goes up for board for now, let's use that template."
        candidates = _explicit_scoped_template_decisions(transcript)
        self.assertEqual(len(candidates), 1)
        self.assertIsNotNone(_validate_resolved_decision(candidates[0], transcript))

    def test_conditional_revision_does_not_undo_adoption(self):
        transcript = "Anything that goes up for board for now, let's use that template if we need to adjust it later."
        self.assertEqual(len(_explicit_scoped_template_decisions(transcript)), 1)

    def test_conditional_adoption_is_not_settled(self):
        transcript = "Let's use the template if we need to submit a request."
        candidate = {'decision': 'Use the template for the request', 'evidence': [transcript]}
        self.assertIsNone(_validate_resolved_decision(candidate, transcript))

    def test_hedged_template_suggestion_not_recovered(self):
        transcript = "Maybe anything that goes up for board should use that template."
        self.assertEqual(_explicit_scoped_template_decisions(transcript), [])

    def test_other_template_conversation_not_recovered(self):
        transcript = "I think I can standardize the board template."
        self.assertEqual(_explicit_scoped_template_decisions(transcript), [])

if __name__ == '__main__': unittest.main()
