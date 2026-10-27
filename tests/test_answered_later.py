import unittest

import ai

QUESTION = "What does the migration tooling stack look like today?"
ANSWER = "It is the standard migration tooling stack, so the stack looks fine today."


def transcript(asker, answerer, parked=False):
    first = f"[00:01] **{asker}**\n\n{QUESTION}"
    if parked:
        first += " I'll take that as a follow up."
    return (
        first + "\n\n"
        f"[00:02] **{answerer}**\n\n{ANSWER}\n"
    )


class AnsweredLaterTests(unittest.TestCase):
    def check(self, text):
        return ai._question_is_answered_later(QUESTION, [QUESTION], text)

    def test_another_person_answering_closes_the_question(self):
        self.assertTrue(self.check(transcript("Dana", "Sam")))

    def test_the_asker_restating_it_later_does_not_close_it(self):
        self.assertFalse(self.check(transcript("Dana", "Dana")))

    def test_a_parked_question_stays_open(self):
        self.assertFalse(self.check(transcript("Dana", "Sam", parked=True)))

    def test_old_labels_still_close_it(self):
        # "Remote" can be several people, so it is not treated as one asker.
        self.assertTrue(self.check(transcript("Remote", "Remote")))


if __name__ == "__main__":
    unittest.main()
