import unittest

import ai
import next_steps_pass as nsp
from memory_reconciliation import _tokens, near_duplicate


def dup(a, b, threshold=0.6):
    return near_duplicate(_tokens(a), [_tokens(b)], threshold)


def clean(memory):
    base = {"commitments": [], "decisions": [], "risks": [], "open_questions": [], "follow_ups": []}
    base.update(memory)
    return ai._high_performance_memory_quality_cleanup(base)


class NearDuplicateTests(unittest.TestCase):
    def test_short_item_repeated_inside_longer_one(self):
        self.assertTrue(dup("Send the deck", "Send the 51 slide deck"))

    def test_plurals_match(self):
        self.assertTrue(dup("Send executive decks to Ribs", "Send the deck to Ribs when he has time"))

    def test_different_objects_are_not_duplicates(self):
        self.assertFalse(dup("Send the deck", "Send the contract to Dana"))
        self.assertFalse(dup("Review the budget", "Review the vendor contract"))

    def test_similar_length_items_sharing_generic_words_stay_separate(self):
        self.assertFalse(dup("Exposure from patching gaps", "Exposure from licensing gaps"))

    def test_single_word_never_matches(self):
        self.assertFalse(near_duplicate({"deck"}, [{"deck", "slide"}]))


class CleanupTests(unittest.TestCase):
    def test_question_mark_decision_dropped(self):
        out = clean({"decisions": [
            {"decision": "On our mainframes from what, 1960 or something like that?.", "evidence": "x"},
            {"decision": "Use a one-year term.", "evidence": "y"}]})
        self.assertEqual([d["decision"] for d in out["decisions"]], ["Use a one-year term."])

    def test_same_owner_duplicates_keep_the_specific_one(self):
        out = clean({"commitments": [
            {"owner": "Jordan", "action": "Send the deck", "status": "open"},
            {"owner": "Jordan", "action": "Send the 51 slide deck", "status": "open"}]})
        self.assertEqual([c["action"] for c in out["commitments"]], ["Send the 51 slide deck"])

    def test_different_owners_are_both_kept(self):
        out = clean({"commitments": [
            {"owner": "Jordan", "action": "Send the deck", "status": "open"},
            {"owner": "Dana", "action": "Send the deck", "status": "open"}]})
        self.assertEqual(len(out["commitments"]), 2)

    def test_different_work_for_same_owner_is_kept(self):
        out = clean({"commitments": [
            {"owner": "Jordan", "action": "Send the deck", "status": "open"},
            {"owner": "Jordan", "action": "Send the contract to Dana", "status": "open"}]})
        self.assertEqual(len(out["commitments"]), 2)


class PossibleItemTests(unittest.TestCase):
    def test_repeated_possible_items_collapse(self):
        items = [{"owner": "", "task": t, "evidence": "e"} for t in (
            "Send executive decks to Ribs",
            "Send the deck to Ribs when he has time",
            "Send the deck to Ribs in the next day or two",
            "Review the quarterly budget carefully")]
        out = nsp.add_next_step_items({"commitments": [], "follow_ups": []}, items)
        self.assertEqual(len(out["follow_ups"]), 2)


if __name__ == "__main__":
    unittest.main()
