import copy, json, unittest
from tools.benchmark.global_veto_compare import global_veto,global_prompt

TRANSCRIPT='[00:01] Speaker A: Who will approve Project Delta? It remains TBD.\n[05:00] Speaker B: We can demonstrate adding a vendor.\n[06:00] Speaker A: The demo is complete.\n'
class GlobalVetoTests(unittest.TestCase):
    def test_baseline_immutable(self):
        baseline={'open_questions':['Existing outstanding question?']};original=copy.deepcopy(baseline)
        out,diag=global_veto(baseline,{},TRANSCRIPT,reviewer=lambda *a: (_ for _ in ()).throw(AssertionError('should not call')))
        self.assertEqual(out,baseline);self.assertEqual(baseline,original)
    def test_reject_demonstration(self):
        proposed={'open_questions':[{'question':'How do we add a vendor?','evidence':'We can demonstrate adding a vendor.'}]}
        result,diag=global_veto({},proposed,TRANSCRIPT,reviewer=lambda *a:json.dumps({'keep_indices':[],'reasons':[{'index':0,'reason':'demo'}]}))
        self.assertEqual([],result.get('open_questions',[]))
    def test_keep_grounded_unresolved(self):
        proposed={'open_questions':[{'question':'Who approves Project Delta?','evidence':'Who will approve Project Delta? It remains TBD.'}]}
        result,diag=global_veto({},proposed,TRANSCRIPT,reviewer=lambda *a:json.dumps({'keep_indices':[0],'reasons':[]}))
        self.assertEqual(1,len(result['open_questions']))
    def test_invalid_indices_fail_closed(self):
        proposed={'risks':[{'risk':'Test risk','evidence':'We can demonstrate adding a vendor.'}]}
        result,diag=global_veto({},proposed,TRANSCRIPT,reviewer=lambda *a:json.dumps({'keep_indices':[20],'reasons':[]}))
        self.assertEqual([],result.get('risks',[]));self.assertTrue(diag['errors'])
    def test_full_context_guard(self):
        result,diag=global_veto({'decisions':['Kept']},{'decisions':[{'decision':'New'}]},'x'*200,reviewer=lambda *a:'{}',max_chars=100)
        self.assertEqual(['Kept'],result['decisions']);self.assertTrue(diag['errors'])
    def test_prompt_mentions_entire_meeting(self):
        self.assertIn('ENTIRE meeting',global_prompt('open_questions',[],[],TRANSCRIPT))
if __name__=='__main__':unittest.main()
