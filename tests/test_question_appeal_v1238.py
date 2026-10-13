import unittest
from tools.benchmark.question_appeal_compare import question_appeal

TRANSCRIPT = "[00:01] **Remote**\nWe still don't know how much of the funding is allocated to third-party spending.\n[00:30] **Remote**\nWe will discuss the matter next month."
CLAIM = 'How much of the funding is allocated to third-party spending?'
QUOTE = "We still don't know how much of the funding is allocated to third-party spending."

class EvidencePreservationTests(unittest.TestCase):
    def reviewer(self, prompt, schema):
        return {'explicit_question_quote':'', 'later_answer_quote':'',
                'demo_or_hypothetical':False,'business_issue':True,
                'explanation':'A real pending allocation question.'}

    def test_statement_evidence_survives_without_explicit_question(self):
        result,diag=question_appeal({'open_questions':[]},
            {'open_questions':[CLAIM]}, {'open_questions':[]}, TRANSCRIPT,
            reviewer=self.reviewer, uncertainty_evidence={CLAIM:QUOTE})
        self.assertEqual(result['open_questions'],[CLAIM])
        self.assertEqual(len(diag['accepted']),1)

    def test_unrelated_evidence_cannot_be_substituted(self):
        result,diag=question_appeal({'open_questions':[]},
            {'open_questions':[CLAIM]}, {'open_questions':[]}, TRANSCRIPT,
            reviewer=self.reviewer, uncertainty_evidence={CLAIM:'We will discuss the matter next month.'})
        self.assertEqual(result['open_questions'],[])
        self.assertEqual(diag['rejected'][0]['reason'],'invalid_discovery_evidence')

    def test_answer_still_vetoes(self):
        text=TRANSCRIPT+'\n[01:00] **Remote**\nThe allocation is 25 percent.'
        def answered(prompt,schema):
            return {'explicit_question_quote':QUOTE,'later_answer_quote':'The allocation is 25 percent.',
                    'demo_or_hypothetical':False,'business_issue':True,'explanation':'Answered later'}
        result,diag=question_appeal({'open_questions':[]},
            {'open_questions':[CLAIM]}, {'open_questions':[]}, text,
            reviewer=answered, uncertainty_evidence={CLAIM:QUOTE})
        self.assertEqual(result['open_questions'],[])
        self.assertEqual(diag['rejected'][0]['reason'],'answered_in_meeting')

    def test_non_durable_still_vetoes(self):
        def nondurable(prompt,schema):
            return {'explicit_question_quote':QUOTE,'later_answer_quote':'',
                    'demo_or_hypothetical':False,'business_issue':False,'explanation':'Not durable'}
        result,diag=question_appeal({'open_questions':[]},
            {'open_questions':[CLAIM]}, {'open_questions':[]}, TRANSCRIPT,
            reviewer=nondurable, uncertainty_evidence={CLAIM:QUOTE})
        self.assertEqual(result['open_questions'],[])
