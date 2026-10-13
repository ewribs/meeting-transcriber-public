import unittest
from tools.benchmark.question_appeal_compare import disputed_uncertainty_review

TRANSCRIPT=('We do not yet know the allocation for partner staffing and vendor spending. '
            'That will affect the team planning for next year. '
            'We also do not know the price of the sample gadget in this demonstration.')

class DisputeReviewTests(unittest.TestCase):
    def test_rescue_real_uncertainty_rejected_as_demo(self):
        q='What is the allocation for partner staffing and vendor spending?'
        quote='We do not yet know the allocation for partner staffing and vendor spending.'
        out,diag=disputed_uncertainty_review({'open_questions':[]},{'open_questions':[]},
            {'proposed':[{'question':q,'evidence_quote':quote}]},
            {'accepted':[],'rejected':[{'question':q,'reason':'demo_or_hypothetical'}]},TRANSCRIPT,
            reviewer=lambda p,s:{'durable_unresolved':True,'resolved_later':False,
                'demonstration_or_example':False,'specific_pending_business_consequence':True,
                'support_quote':quote,'explanation':'Pending planning input'})
        self.assertEqual(out['open_questions'],[q]);self.assertEqual(len(diag['rescued']),1)

    def test_remove_incidental_question_but_preserve_baseline(self):
        q='What is the price of the sample gadget?'
        quote='We also do not know the price of the sample gadget in this demonstration.'
        baseline={'open_questions':['Who owns the migration?']}
        out,diag=disputed_uncertainty_review(baseline,{'open_questions':[baseline['open_questions'][0],q]},
            {'proposed':[{'question':q,'evidence_quote':quote}]},
            {'accepted':[{'question':q}],'rejected':[]},TRANSCRIPT,
            reviewer=lambda p,s:{'durable_unresolved':False,'resolved_later':False,
                'demonstration_or_example':True,'specific_pending_business_consequence':False,
                'support_quote':quote,'explanation':'Demo example'})
        self.assertEqual(out['open_questions'],baseline['open_questions']);self.assertEqual(len(diag['removed']),1)

    def test_reject_invented_quote(self):
        q='What is the allocation for partner staffing and vendor spending?'
        quote='We do not yet know the allocation for partner staffing and vendor spending.'
        out,diag=disputed_uncertainty_review({'open_questions':[]},{'open_questions':[]},
            {'proposed':[{'question':q,'evidence_quote':quote}]},
            {'accepted':[],'rejected':[{'question':q,'reason':'demo_or_hypothetical'}]},TRANSCRIPT,
            reviewer=lambda p,s:{'durable_unresolved':True,'resolved_later':False,
                'demonstration_or_example':False,'specific_pending_business_consequence':True,
                'support_quote':'A statement that was not in the transcript at all.', 'explanation':''})
        self.assertEqual(out['open_questions'],[])
