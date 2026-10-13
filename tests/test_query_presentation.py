import unittest

from query_presentation import (
    format_auto_execution_tooltip,
    format_elapsed,
    format_query_finished_status,
    format_query_ready_status,
    format_query_working_status,
    render_conversation_markdown,
    format_session_prep,
)


class QueryPresentationTests(unittest.TestCase):
    def test_elapsed_format(self):
        self.assertEqual(format_elapsed(0), "00:00")
        self.assertEqual(format_elapsed(65_999), "01:05")

    def test_query_statuses(self):
        self.assertEqual(format_query_ready_status("Balanced"), "Qwen · Balanced · Ready")
        self.assertEqual(format_query_working_status("Balanced"), "Qwen · Balanced · Working…")
        self.assertEqual(
            format_query_finished_status(
                {"profile": "Balanced", "mode": "chunked", "inference_calls": 3},
                "Conservative",
            ),
            "Qwen · Balanced · Chunked · 3 passes",
        )
        self.assertEqual(
            format_query_finished_status({"mode": "direct"}, "Aggressive"),
            "Qwen · Aggressive · Direct",
        )

    def test_conversation_markdown_skips_unknown_and_empty(self):
        markdown = render_conversation_markdown(
            [
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Answer"},
                {"role": "system", "content": "Ignore"},
                {"role": "user", "content": ""},
            ]
        )
        self.assertIn("### You", markdown)
        self.assertIn("Question", markdown)
        self.assertIn("### Assistant", markdown)
        self.assertIn("Answer", markdown)
        self.assertNotIn("Ignore", markdown)

    def test_prep_format_includes_criteria_priorities_and_actions(self):
        prep = {
            "meeting_count": 2,
            "anchor_label": "Alex 1v1",
            "supporting_labels": ["Alex follow-up"],
            "priorities": [
                {
                    "topic": "Renewal",
                    "anchor": True,
                    "recurring": False,
                    "supporting": True,
                    "summary": "Negotiate pricing.",
                    "status": "open",
                }
            ],
            "questions": {"topic": [], "general": []},
            "actions": {
                "commitments": [{"owner": "Avery", "action": "Follow up"}],
                "topic_follow_ups": [],
                "general_follow_ups": [],
            },
        }
        text = format_session_prep(
            prep,
            "SESSION: Alex",
            selection_criteria={"person": "Alex", "days": 30},
        )
        self.assertIn("SESSION: Alex", text)
        self.assertIn("Meetings in context: 2", text)
        self.assertIn("Renewal [Anchor, Supporting]", text)
        self.assertIn("Avery: Follow up", text)

    def test_auto_tooltip_reports_calibration(self):
        text = format_auto_execution_tooltip(
            {
                "mode": "direct",
                "estimated_prompt_tokens": 4612,
                "direct_token_budget": 6000,
                "context_size_tokens": 16384,
                "context_reserve_tokens": 3276,
                "model_budget_factor": 1.0,
                "hardware_budget_factor": 1.0,
                "calibration_factor": 1.0,
                "calibration_sample_count": 2,
                "calibration_reason": "insufficient comparable history",
            }
        )
        self.assertIn("Estimated prompt: 4,612 tokens", text)
        self.assertIn("2/5 comparable samples", text)
        self.assertIn("insufficient comparable history", text)


class QueryPresentationRetryStatusTests(unittest.TestCase):
    def test_direct_retry_shows_two_passes(self):
        text = format_query_finished_status(
            {
                "profile": "Balanced",
                "mode": "direct",
                "inference_calls": 2,
            },
            "Balanced",
        )
        self.assertEqual(
            text,
            "Qwen · Balanced · Direct · 2 passes",
        )

    def test_auto_tooltip_reports_count_retry(self):
        text = format_auto_execution_tooltip(
            {
                "mode": "direct",
                "count_retry_count": 1,
            }
        )
        self.assertIn(
            "Count compliance retry: yes",
            text,
        )


if __name__ == "__main__":
    unittest.main()
