import unittest
from tools.benchmark.adversarial_compare import adversarial_audit

TRANSCRIPT = ('Speaker A: The lead remains TBD, and no one has been assigned yet.\n'
              'Speaker B: We will decide the lead after next week.\n'
              'Speaker A: During the demo, what happens if the button is clicked?\n'
              'Speaker B: The button shows a notification immediately.\n')

class AdversarialAuditTests(unittest.TestCase):
    def test_protected_baseline(self):
        base={'open_questions':['What is the approved budget?']}
        result, d=adversarial_audit(base,{'open_questions':[]},TRANSCRIPT,reviewer=lambda *_: None)
        self.assertEqual(result,base)
        self.assertEqual(d['accepted'],[])

    def test_supported_question_passes_with_second_approval(self):
        item='Who will be appointed as the lead?'
        def reviewer(*_):
            return {'accept':True,'support_quote':'The lead remains TBD, and no one has been assigned yet.',
                    'counterevidence_quote':'','reason':'Unresolved at end'}
        result,d=adversarial_audit({}, {'open_questions':[item]}, TRANSCRIPT, reviewer=reviewer)
        self.assertEqual(result['open_questions'],[item])
        self.assertEqual(len(d['accepted']),1)

    def test_unverifiable_quote_rejected(self):
        def reviewer(*_):return {'accept':True,'support_quote':'This quotation does not exist in the transcript anywhere.',
                                 'counterevidence_quote':'','reason':'OK'}
        result,d=adversarial_audit({}, {'open_questions':['Who leads?']},TRANSCRIPT,reviewer=reviewer)
        self.assertEqual(result['open_questions'],[])
        self.assertEqual(d['rejected'][0]['reason'],'insufficient_verbatim_support')

    def test_counterevidence_blocks_acceptance(self):
        def reviewer(*_):return {'accept':True,'support_quote':'During the demo, what happens if the button is clicked?',
                                 'counterevidence_quote':'The button shows a notification immediately.','reason':'not resolved'}
        result,d=adversarial_audit({}, {'open_questions':['What happens if the button is clicked?']},TRANSCRIPT,reviewer=reviewer)
        self.assertEqual(result['open_questions'],[])
        self.assertEqual(d['rejected'][0]['reason'],'unresolved_counterevidence')

    def test_review_error_fail_closed(self):
        def reviewer(*_):raise RuntimeError('model failed')
        result,d=adversarial_audit({}, {'open_questions':['Who leads?']},TRANSCRIPT,reviewer=reviewer)
        self.assertEqual(result['open_questions'],[])
        self.assertEqual(len(d['errors']),1)

if __name__=='__main__':unittest.main()
