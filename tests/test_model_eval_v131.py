import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.benchmark.model_eval_v13 import run_case, candidate_review

class ReliabilityTests(unittest.TestCase):
    def test_retry_restores_full_window_and_retains_raw(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'private_benchmarks'; case=root/'example'; case.mkdir(parents=True)
            text='Speaker A: I will send the report tomorrow.\n' * 10
            (case/'meeting_transcript_cleaned.md').write_text(text)
            payload=json.dumps({'events':[{'category':'commitment','claim':'Send report',
                'owner':'Speaker A','evidence':'I will send the report tomorrow.'}]})
            with patch('tools.benchmark.model_eval_v13.ollama_generate',side_effect=['bad json',payload]*20) as mock:
                result=run_case('example','mock',case_root=root,run_dir=Path(temp)/'runs',
                                base='http://localhost:11434',size=250,overlap=40,timeout=3)
            self.assertTrue(result['window_coverage_complete'])
            self.assertGreater(mock.call_count,1)
            self.assertTrue((Path(temp)/'runs/example/raw_responses/window_0000_attempt_00.txt').exists())
            self.assertTrue((Path(temp)/'runs/example/result.json').exists())
    def test_unrecovered_failure_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'private_benchmarks'; case=root/'example';case.mkdir(parents=True)
            (case/'meeting_transcript_cleaned.md').write_text('abc '*60)
            with patch('tools.benchmark.model_eval_v13.ollama_generate',return_value='broken'):
                result=run_case('example','mock',case_root=root,run_dir=Path(temp)/'runs',
                                base='http://localhost:11434',size=300,overlap=30,timeout=3,max_retries=1)
            self.assertFalse(result['window_coverage_complete'])
            self.assertTrue(result['failed_window_indices'])
    def test_gold_is_review_only(self):
        with tempfile.TemporaryDirectory() as temp:
            gold=Path(temp)/'expected_memory.json'
            gold.write_text(json.dumps({'expected':{'commitments':[{'description':'Send report',
                'text_contains_any':['report']}]}}))
            report=candidate_review([{'category':'commitment','claim':'Send report'}],gold)
            self.assertTrue(report['review_suggestions'][0]['requires_human_review'])
            self.assertNotIn('precision',report)
            self.assertNotIn('recall',report)
if __name__=='__main__':unittest.main()
