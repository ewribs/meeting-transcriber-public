import unittest
from ai import _risk_evidence_semantically_supports, _validate_resolved_risk
from memory_reconciliation import observed_staffing_risk_supported, audit_final_memory_integrity

QUOTE = "There's a couple of folks that have announced they're leaving as well as someone who is also having potential as like someone who I think is also high potential that is expecting an offer, another internal offer soon."
CLAIM = "High turnover and difficulty retaining talent"

class ObservedStaffingRiskTests(unittest.TestCase):
    def test_upstream_accepts_observed_departures(self):
        self.assertTrue(_risk_evidence_semantically_supports(CLAIM, [QUOTE]))
        self.assertIsNotNone(_validate_resolved_risk({'risk': CLAIM, 'evidence': [QUOTE]}, QUOTE))

    def test_final_audit_preserves_grounded_staffing_risk(self):
        result, audit = audit_final_memory_integrity({'risks': [{'risk': CLAIM, 'evidence': QUOTE}]}, [], QUOTE)
        self.assertEqual(len(result['risks']), 1)

    def test_no_invented_consequence(self):
        self.assertFalse(observed_staffing_risk_supported('Staff departures will delay project delivery', QUOTE))

    def test_negated_departures_are_not_evidence(self):
        self.assertFalse(observed_staffing_risk_supported('High turnover and difficulty retaining talent', 'No staff departures have been announced.'))

    def test_unrelated_nearby_departures_do_not_ground_cost_risk(self):
        self.assertFalse(_risk_evidence_semantically_supports('Potential financial cost overruns from staffing attrition', [QUOTE]))

    def test_question_about_possible_departures_is_not_observation(self):
        self.assertFalse(observed_staffing_risk_supported('Staff attrition risk', 'Are people leaving?'))

if __name__ == '__main__':
    unittest.main()
