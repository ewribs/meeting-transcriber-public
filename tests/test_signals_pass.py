import json
import unittest

import signals_pass as sp

TRANSCRIPT = (
    "[00:01] **Sam**\n\nThe Tanium renewal is 4.8 million for two years, so it goes to Beth, "
    "not Todd, because it is under five.\n\n"
    "[00:02] **Dana**\n\nOkay, that works. How many seats will the vendor need? "
    "I am worried the price could go up if we wait.\n\n"
    "[00:03] **Sam**\n\nThe vendor needs about 300 seats.\n"
)

ROWS = {
    "decisions": [
        {"decision": "The Tanium renewal goes to Beth because it is under five million.",
         "evidence": "it goes to Beth, not Todd, because it is under five."},
        {"decision": "Consider a second vendor.", "evidence": "that works"},
    ],
    "risks": [
        {"risk": "The price could go up if the team waits to renew.",
         "evidence": "I am worried the price could go up if we wait."},
        {"risk": "A made-up risk about staffing levels.", "evidence": "nothing like this was said"},
    ],
    "open_questions": [
        {"question": "How many seats will the vendor need?",
         "evidence": "How many seats will the vendor need?"},
        {"question": "Cheese is great", "evidence": "that works"},
    ],
}


def llm(rows, verdicts=None):
    def ask(prompt, response_format=None):
        if "Does the passage itself clearly say this" in prompt:
            return json.dumps({"says_it": not any(
                word in prompt for word in (verdicts or {}).get("refuse", [])), "reason": "x"})
        if "You are reviewing proposed" in prompt:
            kind = ("decisions" if "proposed decisions" in prompt
                    else "risks" if "proposed risks" in prompt else "open_questions")
            wanted = sp.LABELS[kind][0]
            label_for = (verdicts or {}).get(kind, {})
            count = prompt.count("\n   Quote:")
            return json.dumps({"verdicts": [
                {"number": n + 1, "label": label_for.get(n + 1, wanted)} for n in range(count)]})
        return json.dumps(rows)
    return ask


class SignalsTests(unittest.TestCase):
    def test_extract_checks_quotes_and_plain_rules(self):
        notes = []
        found = sp.extract(TRANSCRIPT, "Sample", llm(ROWS), "Alex", dropped=notes)
        self.assertEqual(len(found["decisions"]), 1)
        self.assertEqual(len(found["risks"]), 1)
        self.assertEqual(len(found["open_questions"]), 1)
        reasons = " ".join(reason for _n, _k, reason, _t in notes)
        self.assertIn("quote not found", reasons)
        self.assertIn("idea or a question", reasons)

    def test_second_look_removes_what_it_labels_otherwise(self):
        kept, removed = sp.run(
            TRANSCRIPT, "Sample",
            llm(ROWS, verdicts={"open_questions": {1: "answered_later"}}), "Alex")
        self.assertEqual(kept["open_questions"], [])
        self.assertEqual(len(removed["open_questions"]), 1)
        self.assertEqual(len(kept["decisions"]), 1)

    def test_a_failing_second_look_keeps_the_items(self):
        calls = {"n": 0}

        def ask(prompt, response_format=None):
            if "You are reviewing proposed" in prompt or "Does the passage" in prompt:
                raise RuntimeError("truncated")
            calls["n"] += 1
            return json.dumps(ROWS)
        kept, _ = sp.run(TRANSCRIPT, "Sample", ask, "Alex")
        self.assertEqual(len(kept["risks"]), 1)

    def test_a_model_error_gives_empty_lists(self):
        def broken(prompt, response_format=None):
            raise RuntimeError("truncated")
        kept, _ = sp.run(TRANSCRIPT, "Sample", broken, "Alex")
        self.assertEqual(kept, {"decisions": [], "risks": [], "open_questions": []})


class FilterTests(unittest.TestCase):
    def test_tasks_are_not_decisions(self):
        self.assertIn("task", sp._plain_filter("decisions", "Sam will create a summary for the renewal."))
        self.assertIsNone(sp._plain_filter("decisions", "The renewal goes to Beth because it is under five million."))

    def test_looked_at_the_data_is_not_a_question_worth_keeping(self):
        self.assertIsNotNone(sp._plain_filter("open_questions", "Will Avery have had a chance to look at the data?"))

    def test_risk_tier_follows_spoken_concern(self):
        rows = {"decisions": [], "open_questions": [], "risks": [
            {"risk": "The price could go up if the team waits to renew.",
             "evidence": "I am worried the price could go up if we wait."},
            {"risk": "The vendor has not yet sent the email, which delays the plan.",
             "evidence": "The vendor needs about 300 seats."}]}
        found = sp.extract(TRANSCRIPT, "Sample", llm(rows), "Alex")
        self.assertEqual([r["firm"] for r in found["risks"]], [True, False])


class QuoteRuleTests(unittest.TestCase):
    def test_two_items_sharing_a_quote_keep_the_first(self):
        rows = {"decisions": [], "open_questions": [], "risks": [
            {"risk": "The price could go up if the team waits to renew.",
             "evidence": "I am worried the price could go up if we wait."},
            {"risk": "The vendor may drop the offer if the team waits too long.",
             "evidence": "I am worried the price could go up if we wait."}]}
        found = sp.extract(TRANSCRIPT, "Sample", llm(rows), "Alex")
        self.assertEqual(len(found["risks"]), 1)

    def test_a_question_needs_a_real_question_or_unknown_in_the_quote(self):
        rows = {"decisions": [], "risks": [], "open_questions": [
            {"question": "What is the vendor price for the next renewal?",
             "evidence": "Okay, that works."}]}
        notes = []
        found = sp.extract(TRANSCRIPT, "Sample", llm(rows), "Alex", dropped=notes)
        self.assertEqual(found["open_questions"], [])

    def test_unsupported_items_are_removed(self):
        kept, removed = sp.run(
            TRANSCRIPT, "Sample",
            llm(ROWS, verdicts={"risks": {1: "routine_status"}}), "Alex")
        self.assertEqual(kept["risks"], [])


class SupportTests(unittest.TestCase):
    def test_an_item_the_passage_does_not_say_is_marked_unconfirmed(self):
        kept, _ = sp.run(TRANSCRIPT, "Sample",
                         llm(ROWS, verdicts={"refuse": ["The price could go up if the team waits"]}), "Alex")
        self.assertEqual(len(kept["risks"]), 1)
        self.assertFalse(kept["risks"][0]["firm"])
        self.assertTrue(kept["decisions"][0].get("firm", True))


class StatementLikeTests(unittest.TestCase):
    def test_confirmed_that_statements_are_not_firm_decisions(self):
        rows = {"risks": [], "open_questions": [], "decisions": [
            {"decision": "Dana confirmed that the team has a fair level of agreement.",
             "evidence": "it goes to Beth, not Todd, because it is under five."},
            {"decision": "The Tanium renewal goes to Beth because it is under five million.",
             "evidence": "The Tanium renewal is 4.8 million for two years"}]}
        kept, _ = sp.run(TRANSCRIPT, "Sample", llm(rows), "Alex")
        flags = {d["text"][:6]: d.get("firm", True) for d in kept["decisions"]}
        self.assertFalse(flags["Dana c"])
        self.assertTrue(flags["The Ta"])

    def test_more_task_verbs_are_rejected_as_decisions(self):
        self.assertIsNotNone(sp._plain_filter("decisions", "Sam will work with Dana on the move."))


if __name__ == "__main__":
    unittest.main()
