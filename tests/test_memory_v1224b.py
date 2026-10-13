"""Sanitized v12.24b consolidation regressions (no private meeting content)."""
import unittest
from ai import _deduplicate_commitments, _same_negative_workspace_decision


class MemoryConsolidationTests(unittest.TestCase):
    def test_duplicate_historical_workspace_decisions(self):
        a = {"decision": "Do not retroactively update existing workspaces."}
        b = {"decision": "Historical workspaces will not be changed."}
        self.assertTrue(_same_negative_workspace_decision(a, b))

    def test_distinct_workspace_decisions_not_merged(self):
        a = {"decision": "Do not retroactively update existing workspaces."}
        b = {"decision": "Require approval before creating new workspaces."}
        self.assertFalse(_same_negative_workspace_decision(a, b))

    def test_renewal_document_duplicate_same_owner(self):
        items = [
            {"owner":"Jordan", "action":"Pull together renewal paperwork and quotes", "evidence":"I'll pull together the renewal paperwork and quotes."},
            {"owner":"Jordan", "action":"Pull together the renewals and update the documents", "evidence":"I'll pull together the renewals and update the documents."},
        ]
        self.assertEqual(len(_deduplicate_commitments(items)), 1)

    def test_renewals_for_different_owners_remain_distinct(self):
        items = [
            {"owner":"Jordan", "action":"Pull together renewal paperwork", "evidence":"I'll pull together renewal paperwork."},
            {"owner":"Taylor", "action":"Pull together renewal paperwork", "evidence":"I'll pull together renewal paperwork."},
        ]
        self.assertEqual(len(_deduplicate_commitments(items)), 2)


if __name__ == "__main__":
    unittest.main()
