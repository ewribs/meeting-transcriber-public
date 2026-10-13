import unittest
from tools.benchmark.question_appeal_compare import question_appeal

TRANSCRIPT=('Speaker A: Who will approve the new supplier contract under Project Delta? '
            'That is still undecided.\n'
            'Speaker B: In the demo, what happens when you click the icon?\n'
            'Speaker A: Clicking the icon opens the settings page.\n')

class QuestionAppealTests(unittest.TestCase):
    def test_rescue_unanswered_business_question(self):
        q='Who will approve the new supplier contract under Project Delta?'
        def reviewer(*_): return {'explicit_question_quote':q,'later_answer_quote':'','demo_or_hypothetical':False,'business_issue':True,'explanation':'Undecided'}
        out,diag=question_appeal({'open_questions':[]},{'open_questions':[q]},{'open_questions':[]},TRANSCRIPT,reviewer=reviewer)
        self.assertEqual(out['open_questions'],[q]);self.assertEqual(len(diag['accepted']),1)
    def test_demos_stay_excluded(self):
        q='what happens when you click the icon?'
        def reviewer(*_):return {'explicit_question_quote':'In the demo, what happens when you click the icon?','later_answer_quote':'','demo_or_hypothetical':True,'business_issue':False,'explanation':'demo'}
        out,_=question_appeal({}, {'open_questions':[q]}, {},TRANSCRIPT,reviewer=reviewer)
        self.assertFalse(out.get('open_questions'))
    def test_answered_questions_stay_excluded(self):
        q='what happens when you click the icon?'
        def reviewer(*_):return {'explicit_question_quote':'In the demo, what happens when you click the icon?','later_answer_quote':'Clicking the icon opens the settings page.','demo_or_hypothetical':False,'business_issue':True,'explanation':'answered'}
        out,diag=question_appeal({}, {'open_questions':[q]}, {},TRANSCRIPT,reviewer=reviewer)
        self.assertFalse(out.get('open_questions'));self.assertEqual(diag['rejected'][0]['reason'],'answered_in_meeting')
    def test_no_unanchored_quote(self):
        def reviewer(*_):return {'explicit_question_quote':'This statement is absolutely not present in the transcript','later_answer_quote':'','demo_or_hypothetical':False,'business_issue':True,'explanation':'none'}
        out,diag=question_appeal({}, {'open_questions':['Who signs?']},{},TRANSCRIPT,reviewer=reviewer)
        self.assertFalse(out.get('open_questions'));self.assertEqual(diag['rejected'][0]['reason'],'missing_exact_question_evidence')
    def test_baseline_untouched(self):
        base={'open_questions':['Who owns existing records?'],'decisions':[{'decision':'Keep existing structure'}]}
        out,_=question_appeal(base,{},base,TRANSCRIPT,reviewer=lambda *_: None)
        self.assertEqual(out,base)

if __name__=='__main__': unittest.main()
