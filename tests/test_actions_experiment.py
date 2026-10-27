import json
import unittest

from tools.refactor import actions_experiment as experiment

TRANSCRIPT = (
    "[00:01] **Sam**\n\nI will send the renewal summary to Dana by Friday.\n\n"
    "[00:02] **Dana**\n\nGreat, thanks.\n"
)


def reply(rows):
    return lambda prompt, response_format=None: json.dumps({"actions": rows})


class ExtractTests(unittest.TestCase):
    def run_with(self, rows):
        return experiment.extract(TRANSCRIPT, "Sample", reply(rows), "Alex")

    def test_a_quoted_action_is_kept(self):
        items = self.run_with([{
            "owner": "Sam", "task": "Send the renewal summary to Dana", "due": "Friday",
            "evidence": "I will send the renewal summary to Dana by Friday."}])
        self.assertEqual(items[0]["owner"], "Sam")
        self.assertEqual(items[0]["due"], "Friday")

    def test_an_invented_quote_is_dropped(self):
        self.assertEqual(self.run_with([{
            "owner": "Sam", "task": "Send the deck", "due": "",
            "evidence": "I will send the deck tomorrow."}]), [])

    def test_unknown_owners_are_written_as_unknown(self):
        items = self.run_with([{
            "owner": "Remote", "task": "Send the renewal summary to Dana", "due": "",
            "evidence": "I will send the renewal summary to Dana by Friday."}])
        self.assertEqual(items[0]["owner"], "Unknown")

    def test_the_same_task_is_listed_once(self):
        row = {"owner": "Sam", "task": "Send the renewal summary to Dana", "due": "",
               "evidence": "I will send the renewal summary to Dana by Friday."}
        self.assertEqual(len(self.run_with([row, dict(row)])), 1)

    def test_a_model_error_gives_an_empty_list(self):
        def broken(prompt, response_format=None):
            raise RuntimeError("truncated")
        self.assertEqual(experiment.extract(TRANSCRIPT, "Sample", broken, "Alex"), [])


class LocateTests(unittest.TestCase):
    CHUNK = ("[00:05] **Sam**\n\nI pinged them this morning and said, hey, where you at? "
             "Still waiting on quotes from the reseller.\n")

    def test_a_quote_with_a_dropped_word_is_matched(self):
        found = experiment.locate(
            "I pinged them this morning and said where you at? Still waiting on quotes",
            self.CHUNK)
        self.assertIn("pinged them this morning", found)
        self.assertNotIn("**", found)

    def test_an_unrelated_quote_is_not_matched(self):
        self.assertIsNone(experiment.locate(
            "We will review the budget with finance next quarter", self.CHUNK))

    def test_very_short_quotes_are_never_matched_loosely(self):
        self.assertIsNone(experiment.locate("where you at", self.CHUNK))


class TidyAndPastTests(unittest.TestCase):
    def test_speech_leftovers_are_removed_from_the_start(self):
        self.assertEqual(experiment.tidy_task("I'll circle back with Dana"), "Circle back with Dana")
        self.assertEqual(experiment.tidy_task("I will send the deck"), "Send the deck")
        self.assertEqual(experiment.tidy_task("Send the deck"), "Send the deck")

    def test_something_the_speaker_says_already_happened_is_dropped(self):
        self.assertEqual(experiment.not_an_action(
            "Ping the vendor for quotes", "I pinged them this morning and said where you at?"),
            "already happened")

    def test_a_past_mention_with_a_plan_is_kept(self):
        self.assertIsNone(experiment.not_an_action(
            "Send the quotes to Dana",
            "I sent a draft last time, and I'll send the final one tomorrow."))


class FirmTests(unittest.TestCase):
    def test_first_person_by_the_owner_is_firm(self):
        self.assertTrue(experiment.is_firm("Sam", "Sam", "I'll send it Friday."))
        self.assertTrue(experiment.is_firm("Sam", "sam", "I'm working on the summary."))

    def test_a_group_plan_is_not_firm(self):
        self.assertFalse(experiment.is_firm("Sam", "Sam", "We will create packages."))

    def test_someone_elses_commitment_is_not_firm(self):
        self.assertFalse(experiment.is_firm("Dana", "Sam", "I'll send it Friday."))

    def test_a_conditional_first_person_commitment_is_still_firm(self):
        # The condition stays in the item's wording; it is still the person's commitment.
        self.assertTrue(experiment.is_firm(
            "Sam", "Sam", "If he's going to need 300, then I will negotiate a better price."))

    def test_unknown_owner_is_never_firm(self):
        self.assertFalse(experiment.is_firm("Unknown", "Sam", "I'll send it Friday."))
        self.assertFalse(experiment.is_firm("Sam", None, "I'll send it Friday."))


class NotAnActionTests(unittest.TestCase):
    def test_reasons(self):
        self.assertEqual(experiment.not_an_action("Wait for Avery to finalize it", ""),
                         "waiting is not an action")
        self.assertEqual(experiment.not_an_action("Put the note", "I'll put it right now."),
                         "done during the meeting")
        self.assertEqual(experiment.not_an_action("Meet with Splunk last week", ""),
                         "already happened")

    def test_real_actions_pass(self):
        self.assertIsNone(experiment.not_an_action(
            "Send the renewal summary to Dana by Friday", "I will send it by Friday."))
        self.assertIsNone(experiment.not_an_action(
            "Follow up with the vendor about waiting on quotes", ""))


if __name__ == "__main__":
    unittest.main()
