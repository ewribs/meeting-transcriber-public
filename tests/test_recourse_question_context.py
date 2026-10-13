import unittest

from memory_reconciliation import stabilize_evidence_bound_recall


class RecourseQuestionContextTests(unittest.TestCase):
    def run_recovery(self, transcript):
        result, audit = stabilize_evidence_bound_recall(
            {'open_questions': [], 'follow_ups': []}, transcript)
        return result['open_questions'], audit

    def test_nearby_explicit_uncertainty_is_recovered(self):
        questions, audit = self.run_recovery(
            "What recourse do we have? I don't know if we have any.")
        self.assertEqual(len(questions), 1)
        self.assertEqual(audit[-1]['reason'], 'local_explicit_unresolved_recourse_question')

    def test_unrelated_distant_uncertainty_is_not_combined(self):
        questions, _ = self.run_recovery(
            'What recourse do we have? ' + 'The renewal is proceeding. ' * 70 +
            "I don't know if we have any other options.")
        self.assertEqual(questions, [])

    def test_explicit_answer_prevents_recovery(self):
        questions, _ = self.run_recovery(
            "What recourse do we have? I don't know if we have any. "
            "Our recourse is to terminate under section four.")
        self.assertEqual(questions, [])

    def test_no_explicit_uncertainty_no_recovery(self):
        questions, _ = self.run_recovery('What recourse do we have? We need to review the terms.')
        self.assertEqual(questions, [])


if __name__ == '__main__':
    unittest.main()
