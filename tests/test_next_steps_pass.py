import json
import os
import unittest
from unittest import mock

import next_steps_pass as nsp

TRANSCRIPT = (
    "Mic: Can you send me the pricing sheet tomorrow?\n"
    "Remote: Sure, I will send the pricing sheet tomorrow.\n"
    "Mic: I will update the project plan by Friday.\n"
    "Remote: We already sent the contract last week.\n"
)


def reply(*rows):
    return json.dumps({"next_steps": [
        {"owner": o, "task": t, "evidence": e} for o, t, e in rows]})


class ExtractTests(unittest.TestCase):
    def run_pass(self, ask, **kw):
        return nsp.extract_next_steps(TRANSCRIPT, "Test meeting", ask, "Sam", **kw)

    def test_accepts_exact_quote_and_maps_mic(self):
        ask = lambda p, response_format=None: reply(
            ("Mic", "Update the project plan by Friday", "I will update the project plan by Friday"))
        items = self.run_pass(ask)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["owner"], "Sam")

    def test_rejects_invented_quote(self):
        ask = lambda p, response_format=None: reply(
            ("Unknown", "Send the signed contract today", "I will send the signed contract today"))
        self.assertEqual(self.run_pass(ask), [])

    def test_remote_and_unknown_owner_blank(self):
        ask = lambda p, response_format=None: reply(
            ("Remote", "Send the pricing sheet tomorrow", "I will send the pricing sheet tomorrow"),
            ("Unknown", "Update the project plan again", "I will update the project plan by Friday"))
        owners = [i["owner"] for i in self.run_pass(ask)]
        self.assertEqual(owners, ["", ""])

    def test_rejects_past_tense_evidence(self):
        ask = lambda p, response_format=None: reply(
            ("Unknown", "Send the contract to them", "We already sent the contract"))
        self.assertEqual(self.run_pass(ask), [])

    def test_dedupes_same_task(self):
        ask = lambda p, response_format=None: reply(
            ("Mic", "Update the project plan", "I will update the project plan"),
            ("Mic", "update the  project plan", "I will update the project plan"))
        self.assertEqual(len(self.run_pass(ask)), 1)

    def test_truncation_splits_and_retries(self):
        calls = []

        def ask(prompt, response_format=None):
            calls.append(prompt)
            if len(calls) == 1:
                raise RuntimeError("reply truncated at ceiling")
            return reply()

        halves = lambda chunk: [chunk[:20], chunk[20:]]
        self.assertEqual(self.run_pass(ask, split=halves), [])
        self.assertEqual(len(calls), 3)

    def test_other_errors_raise(self):
        def ask(prompt, response_format=None):
            raise RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            self.run_pass(ask)

    def test_rejects_open_option_tasks(self):
        ask = lambda p, response_format=None: reply(
            ("Mic", "Consider updating the project plan", "I will update the project plan by Friday"),
            ("Mic", "Evaluate whether to update the plan", "I will update the project plan by Friday"),
            ("Mic", "Regroup later about the plan", "I will update the project plan by Friday"))
        self.assertEqual(self.run_pass(ask), [])

    def test_bad_json_is_ignored(self):
        self.assertEqual(self.run_pass(lambda p, response_format=None: "not json"), [])


class AddItemsTests(unittest.TestCase):
    def test_adds_possible_and_skips_duplicates(self):
        memory = {"commitments": [{"action": "Update the project plan by Friday"}],
                  "follow_ups": []}
        items = [
            {"owner": "Sam", "task": "Update the project plan by Friday", "evidence": "x"},
            {"owner": "", "task": "Send the pricing sheet tomorrow", "evidence": "y"},
        ]
        out = nsp.add_next_step_items(memory, items)
        self.assertEqual(len(out["follow_ups"]), 1)
        self.assertTrue(out["follow_ups"][0].startswith("Possible commitment (unconfirmed): "))
        self.assertEqual(memory["follow_ups"], [])

    def test_owner_in_label_and_limit(self):
        tasks = ["Review the budget spreadsheet", "Call the vendor about shipping",
                 "Draft the onboarding checklist", "Schedule the quarterly workshop",
                 "Collect feedback from customers", "Prepare the hiring proposal"]
        items = [{"owner": "Sam", "task": t, "evidence": "e"} for t in tasks]
        out = nsp.add_next_step_items({"follow_ups": []}, items, limit=3)
        self.assertEqual(len(out["follow_ups"]), 3)
        self.assertIn("owner Sam", out["follow_ups"][0])


class RunTests(unittest.TestCase):
    def test_errors_are_swallowed(self):
        def ask(prompt, response_format=None):
            raise RuntimeError("boom")
        memory = {"follow_ups": []}
        out = nsp.run_next_steps_pass("m", TRANSCRIPT, memory, ask, None, "Sam")
        self.assertIs(out, memory)

    def test_off_switch(self):
        def ask(prompt, response_format=None):
            raise AssertionError("should not be called")
        memory = {"follow_ups": []}
        with mock.patch.dict(os.environ, {"MT_NEXT_STEPS_PASS": "0"}):
            self.assertIs(nsp.run_next_steps_pass("m", TRANSCRIPT, memory, ask, None, "Sam"), memory)


SPEAKER_TRANSCRIPT = (
    "# Meeting Transcript\n\n"
    "[00:00] **Remote**\n\nI will come back with a confirmation on Friday.\n\n\n"
    "[00:10] **Mic**\n\nI will update the project plan by Friday.\n\n\n"
)


class OwnerCheckTests(unittest.TestCase):
    def run_owner(self, owner, quote):
        ask = lambda p, response_format=None: reply((owner, "Send the confirmation to the team", quote))
        return nsp.extract_next_steps(SPEAKER_TRANSCRIPT, "m", ask, "Sam")

    def test_self_owner_blanked_when_quote_is_in_remote_turn(self):
        items = self.run_owner("Mic", "I will come back with a confirmation on Friday")
        self.assertEqual(items[0]["owner"], "")

    def test_self_owner_kept_when_quote_is_in_mic_turn(self):
        items = self.run_owner("Mic", "I will update the project plan by Friday")
        self.assertEqual(items[0]["owner"], "Sam")

    def test_other_names_are_not_touched(self):
        items = self.run_owner("Dana", "I will come back with a confirmation on Friday")
        self.assertEqual(items[0]["owner"], "Dana")

    def test_unknown_speaker_leaves_owner_alone(self):
        ask = lambda p, response_format=None: reply(("Mic", "Send the confirmation to the team", "I will update the project plan by Friday"))
        items = nsp.extract_next_steps("no headers here. I will update the project plan by Friday.", "m", ask, "Sam")
        self.assertEqual(items[0]["owner"], "Sam")


class VerifyTests(unittest.TestCase):
    ITEMS = [
        {"owner": "", "task": "Send the notes tomorrow", "evidence": "I will send you the notes tomorrow"},
        {"owner": "", "task": "Engage finance partners on measures", "evidence": "we are going to have finance partners running alongside them"},
        {"owner": "", "task": "Consider removing the link", "evidence": "maybe we could remove the link"},
    ]
    TEXT = ("I will send you the notes tomorrow. Also we are going to have finance partners "
            "running alongside them. And maybe we could remove the link.")

    def verdicts(self, *labels):
        return lambda p, response_format=None: json.dumps({"verdicts": [
            {"number": n, "label": label} for n, label in enumerate(labels, 1)]})

    def test_only_commitments_are_kept(self):
        kept = nsp.verify_next_steps(self.ITEMS, self.TEXT,
                                     self.verdicts("commitment", "plan_description", "suggestion"))
        self.assertEqual([i["task"] for i in kept], ["Send the notes tomorrow"])

    def test_already_done_is_dropped(self):
        kept = nsp.verify_next_steps(self.ITEMS, self.TEXT,
                                     self.verdicts("already_done", "commitment", "commitment"))
        self.assertEqual(len(kept), 2)

    def test_missing_verdicts_keep_the_item(self):
        kept = nsp.verify_next_steps(self.ITEMS, self.TEXT, self.verdicts("plan_description"))
        self.assertEqual(len(kept), 2)

    def test_model_failure_keeps_everything(self):
        def ask(prompt, response_format=None):
            raise RuntimeError("reply truncated")
        self.assertEqual(len(nsp.verify_next_steps(self.ITEMS, self.TEXT, ask)), 3)
        self.assertEqual(len(nsp.verify_next_steps(self.ITEMS, self.TEXT, lambda p, response_format=None: "nope")), 3)

    def test_prompt_includes_surrounding_transcript(self):
        seen = []
        def ask(prompt, response_format=None):
            seen.append(prompt)
            return json.dumps({"verdicts": []})
        nsp.verify_next_steps(self.ITEMS[:1], "Intro words. I will send you the notes tomorrow. Closing words.", ask)
        self.assertIn("Intro words", seen[0])
        self.assertIn("Closing words", seen[0])

    def test_run_pass_uses_verification_and_can_be_switched_off(self):
        calls = []
        def ask(prompt, response_format=None):
            calls.append(prompt)
            if "reviewing proposed next steps" in prompt:
                return json.dumps({"verdicts": [{"number": 1, "label": "plan_description"}]})
            return reply(("Unknown", "Send the pricing sheet tomorrow", "I will send the pricing sheet tomorrow"))
        out = nsp.run_next_steps_pass("m", TRANSCRIPT, {"follow_ups": []}, ask, None, "Sam")
        self.assertEqual(out["follow_ups"], [])
        with mock.patch.dict(os.environ, {"MT_NEXT_STEPS_VERIFY": "0"}):
            out = nsp.run_next_steps_pass("m", TRANSCRIPT, {"follow_ups": []}, ask, None, "Sam")
        self.assertEqual(len(out["follow_ups"]), 1)


if __name__ == "__main__":
    unittest.main()
