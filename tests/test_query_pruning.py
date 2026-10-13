import unittest

from query.pruning import prepare_query_memory


def _memory():
    return {
        "active_topics": [
            {
                "topic_key": "vendor_alpha",
                "topic": "Vendor Alpha renewal",
                "summary": "Current Vendor Alpha renewal discussion",
            },
            {
                "topic_key": "cloud_provider_a",
                "topic": "Cloud Provider A migration",
                "summary": "Current Cloud Provider A migration discussion",
            },
        ],
        "anchor_topics": [
            {
                "topic_key": "vendor_alpha",
                "topic": "Vendor Alpha renewal",
                "summary": "Current Vendor Alpha renewal discussion",
            }
        ],
        "supporting_topics": [],
        "recurring_topics": [],
        "topic_history": {
            "vendor_alpha": [
                {
                    "meeting": f"2026-0{i}-01_test",
                    "topic": "Vendor Alpha renewal",
                    "summary": f"Vendor Alpha update {i}",
                    "status": "ongoing",
                }
                for i in range(1, 8)
            ],
            "cloud_provider_a": [
                {
                    "meeting": f"2026-0{i}-02_test",
                    "topic": "Cloud Provider A migration",
                    "summary": f"Cloud Provider A update {i}",
                    "status": "ongoing",
                }
                for i in range(1, 6)
            ],
            "old_closed": [
                {
                    "meeting": "2025-01-01_test",
                    "topic": "Old closed topic",
                    "summary": "No longer active",
                    "status": "closed",
                }
            ],
        },
        "decisions": [
            {
                "meeting": f"2026-01-{i:02d}_test",
                "decision": f"Decision {i}",
            }
            for i in range(1, 13)
        ],
        "commitments": [
            {"meeting": "x", "commitment": "keep me"}
        ],
    }


class QueryPruningTests(unittest.TestCase):
    def test_topical_query_keeps_more_matching_history(self):
        original = _memory()

        prepared = prepare_query_memory(
            "What is happening with Vendor Alpha?",
            original,
        )

        self.assertEqual(
            len(prepared["topic_history"]["vendor_alpha"]),
            6,
        )
        self.assertEqual(
            len(prepared["topic_history"]["cloud_provider_a"]),
            2,
        )
        self.assertNotIn(
            "old_closed",
            prepared["topic_history"],
        )
        self.assertEqual(
            len(original["topic_history"]["vendor_alpha"]),
            7,
        )

    def test_broad_history_request_keeps_full_memory(self):
        original = _memory()

        prepared = prepare_query_memory(
            "Give me the full history over time.",
            original,
        )

        self.assertEqual(
            prepared,
            original,
        )
        self.assertIsNot(
            prepared,
            original,
        )

    def test_recent_decisions_are_retained_for_unmatched_query(self):
        prepared = prepare_query_memory(
            "What should I prepare for Alex?",
            _memory(),
        )

        self.assertEqual(
            len(prepared["decisions"]),
            8,
        )
        self.assertEqual(
            prepared["decisions"][0]["decision"],
            "Decision 5",
        )
        self.assertEqual(
            prepared["decisions"][-1]["decision"],
            "Decision 12",
        )


if __name__ == "__main__":
    unittest.main()
