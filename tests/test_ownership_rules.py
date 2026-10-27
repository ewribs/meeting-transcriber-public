import unittest

import ai
import config
import transcript_view as tv

SELF = str(config.SELF_NAME)


class OwnerForSpeakerTests(unittest.TestCase):
    def test_user_person_and_unknown(self):
        self.assertEqual(tv.owner_for_speaker("Mic"), SELF)
        self.assertEqual(tv.owner_for_speaker(SELF), SELF)
        self.assertEqual(tv.owner_for_speaker("Pat Lee"), "Pat Lee")
        for label in ("Remote", "Unidentified", "unknown", "Speaker A", "", None):
            self.assertEqual(tv.owner_for_speaker(label), "", label)


class FallbackOwnerTests(unittest.TestCase):
    def owners(self, speaker):
        chunk = (f"[00:05] **{speaker}**\n\n"
                 "My action item is to send the budget file to finance.\n")
        return [item["owner"] for item in ai._explicit_commitment_fallbacks(chunk)]

    def test_each_kind_of_speaker(self):
        self.assertEqual(self.owners("Mic"), [SELF])
        self.assertEqual(self.owners("Pat Lee"), ["Pat Lee"])
        self.assertEqual(self.owners("Remote"), ["Unknown"])
        self.assertEqual(self.owners("Unidentified"), ["Unknown"])


class AuthoritativeOwnerTests(unittest.TestCase):
    def owner(self, speaker):
        quote = "I will send the budget file to finance tomorrow"
        transcript = f"[00:05] **{speaker}**\n\n{quote}.\n"
        return ai._authoritative_first_person_owner([quote], transcript, {})

    def test_named_person_owns_their_promise(self):
        self.assertEqual(self.owner("Pat Lee"), "Pat Lee")

    def test_unidentified_and_remote_stay_unowned(self):
        self.assertEqual(self.owner("Unidentified"), "")
        self.assertEqual(self.owner("Remote"), "")


if __name__ == "__main__":
    unittest.main()


class QuestionRejectionReasonTests(unittest.TestCase):
    def test_a_question_answered_later_says_so(self):
        transcript = (
            "[00:05] **Pat Lee**\n\nWhat is the deadline for the vendor contract renewal?\n\n"
            "[00:20] **Sam**\n\nThe vendor contract renewal deadline is Friday, so we will sign it now.\n")
        question = "What is the deadline for the vendor contract renewal?"
        item = {"question": question, "evidence": [question]}
        result = ai._diagnose_resolved_rejection("questions", item, transcript)
        self.assertNotEqual(result["reason"], "unknown_validator_rejection")


class WhetherQuestionTests(unittest.TestCase):
    def test_whether_form_is_a_question(self):
        self.assertTrue(ai._resolved_question_is_well_formed(
            "Whether the tool will pull in external information"))
        self.assertTrue(ai._resolved_question_is_well_formed(
            "Whether Riley will make the board aware of the situation"))

    def test_other_non_questions_are_still_refused(self):
        for text in ("The vendor will send the contract on Friday",
                     "Whether",
                     "Whether yes? and then more words follow here",
                     "Whether [12:30] **Pat** said it"):
            self.assertFalse(ai._resolved_question_is_well_formed(text), text)




class KeepVerifiedQuestionTests(unittest.TestCase):
    def test_a_verified_whether_question_survives_normalizing(self):
        text = "Whether the tool will pull in external information"
        self.assertEqual(ai._normalize_open_questions([text]), [])
        self.assertEqual(ai._normalize_open_questions_keeping_verified([text], {text}), [text])

    def test_an_unverified_one_is_dropped_as_before(self):
        text = "Whether the tool will pull in external information"
        self.assertEqual(ai._normalize_open_questions_keeping_verified([text], set()), [])

    def test_ordinary_questions_are_unchanged(self):
        text = "What is the deadline for the vendor contract renewal?"
        self.assertEqual(ai._normalize_open_questions_keeping_verified([text], {text}), [text])
        self.assertEqual(ai._normalize_open_questions([text]), [text])
