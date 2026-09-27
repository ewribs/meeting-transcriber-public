import json
import unittest
from unittest.mock import patch

import ai


class PromptPrivacyTests(unittest.TestCase):
    @patch("ai.ask_llm")
    def test_meeting_memory_prompt_uses_generic_supplier_examples(self, mock_ask_llm):
        mock_ask_llm.return_value = json.dumps(
            {
                "topics": [],
                "commitments": [],
                "decisions": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        ai.build_meeting_memory(
            meeting_label="Example Meeting",
            meeting_summary="Vendor Alpha renewal remains open.",
        )

        prompt = mock_ask_llm.call_args.args[0]
        self.assertIn("Vendor Alpha", prompt)
        self.assertIn("Platform Gamma", prompt)
        self.assertIn('topic_key: "vendor_alpha_renewal"', prompt)
        self.assertIn('"Get Alex\'s update on Vendor Alpha"', prompt)

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_grounded_extraction_prompt_uses_generic_decision_examples(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "We agreed to use a one-year term."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        ai.extract_grounded_commitments_and_decisions(
            meeting_label="Example Meeting",
            transcript=transcript,
        )

        prompt = mock_ask_llm.call_args.args[0]
        self.assertIn("cut Vendor Gamma from the list", prompt)
        self.assertIn("we selected Vendor Delta", prompt)
        self.assertIn("we are going with Vendor Delta", prompt)


if __name__ == "__main__":
    unittest.main()
