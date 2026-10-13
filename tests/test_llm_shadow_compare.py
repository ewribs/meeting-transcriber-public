import json
import unittest
from tools.benchmark.llm_shadow_compare import resolve_llm_shadow

class LLMShadowTests(unittest.TestCase):
    def setUp(self):
        self.quote='I will send the updated report tomorrow to Finance.'
        self.trace={'merged_events':[{'event_type':'commitment','subject':'send updated report','speaker':'Mic','evidence':[self.quote]}]}
        self.transcript='[01:00] Mic\n'+self.quote
    def llm(self,owner='Alex',evidence=None,category='commitments'):
        def respond(_prompt,_schema):
            return json.dumps({'items':[{'id':0,'category':category,'text':'Send updated report to Finance.','owner':owner,'evidence':evidence or self.quote,'reason':'explicit'}]})
        return respond
    def test_verified_owner_keeps_action(self):
        m,d=resolve_llm_shadow(self.trace,self.transcript,[{'name':'Alex'}],llm=self.llm())
        self.assertEqual(len(m['commitments']),1)
        self.assertEqual(m['commitments'][0]['owner'],'Alex')
    def test_unknown_owner_preserved_only_in_diagnostics(self):
        m,d=resolve_llm_shadow(self.trace,self.transcript,[],llm=self.llm('Remote'))
        self.assertEqual(m['commitments'],[])
        self.assertEqual(len(d['uncertain_ownership']),1)
    def test_invented_evidence_rejected(self):
        m,d=resolve_llm_shadow(self.trace,self.transcript,[{'name':'Alex'}],llm=self.llm(evidence='An unrelated statement with enough words.'))
        self.assertEqual(m['commitments'],[])
    def test_no_gold_input(self):
        m,d=resolve_llm_shadow(self.trace,self.transcript,[{'name':'Alex'}],llm=self.llm(category='none'))
        self.assertFalse(any(m[k] for k in ('commitments','decisions','risks','open_questions')))

if __name__=='__main__':unittest.main()
