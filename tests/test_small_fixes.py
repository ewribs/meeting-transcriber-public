import unittest

import ai
from memory_reconciliation import scrub_channel_labels


class ScrubTests(unittest.TestCase):
    def test_labels_are_replaced_in_name_positions(self):
        mem = {"commitments": [{"owner": "Unknown",
                                "action": "Send the proposal to Mic and Sam"},
                               {"owner": "Unknown",
                                "action": "Set up a meeting with Sam, Casey, and Remote"}],
               "follow_ups": ["Possible commitment (unconfirmed): Ask Remote for the data"]}
        out = scrub_channel_labels(mem, "Sam")
        self.assertEqual(out["commitments"][0]["action"], "Send the proposal to Sam and Sam")
        self.assertEqual(out["commitments"][1]["action"],
                         "Set up a meeting with Sam, Casey, and the remote participants")

    def test_ordinary_phrases_are_untouched(self):
        mem = {"commitments": [{"action": "Review the Remote work policy"},
                               {"action": "Update the Mic setup guide"}]}
        out = scrub_channel_labels(mem, "Sam")
        self.assertEqual(out["commitments"][0]["action"], "Review the Remote work policy")
        self.assertEqual(out["commitments"][1]["action"], "Update the Mic setup guide")


class DecisionTests(unittest.TestCase):
    def test_generic_drop_is_not_well_formed(self):
        self.assertFalse(ai._decision_candidate_is_well_formed("Drop things.", "drop things"))
        self.assertTrue(ai._decision_candidate_is_well_formed("Drop them.", "we dropped them"))

    def test_decision_made_language_is_explicit(self):
        self.assertTrue(ai._decision_evidence_is_explicit("Decision made. Let's cancel the meeting."))
        self.assertTrue(ai._decision_evidence_is_explicit("We've decided to cancel the review."))
        self.assertFalse(ai._decision_evidence_is_explicit("Should we cancel the review?"))


if __name__ == "__main__":
    unittest.main()
