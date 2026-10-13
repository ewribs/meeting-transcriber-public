"""Verified items removed by a late gate are shown as 'Possible', never silently lost."""

import os
import unittest
from unittest.mock import patch

from memory_reconciliation import demote_dropped_items

QUOTE = "that is a risk right to the business if we lose patches"


def _baseline():
    return {
        "commitments": [{"owner": "Unknown", "action": "Send the vendor contact over",
                         "evidence": "I will send you the contact"}],
        "decisions": [],
        "risks": [{"risk": "Risk of losing access to critical patches", "evidence": QUOTE}],
        "follow_ups": [],
    }


class PossibleItemsTests(unittest.TestCase):
    def test_dropped_items_are_listed_as_possible(self):
        final = {"commitments": [], "decisions": [], "risks": [], "follow_ups": []}
        result = demote_dropped_items(_baseline(), final)
        text = " | ".join(result["follow_ups"])
        self.assertIn("Possible risk (unconfirmed)", text)
        self.assertIn("Possible commitment (unconfirmed)", text)
        # strict lists are untouched
        self.assertEqual(result["risks"], [])
        self.assertEqual(result["commitments"], [])

    def test_items_that_survived_are_not_repeated(self):
        final = {"commitments": [], "decisions": [], "follow_ups": [],
                 "risks": [{"risk": "Risk of losing access to critical patches", "evidence": QUOTE}]}
        result = demote_dropped_items(_baseline(), final)
        self.assertNotIn("Possible risk", " | ".join(result["follow_ups"]))

    def test_named_owner_is_shown(self):
        base = {"commitments": [{"owner": "Pat", "action": "Draft the renewal memo", "evidence": "x"}]}
        result = demote_dropped_items(base, {"commitments": [], "follow_ups": []})
        self.assertIn("owner Pat", result["follow_ups"][0])

    def test_same_quote_is_listed_once(self):
        base = {"commitments": [
            {"owner": "Pat", "action": "Coordinate with the vendor to set up a call", "evidence": "same quote"},
            {"owner": "Unknown", "action": "Setting up a meeting with the vendor", "evidence": "same quote"},
        ]}
        result = demote_dropped_items(base, {"commitments": [], "follow_ups": []})
        self.assertEqual(len(result["follow_ups"]), 1)

    def test_limit_and_off_switch(self):
        topics = ["patching", "licensing", "staffing", "budget", "security", "latency", "contracts", "migration", "training"]
        base = {"risks": [{"risk": f"Exposure from {topic} gaps", "evidence": f"quote {topic}"} for topic in topics]}
        result = demote_dropped_items(base, {"risks": [], "follow_ups": []})
        self.assertEqual(len(result["follow_ups"]), 6)
        with patch.dict(os.environ, {"MT_DEMOTE_DROPPED": "0"}):
            off = demote_dropped_items(base, {"risks": [], "follow_ups": []})
        self.assertEqual(off["follow_ups"], [])


if __name__ == "__main__":
    unittest.main()
