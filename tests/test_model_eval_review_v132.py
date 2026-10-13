import csv
import json
import tempfile
import unittest
from pathlib import Path
from tools.benchmark.model_eval_review_v132 import initialize,score,read_csv,write_csv,FIELDS,GOLD_FIELDS

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'result.json'
        self.source.write_text(json.dumps({'model':'mock','case':'synthetic','window_coverage_complete':True,
            'events':[{'category':'commitment','claim':'Send report','owner':'Speaker A','evidence':'I will send report','window':0,'char_start':3},
                      {'category':'decision','claim':'Send report','owner':None,'evidence':'I will send report','window':0}]}))
        self.gold=self.root/'expected_memory.json'
        self.gold.write_text(json.dumps({'expected':{'commitments':[{'description':'Send report'}],
                                                       'risks':[{'description':'Late launch'}]}}))
        self.out=self.root/'review'
    def test_init_preserves_unlabeled_reviews(self):
        self.assertEqual(initialize(self.source,self.out,self.gold),(2,2))
        with self.assertRaises(FileExistsError): initialize(self.source,self.out,self.gold)
        self.assertEqual(read_csv(self.out/'candidates.csv')[0]['label'],'')
    def test_incomplete_cannot_score(self):
        initialize(self.source,self.out,self.gold)
        result=score(self.out)
        self.assertFalse(result['complete'])
        self.assertNotIn('gold_event_recall',result)
    def test_scoring_with_explicit_missed_gold(self):
        initialize(self.source,self.out,self.gold)
        events=read_csv(self.out/'candidates.csv')
        events[0].update(label='correct',evidence_check='supported',owner_check='supported',status_check='supported',gold_id='commitment:001')
        events[1].update(label='wrong_category',correct_category='commitment',evidence_check='supported',owner_check='unknown',status_check='supported')
        write_csv(self.out/'candidates.csv',FIELDS,events)
        gold=read_csv(self.out/'gold_coverage.csv')
        gold[0]['disposition']='reviewed_present';gold[1]['disposition']='reviewed_missed'
        write_csv(self.out/'gold_coverage.csv',GOLD_FIELDS,gold)
        scored=score(self.out)
        self.assertTrue(scored['complete'])
        self.assertEqual(scored['strict_category_precision'],.5)
        self.assertEqual(scored['gold_event_recall'],.5)
    def test_unsupported_gold_link_rejected(self):
        initialize(self.source,self.out,self.gold)
        events=read_csv(self.out/'candidates.csv')
        for event in events: event.update(label='unsupported',evidence_check='unsupported',owner_check='unknown',status_check='unknown')
        events[0]['gold_id']='commitment:001'
        write_csv(self.out/'candidates.csv',FIELDS,events)
        gold=read_csv(self.out/'gold_coverage.csv')
        for row in gold: row['disposition']='reviewed_missed'
        write_csv(self.out/'gold_coverage.csv',GOLD_FIELDS,gold)
        self.assertFalse(score(self.out)['complete'])
    def test_no_gold_means_no_recall(self):
        initialize(self.source,self.out)
        self.assertFalse(score(self.out)['complete'])

if __name__=='__main__':unittest.main()
