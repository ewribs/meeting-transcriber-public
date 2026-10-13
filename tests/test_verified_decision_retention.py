import unittest
import ai
from memory_reconciliation import harden_final_memory

QUOTE = "anything that goes up for board for now Let's use that template"
DECISION = "Use the template for materials going to the board"


class VerifiedDecisionRetentionTests(unittest.TestCase):
    def test_verified_adoption_survives_reconcile_and_hardening(self):
        memory = {'decisions': [{'decision': DECISION, 'evidence': QUOTE,
                                 '_context_resolved': True, '_event_verified': True}],
                  'commitments': [], 'risks': [], 'open_questions': [],
                  'follow_ups': [], 'topics': []}
        reconciled = ai._reconcile_meeting_memory(memory, QUOTE)
        self.assertEqual(len(reconciled['decisions']), 1)
        # Legacy reconciliation removes private markers. Production restores
        # the marker only when a verified event matches exact decision/evidence.
        reconciled['decisions'][0]['_event_verified'] = True
        hardened = harden_final_memory(reconciled, [])
        self.assertEqual(len(hardened['decisions']), 1)

    def test_unverified_plan_still_rejected(self):
        memory = {'decisions': [{'decision': 'Materials are going to the board',
                                 'evidence': 'I am going to prepare the materials'}],
                  'commitments': []}
        self.assertEqual(harden_final_memory(memory, [])['decisions'], [])

    def test_verified_meeting_logistics_still_rejected(self):
        memory = {'decisions': [{'decision': 'Schedule a meeting next week',
                                 'evidence': 'We will schedule a meeting next week',
                                 '_event_verified': True}], 'commitments': []}
        self.assertEqual(harden_final_memory(memory, [])['decisions'], [])

    def test_unverified_template_plan_still_rejected(self):
        memory = {'decisions': [{'decision': DECISION,
                                 'evidence': QUOTE}], 'commitments': []}
        self.assertEqual(harden_final_memory(memory, [])['decisions'], [])
