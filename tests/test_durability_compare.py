import copy, json, unittest
from tools.benchmark.durability_compare import durability_filter,review_prompt,prioritize

SOURCE='[00:01] **Remote**\nWho approves Platform Beta? It remains TBD.\n[00:15] **Remote**\nWe use Platform Beta for a sample demo.\n'
Q='Who approves Platform Beta? It remains TBD.'
class DurabilityReviewTests(unittest.TestCase):
    def test_question_contract_requires_unresolved_but_not_owner(self):
        prompt=review_prompt('open_questions',{'question':'Who approves Platform Beta?','evidence':Q},SOURCE,[])
        self.assertIn('No owner is required',prompt)
    def test_baseline_immutable_and_reject_unanchored(self):
        baseline={'open_questions':['Existing question?']}
        original=copy.deepcopy(baseline)
        recovered={'open_questions':[{'question':'Fake question','evidence':'Not present in transcript fake evidence'}]}
        enriched,diag=durability_filter(baseline,recovered,SOURCE,reviewer=lambda *a: (_ for _ in ()).throw(AssertionError('must not call')))
        self.assertEqual(original,baseline)
        self.assertEqual(['Existing question?'],enriched['open_questions'])
        self.assertEqual('weak_evidence',diag['rejected'][0]['reason_code'])
    def test_durable_question_accepted(self):
        evidence=Q
        candidate={'question':'Who approves Platform Beta?','evidence':evidence}
        def reviewer(prompt,schema):return json.dumps({'durable':True,'reason_code':'durable','rationale':'still TBD','evidence':evidence})
        result,diag=durability_filter({}, {'open_questions':[candidate]}, SOURCE,reviewer=reviewer)
        self.assertEqual(1,len(result['open_questions']))
        self.assertEqual(1,len(diag['accepted']))
    def test_demo_question_rejected_with_reason(self):
        candidate={'open_questions':[{'question':'How does the demo work?','evidence':'We use Platform Beta for a sample demo.'}]}
        def reviewer(prompt,schema):return json.dumps({'durable':False,'reason_code':'not_durable','rationale':'demo','evidence':''})
        result,diag=durability_filter({},candidate,SOURCE,reviewer=reviewer)
        self.assertEqual([],result['open_questions'])
        self.assertEqual('not_durable',diag['rejected'][0]['reason_code'])
    def test_category_specific_prompts(self):
        self.assertIn('settled',review_prompt('decisions',{},SOURCE,[]))
        self.assertIn('possible harmful consequence',review_prompt('risks',{},SOURCE,[]))
    def test_budget_is_diagnostic_not_acceptance(self):
        result,diag=durability_filter({}, {'open_questions':[{'question':'one','evidence':Q},{'question':'two','evidence':Q}]}, SOURCE,reviewer=lambda p,s:json.dumps({'durable':True,'reason_code':'durable','rationale':'yes','evidence':Q}),review_budget=1)
        self.assertEqual(1,len(diag['skipped_budget']))
        self.assertEqual(1,len(result['open_questions']))
if __name__=='__main__':unittest.main()
