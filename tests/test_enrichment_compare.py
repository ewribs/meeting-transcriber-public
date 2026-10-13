import unittest
from tools.benchmark.enrichment_compare import enrich_baseline, context_excerpt

TEXT='Speaker A: I will send the renewal packet tomorrow. Speaker B: All right, thanks. Speaker A: The documentation is ready.'
BASE={'topics':[],'commitments':[{'owner':'Alex','action':'Send the renewal packet tomorrow.','evidence':'I will send the renewal packet tomorrow.'}], 'decisions':[],'risks':[],'open_questions':[],'follow_ups':[]}
PEOPLE=[{'name':'Alex'}]

class EnrichmentTests(unittest.TestCase):
    def test_non_destructive_duplicate(self):
        candidate={'commitments':[{'owner':'Alex','action':'Send renewal packet tomorrow.','evidence':'I will send the renewal packet tomorrow.'}]}
        enriched,diag=enrich_baseline(BASE,candidate,TEXT,PEOPLE,reviewer=lambda *_:self.fail('should not call reviewer'))
        self.assertEqual(enriched,BASE)
        self.assertEqual(len(diag['accepted']),0)
    def test_reject_owner_uncertainty(self):
        text='Speaker A: I will call the provider tomorrow.'
        candidate={'commitments':[{'owner':'Remote','action':'Call the provider tomorrow','evidence':'I will call the provider tomorrow.'}]}
        verdict=lambda *_:'{"accept":true,"category":"commitments","owner":"Remote","evidence":"I will call the provider tomorrow.","reason":"explicit"}'
        enriched,diag=enrich_baseline(BASE,candidate,text,PEOPLE,reviewer=verdict)
        self.assertEqual(enriched,BASE)
        self.assertEqual(len(diag['accepted']),0)
    def test_add_verifiable_new_question(self):
        text='Speaker A: Who owns the approval? We have not decided yet.'
        candidate={'open_questions':[{'question':'Who owns the approval?','evidence':'Who owns the approval?'}]}
        verdict=lambda *_:'{"accept":true,"category":"open_questions","owner":"","evidence":"Who owns the approval?","reason":"unresolved"}'
        out,diag=enrich_baseline(BASE,candidate,text,PEOPLE,reviewer=verdict)
        self.assertEqual(len(out['open_questions']),1)
        self.assertEqual(len(BASE['open_questions']),0)
        self.assertEqual(len(diag['accepted']),1)
    def test_reject_fabricated_evidence(self):
        candidate={'decisions':[{'decision':'Adopt a new policy','evidence':'This quote does not exist anywhere in transcript'}]}
        enriched,diag=enrich_baseline(BASE,candidate,TEXT,PEOPLE,reviewer=lambda *_:self.fail('should not call reviewer'))
        self.assertEqual(enriched,BASE)
        self.assertEqual(len(diag['accepted']),0)
    def test_context_excerpt(self):
        self.assertIn('We have not decided yet',context_excerpt('Who owns the approval?  We have not decided yet.','Who owns the approval?'))

if __name__=='__main__':unittest.main()
