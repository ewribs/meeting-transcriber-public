"""Sanitized event-linked shadow comparison tests; no private meeting data."""
import unittest
from tools.benchmark.shadow_compare import resolve_shadow

class ShadowCompareTests(unittest.TestCase):
    def test_grounded_future_commitment_with_known_owner(self):
        text='Speaker A: I will send the Platform Beta draft tomorrow.'
        trace={'identity_map':{'remote':'Speaker A'},'merged_events':[{'event_type':'commitment','speaker':'Remote','subject':'send the Platform Beta draft','evidence':[text]}]}
        memory,diag=resolve_shadow(trace,text)
        self.assertEqual(len(memory['commitments']),1)
        self.assertEqual(memory['commitments'][0]['owner'],'Speaker A')

    def test_refuses_channel_owner(self):
        text='I will send the Platform Beta draft tomorrow.'
        trace={'merged_events':[{'event_type':'commitment','speaker':'Remote','subject':'send the Platform Beta draft','evidence':[text]}]}
        memory,diag=resolve_shadow(trace,text)
        self.assertEqual(memory['commitments'],[])
        self.assertEqual(diag['unresolved_owner'],1)

    def test_no_summary_question_resurrection(self):
        text='How do teams think about budget during training?'
        trace={'merged_events':[],'baseline_memory':{'open_questions':['How do teams think about budget?']}}
        memory,_=resolve_shadow(trace,text)
        self.assertEqual(memory['open_questions'],[])

    def test_question_requires_source_evidence(self):
        text='Who owns Platform Beta? It is still undecided.'
        trace={'merged_events':[{'event_type':'question','speaker':'Remote','subject':'who owns Platform Beta','evidence':[text]}]}
        memory,_=resolve_shadow(trace,text)
        self.assertEqual(len(memory['open_questions']),1)
        trace['merged_events'][0]['evidence']=['This text never appeared in the transcript.']
        memory,_=resolve_shadow(trace,text)
        self.assertEqual(memory['open_questions'],[])

    def test_duplicate_actions(self):
        text='I will send the Platform Beta contract draft tomorrow.'
        trace={'identity_map':{'mic':'Speaker A'},'merged_events':[
            {'event_type':'commitment','speaker':'Mic','subject':'send the Platform Beta contract draft','evidence':[text]},
            {'event_type':'next_step','speaker':'Mic','subject':'send Platform Beta contract draft','evidence':[text]},
        ]}
        memory,_=resolve_shadow(trace,text)
        self.assertEqual(len(memory['commitments']),1)

if __name__=='__main__':unittest.main()
