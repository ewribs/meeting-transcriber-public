import unittest
from unittest.mock import patch

import ai


class DirectSummaryTests(unittest.TestCase):
    def test_direct_summary_uses_full_transcript_then_polishes(self):
        transcript = "**Remote**\nWe decided to proceed with ExampleCo if legal approves."

        with patch("ai.ask_llm", return_value="draft") as ask, patch(
            "ai.polish_meeting_summary", return_value="polished"
        ) as polish:
            result = ai.summarize_meeting_direct(transcript)

        self.assertEqual(result, "polished")
        self.assertEqual(ask.call_count, 1)
        prompt = ask.call_args.args[0]
        self.assertIn(transcript, prompt)
        self.assertIn("conditional", prompt.lower())
        polish.assert_called_once_with(
            "draft",
            source_material=transcript,
            source_label="complete chronological transcript",
            timeout_seconds=None,
        )


if __name__ == "__main__":
    unittest.main()
