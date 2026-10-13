import unittest
from tools.benchmark.model_eval_v13 import parse_events, windows

class ModelEvalV13Tests(unittest.TestCase):
    def test_contiguous_quotes_are_accepted(self):
        passage='Speaker A: I will send the report next week.'
        raw='{"events":[{"category":"commitment","claim":"Send report","owner":"Speaker A","evidence":"I will send the report next week."}]}'
        items, errors=parse_events(raw,passage)
        self.assertEqual(len(items),1)
        self.assertEqual(errors,[])
    def test_invented_evidence_is_rejected(self):
        items, errors=parse_events('{"events":[{"category":"decision","claim":"Approved budget","evidence":"Approved budget"}]}','We discussed a budget.')
        self.assertEqual(items,[])
        self.assertIn('item_0:not_verbatim',errors)
    def test_malformed_json_rejected(self):
        self.assertEqual(parse_events('oops','hello')[1],['invalid_json'])
    def test_windows_preserve_coverage(self):
        sample='one line\n' * 120
        result=windows(sample,size=250,overlap=40)
        self.assertGreater(len(result),1)
        covered=[False]*len(sample)
        for start,end,_ in result:
            covered[start:end]=[True]*(end-start)
        self.assertTrue(all(covered))
    def test_schema_rejection(self):
        self.assertEqual(parse_events('[]','abc')[1],['invalid_schema'])

if __name__=='__main__':unittest.main()
