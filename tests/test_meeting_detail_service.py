import json
import tempfile
import unittest
from pathlib import Path

from meeting_detail_service import load_meeting_detail


class MeetingDetailServiceTests(unittest.TestCase):
    def test_loads_summary_and_topics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)

            (run / "meeting_summary.md").write_text(
                "# Summary\n\nImportant discussion.",
                encoding="utf-8",
            )

            (run / "meeting_memory.json").write_text(
                json.dumps(
                    {
                        "topics": [
                            {
                                "topic_key": "cloud_provider_a",
                                "topic": "Cloud Provider A renewal",
                                "status": "active",
                                "summary": "Commercial strategy",
                            },
                            {
                                "topic_key": "vendor_alpha",
                                "topic": "Vendor Alpha",
                                "status": "open",
                                "summary": "Renewal planning",
                            },
                        ],
                        "decisions": [
                            {
                                "decision": "Use a one-year term.",
                                "evidence": "Let's do one year.",
                            },
                            "Hold pricing flat.",
                        ],
                        "commitments": [
                            {
                                "owner": "Jordan",
                                "action": "Send the deck to Casey.",
                                "status": "open",
                                "evidence": "I'll send the deck.",
                            }
                        ],
                        "open_questions": [
                            "Will the supplier accept the term?"
                        ],
                        "follow_ups": [
                            "Schedule the supplier call."
                        ],
                    }
                ),
                encoding="utf-8",
            )

            detail = load_meeting_detail(
                {"location": str(run)}
            )

            self.assertTrue(detail["has_summary"])
            self.assertTrue(detail["has_memory"])
            self.assertIn(
                "Important discussion.",
                detail["summary"],
            )
            self.assertEqual(
                detail["topics"][0],
                {
                    "name": "Cloud Provider A renewal",
                    "status": "active",
                    "summary": "Commercial strategy",
                },
            )
            self.assertEqual(
                detail["decisions"],
                ["Use a one-year term.", "Hold pricing flat."],
            )
            self.assertEqual(
                detail["commitments"],
                [
                    {
                        "owner": "Jordan",
                        "action": "Send the deck to Casey.",
                        "status": "open",
                    }
                ],
            )
            self.assertEqual(
                detail["open_questions"],
                ["Will the supplier accept the term?"],
            )
            self.assertEqual(
                detail["follow_ups"],
                ["Schedule the supplier call."],
            )

    def test_missing_optional_files_return_empty_detail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            detail = load_meeting_detail(
                {"location": temp_dir}
            )

            self.assertEqual(detail["summary"], "")
            self.assertEqual(detail["topics"], [])
            self.assertEqual(detail["decisions"], [])
            self.assertEqual(detail["commitments"], [])
            self.assertEqual(detail["open_questions"], [])
            self.assertEqual(detail["follow_ups"], [])
            self.assertFalse(detail["has_summary"])
            self.assertFalse(detail["has_memory"])

    def test_invalid_memory_does_not_break_catalog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)
            (run / "meeting_memory.json").write_text(
                "{not json",
                encoding="utf-8",
            )

            detail = load_meeting_detail(
                {"location": str(run)}
            )

            self.assertEqual(detail["topics"], [])
            self.assertFalse(detail["has_memory"])

    def test_missing_processing_metadata_returns_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)
            (run / "meeting_summary.md").write_text(
                "# Summary\n\nPublished meeting.",
                encoding="utf-8",
            )
            (run / "meeting_memory.json").write_text(
                json.dumps({"topics": []}),
                encoding="utf-8",
            )
            (run / "meeting_metadata.json").write_text(
                json.dumps({"schema_version": 1}),
                encoding="utf-8",
            )

            detail = load_meeting_detail({"location": str(run)})

            self.assertIsNone(detail["processing"])
            self.assertTrue(detail["has_summary"])
            self.assertTrue(detail["has_memory"])

    def test_processing_metadata_is_normalized_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run = Path(temp_dir)
            (run / "meeting_metadata.json").write_text(
                json.dumps(
                    {
                        "processing": {
                            "ai_model": "qwen3:14b",
                            "profile_display": "Auto → High Performance",
                            "mode": "direct",
                            "context_size_tokens": 40960,
                            "estimated_prompt_tokens": 12000,
                            "whisper_model": "medium.en",
                            "whisper_chunk_minutes": 5,
                        }
                    }
                ),
                encoding="utf-8",
            )

            detail = load_meeting_detail({"location": str(run)})

            self.assertEqual(detail["processing"]["ai_model"], "qwen3:14b")
            self.assertEqual(detail["processing"]["context_size_tokens"], 40960)


if __name__ == "__main__":
    unittest.main()
