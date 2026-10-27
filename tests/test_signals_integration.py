import json
import unittest

import ai
import signals_pass as sp

DRAFT = (
    "# Meeting Summary\n\n## Decisions\n\nNone identified.\n\n## Action Items\n\nx\n\n"
    "## Risks and Concerns\n\nNone identified.\n\n## Open Questions\n\nNone identified.\n\n"
    "## Topics\n\nNone identified.\n"
)
TRANSCRIPT = (
    "[00:01] **Sam**\n\nThe Tanium renewal is 4.8 million, so it goes to Beth, not Todd, "
    "because it is under five.\n\n"
    "[00:02] **Dana**\n\nOkay, that works. How many seats will the vendor need?\n"
)
ROWS = {
    "decisions": [{"decision": "The Tanium renewal goes to Beth because it is under five million.",
                   "evidence": "it goes to Beth, not Todd, because it is under five."}],
    "risks": [],
    "open_questions": [{"question": "How many seats will the vendor need?",
                        "evidence": "How many seats will the vendor need?"}],
}


def llm(rows):
    def ask(prompt, response_format=None):
        if "Does the passage itself clearly say this" in prompt:
            return json.dumps({"says_it": True, "reason": "x"})
        if "You are reviewing proposed" in prompt:
            count = prompt.count("\n   Quote:")
            kind_label = ("decision" if "proposed decisions" in prompt else "open")
            return json.dumps({"verdicts": [
                {"number": n + 1, "label": kind_label} for n in range(count)]})
        return json.dumps(rows)
    return ask


class ComposeTests(unittest.TestCase):
    def test_unconfirmed_blocks_are_labelled_under_each_section(self):
        memory = {"decisions": [{"decision": "Tanium goes to Beth."}], "commitments": [],
                  "risks": [], "open_questions": [], "topics": [],
                  "other_decisions": ["Vendor X may be chosen."],
                  "other_risks": ["Price may rise."],
                  "other_questions": ["How many seats are needed?"]}
        result = ai.compose_summary_with_meeting_memory(DRAFT, memory)
        self.assertIn("- Tanium goes to Beth.", result)
        self.assertIn("**Possible decisions (unconfirmed)**\n\n- Vendor X may be chosen.", result)
        self.assertIn("**Possible risks (unconfirmed)**\n\n- Price may rise.", result)
        self.assertIn("**Possible open questions (unconfirmed)**\n\n- How many seats are needed?", result)

    def test_without_extra_items_the_sections_are_unchanged(self):
        memory = {"decisions": [], "commitments": [], "risks": [], "open_questions": [], "topics": []}
        result = ai.compose_summary_with_meeting_memory(DRAFT, memory)
        self.assertNotIn("unconfirmed", result)


class RunSignalsPassTests(unittest.TestCase):
    def test_new_items_replace_questions_and_keep_older_decisions(self):
        memory = {"decisions": [{"decision": "An older strict decision about hiring."}],
                  "risks": [], "open_questions": ["An old meh question?"]}
        result, ok = sp.run_signals_pass("Sample", TRANSCRIPT, memory, llm(ROWS), "Alex")
        self.assertTrue(ok)
        texts = [d["decision"] for d in result["decisions"]]
        self.assertIn("An older strict decision about hiring.", texts)
        self.assertEqual(result["open_questions"], ["How many seats will the vendor need?"])

    def test_a_decision_that_repeats_an_action_item_is_dropped(self):
        memory = {"decisions": [], "risks": [], "open_questions": [],
                  "commitments": [{"owner": "Sam", "action": "Send the Tanium renewal to Beth"}]}
        result, ok = sp.run_signals_pass("Sample", TRANSCRIPT, memory, llm(ROWS), "Alex")
        self.assertTrue(ok)
        self.assertEqual(result["decisions"], [])

    def test_older_decisions_that_are_tasks_or_secondhand_are_not_firm(self):
        memory = {"decisions": [
            {"decision": "Sam will follow up on the vendor contract."},
            {"decision": "Morgan asked the vendor to extend the licence."},
            {"decision": "The hiring freeze runs through the end of the quarter."}],
            "risks": [], "open_questions": [], "commitments": []}
        result, ok = sp.run_signals_pass("Sample", TRANSCRIPT, memory, llm(ROWS), "Alex")
        firm = [d["decision"] for d in result["decisions"]]
        self.assertIn("The hiring freeze runs through the end of the quarter.", firm)
        self.assertNotIn("Morgan asked the vendor to extend the licence.", firm)
        self.assertNotIn("Sam will follow up on the vendor contract.", firm)
        self.assertIn("Morgan asked the vendor to extend the licence.", result["other_decisions"])
        self.assertNotIn("Sam will follow up on the vendor contract.", result["other_decisions"])

    def test_two_firm_risks_about_the_same_thing_keep_one(self):
        memory = {"decisions": [], "open_questions": [], "commitments": [], "risks": [
            {"risk": "Canadian wildfires could force outdoor events to be cancelled."},
            {"risk": "Outdoor events might be cancelled because of Canadian wildfires smoke."}]}
        result, _ok = sp.run_signals_pass("Sample", TRANSCRIPT, memory, llm(ROWS), "Alex")
        self.assertEqual(len(result["risks"]), 1)

    def test_a_failure_leaves_the_memory_alone(self):
        memory = {"decisions": [], "risks": [], "open_questions": ["Old question?"]}
        original = sp.run
        sp.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            result, ok = sp.run_signals_pass("Sample", TRANSCRIPT, memory, llm(ROWS), "Alex")
        finally:
            sp.run = original
        self.assertFalse(ok)
        self.assertEqual(result["open_questions"], ["Old question?"])


if __name__ == "__main__":
    unittest.main()
