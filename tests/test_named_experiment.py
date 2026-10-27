import unittest

from tools.refactor import named_experiment as ne


class ReportTests(unittest.TestCase):
    OLD = {"commitments": [{"owner": "Unknown", "action": "Send the file"}],
           "decisions": [], "open_questions": [], "risks": [], "follow_ups": []}
    NEW = {"commitments": [{"owner": "Pat Lee", "action": "Send the file"}],
           "decisions": [{"decision": "Go ahead"}], "open_questions": [],
           "risks": [], "follow_ups": []}

    def test_counts_unowned(self):
        self.assertEqual(ne.summarise(self.OLD)["commitments_unowned"], 1)
        self.assertEqual(ne.summarise(self.NEW)["commitments_unowned"], 0)

    def test_report_shows_both_sides(self):
        text = ne.report("run", self.OLD, self.NEW)
        self.assertIn("[Unknown] Send the file", text)
        self.assertIn("[Pat Lee] Send the file", text)
        self.assertIn("| commitments_unowned | 1 | 0 |", text)


if __name__ == "__main__":
    unittest.main()
