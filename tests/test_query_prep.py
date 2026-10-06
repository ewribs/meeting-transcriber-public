import unittest

from query.context import build_meeting_context
from query.prep import build_meeting_prep


def _selected(meeting_run: str, title: str) -> dict:
    return {
        "meeting_run": meeting_run,
        "display_title": title,
        "participants": ["Speaker A"],
        "relevance_weight": 1,
    }


class QueryPrepTests(unittest.TestCase):
    def test_latest_unassigned_open_question_is_preserved_for_prep(self):
        older_run = "2026-01-08_PlatformAlpha"
        latest_run = "2026-01-15_PlatformAlpha"

        memories = [
            (
                older_run,
                {
                    "topics": [
                        {
                            "topic_key": "platform_alpha_renewal",
                            "topic": "Platform Alpha Renewal",
                            "status": "ongoing",
                            "summary": "Earlier renewal discussion.",
                        }
                    ],
                    "decisions": [],
                    "open_questions": [
                        "Will the earlier pricing model continue?"
                    ],
                    "commitments": [],
                    "follow_ups": [],
                },
            ),
            (
                latest_run,
                {
                    "topics": [
                        {
                            "topic_key": "platform_alpha_renewal",
                            "topic": "Platform Alpha Renewal",
                            "status": "ongoing",
                            "summary": "Current renewal discussion.",
                        }
                    ],
                    "decisions": [],
                    "open_questions": [
                        "Who owns the final approval?"
                    ],
                    "commitments": [],
                    "follow_ups": [],
                },
            ),
        ]

        selected = [
            _selected(older_run, "Platform Alpha - Earlier"),
            _selected(latest_run, "Platform Alpha - Latest"),
        ]

        context = build_meeting_context(memories, selected)
        prep = build_meeting_prep(context)

        self.assertEqual(
            prep["questions"]["general"],
            ["Who owns the final approval?"],
        )
        self.assertNotIn(
            "Will the earlier pricing model continue?",
            prep["questions"]["general"],
        )

    def test_topic_specific_question_remains_grouped(self):
        meeting_run = "2026-02-02_VendorAlpha"
        memories = [
            (
                meeting_run,
                {
                    "topics": [
                        {
                            "topic_key": "vendor_alpha_renewal",
                            "topic": "Vendor Alpha Renewal",
                            "status": "ongoing",
                            "summary": "Renewal remains active.",
                        }
                    ],
                    "decisions": [],
                    "open_questions": [
                        "Will Vendor Alpha extend the current term?"
                    ],
                    "commitments": [],
                    "follow_ups": [],
                },
            )
        ]

        context = build_meeting_context(
            memories,
            [_selected(meeting_run, "Vendor Alpha")],
        )
        prep = build_meeting_prep(context)

        self.assertEqual(prep["questions"]["general"], [])
        self.assertEqual(
            prep["questions"]["topic"],
            [
                {
                    "topic_key": "vendor_alpha_renewal",
                    "topic": "Vendor Alpha Renewal",
                    "questions": [
                        "Will Vendor Alpha extend the current term?"
                    ],
                }
            ],
        )

    def test_prep_keeps_only_anchor_meeting_commitments(self):
        older_run = "2026-03-01_ProjectDelta"
        latest_run = "2026-03-08_ProjectDelta"
        memories = [
            (
                older_run,
                {
                    "topics": [
                        {
                            "topic_key": "project_delta",
                            "topic": "Project Delta",
                            "status": "ongoing",
                            "summary": "Earlier discussion.",
                        }
                    ],
                    "decisions": [],
                    "open_questions": [],
                    "commitments": [
                        {
                            "owner": "Speaker A",
                            "action": "Send the old worksheet",
                            "status": "open",
                        }
                    ],
                    "follow_ups": [],
                },
            ),
            (
                latest_run,
                {
                    "topics": [
                        {
                            "topic_key": "project_delta",
                            "topic": "Project Delta",
                            "status": "ongoing",
                            "summary": "Current discussion.",
                        }
                    ],
                    "decisions": [],
                    "open_questions": [],
                    "commitments": [
                        {
                            "owner": "Speaker B",
                            "action": "Confirm the current timeline",
                            "status": "open",
                        }
                    ],
                    "follow_ups": [],
                },
            ),
        ]

        selected = [
            _selected(older_run, "Project Delta - Earlier"),
            _selected(latest_run, "Project Delta - Latest"),
        ]

        context = build_meeting_context(memories, selected)
        prep = build_meeting_prep(context)

        self.assertEqual(
            prep["actions"]["commitments"],
            [
                {
                    "owner": "Speaker B",
                    "action": "Confirm the current timeline",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
