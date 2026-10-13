import unittest
from tools.benchmark.question_appeal_compare import question_appeal

class ExpandedQuestionAppealTests(unittest.TestCase):
    def test_can_consider_locally_verified_question_rejected_globally(self):
        q={'question':'Which business group will own approvals?','evidence':'Which business group will own approvals?'}
        transcript='Which business group will own approvals? We have not decided yet.'
        def reviewer(prompt, schema):
            return {'explicit_question_quote':'Which business group will own approvals?',
                    'later_answer_quote':'','demo_or_hypothetical':False,
                    'business_issue':True,'explanation':'Ownership remains unresolved.'}
        out,diag=question_appeal({'open_questions':[]},{'open_questions':[]},{'open_questions':[]},transcript,
                                 reviewer=reviewer,locally_approved={'open_questions':[q]})
        self.assertEqual(len(out['open_questions']),1)
        self.assertEqual(len(diag['accepted']),1)

    def test_rejects_locally_verified_question_answered_later(self):
        q={'question':'Which team owns supplier approvals?','evidence':'Which team owns supplier approvals?'}
        transcript='Which team owns supplier approvals? Later we decided the finance team owns approvals.'
        def reviewer(prompt, schema):
            return {'explicit_question_quote':'Which team owns supplier approvals?',
                    'later_answer_quote':'the finance team owns approvals',
                    'demo_or_hypothetical':False,'business_issue':True,'explanation':'Answered.'}
        out,diag=question_appeal({'open_questions':[]},{'open_questions':[]},{'open_questions':[]},transcript,
                                 reviewer=reviewer,locally_approved={'open_questions':[q]})
        self.assertEqual(out['open_questions'],[])
        self.assertEqual(diag['rejected'][0]['reason'],'answered_in_meeting')

if __name__=='__main__': unittest.main()
