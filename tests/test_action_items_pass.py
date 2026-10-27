import json
import unittest

import action_items_pass as pass_

TRANSCRIPT = (
    "[00:01] **Sam**\n\nI will send the renewal summary to Dana by Friday. "
    "We could also look at a second vendor someday.\n\n"
    "[00:02] **Dana**\n\nOkay. I'll review the budget with finance on Monday.\n"
)
ROWS = [
    {"owner": "Sam", "task": "Send the renewal summary to Dana", "due": "Friday",
     "evidence": "I will send the renewal summary to Dana by Friday."},
    {"owner": "Sam", "task": "Look at a second vendor", "due": "not specified",
     "evidence": "We could also look at a second vendor someday."},
    {"owner": "Dana", "task": "Review the budget with finance", "due": "Monday",
     "evidence": "I'll review the budget with finance on Monday."},
]


def fake_llm(rows, verdict="commitment"):
    def ask(prompt, response_format=None):
        if "reviewing proposed next steps" in prompt:
            count = prompt.count("Proposed next step:")
            return json.dumps({"verdicts": [
                {"number": n + 1, "label": verdict} for n in range(count)]})
        return json.dumps({"actions": rows})
    return ask


def run(memory, ask):
    return pass_.run_action_items_pass("Sample", TRANSCRIPT, memory, ask, None, "Alex")


class ActionItemsPassTests(unittest.TestCase):
    def test_firm_items_become_commitments_and_the_rest_are_listed_separately(self):
        memory, ok = run({"commitments": [], "follow_ups": []}, fake_llm(ROWS))
        self.assertTrue(ok)
        owners = [(c["owner"], c["due"]) for c in memory["commitments"]]
        self.assertEqual(owners, [("Sam", "Friday"), ("Dana", "Monday")])
        self.assertEqual(memory["other_next_steps"], ["Sam - Look at a second vendor"])

    def test_old_strict_commitments_are_kept_unless_they_repeat_a_new_one(self):
        old = [{"owner": "Sam", "action": "Send the renewal summary", "status": "open"},
               {"owner": "Dana", "action": "Update the vendor tracker", "status": "open"}]
        memory, _ = run({"commitments": old, "follow_ups": []}, fake_llm(ROWS))
        actions = [c["action"] for c in memory["commitments"]]
        self.assertIn("Update the vendor tracker", actions)
        self.assertEqual(sum("renewal summary" in a for a in actions), 1)

    def test_old_possible_commitment_lines_are_replaced(self):
        memory, _ = run({"commitments": [], "follow_ups": [
            "Possible commitment (unconfirmed): Something old.",
            "Possible risk (unconfirmed): Keep this one."]}, fake_llm(ROWS))
        self.assertEqual(memory["follow_ups"], ["Possible risk (unconfirmed): Keep this one."])

    def test_a_failure_leaves_the_memory_unchanged_and_says_so(self):
        original = {"commitments": [{"owner": "Sam", "action": "x"}], "follow_ups": []}

        def broken(prompt, response_format=None):
            raise KeyError("boom")
        memory, ok = run(original, broken)
        self.assertEqual(memory, original)
        self.assertFalse(ok)

    def test_it_can_be_switched_off(self):
        import os
        os.environ["MT_ACTION_ITEMS_PASS"] = "0"
        try:
            memory, ok = run({"commitments": []}, fake_llm(ROWS))
        finally:
            del os.environ["MT_ACTION_ITEMS_PASS"]
        self.assertFalse(ok)

    def test_no_due_text_is_not_shown(self):
        self.assertEqual(pass_.clean_due("not specified"), "")
        self.assertEqual(pass_.clean_due(" Friday "), "Friday")


if __name__ == "__main__":
    unittest.main()
