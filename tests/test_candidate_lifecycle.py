import copy
import unittest
from candidate_lifecycle import snapshot, transition


class CandidateLifecycleTests(unittest.TestCase):
    def test_snapshot_does_not_mutate_input(self):
        memory = {'decisions': [{'decision': 'Use template', 'evidence': 'exact'}]}
        original = copy.deepcopy(memory)
        snap = snapshot(memory)
        snap['decisions'][0]['value']['decision'] = 'changed'
        self.assertEqual(memory, original)

    def test_changes_record_added_removed_modified(self):
        before = snapshot({'decisions': [{'decision': 'Use template', 'evidence': 'a'}],
                           'risks': [{'risk': 'Staffing'}]})
        after = snapshot({'decisions': [{'decision': 'Use template', 'evidence': 'b'}],
                          'open_questions': ['When?']})
        changes = transition(before, after, 'reconcile')
        self.assertEqual(sorted(x['change'] for x in changes), ['added', 'modified', 'removed'])
        self.assertTrue(all(x['stage'] == 'reconcile' for x in changes))

    def test_nullable_categories(self):
        self.assertEqual(snapshot({'decisions': None})['decisions'], [])


if __name__ == '__main__':
    unittest.main()
