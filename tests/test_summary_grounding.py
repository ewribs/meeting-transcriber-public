import unittest
from unittest.mock import patch

import ai


class SummaryGroundingTests(unittest.TestCase):
    def test_structured_memory_replaces_precision_sensitive_sections(self):
        draft = """# Meeting Summary

## Decisions

None identified.

## Action Items

- Invented action

## Open Questions

- What should happen next?
"""
        memory = {
            "decisions": [
                {
                    "decision": "Cut Vendor Gamma from the vendor list.",
                    "evidence": "The decision is to cut Vendor Gamma from the vendor list.",
                }
            ],
            "commitments": [],
            "open_questions": [],
            "topics": [
                {
                    "topic": "MFD RFP Recommendation",
                    "status": "ongoing",
                    "summary": "Vendor Gamma was removed from the vendor list.",
                }
            ],
        }

        result = ai.compose_summary_with_meeting_memory(draft, memory)

        self.assertIn("- Cut Vendor Gamma from the vendor list.", result)
        self.assertNotIn("Invented action", result)
        self.assertNotIn("What should happen next?", result)
        self.assertIn("## Topics", result)
        self.assertIn("### MFD RFP Recommendation — ongoing", result)

    def test_grounded_polish_prompt_contains_consistency_rules_and_source(self):
        prompt = ai.build_grounded_summary_polish_prompt(
            "# Meeting Summary\n\n## Decisions\n\nNone identified.",
            source_material="The team explicitly decided to renew Vendor A.",
            source_label="complete chronological transcript",
        )

        self.assertIn("complete chronological transcript", prompt.lower())
        self.assertIn("Never promote discussion", prompt)
        self.assertIn("ACTION ITEMS", prompt)
        self.assertIn("OPEN QUESTIONS", prompt)
        self.assertIn("CROSS-SECTION CONSISTENCY", prompt)
        self.assertIn("no decisions", prompt)
        self.assertIn("explicitly decided to renew Vendor A", prompt)

    @patch("ai.ask_llm", return_value="# Meeting Summary\n\nGrounded.")
    def test_direct_summary_polish_receives_original_transcript(self, ask_llm):
        transcript = "The team explicitly decided to renew Vendor A."

        ai.summarize_meeting_direct(transcript, timeout_seconds=12)

        self.assertEqual(ask_llm.call_count, 2)
        final_prompt = ask_llm.call_args_list[-1].args[0]
        self.assertIn("SOURCE OF TRUTH", final_prompt)
        self.assertIn(transcript, final_prompt)
        self.assertEqual(
            ask_llm.call_args_list[-1].kwargs["timeout_seconds"],
            12,
        )

    @patch("ai.polish_meeting_summary", return_value="grounded")
    @patch("ai.ask_llm", return_value="draft")
    @patch("ai.chunk_transcript", return_value=["first", "second"])
    def test_chunked_summary_polish_uses_section_summaries(
        self,
        _chunk_transcript,
        _ask_llm,
        polish,
    ):
        result = ai.summarize_meeting_in_chunks(
            "large transcript",
            timeout_seconds=34,
        )

        self.assertEqual(result, "grounded")
        kwargs = polish.call_args.kwargs
        self.assertEqual(kwargs["source_label"], "chronological section summaries")
        self.assertIn("draft", polish.call_args.args[0])
        self.assertEqual(kwargs["source_material"], "draft\n\ndraft")
        self.assertEqual(kwargs["timeout_seconds"], 34)


if __name__ == "__main__":
    unittest.main()
