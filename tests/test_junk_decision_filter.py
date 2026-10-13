import unittest

import ai

JUNK = [
    "Drop their.", "Drop 75.", "Drop everybody.", "Drop our.", "Drop big.", "Drop your.",
    "Decision was made.", "Decision is for your organization.",
    "Move forward with this.", "Not to fucking do that.",
    "Is, at one point we thought right after the session.",
    'To it, and he\'s saying, "Well, we should\'ve never agreed to that." That my problem.',
]

REAL = [
    "Mainframe is out.", "Decision to go with mender.", "Drop the spreadsheet.", "Drop Atlas.", "Drop HP.",
    "Continue with DB2 as one of our sources of database.",
    "Supply Hive was chosen because we pay based on suppliers, not users.",
    "We decided to move ahead with Lumen.", "to continue GEP through year-end",
    "To cancel the meeting about the MSA", "Proceed with a follow-up discussion with TD Global.",
    "Use the template for materials going to the board",
]


def clean(texts):
    memory = {"commitments": [], "risks": [], "open_questions": [], "follow_ups": [],
              "decisions": [{"decision": t, "evidence": "x"} for t in texts]}
    return [d["decision"] for d in ai._high_performance_memory_quality_cleanup(memory)["decisions"]]


class JunkDecisionTests(unittest.TestCase):
    def test_junk_is_dropped(self):
        for text in JUNK:
            with self.subTest(text=text):
                self.assertEqual(clean([text]), [])

    def test_real_decisions_are_kept(self):
        for text in REAL:
            with self.subTest(text=text):
                self.assertEqual(clean([text]), [text])


class FinalFilterTests(unittest.TestCase):
    def test_final_filter_drops_junk_and_keeps_the_rest(self):
        memory = {"decisions": [{"decision": "Drop their."}, {"decision": "Mainframe is out."},
                                {"decision": "Is this approved?"}], "risks": []}
        result = ai._drop_junk_decisions(memory)
        self.assertEqual([d["decision"] for d in result["decisions"]], ["Mainframe is out."])
        self.assertEqual(len(memory["decisions"]), 3)  # original is not changed

    def test_nothing_to_drop_returns_same_object(self):
        memory = {"decisions": [{"decision": "Mainframe is out."}]}
        self.assertIs(ai._drop_junk_decisions(memory), memory)

    def test_missing_decisions_are_fine(self):
        self.assertEqual(ai._drop_junk_decisions({"risks": []}), {"risks": []})


if __name__ == "__main__":
    unittest.main()
