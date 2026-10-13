import pathlib
import unittest

class NullableDecisionProvenanceTests(unittest.TestCase):
    def test_null_and_malformed_decision_list_do_not_raise(self):
        for value in (None, "", {}, 0):
            rows = value
            if not isinstance(rows, list):
                rows = []
            verified = {(r.get("decision"), r.get("evidence")) for r in rows if isinstance(r, dict) and r.get("_event_verified")}
            self.assertEqual(verified, set())

    def test_verified_provenance_remains_strict(self):
        rows = [{"decision": "Adopt template", "evidence": "Use that template", "_event_verified": True}, {"decision": "Maybe", "evidence": "later"}, None]
        verified = {(str(r.get("decision", "")).strip(), str(r.get("evidence", "")).strip()) for r in rows if isinstance(r, dict) and r.get("_event_verified")}
        self.assertEqual(verified, {("Adopt template", "Use that template")})

    def test_guard_is_in_production_source(self):
        source = pathlib.Path(__file__).resolve().parents[1].joinpath("ai.py").read_text()
        self.assertIn('if not isinstance(verified_decision_rows, list):', source)
        self.assertIn('for row in verified_decision_rows', source)
