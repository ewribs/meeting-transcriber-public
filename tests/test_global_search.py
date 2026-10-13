import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from global_search import global_search


class GlobalSearchTests(unittest.TestCase):
    def test_searches_structured_meeting_fields_and_sessions(self):
        meetings = [
            {
                "meeting_run": "2026-09-21_0900_Jordan",
                "display_title": "Jordan 1v1",
                "meeting_datetime": "2026-09-21T09:00:00",
                "participants": ["Jordan"],
                "location": "/tmp/jordan",
            },
            {
                "meeting_run": "2026-09-20_0900_Other",
                "display_title": "Other",
                "meeting_datetime": "2026-09-20T09:00:00",
                "participants": [],
                "location": "/tmp/other",
            },
        ]

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            (sessions_dir / "Security Renewals.json").write_text(
                json.dumps(
                    {
                        "meeting_runs": ["a", "b"],
                        "selection_criteria": {
                            "person": "Jordan",
                            "topic": "Security Vendor B",
                            "history_days": 90,
                        },
                        "conversation_history": [],
                    }
                ),
                encoding="utf-8",
            )

            def detail(meeting):
                if meeting["display_title"] == "Jordan 1v1":
                    return {
                        "summary": "Supplier renewals were reviewed.",
                        "topics": [
                            {
                                "name": "Security Vendor B Renewal",
                                "status": "ongoing",
                                "summary": "DLP charges need a PO split.",
                            }
                        ],
                        "decisions": ["Proceed with the renewal co-term."],
                        "commitments": [
                            {
                                "owner": "Jordan",
                                "action": "Coordinate DLP charge",
                                "status": "open",
                            }
                        ],
                        "open_questions": [],
                        "follow_ups": [],
                    }
                return {
                    "summary": "Unrelated",
                    "topics": [],
                    "decisions": [],
                    "commitments": [],
                    "open_questions": [],
                    "follow_ups": [],
                }

            with patch("global_search.load_meeting_detail", side_effect=detail):
                results = global_search(
                    "Security Vendor B",
                    meetings,
                    sessions_dir,
                )

        self.assertEqual(len(results["meetings"]), 1)
        self.assertEqual(results["meetings"][0]["meeting_run"], "2026-09-21_0900_Jordan")
        self.assertIn("Security Vendor B Renewal", results["meetings"][0]["snippet"])
        self.assertEqual(len(results["sessions"]), 1)
        self.assertEqual(results["sessions"][0]["session_name"], "Security Renewals")


    def test_fixed_session_matches_content_from_included_meeting(self):
        meetings = [
            {
                "meeting_run": "2026-09-22_0900_Vendor Alpha",
                "display_title": "Vendor Review",
                "meeting_datetime": "2026-09-22T09:00:00",
                "participants": ["Morgan"],
                "location": "/tmp/vendor-alpha",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            (sessions_dir / "Strategic Deals.json").write_text(
                json.dumps(
                    {
                        "meeting_runs": ["2026-09-22_0900_Vendor Alpha"],
                        "conversation_history": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "global_search.load_meeting_detail",
                return_value={
                    "summary": "Reviewed Vendor Alpha legal terms and renewal strategy.",
                    "topics": [
                        {
                            "name": "Vendor Alpha Framework",
                            "status": "ongoing",
                            "summary": "Legal terms remain under review.",
                        }
                    ],
                    "decisions": [],
                    "commitments": [],
                    "open_questions": [],
                    "follow_ups": [],
                },
            ):
                results = global_search(
                    "Vendor Alpha",
                    meetings,
                    sessions_dir,
                )

        self.assertEqual(len(results["sessions"]), 1)
        self.assertEqual(
            results["sessions"][0]["session_name"],
            "Strategic Deals",
        )
        self.assertIn(
            "Included topic",
            results["sessions"][0]["snippet"],
        )

    def test_session_matches_saved_conversation_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions_dir = Path(tmp)
            (sessions_dir / "Supplier Strategy.json").write_text(
                json.dumps(
                    {
                        "meeting_runs": [],
                        "conversation_history": [
                            {
                                "role": "assistant",
                                "content": "Vendor Alpha legal terms remain a key open item.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            results = global_search(
                "Vendor Alpha",
                [],
                sessions_dir,
            )

        self.assertEqual(len(results["sessions"]), 1)
        self.assertEqual(
            results["sessions"][0]["session_name"],
            "Supplier Strategy",
        )
        self.assertIn(
            "Session conversation",
            results["sessions"][0]["snippet"],
        )

    def test_multi_term_match_can_span_meeting_fields(self):
        meetings = [
            {
                "meeting_run": "2026-09-21_0900_Jordan",
                "display_title": "Jordan 1v1",
                "meeting_datetime": "2026-09-21T09:00:00",
                "participants": ["Jordan"],
                "location": "/tmp/jordan",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "global_search.load_meeting_detail",
                return_value={
                    "summary": "Reviewed the renewal portfolio.",
                    "topics": [
                        {
                            "name": "Security Vendor B Renewal",
                            "status": "ongoing",
                            "summary": "Friday call preparation.",
                        }
                    ],
                    "decisions": [],
                    "commitments": [],
                    "open_questions": [],
                    "follow_ups": [],
                },
            ):
                results = global_search(
                    "Jordan Security Vendor B",
                    meetings,
                    Path(tmp),
                )

        self.assertEqual(len(results["meetings"]), 1)

    def test_empty_query_returns_no_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = global_search("   ", [], Path(tmp))
        self.assertEqual(results, {"meetings": [], "sessions": []})


if __name__ == "__main__":
    unittest.main()
