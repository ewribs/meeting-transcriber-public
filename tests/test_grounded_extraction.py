import json
import unittest
from unittest.mock import patch

import ai


class GroundedExtractionTests(unittest.TestCase):
    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_validated_decisions_are_returned(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "We agreed to use a one-year term."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [
                    {
                        "decision": "Use a one-year term.",
                        "evidence": "We agreed to use a one-year term.",
                    }
                ],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="Test Meeting",
            transcript=transcript,
            participants=[],
        )

        self.assertEqual(result["commitments"], [])
        self.assertEqual(
            result["decisions"],
            [
                {
                    "decision": "Use a one-year term.",
                    "evidence": "We agreed to use a one-year term.",
                }
            ],
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_explicit_vendor_exclusion_is_recovered_when_model_omits_it(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "The decision is to cut Vendor Gamma from the vendor list."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="TEST8",
            transcript=transcript,
        )

        self.assertEqual(
            result["decisions"],
            [
                {
                    "decision": "The decision is to cut Vendor Gamma from the vendor list",
                    "evidence": transcript,
                }
            ],
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_test9_decisions_are_entailed_deduplicated_and_recovered(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        network_provider_a_evidence = (
            "We are moving forward with Network Provider A and will re-engage Vendor Beta later."
        )
        malformed_duplicate = (
            "We are moving forward with Network Provider A, throttle it through the interim "
            "noise, and will re-engage Vendor Beta later."
        )
        vendor_gamma_evidence = "I gave approval to cut Vendor Gamma loose."
        vendor_delta_evidence = (
            "Vendor Delta was over budget, Vendor Epsilon was cheaper, and I am unlikely to "
            "recommend Vendor Delta."
        )
        transcript = " ".join((network_provider_a_evidence, malformed_duplicate, vendor_gamma_evidence, vendor_delta_evidence))
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [
                    {
                        "decision": "Move ahead with Network Provider A and re-engage Vendor Beta later.",
                        "evidence": network_provider_a_evidence,
                    },
                    {
                        "decision": malformed_duplicate,
                        "evidence": malformed_duplicate,
                    },
                    {
                        "decision": "Vendor Delta was selected.",
                        "evidence": vendor_delta_evidence,
                    },
                ],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="TEST9",
            transcript=transcript,
        )

        decision_text = [item["decision"] for item in result["decisions"]]
        self.assertEqual(
            sum("Network Provider A" in item for item in decision_text),
            1,
        )
        self.assertIn(
            "Move ahead with Network Provider A and re-engage Vendor Beta later.",
            decision_text,
        )
        self.assertIn("I gave approval to cut Vendor Gamma loose", decision_text)
        self.assertFalse(any("selected" in item for item in decision_text))
        self.assertFalse(any("throttle" in item for item in decision_text))

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_test9_malformed_question_fragment_is_rejected(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "Where did, Theron? What price did Vendor Epsilon quote for support?"
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "open_questions": [
                    {
                        "question": "where did, Theron?",
                        "evidence": "Where did, Theron?",
                    },
                    {
                        "question": "What price did Vendor Epsilon quote for support?",
                        "evidence": "What price did Vendor Epsilon quote for support?",
                    },
                ],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="TEST9",
            transcript=transcript,
        )

        self.assertEqual(
            result["open_questions"],
            ["What price did Vendor Epsilon quote for support?"],
        )

    @patch("ai.extract_grounded_commitments_and_decisions")
    @patch("ai.build_meeting_memory")
    def test_summary_generated_questions_and_followups_are_not_authoritative(
        self,
        build_memory,
        extract_grounded,
    ):
        build_memory.return_value = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "open_questions": [
                "What are the next steps for the MFD recommendation?"
            ],
            "follow_ups": ["Finalize the MFD recommendation"],
        }
        extract_grounded.return_value = {
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
        }

        result = ai.build_complete_meeting_memory(
            meeting_label="TEST8",
            meeting_summary="summary",
            transcript="transcript",
        )

        self.assertEqual(result["open_questions"], [])
        self.assertEqual(result["follow_ups"], [])

    @patch("ai.extract_grounded_commitments_and_decisions")
    @patch("ai.build_meeting_memory")
    def test_test9_topics_follow_authoritative_actions_status_and_decisions(
        self,
        build_memory,
        extract_grounded,
    ):
        transcript = (
            "We are moving forward with Network Provider A and will re-engage Vendor Beta later. "
            "Vendor Delta was over budget and Vendor Epsilon was cheaper. "
            "The Colocation Provider A monitor invoicing issue is resolved, but the Colocation Provider A "
            "amendment is still in my inbox unread."
        )
        build_memory.return_value = {
            "topics": [
                {
                    "topic_key": "network_provider_a_plan",
                    "topic": "Network Provider A NAS",
                    "status": "ongoing",
                    "summary": (
                        "The Network Provider A plan is proceeding. Action item to finalize "
                        "the plan was identified."
                    ),
                },
                {
                    "topic_key": "mfd_rfp",
                    "topic": "MFD RFP",
                    "status": "open",
                    "summary": "Vendor Epsilon may be preferred because it was cheaper.",
                },
                {
                    "topic_key": "colocation_provider_a_amendment",
                    "topic": "Colocation Provider A Amendment",
                    "status": "closed",
                    "summary": "The monitor invoicing issue was resolved.",
                },
            ],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
        }
        extract_grounded.return_value = {
            "commitments": [],
            "decisions": [
                {
                    "decision": "Move ahead with Network Provider A and re-engage Vendor Beta later.",
                    "evidence": (
                        "We are moving forward with Network Provider A and will re-engage "
                        "Vendor Beta later."
                    ),
                },
                {
                    "decision": "Vendor Delta was selected.",
                    "evidence": "Vendor Delta was over budget and Vendor Epsilon was cheaper.",
                },
            ],
            "open_questions": [],
            "follow_ups": [],
        }

        result = ai.build_complete_meeting_memory(
            meeting_label="TEST9",
            meeting_summary="summary",
            transcript=transcript,
        )

        self.assertEqual(
            [item["decision"] for item in result["decisions"]],
            ["Move ahead with Network Provider A and re-engage Vendor Beta later."],
        )
        self.assertNotIn("Action item", result["topics"][0]["summary"])
        self.assertIn("Vendor Epsilon may be preferred", result["topics"][1]["summary"])
        self.assertEqual(result["topics"][2]["status"], "open")

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_questions_and_followups_require_verbatim_evidence(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "We discussed the MFD recommendation."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "open_questions": [
                    {
                        "question": "What are the next steps?",
                        "evidence": "What are the next steps?",
                    }
                ],
                "follow_ups": [
                    {
                        "follow_up": "Finalize the recommendation",
                        "evidence": "Please finalize the recommendation.",
                    }
                ],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="TEST8",
            transcript=transcript,
        )

        self.assertEqual(result["open_questions"], [])
        self.assertEqual(result["follow_ups"], [])

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_unsupported_commitment_paraphrase_falls_back_to_quote(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "I'll send the report."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Send the report to Finance by Friday",
                        "evidence": transcript,
                    }
                ],
                "decisions": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="TEST8",
            transcript=transcript,
        )

        self.assertEqual(result["commitments"][0]["action"], transcript)

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_social_attendance_is_not_a_work_commitment(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "I'll be there. I can make it. "
            "I'll send the revised deck this week."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Attend the meeting",
                        "evidence": "I'll be there.",
                    },
                    {
                        "owner": "Unknown",
                        "action": "Attend the meeting",
                        "evidence": "I can make it.",
                    },
                    {
                        "owner": "Unknown",
                        "action": "Send the revised deck",
                        "evidence": "I'll send the revised deck this week.",
                    },
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-COMMITMENT-TEST",
            transcript=transcript,
        )

        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(
            result["commitments"][0]["evidence"],
            "I'll send the revised deck this week.",
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_risks_require_explicit_non_negated_verbatim_evidence(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "we just gotta get delivery before the end of the year four to six weeks "
            "for hardware so it's really not we're not at any risk really no. "
            "I am worried the support renewal could miss the December deadline."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "risks": [
                    {
                        "risk": "Hardware delivery timing is a risk.",
                        "evidence": "we're not at any risk really no",
                    },
                    {
                        "risk": "Support renewal could miss the December deadline.",
                        "evidence": "I am worried the support renewal could miss the December deadline.",
                    },
                    {
                        "risk": "Vendor complexity could increase long-term costs.",
                        "evidence": "four to six weeks for hardware",
                    },
                ],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="RISKTEST",
            transcript=transcript,
        )

        self.assertEqual(
            result["risks"],
            [
                {
                    "risk": "Support renewal could miss the December deadline.",
                    "evidence": "I am worried the support renewal could miss the December deadline.",
                }
            ],
        )

    @patch("ai.extract_grounded_commitments_and_decisions")
    @patch("ai.build_meeting_memory")
    def test_grounded_risks_replace_summary_generated_risks(
        self,
        build_memory,
        extract_grounded,
    ):
        build_memory.return_value = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "risks": ["Invented narrative risk"],
            "open_questions": [],
            "follow_ups": [],
        }
        extract_grounded.return_value = {
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": [],
            "follow_ups": [],
        }

        result = ai.build_complete_meeting_memory(
            meeting_label="RISKTEST",
            meeting_summary="summary",
            transcript="there is no risk here",
        )

        self.assertEqual(result["risks"], [])

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_conditional_offer_is_not_a_work_commitment(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "If you need help with the analysis, give it to me and I'll help. "
            "I'll send the revised deck tomorrow."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Help with the analysis",
                        "evidence": "If you need help with the analysis, give it to me and I'll help.",
                    },
                    {
                        "owner": "Unknown",
                        "action": "Send the revised deck",
                        "evidence": "I'll send the revised deck tomorrow.",
                    },
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-CONDITIONAL-COMMITMENT",
            transcript=transcript,
        )

        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(
            result["commitments"][0]["evidence"],
            "I'll send the revised deck tomorrow.",
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_adjacent_pronoun_commitment_is_merged(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "I'll notify the team. Yeah, I'll take care of it."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Notify the team",
                        "evidence": "I'll notify the team.",
                    },
                    {
                        "owner": "Unknown",
                        "action": "Take care of it",
                        "evidence": "I'll take care of it.",
                    },
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-MERGE-COMMITMENT",
            transcript=transcript,
        )

        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(
            result["commitments"][0]["evidence"],
            "I'll notify the team. Yeah, I'll take care of it.",
        )

    def test_pronominal_removal_decision_uses_nearby_topic_context(self):
        transcript = (
            "We reviewed Vendor Atlas Replacement and the remaining transition work. "
            "We got approval and we dropped them."
        )
        memory = {
            "topics": [
                {
                    "topic_key": "vendor_atlas_replacement",
                    "topic": "Vendor Atlas Replacement",
                    "status": "closed",
                    "summary": "Vendor Atlas Replacement is closed.",
                }
            ],
            "commitments": [],
            "decisions": [
                {
                    "decision": "Drop them.",
                    "evidence": "we dropped them",
                }
            ],
            "risks": [],
            "open_questions": [],
            "follow_ups": [],
        }

        result = ai._reconcile_meeting_memory(memory, transcript)

        self.assertEqual(
            result["decisions"],
            [
                {
                    "decision": "Drop Vendor Atlas.",
                    "evidence": "we dropped them",
                }
            ],
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_explicit_unresolved_question_is_recovered_when_model_omits_it(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "What is the path to incorporate the amendment into the agreement. "
            "That item is still open and I am unclear how it carries over. "
            "Are these separate orders. It will be a single order."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-QUESTION-RECOVERY",
            transcript=transcript,
        )

        self.assertEqual(
            result["open_questions"],
            ["What is the path to incorporate the amendment into the agreement"],
        )



    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_conditional_offer_with_name_prefix_is_not_commitment(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "Jordan, if I can help with some of this, let me help, please. "
            "I'll send the revised plan tomorrow."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Help with some of this",
                        "evidence": "Jordan, if I can help with some of this, let me help, please.",
                    },
                    {
                        "owner": "Unknown",
                        "action": "Send the revised plan",
                        "evidence": "I'll send the revised plan tomorrow.",
                    },
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-CONDITIONAL-OFFER-PREFIX",
            transcript=transcript,
        )

        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(
            result["commitments"][0]["evidence"],
            "I'll send the revised plan tomorrow.",
        )

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_indistinct_commitment_is_rejected(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = "I'll touch base on (indistinct)."
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Unknown",
                        "action": "Touch base",
                        "evidence": "I'll touch base on (indistinct)",
                    }
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-INDISTINCT-COMMITMENT",
            transcript=transcript,
        )

        self.assertEqual(result["commitments"], [])

    def test_pronominal_removal_does_not_cross_speaker_boundary(self):
        transcript = (
            "[01:00] **Remote**\n\n"
            "We reviewed Vendor Atlas Replacement and the remaining transition work.\n\n"
            "[01:15] **Mic**\n\n"
            "On a separate personal topic, we dropped them."
        )
        memory = {
            "topics": [
                {
                    "topic_key": "vendor_atlas_replacement",
                    "topic": "Vendor Atlas Replacement",
                    "status": "ongoing",
                    "summary": "Vendor Atlas Replacement is still under review.",
                }
            ],
            "commitments": [],
            "decisions": [
                {
                    "decision": "Drop them.",
                    "evidence": "we dropped them",
                }
            ],
            "risks": [],
            "open_questions": [],
            "follow_ups": [],
        }

        result = ai._reconcile_meeting_memory(memory, transcript)

        self.assertEqual(result["decisions"], [])

    def test_open_questions_reject_spill_and_deduplicate_variants(self):
        questions = [
            "what is the cap for that",
            "what is the cap for that because the current language is unclear",
            "have the language, I don't know what are the conditions for\n\n[03:50] **Mic**",
            "is it fair to say that commercials were good",
        ]

        result = ai._normalize_open_questions(questions)

        self.assertEqual(result, ["what is the cap for that"])

    @patch("ai.ask_llm")
    @patch("ai.chunk_transcript")
    def test_question_fallback_does_not_borrow_uncertainty_before_question(
        self,
        mock_chunk_transcript,
        mock_ask_llm,
    ):
        transcript = (
            "We are not sure about an earlier issue. "
            "Are these separate orders. It will be a single order."
        )
        mock_chunk_transcript.return_value = [transcript]
        mock_ask_llm.return_value = json.dumps(
            {
                "commitments": [],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )

        result = ai.extract_grounded_commitments_and_decisions(
            meeting_label="GENERIC-QUESTION-NO-BORROW",
            transcript=transcript,
        )

        self.assertEqual(result["open_questions"], [])

    def test_open_questions_reject_incomplete_question_fragments(self):
        questions = [
            "what is offered I'll walk you through",
            "which would fix some of that timing iteration",
            "what guidance do you have for like making",
            "what is the cap for that",
            "how should we handle the renewal timing",
        ]

        result = ai._normalize_open_questions(questions)

        self.assertEqual(
            result,
            [
                "what is the cap for that",
                "how should we handle the renewal timing",
            ],
        )



if __name__ == "__main__":
    unittest.main()
