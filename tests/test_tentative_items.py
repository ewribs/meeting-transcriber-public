import unittest

from memory_reconciliation import demote_tentative_events


def _row(subject, reason="conditional_or_tentative", kind="next_step", owner=None):
    return {"event_type": kind, "subject": subject, "reason": reason, "owner": owner}


class TentativeItemsTests(unittest.TestCase):
    def test_tentative_next_step_becomes_possible(self):
        out = demote_tentative_events(
            [_row("send a polished framework response to the vendor")],
            {"commitments": [], "follow_ups": []})
        self.assertEqual(len(out["follow_ups"]), 1)
        self.assertTrue(out["follow_ups"][0].startswith("Possible commitment (unconfirmed)"))

    def test_other_reasons_and_short_subjects_are_ignored(self):
        ledger = [_row("introduce himself", reason="future_work_or_owner_unverified"),
                  _row("send it", reason="conditional_or_tentative"),
                  _row("review the budget numbers carefully", kind="question")]
        out = demote_tentative_events(ledger, {"commitments": [], "follow_ups": []})
        self.assertEqual(out["follow_ups"], [])

    def test_duplicates_of_shown_items_and_limit(self):
        shown = {"commitments": [{"action": "send a polished framework response to the vendor"}],
                 "follow_ups": []}
        self.assertEqual(demote_tentative_events(
            [_row("send a polished framework response to the vendor")], shown)["follow_ups"], [])
        many = [_row(f"prepare topic{i}word{i} deliverable{i} summary") for i in range(8)]
        out = demote_tentative_events(many, {"commitments": [], "follow_ups": []})
        self.assertEqual(len(out["follow_ups"]), 3)


if __name__ == "__main__":
    unittest.main()
