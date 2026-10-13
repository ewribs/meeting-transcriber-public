import unittest
from tools.benchmark.category_recovery_compare import select_contexts, recover, proposed_prompt, review_prompt

TEXT='[00:01] **Remote**\nWho owns Platform Beta approvals? That is still TBD.\n\n[00:10] **Remote**\nWe will use the existing policy for contract approvals.\n'
class CategoryRecoveryTests(unittest.TestCase):
    def test_open_question_context(self):
        self.assertTrue(any('TBD' in x['source'] for x in select_contexts(TEXT,'open_questions')))
    def test_distinct_category_rules(self):
        self.assertIn('need not have an owner',review_prompt('open_questions',{},TEXT,[]))
        self.assertIn('settled choice',review_prompt('decisions',{},TEXT,[]))
    def test_fail_closed_unanchored(self):
        def llm(prompt,schema):
            if 'Extract only durable' in prompt:
                return '{"items":[{"category":"open_questions","claim":"Who approves Platform Beta?","evidence":"fabricated evidence that is definitely long enough","owner":""}]}'
            raise AssertionError('review must not run for unsupported evidence')
        memory,diag=recover({},TEXT,[],llm=llm)
        self.assertEqual([],memory['open_questions'])
        self.assertTrue(any(x['reason']=='unanchored proposed evidence' for x in diag['rejected']))
    def test_valid_question_without_owner(self):
        quote='Who owns Platform Beta approvals? That is still TBD.'
        def llm(prompt,schema):
            if 'Extract only durable' in prompt:
                if 'open_questions' in prompt.split(' from provided SOURCE')[0]:
                    return __import__('json').dumps({'items':[{'category':'open_questions','claim':'Who owns Platform Beta approvals?','evidence':quote,'owner':''}]})
                return '{"items":[]}'
            return __import__('json').dumps({'valid':True,'category':'open_questions','reason':'open','evidence':quote,'owner':''})
        memory,diag=recover({},TEXT,[],llm=llm)
        self.assertEqual(1,len(memory['open_questions']))
        self.assertEqual(1,len(diag['accepted']))
if __name__=='__main__':unittest.main()
