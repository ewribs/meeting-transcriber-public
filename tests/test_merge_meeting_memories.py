import unittest

from merge_meeting_memories import merge_memories


class MergeMeetingMemoriesTests(unittest.TestCase):
    def test_structured_decisions_are_normalized_for_merged_context(self):
        merged = merge_memories(
            [
                (
                    "2026-09-24_test",
                    {
                        "topics": [],
                        "commitments": [],
                        "decisions": [
                            {
                                "decision": "Use a one-year term.",
                                "evidence": "We agreed to use a one-year term.",
                            },
                            "Hold pricing flat.",
                        ],
                        "open_questions": [],
                        "follow_ups": [],
                    },
                )
            ]
        )

        self.assertEqual(
            merged["decisions"],
            [
                {
                    "meeting": "2026-09-24_test",
                    "decision": "Use a one-year term.",
                    "evidence": "We agreed to use a one-year term.",
                },
                {
                    "meeting": "2026-09-24_test",
                    "decision": "Hold pricing flat.",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
