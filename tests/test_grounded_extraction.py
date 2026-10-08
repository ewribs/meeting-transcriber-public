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



    def test_precision_v3_rejects_fake_is_out_decisions(self):
        self.assertFalse(
            ai._decision_evidence_is_explicit("Field is out doing field things")
        )
        self.assertFalse(
            ai._decision_evidence_is_explicit("OS is out?")
        )
        self.assertTrue(
            ai._decision_evidence_is_explicit("Vendor Atlas is out.")
        )

    def test_precision_v3_rejects_malformed_open_questions(self):
        result = ai._normalize_open_questions(
            [
                "have it listed but we don't have savings attached to it at this point Correct",
                "do it, we shouldn't be doing it",
                "why would we convert them all?",
            ]
        )
        self.assertEqual(result, ["why would we convert them all?"])

    def test_precision_v3_rejects_locally_answered_question(self):
        transcript = (
            "[10:00] **Mic**\nWhen do you think this goes back to them?\n\n"
            "[10:05] **Remote**\nHopefully early next week."
        )
        self.assertFalse(
            ai._question_is_locally_unresolved(
                "When do you think this goes back to them?",
                transcript,
            )
        )

    def test_precision_v3_keeps_explicitly_unresolved_question(self):
        transcript = (
            "[10:00] **Mic**\nWhy would we convert them all?\n\n"
            "[10:05] **Remote**\nI don't know if I can answer that. We still need to validate the target state."
        )
        self.assertTrue(
            ai._question_is_locally_unresolved(
                "Why would we convert them all?",
                transcript,
            )
        )

    def test_precision_v3_rejects_clipped_commitment(self):
        self.assertFalse(
            ai._commitment_is_actionable("I'll put it I just", "I'll put it I just")
        )
        self.assertTrue(
            ai._commitment_is_actionable(
                "I'll send you the updated file",
                "I'll send you the updated file",
            )
        )

    def test_precision_v3_deduplicates_exact_commitments(self):
        commitments = [
            {
                "owner": "Person A",
                "action": "I'll send the file",
                "evidence": "I'll send the file",
                "status": "open",
            },
            {
                "owner": "Person A",
                "action": "I'll send the file",
                "evidence": "I'll send the file",
                "status": "open",
            },
        ]
        result = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(result), 1)


    def test_precision_v4_fallback_requires_decision_evidence(self):
        transcript = (
            "Field is out doing field things. "
            "OS is out? "
            "VendorAtlas is out."
        )

        result = ai._explicit_decision_fallbacks(transcript)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["evidence"], "VendorAtlas is out.")

    def test_precision_v4_fallback_rejects_descriptive_is_out_statement(self):
        result = ai._explicit_decision_fallbacks(
            "The field is out doing field things today."
        )
        self.assertEqual(result, [])

    def test_precision_v4_fallback_rejects_interrogative_is_out_statement(self):
        result = ai._explicit_decision_fallbacks("OS is out?")
        self.assertEqual(result, [])


    def test_precision_v5_rejects_cut_over_as_removal_decision(self):
        transcript = (
            "The migration will continue next month and one third of the sites "
            "will need a cut over before activation."
        )
        self.assertEqual(ai._recover_explicit_removal_decisions(transcript), [])

    def test_precision_v5_resolves_opaque_commitment_from_tight_context(self):
        transcript = (
            "We need to send the updated pricing spreadsheet to the finance team. "
            "I'll do that right now."
        )
        resolved = ai._resolve_commitment_action(
            "Send the updated pricing spreadsheet to the finance team",
            "I'll do that right now.",
            transcript,
        )
        self.assertEqual(
            resolved,
            "Send the updated pricing spreadsheet to the finance team",
        )

    def test_precision_v5_omits_unresolved_opaque_commitment(self):
        transcript = "We talked through several options. I'll do that right now."
        self.assertIsNone(
            ai._resolve_commitment_action(
                "I'll do that right now",
                "I'll do that right now.",
                transcript,
            )
        )

    def test_precision_v8_rejects_tasking_commitment_without_topic(self):
        transcript = (
            "We need to decide the future state for Platform Beta. "
            "I'll meet with Speaker B and Speaker C next week. "
            "I'm going to put them to task on that too."
        )
        self.assertIsNone(
            ai._resolve_commitment_action(
                "Put Speaker B and Speaker C to task",
                "I'm going to put them to task on that too.",
                transcript,
            )
        )

    def test_precision_v8_keeps_tasking_commitment_with_grounded_topic(self):
        transcript = (
            "We need to decide the Platform Beta future state. "
            "I'll meet with Speaker B and Speaker C next week. "
            "I'm going to put them to task on that too."
        )
        resolved = ai._resolve_commitment_action(
            "Put Speaker B and Speaker C to task on Platform Beta future state",
            "I'm going to put them to task on that too.",
            transcript,
        )
        self.assertEqual(
            resolved,
            "Put Speaker B and Speaker C to task on Platform Beta future state",
        )

    def test_precision_v8_rejects_unresolved_second_person_commitment(self):
        transcript = "I'll include you on the project emails going forward."
        self.assertIsNone(
            ai._resolve_commitment_action(
                "I'll include you on the project emails going forward.",
                "I'll include you on the project emails going forward.",
                transcript,
            )
        )

    def test_precision_v5_omits_low_value_social_photo_commitment(self):
        transcript = (
            "That team picture was funny. I'll post the picture to the group chat."
        )
        self.assertIsNone(
            ai._resolve_commitment_action(
                "I'll post the picture to the group chat",
                "I'll post the picture to the group chat.",
                transcript,
            )
        )

    def test_precision_v5_rejects_repeated_and_chopped_open_question(self):
        question = (
            "do you do you think Vendor Alpha will have that broken out in the "
            "way you described except for the"
        )
        self.assertFalse(ai._is_well_formed_question(question))

    def test_precision_v5_rejects_conversational_problem_question(self):
        transcript = (
            "I mean, I guess, is it our problem? It's a purchase order and the "
            "lines have to be right. Who owns fixing them?"
        )
        self.assertFalse(
            ai._question_is_locally_unresolved("is it our problem?", transcript)
        )

    def test_precision_v5_recovers_plainly_stated_explicit_risk(self):
        result = ai._explicit_risk_fallbacks(
            "We're still at risk of a single instance failure. "
            "The team will review mitigation next week."
        )
        self.assertEqual(len(result), 1)
        self.assertIn("single instance failure", result[0]["risk"])

    def test_precision_v5_does_not_recover_negated_risk(self):
        result = ai._explicit_risk_fallbacks(
            "We are not at risk of a single instance failure."
        )
        self.assertEqual(result, [])

    def test_precision_v6_rejects_question_with_trailing_conversation(self):
        self.assertFalse(
            ai._is_well_formed_question(
                "What is the conflict with Platform Beta? Let me understand"
            )
        )


    def test_precision_v9_rejects_diagnostic_question_when_local_discussion_explains_issue(self):
        transcript = (
            "[04:03] **Remote**\nWhat is the conflict with Platform Beta?\n\n"
            "[04:10] **Mic**\nWhat is the timing dependency?\n\n"
            "[04:20] **Remote**\nIf Platform Beta slips, several dependent services "
            "would remain on legacy hosting and we would have to migrate them separately."
        )
        self.assertFalse(
            ai._question_is_locally_unresolved(
                "What is the conflict with Platform Beta?",
                transcript,
            )
        )

    def test_precision_v9_keeps_diagnostic_question_when_issue_is_explicitly_unknown(self):
        transcript = (
            "[04:03] **Remote**\nWhat is the conflict with Platform Beta?\n\n"
            "[04:10] **Mic**\nI don't know yet. We still need to investigate the dependency."
        )
        self.assertTrue(
            ai._question_is_locally_unresolved(
                "What is the conflict with Platform Beta?",
                transcript,
            )
        )

    def test_precision_v6_rejects_immediately_answered_duration_question(self):
        transcript = (
            "[04:45] **Mic**\n\nIs it two years?\n\n"
            "[04:50] **Remote**\n\nThey describe it as a three-year transition, "
            "probably three to five years."
        )
        self.assertFalse(
            ai._question_is_locally_unresolved("Is it two years?", transcript)
        )

    def test_precision_v6_rejects_clipped_risk_ending_in_comma(self):
        risk = (
            "the risk that we see is that as we send the communication "
            "to the business where we say,"
        )
        self.assertFalse(ai._risk_is_supported(risk, risk))

    def test_precision_v6_rejects_long_conversational_concern_spill(self):
        risk = (
            "I'm a little concerned about this topic and like the expectations "
            "of what we're gonna like what we're gonna get out of the discussion "
            "yes I mean Speaker A we just had this conversation earlier this week"
        )
        self.assertFalse(ai._risk_is_supported(risk, risk))

    def test_precision_v6_preserves_complete_explicit_risk(self):
        risk = (
            "the risk here is that late changes may create resistance from the team"
        )
        self.assertTrue(ai._risk_is_supported(risk, risk))

    def test_precision_v6_resolves_opaque_follow_up_from_tight_context(self):
        transcript = (
            "We need to decide whether Platform Beta stays in the target state. "
            "We will take that as a follow-up to make a decision."
        )
        resolved = ai._resolve_follow_up_action(
            "Decide whether Platform Beta stays in the target state",
            "We will take that as a follow-up to make a decision.",
            transcript,
        )
        self.assertEqual(
            resolved,
            "Decide whether Platform Beta stays in the target state",
        )

    def test_precision_v6_omits_unresolved_opaque_follow_up(self):
        transcript = (
            "We covered several unrelated topics. "
            "We will take that as a follow-up to make a decision."
        )
        self.assertIsNone(
            ai._resolve_follow_up_action(
                "Take that as a follow-up to make a decision",
                "We will take that as a follow-up to make a decision.",
                transcript,
            )
        )

    def test_precision_v6_follow_up_uses_model_action_not_opaque_evidence(self):
        transcript = (
            "Please send the Platform Beta review slides to the working group. "
            "We can absolutely, as a follow-up, send those out tomorrow."
        )
        resolved = ai._resolve_follow_up_action(
            "Send the Platform Beta review slides to the working group",
            "We can absolutely, as a follow-up, send those out tomorrow.",
            transcript,
        )
        self.assertEqual(
            resolved,
            "Send the Platform Beta review slides to the working group",
        )

    def test_precision_v7_recovers_complete_risk_across_adjacent_same_channel_blocks(self):
        transcript = (
            "[10:02] **Remote**\n\n"
            "We need capacity for Project Delta before the renewal next June,\n\n"
            "[10:44] **Remote**\n\n"
            "and teams are saying this was not in their plan. "
            "I think the risk here is that late-arriving work may create resistance around that. "
            "Where are you hearing that?"
        )
        result = ai._explicit_risk_fallbacks(transcript)
        self.assertEqual(len(result), 1)
        self.assertIn("late-arriving work may create resistance", result[0]["risk"])

    def test_precision_v7_does_not_merge_risk_context_across_channel_change(self):
        transcript = (
            "[10:02] **Remote**\n\n"
            "I think the risk here is that this may continue,\n\n"
            "[10:44] **Mic**\n\n"
            "and the team could resist the change."
        )
        self.assertEqual(ai._explicit_risk_fallbacks(transcript), [])

    def test_precision_v7_rejects_vague_follow_up_decision_reference(self):
        transcript = (
            "We discussed several options during the session. "
            "We will take that as a follow-up to make a decision from today's session."
        )
        self.assertIsNone(
            ai._resolve_follow_up_action(
                "Take a follow-up on the decision from today's session",
                "We will take that as a follow-up to make a decision from today's session.",
                transcript,
            )
        )

    def test_precision_v7_rejects_conversational_follow_up_action_text(self):
        transcript = (
            "We have review slides for Platform Beta. "
            "We can absolutely, as a follow-up, send out what we're looking at because slides are associated."
        )
        self.assertIsNone(
            ai._resolve_follow_up_action(
                "We can absolutely, as a follow-up, send out what we're looking at because slides are associated",
                "We can absolutely, as a follow-up, send out what we're looking at because slides are associated.",
                transcript,
            )
        )

    def test_precision_v7_keeps_grounded_self_contained_follow_up_action(self):
        transcript = (
            "We have Platform Beta review slides for the working group. "
            "We can absolutely, as a follow-up, send those slides to the working group tomorrow."
        )
        resolved = ai._resolve_follow_up_action(
            "Send the Platform Beta review slides to the working group",
            "We can absolutely, as a follow-up, send those slides to the working group tomorrow.",
            transcript,
        )
        self.assertEqual(
            resolved,
            "Send the Platform Beta review slides to the working group",
        )


    def test_precision_v10_rejects_pronominal_drop_directives_as_decisions(self):
        transcript = (
            "[01:00] **Mic**\n\nI'm going to show the current plan.\n\n"
            "[01:10] **Remote**\n\nYou deliberately drop those when usage falls.\n\n"
            "[01:20] **Mic**\n\nJust drop me the names when you have them."
        )
        self.assertEqual(ai._recover_explicit_removal_decisions(transcript), [])

    def test_precision_v10_recovers_explicit_action_item_when_model_omits_it(self):
        transcript = (
            "[01:00] **Remote**\n\n"
            "I will take the action to draft an email on Platform Beta and then you can edit it."
        )
        recovered = ai._explicit_commitment_fallbacks(transcript)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["owner"], "Unknown")
        self.assertEqual(recovered[0]["action"], "Draft an email on Platform Beta")
        self.assertEqual(
            recovered[0]["evidence"],
            "I will take the action to draft an email on Platform Beta",
        )

    def test_precision_v10_recovers_i_have_an_action_item_wording(self):
        transcript = "I have an action item to send the revised workbook to Finance."
        recovered = ai._explicit_commitment_fallbacks(transcript)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(
            recovered[0]["action"],
            "Send the revised workbook to Finance",
        )

    def test_precision_v10_rejects_same_block_question_that_is_answered(self):
        transcript = (
            "How are you doing with Platform Beta capacity? "
            "We reduced the additional capacity to one thousand units after optimization."
        )
        self.assertFalse(
            ai._question_is_locally_unresolved(
                "How are you doing with Platform Beta capacity?", transcript
            )
        )

    def test_precision_v10_rejects_immediately_answered_question_even_with_later_unknown_phrase(self):
        transcript = (
            "Have you heard that as well? No, they do negotiate. "
            "If you don't know your baseline, it is hard to build the strategy."
        )
        self.assertFalse(
            ai._question_is_locally_unresolved("Have you heard that as well?", transcript)
        )

    def test_precision_v10_keeps_explicitly_unresolved_question(self):
        transcript = (
            "Have you heard whether Platform Beta will change? "
            "I don't know yet; we need to confirm with the product team."
        )
        self.assertTrue(
            ai._question_is_locally_unresolved(
                "Have you heard whether Platform Beta will change?", transcript
            )
        )

    def test_precision_v101_keeps_yes_answer_that_requires_double_check(self):
        transcript = (
            "Do you know if the extension includes the price protection? "
            "Yeah, it should have. I'll have to double check to make sure it is included."
        )
        self.assertTrue(
            ai._question_is_locally_unresolved(
                "Do you know if the extension includes the price protection?", transcript
            )
        )

    def test_precision_v101_fallback_recovers_question_with_tentative_yes_answer(self):
        transcript = (
            "Do you know if the extension includes the price protection? "
            "Yeah, it should have. I'll have to double check to make sure it is included."
        )
        self.assertEqual(
            ai._explicit_unresolved_question_fallbacks(transcript),
            ["Do you know if the extension includes the price protection?"],
        )

    def test_precision_v101_keeps_tentatively_answered_owner_question(self):
        transcript = (
            "[40:46] **Mic**\n\nWho owns the Platform Beta admin portal?\n\n"
            "[40:49] **Remote**\n\nPlatform Operations would be Team Delta. "
            "I think it's them; I'll reach out and see if they do or if it's somebody else."
        )
        self.assertTrue(
            ai._question_is_locally_unresolved(
                "Who owns the Platform Beta admin portal?", transcript
            )
        )


    def test_precision_v102_contextualizes_opaque_open_question(self):
        transcript = (
            "[12:00] **Remote**\n\n"
            "The 10% price cap, whether or not that was extended into the renewal, "
            "is something we still need to verify. Do you know if that got extended? "
            "Yeah, it should have. I'll have to double check to make sure it was included."
        )
        self.assertEqual(
            ai._contextualize_open_question(
                "Do you know if that got extended?", transcript
            ),
            "Was the 10% price cap extended into the renewal?",
        )

    def test_precision_v102_omits_opaque_open_question_without_clear_antecedent(self):
        transcript = (
            "[12:00] **Remote**\n\n"
            "We talked through several renewal items. Do you know if that got extended? "
            "I'm not sure; I'll have to verify."
        )
        self.assertIsNone(
            ai._contextualize_open_question(
                "Do you know if that got extended?", transcript
            )
        )

    def test_precision_v102_reconcile_rewrites_question_for_durable_memory(self):
        transcript = (
            "[12:00] **Remote**\n\n"
            "The 10% price cap, whether or not that was extended into the renewal, "
            "is something we still need to verify. Do you know if that got extended? "
            "Yeah, it should have. I'll have to double check to make sure it was included."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": ["Do you know if that got extended?"],
            "follow_ups": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(
            result["open_questions"],
            ["Was the 10% price cap extended into the renewal?"],
        )

    def test_precision_v101_remote_model_commitment_owner_is_not_inferred(self):
        transcript = (
            "[01:00] **Remote**\n\n"
            "I will take the action to draft the Platform Beta email."
        )
        original = ai.ask_llm
        ai.ask_llm = lambda *args, **kwargs: json.dumps(
            {
                "commitments": [
                    {
                        "owner": "Speaker A",
                        "action": "Draft the Platform Beta email",
                        "evidence": "I will take the action to draft the Platform Beta email",
                    }
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }
        )
        try:
            result = ai.extract_grounded_commitments_and_decisions(
                "Generic Meeting",
                transcript,
                participants=[{"name": "Speaker A"}],
                chunk_words=1500,
            )
        finally:
            ai.ask_llm = original
        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(result["commitments"][0]["owner"], "Unknown")

    def test_precision_v11_contextual_resolver_recovers_named_action_and_durable_memory(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "We want to explore Vendor Alpha before deciding whether to change support. "
            "[00:30] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a follow-up meeting set up "
            "with Vendor Alpha for the four of us? "
            "[00:50] **Remote**\n\n"
            "Send me the contact, Speaker B, and I'll reach out to Vendor Alpha and set up "
            "the follow-up meeting for the four of us. "
            "[01:20] **Mic**\n\n"
            "Are we forfeiting our perpetual license rights if we move to Vendor Alpha? "
            "[01:35] **Remote**\n\n"
            "I don't know. We'll need to find out. "
            "[02:00] **Mic**\n\n"
            "There is a risk of IP infringement if Vendor Alpha redistributes patches "
            "without the right permissions. "
            "[02:30] **Mic**\n\n"
            "Let's have the follow-up conversation with Vendor Alpha and then decide "
            "whether to proceed."
        )
        first_pass = {
            "commitments": [
                {
                    "owner": "Unknown",
                    "action": "I'll reach out to Vendor Alpha",
                    "status": "open",
                    "evidence": "I'll reach out to Vendor Alpha",
                }
            ],
            "decisions": [],
            "risks": [
                {
                    "risk": "There is a risk",
                    "evidence": [
                        "There is a risk of IP infringement if Vendor Alpha redistributes patches without the right permissions.",
                    ],
                }
            ],
            "open_questions": [],
        }
        resolved_json = {
            "commitments": [
                {
                    "owner": "Speaker B",
                    "action": "Reach out to Vendor Alpha and set up the follow-up meeting for the four of us.",
                    "evidence": [
                        "Speaker B, why don't you take the lead on getting a follow-up meeting set up with Vendor Alpha for the four of us?",
                        "Send me the contact, Speaker B, and I'll reach out to Vendor Alpha and set up the follow-up meeting for the four of us.",
                    ],
                }
            ],
            "decisions": [
                {
                    "decision": "Have the follow-up conversation with Vendor Alpha before deciding whether to proceed.",
                    "evidence": [
                        "Let's have the follow-up conversation with Vendor Alpha and then decide whether to proceed.",
                        "We want to explore Vendor Alpha before deciding whether to change support.",
                    ],
                }
            ],
            "risks": [
                {
                    "risk": "IP infringement risk if Vendor Alpha redistributes patches without the right permissions.",
                    "evidence": "There is a risk of IP infringement if Vendor Alpha redistributes patches without the right permissions.",
                }
            ],
            "open_questions": [
                {
                    "question": "Are we forfeiting our perpetual license rights if we move to Vendor Alpha?",
                    "evidence": [
                        "Are we forfeiting our perpetual license rights if we move to Vendor Alpha?",
                        "I don't know. We'll need to find out.",
                    ],
                }
            ],
        }

        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", return_value=json.dumps(resolved_json)):
            result = ai._resolve_meeting_memory_contextually(
                "Generic Meeting", transcript, first_pass
            )

        self.assertIsNotNone(result)
        self.assertEqual(result["commitments"][0]["owner"], "Speaker B")
        self.assertIn("Vendor Alpha", result["commitments"][0]["action"])
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(
            result["open_questions"],
            ["Are we forfeiting our perpetual license rights if we move to Vendor Alpha?"],
        )


    def test_precision_v11_1_rejected_resolver_category_does_not_erase_baseline(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on setting up a call with Vendor Alpha? "
            "[00:20] **Remote**\n\n"
            "I'll reach out to them."
        )
        first_pass = {
            "commitments": [{
                "owner": "Unknown",
                "action": "I'll reach out to them.",
                "status": "open",
                "evidence": "I'll reach out to them.",
            }],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        # The model attempted an action, but supplied non-transcript evidence.
        # v11 used to turn that validation miss into an authoritative empty list.
        proposed = {
            "commitments": [{
                "owner": "Speaker B",
                "action": "Arrange a call with Vendor Alpha.",
                "evidence": ["This quote is not in the transcript."],
            }],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", return_value=json.dumps(proposed)):
            result = ai._resolve_meeting_memory_contextually(
                "Generic Meeting", transcript, first_pass
            )
        self.assertIsNotNone(result)
        self.assertIsNone(result["commitments"])
        self.assertEqual(result["decisions"], [])

    def test_precision_v11_1_context_grounding_allows_supported_normalization(self):
        context = (
            "Speaker B, why don't you take the lead on getting a meeting set up with Vendor Alpha? "
            "I'll reach out to Vendor Alpha and set up the meeting."
        )
        self.assertTrue(
            ai._resolved_text_is_grounded_in_context(
                "Reach out to Vendor Alpha and arrange the meeting.",
                context,
            )
        )

    def test_precision_v112_summary_cues_are_semantic_hints_not_evidence(self):
        summary = (
            "## Presentations and Updates\n\n"
            "- The team agreed to set up a follow-up call with Vendor Alpha to review pricing and support.\n"
            "- General background was also discussed.\n"
            "## Key Themes and Takeaways\n\n"
            "- Legal risk should be understood before proceeding.\n"
        )
        cues = ai._summary_memory_cues(summary)
        self.assertEqual(len(cues), 2)
        self.assertIn("agreed to set up a follow-up call", cues[0])
        self.assertIn("Legal risk", cues[1])

    def test_precision_v112_contextual_resolver_receives_summary_cues(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a follow-up meeting set up with Vendor Alpha? "
            "[00:30] **Remote**\n\n"
            "Send me the contact and I'll reach out to Vendor Alpha. "
            "[00:50] **Mic**\n\n"
            "Let's have that conversation and then decide whether to proceed."
        )
        summary = (
            "## Presentations and Updates\n\n"
            "- The team agreed to set up a follow-up call with Vendor Alpha before deciding whether to proceed."
        )
        first_pass = {
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        proposed = {
            "commitments": [{
                "owner": "Speaker B",
                "action": "Set up a follow-up meeting with Vendor Alpha.",
                "evidence": [
                    "Speaker B, why don't you take the lead on getting a follow-up meeting set up with Vendor Alpha?",
                    "Send me the contact and I'll reach out to Vendor Alpha.",
                ],
            }],
            "decisions": [{
                "decision": "Have the follow-up conversation with Vendor Alpha before deciding whether to proceed.",
                "evidence": [
                    "Let's have that conversation and then decide whether to proceed.",
                ],
            }],
            "risks": [],
            "open_questions": [],
        }
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()
        captured = {}

        def fake_ask(prompt, **kwargs):
            captured["prompt"] = prompt
            return json.dumps(proposed)

        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", side_effect=fake_ask):
            result = ai._resolve_meeting_memory_contextually(
                "Generic Meeting", transcript, first_pass, meeting_summary=summary
            )

        self.assertIsNotNone(result)
        self.assertIn("Narrative-summary cues", captured["prompt"])
        self.assertIn("team agreed to set up a follow-up call", captured["prompt"])
        self.assertEqual(result["commitments"][0]["owner"], "Speaker B")
        self.assertEqual(len(result["decisions"]), 1)

    def test_precision_v112_high_performance_cleanup_drops_raw_risk_fragment(self):
        memory = {
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
            "risks": [{
                "risk": "a risk that I don't think we want to entertain, so we want to be locked tight with that stuff",
                "evidence": "a risk that I don't think we want to entertain, so we want to be locked tight with that stuff",
            }],
        }
        cleaned = ai._high_performance_memory_quality_cleanup(memory)
        self.assertEqual(cleaned["risks"], [])



    def test_precision_v12_event_pipeline_links_assignment_acceptance_and_memory(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on setting up a follow-up call with Vendor Alpha? "
            "[00:20] **Remote**\n\n"
            "Send me the Vendor Alpha contact and I'll reach out to them. "
            "[00:40] **Mic**\n\n"
            "Let's have that conversation with Vendor Alpha and then decide whether to proceed. "
            "[01:00] **Mic**\n\n"
            "There is an IP infringement risk if Vendor Alpha redistributes patches without permission. "
            "[01:20] **Remote**\n\n"
            "We still need to find out whether Vendor Alpha preserves our perpetual license rights."
        )
        summary = (
            "## Presentations and Updates\n\n"
            "- The team agreed to set up a follow-up call with Vendor Alpha before deciding whether to proceed.\n"
            "- Legal risk and perpetual license rights remain concerns."
        )
        baseline = {
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        event_payload = {
            "events": [
                {
                    "event_type": "assignment",
                    "speaker": "Mic",
                    "target": "Speaker B",
                    "subject": "Set up a follow-up call with Vendor Alpha.",
                    "status": "proposed",
                    "evidence": ["Speaker B, why don't you take the lead on setting up a follow-up call with Vendor Alpha?"],
                },
                {
                    "event_type": "commitment",
                    "speaker": "Speaker B",
                    "target": "",
                    "subject": "Reach out to Vendor Alpha.",
                    "status": "accepted",
                    "evidence": ["Send me the Vendor Alpha contact and I'll reach out to them."],
                },
                {
                    "event_type": "agreement",
                    "speaker": "Mic",
                    "target": "",
                    "subject": "Have a follow-up conversation before deciding whether to proceed.",
                    "status": "settled",
                    "evidence": ["Let's have that conversation with Vendor Alpha and then decide whether to proceed."],
                },
                {
                    "event_type": "concern",
                    "speaker": "Mic",
                    "target": "",
                    "subject": "IP infringement if patches are redistributed without permission.",
                    "status": "stated",
                    "evidence": ["There is an IP infringement risk if Vendor Alpha redistributes patches without permission."],
                },
                {
                    "event_type": "uncertainty",
                    "speaker": "Speaker B",
                    "target": "",
                    "subject": "Whether Vendor Alpha preserves perpetual license rights.",
                    "status": "unresolved",
                    "evidence": ["We still need to find out whether Vendor Alpha preserves our perpetual license rights."],
                },
            ]
        }
        resolved_payload = {
            "commitments": [{
                "owner": "Speaker B",
                "action": "Set up a follow-up call with Vendor Alpha.",
                "evidence": [
                    "Speaker B, why don't you take the lead on setting up a follow-up call with Vendor Alpha?",
                    "Send me the Vendor Alpha contact and I'll reach out to them.",
                ],
            }],
            "decisions": [{
                "decision": "Have a follow-up conversation with Vendor Alpha before deciding whether to proceed.",
                "evidence": ["Let's have that conversation with Vendor Alpha and then decide whether to proceed."],
            }],
            "risks": [{
                "risk": "IP infringement risk if Vendor Alpha redistributes patches without permission.",
                "evidence": ["There is an IP infringement risk if Vendor Alpha redistributes patches without permission."],
            }],
            "open_questions": [{
                "question": "Will Vendor Alpha preserve our perpetual license rights?",
                "evidence": ["We still need to find out whether Vendor Alpha preserves our perpetual license rights."],
            }],
        }
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", side_effect=[json.dumps(event_payload), json.dumps(resolved_payload)]) as mock_ask:
            result = ai._resolve_meeting_memory_event_pipeline(
                "Generic Meeting", transcript, baseline, meeting_summary=summary
            )

        self.assertIsNotNone(result)
        self.assertEqual(mock_ask.call_count, 2)
        self.assertEqual(result["commitments"][0]["owner"], "Speaker B")
        self.assertEqual(result["commitments"][0]["action"], "Set up a follow-up call with Vendor Alpha.")
        self.assertEqual(len(result["commitments"][0]["supporting_evidence"]), 1)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(result["open_questions"], ["Will Vendor Alpha preserve our perpetual license rights?"])

    def test_precision_v12_event_extraction_rejects_non_transcript_evidence(self):
        transcript = "[00:00] **Mic**\n\nSpeaker B, please arrange a call with Vendor Alpha."
        payload = {
            "events": [{
                "event_type": "assignment",
                "speaker": "Mic",
                "target": "Speaker B",
                "subject": "Arrange a call with Vendor Alpha.",
                "status": "proposed",
                "evidence": ["Speaker B was assigned the Vendor Alpha call."],
            }]
        }
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", return_value=json.dumps(payload)):
            events = ai._extract_memory_events("Generic Meeting", transcript)
        self.assertEqual(events, [])


    def test_precision_v12_event_grounding_tolerates_harmless_quote_formatting(self):
        transcript = "[00:00] **Mic**\n\nSpeaker B, why don’t you take the lead on getting something set up for the four of us?"
        item = {
            "event_type": "assignment",
            "speaker": "Mic",
            "target": "Speaker B",
            "subject": "Arrange the follow-up meeting.",
            "status": "proposed",
            "evidence": ["Speaker B why don't you take the lead on getting something set up for the four of us"],
        }
        validated = ai._validate_memory_event(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["target"], "Speaker B")
        self.assertEqual(
            validated["evidence"],
            ["Speaker B, why don’t you take the lead on getting something set up for the four of us"],
        )

    def test_precision_v12_event_grounding_keeps_valid_spans_when_one_quote_is_bad(self):
        transcript = "[00:00] **Remote**\n\nSend me the Vendor Alpha contact and I'll reach out to them."
        item = {
            "event_type": "commitment",
            "speaker": "Remote",
            "target": "Speaker B",
            "subject": "Reach out to Vendor Alpha.",
            "status": "accepted",
            "evidence": [
                "Send me the Vendor Alpha contact and I’ll reach out to them.",
                "Speaker B promised to schedule the call.",
            ],
        }
        validated = ai._validate_memory_event(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(len(validated["evidence"]), 1)
        self.assertIn("Send me the Vendor Alpha contact", validated["evidence"][0])

    def test_precision_v12_event_grounding_still_rejects_semantic_paraphrase(self):
        transcript = "[00:00] **Mic**\n\nSpeaker B, please arrange a call with Vendor Alpha."
        item = {
            "event_type": "assignment",
            "speaker": "Mic",
            "target": "Speaker B",
            "subject": "Arrange a call with Vendor Alpha.",
            "status": "proposed",
            "evidence": ["Speaker B was assigned the Vendor Alpha call."],
        }
        self.assertIsNone(ai._validate_memory_event(item, transcript))

    def test_precision_v12_diagnostics_capture_event_and_verification_counts(self):
        ai._reset_memory_resolution_diagnostics()
        transcript = (
            "[00:00] **Mic**\n\nSpeaker B, please arrange a call with Vendor Alpha.\n\n"
            "[00:10] **Remote**\n\nSend me the Vendor Alpha contact and I'll reach out to them.\n\n"
            "[00:20] **Mic**\n\nLet's have that conversation with Vendor Alpha and then decide whether to proceed.\n\n"
            "[00:30] **Mic**\n\nThere is an IP infringement risk if Vendor Alpha redistributes patches without permission.\n\n"
            "[00:40] **Mic**\n\nWe still need to find out whether Vendor Alpha preserves our perpetual license rights."
        )
        baseline = {"commitments": [], "decisions": [], "risks": [], "open_questions": []}
        event_payload = {"events": [
            {"event_type": "assignment", "speaker": "Mic", "target": "Speaker B", "subject": "Arrange a call with Vendor Alpha.", "status": "proposed", "evidence": ["Speaker B, please arrange a call with Vendor Alpha."]},
            {"event_type": "commitment", "speaker": "Remote", "target": "Speaker B", "subject": "Reach out to Vendor Alpha.", "status": "accepted", "evidence": ["Send me the Vendor Alpha contact and I'll reach out to them."]},
            {"event_type": "agreement", "speaker": "Mic", "target": "", "subject": "Have a conversation before deciding.", "status": "accepted", "evidence": ["Let's have that conversation with Vendor Alpha and then decide whether to proceed."]},
            {"event_type": "concern", "speaker": "Mic", "target": "", "subject": "IP infringement risk.", "status": "open", "evidence": ["There is an IP infringement risk if Vendor Alpha redistributes patches without permission."]},
            {"event_type": "uncertainty", "speaker": "Mic", "target": "", "subject": "Whether perpetual license rights remain.", "status": "open", "evidence": ["We still need to find out whether Vendor Alpha preserves our perpetual license rights."]},
        ]}
        resolved_payload = {
            "commitments": [{"owner": "Speaker B", "action": "Arrange a call with Vendor Alpha.", "evidence": ["Speaker B, please arrange a call with Vendor Alpha.", "Send me the Vendor Alpha contact and I'll reach out to them."]}],
            "decisions": [{"decision": "Have a conversation with Vendor Alpha before deciding whether to proceed.", "evidence": ["Let's have that conversation with Vendor Alpha and then decide whether to proceed."]}],
            "risks": [{"risk": "IP infringement risk if Vendor Alpha redistributes patches without permission.", "evidence": ["There is an IP infringement risk if Vendor Alpha redistributes patches without permission."]}],
            "open_questions": [{"question": "Will Vendor Alpha preserve our perpetual license rights?", "evidence": ["We still need to find out whether Vendor Alpha preserves our perpetual license rights."]}],
        }
        profile = type("Profile", (), {"resolved_name": "High Performance", "direct_token_budget": 32000, "llm_call_timeout_seconds": 150})()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", side_effect=[json.dumps(event_payload), json.dumps(resolved_payload)]):
            result = ai._resolve_meeting_memory_event_pipeline("Generic Meeting", transcript, baseline)
        self.assertIsNotNone(result)
        diagnostics = ai.get_last_memory_resolution_diagnostics()
        self.assertEqual(diagnostics["pipeline"], "v12_events")
        self.assertEqual(diagnostics["status"], "verified")
        self.assertEqual(diagnostics["events_proposed"], 5)
        self.assertEqual(diagnostics["events_grounded"], 5)
        self.assertEqual(diagnostics["event_types_grounded"]["assignment"], 1)
        self.assertEqual(diagnostics["event_types_grounded"]["commitment"], 1)
        self.assertEqual(diagnostics["actions_proposed"], 1)
        self.assertEqual(diagnostics["actions_retained"], 1)
        self.assertEqual(diagnostics["decisions_retained"], 1)
        self.assertEqual(diagnostics["risks_retained"], 1)
        self.assertEqual(diagnostics["questions_retained"], 1)

    def test_precision_v12_lower_profile_skips_event_pipeline(self):
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "Balanced",
                "direct_token_budget": 18000,
                "llm_call_timeout_seconds": 180,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="qwen3:8b"), \
             patch("ai.ask_llm") as mock_ask:
            result = ai._resolve_meeting_memory_event_pipeline(
                "Generic Meeting",
                "[00:00] **Mic**\n\nLet's follow up on Vendor Alpha.",
                {"commitments": [], "decisions": [], "risks": [], "open_questions": []},
            )
        self.assertIsNone(result)
        mock_ask.assert_not_called()

    def test_precision_v11_lower_profile_keeps_existing_single_pass_plumbing(self):
        profile = type(
            "Profile",
            (),
            {
                "resolved_name": "Balanced",
                "direct_token_budget": 18000,
                "llm_call_timeout_seconds": 180,
            },
        )()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="qwen3:8b"), \
             patch("ai.ask_llm") as mock_ask:
            result = ai._resolve_meeting_memory_contextually(
                "Generic Meeting",
                "[00:00] **Mic**\n\nLet's follow up on Vendor Alpha.",
                {
                    "commitments": [],
                    "decisions": [],
                    "risks": [],
                    "open_questions": [],
                },
            )
        self.assertIsNone(result)
        mock_ask.assert_not_called()

    def test_precision_v123_records_rejected_event_reason(self):
        transcript = "[00:00] **Mic**\n\nSpeaker B, please arrange a call with Vendor Alpha."
        event_payload = {"events": [
            {
                "event_type": "assignment",
                "speaker": "Mic",
                "target": "Speaker B",
                "subject": "Arrange a call with Vendor Alpha.",
                "status": "proposed",
                "evidence": ["Speaker B should arrange a call with Vendor Alpha."],
            }
        ]}
        profile = type("Profile", (), {"resolved_name": "High Performance", "direct_token_budget": 32000, "llm_call_timeout_seconds": 150})()
        ai._reset_memory_resolution_diagnostics()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", return_value=json.dumps(event_payload)):
            events = ai._extract_memory_events("Generic Meeting", transcript)
        self.assertEqual(events, [])
        diagnostics = ai.get_last_memory_resolution_diagnostics()
        self.assertEqual(diagnostics["events_proposed"], 1)
        self.assertEqual(diagnostics["events_grounded"], 0)
        self.assertEqual(diagnostics["rejected_events"][0]["event_type"], "assignment")
        self.assertEqual(diagnostics["rejected_events"][0]["reason"], "evidence_not_found")

    def test_precision_v123_records_final_rejection_reason(self):
        transcript = "[00:00] **Mic**\n\nSpeaker B, please arrange a call with Vendor Alpha."
        events = [{
            "event_type": "assignment",
            "speaker": "Mic",
            "target": "Speaker B",
            "subject": "Arrange a call with Vendor Alpha.",
            "status": "proposed",
            "evidence": ["Speaker B, please arrange a call with Vendor Alpha."],
        }]
        resolved_payload = {
            "commitments": [{
                "owner": "Speaker C",
                "action": "Arrange a call with Vendor Alpha.",
                "evidence": ["Speaker B, please arrange a call with Vendor Alpha."],
            }],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        profile = type("Profile", (), {"resolved_name": "High Performance", "direct_token_budget": 32000, "llm_call_timeout_seconds": 150})()
        ai._reset_memory_resolution_diagnostics()
        with patch("ai.get_execution_profile", return_value=profile), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai.ask_llm", return_value=json.dumps(resolved_payload)):
            result = ai._resolve_meeting_memory_from_events(
                "Generic Meeting", transcript,
                {"commitments": [], "decisions": [], "risks": [], "open_questions": []},
                events,
            )
        self.assertIsNotNone(result)
        diagnostics = ai.get_last_memory_resolution_diagnostics()
        self.assertEqual(diagnostics["actions_proposed"], 1)
        self.assertEqual(diagnostics["actions_retained"], 0)
        rejected = diagnostics["rejected_final"]["actions"][0]
        self.assertEqual(rejected["owner"], "Speaker C")
        self.assertEqual(rejected["reason"], "owner_not_grounded")

    def test_precision_v124_recovers_named_assignment_from_transcript_not_summary_evidence(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the group?\n\n"
            "[00:20] **Remote**\n\nSounds good."
        )
        item = {
            "event_type": "assignment",
            "speaker": "Mic",
            "target": "Speaker B",
            "subject": "set up a call with the group",
            "status": "proposed",
            "evidence": ["Speaker B - Coordinate a call with Vendor Alpha - Due date not identified."],
        }
        validated = ai._validate_memory_event(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(
            validated["evidence"],
            ["Speaker B, why don't you take the lead on getting a call set up for the group?"],
        )

    def test_precision_v124_normalized_action_uses_grounded_assignment_without_lexical_gate(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the group?"
        )
        item = {
            "owner": "Speaker B",
            "action": "Arrange the follow-up discussion with Vendor Alpha for the group.",
            "evidence": [
                "Speaker B, why don't you take the lead on getting a call set up for the group?"
            ],
        }
        validated = ai._validate_resolved_commitment(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["owner"], "Speaker B")
        self.assertEqual(
            validated["action"],
            "Arrange the follow-up discussion with Vendor Alpha for the group.",
        )

    def test_precision_v124_normalized_decision_does_not_require_lexical_overlap(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Let's have that conversation with Vendor Alpha and then decide whether to proceed."
        )
        item = {
            "decision": "Continue evaluating Vendor Alpha through a follow-up discussion before choosing a provider.",
            "evidence": [
                "Let's have that conversation with Vendor Alpha and then decide whether to proceed."
            ],
        }
        validated = ai._validate_resolved_decision(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(
            validated["decision"],
            "Continue evaluating Vendor Alpha through a follow-up discussion before choosing a provider.",
        )

    def test_precision_v124_normalized_open_question_uses_exact_unresolved_evidence(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "I wonder if they have different support models, one with upgrades and patches and one without."
        )
        item = {
            "question": "What support options does Vendor Alpha offer for patches and upgrades?",
            "evidence": [
                "I wonder if they have different support models, one with upgrades and patches and one without."
            ],
        }
        validated = ai._validate_resolved_question(item, transcript)
        self.assertEqual(
            validated,
            "What support options does Vendor Alpha offer for patches and upgrades?",
        )


# v12.5 downstream reconciliation regression coverage.
class PrecisionV125DownstreamReconciliationTests(unittest.TestCase):
    def test_event_verified_action_survives_final_reconciliation(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the group?"
        )
        memory = {
            "topics": [],
            "commitments": [{
                "owner": "Speaker B",
                "action": "Arrange the follow-up discussion with Vendor Alpha for the group.",
                "status": "open",
                "evidence": "Speaker B, why don't you take the lead on getting a call set up for the group?",
                "_context_resolved": True,
                "_event_verified": True,
            }],
            "decisions": [],
            "risks": [],
            "open_questions": [],
            "follow_ups": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(len(result["commitments"]), 1)
        self.assertEqual(result["commitments"][0]["owner"], "Speaker B")
        self.assertEqual(
            result["commitments"][0]["action"],
            "Arrange the follow-up discussion with Vendor Alpha for the group.",
        )
        self.assertNotIn("_event_verified", result["commitments"][0])
        self.assertNotIn("_context_resolved", result["commitments"][0])

    def test_event_verified_decision_survives_final_reconciliation(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Let's have that conversation with Vendor Alpha and then decide whether to proceed."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [{
                "decision": "Continue evaluating Vendor Alpha through a follow-up discussion before choosing a provider.",
                "evidence": "Let's have that conversation with Vendor Alpha and then decide whether to proceed.",
                "_context_resolved": True,
                "_event_verified": True,
            }],
            "risks": [],
            "open_questions": [],
            "follow_ups": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(
            result["decisions"][0]["decision"],
            "Continue evaluating Vendor Alpha through a follow-up discussion before choosing a provider.",
        )
        self.assertNotIn("_event_verified", result["decisions"][0])

    def test_event_verified_normalized_question_survives_final_reconciliation(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "I wonder if they have different support models, one with upgrades and patches and one without."
        )
        question = "What support options does Vendor Alpha offer for patches and upgrades?"
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": [question],
            "follow_ups": [],
        }
        result = ai._reconcile_meeting_memory(
            memory,
            transcript,
            verified_open_questions={question},
        )
        self.assertEqual(result["open_questions"], [question])


# v12.6 cleanup regression coverage.
class PrecisionV126CleanupTests(unittest.TestCase):
    def test_verified_risk_is_normalized_and_internal_marker_is_stripped(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "We do not want to go into an end of support where we cannot get patches or updates, "
            "so that is a risk to the business."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
            "risks": [{
                "risk": "Going into an end of support where we cannot get patches or updates",
                "evidence": "We do not want to go into an end of support where we cannot get patches or updates, so that is a risk to the business.",
                "_event_verified": True,
            }],
        }
        cleaned = ai._high_performance_memory_quality_cleanup(memory)
        cleaned["risks"][0]["risk"] = ai._normalize_verified_risk_text(
            cleaned["risks"][0]["risk"], cleaned["risks"][0]["evidence"]
        )
        result = ai._reconcile_meeting_memory(cleaned, transcript)
        self.assertEqual(
            result["risks"][0]["risk"],
            "Risk of losing access to critical patches and upgrades under an inadequate support arrangement",
        )
        self.assertNotIn("_event_verified", result["risks"][0])

    def test_verified_question_set_recovers_unresolved_perpetual_rights_issue(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "We want to make sure that when we walk away from the support relationship, "
            "we still have the perpetual rights to the licenses we have today. "
            "Are we forfeiting our licenses? I think we will need to talk to them."
        )
        existing = "What support models does Vendor Alpha offer?"
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "risks": [],
            "open_questions": [existing],
            "follow_ups": [],
        }
        result = ai._reconcile_meeting_memory(
            memory, transcript, verified_open_questions={existing}
        )
        self.assertIn(existing, result["open_questions"])
        self.assertIn(
            "Will we retain perpetual license rights if the support relationship ends?",
            result["open_questions"],
        )

    def test_decision_keeps_contentful_quote_primary_and_agreement_supporting(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, as a next step, do you want us to set up the initial call?\n\n"
            "[00:20] **Remote**\n\n"
            "Yes, let's have that conversation for sure.\n\n"
            "[00:30] **Mic**\n\n"
            "That's what we'll do."
        )
        item = {
            "decision": "Set up an initial call with Vendor Alpha before deciding whether to proceed.",
            "evidence": ["Speaker B, as a next step, do you want us to set up the initial call?"],
        }
        validated = ai._validate_resolved_decision(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(
            validated["evidence"],
            "Speaker B, as a next step, do you want us to set up the initial call?",
        )
        self.assertIn("supporting_evidence", validated)
        self.assertTrue(
            any("conversation" in value.casefold() or "what we'll do" in value.casefold()
                for value in validated["supporting_evidence"])
        )

    def test_internal_markers_are_removed_from_all_persisted_precision_sections(self):
        memory = {
            "topics": [],
            "commitments": [{"owner": "Speaker B", "action": "Call Vendor Alpha", "evidence": "Call Vendor Alpha", "_event_verified": True}],
            "decisions": [{"decision": "Evaluate Vendor Alpha", "evidence": "Evaluate Vendor Alpha", "_context_resolved": True}],
            "risks": [{"risk": "Risk of service interruption", "evidence": "Risk of service interruption", "_event_verified": True}],
            "open_questions": [],
            "follow_ups": [],
        }
        result = ai._strip_internal_memory_markers(memory)
        for section in ("commitments", "decisions", "risks"):
            for item in result[section]:
                self.assertFalse(any(key.startswith("_") for key in item))


# v12.7 decision semantic-evidence consistency regression coverage.
class PrecisionV127DecisionConsistencyTests(unittest.TestCase):
    def test_rejects_unrelated_decision_supported_only_by_generic_agreement(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "We should get a copy of Vendor Alpha's contract and review the legal risk before moving forward.\n\n"
            "[00:25] **Remote**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the four of us?\n\n"
            "[00:45] **Mic**\n\n"
            "Yeah, the four of us, right? That's what we'll do."
        )
        item = {
            "decision": "Due diligence, including contract review and risk assessment, is necessary before engaging with a new support provider.",
            "evidence": ["Yeah, the four of us, right? That's what we'll do."],
        }
        self.assertIsNone(ai._validate_resolved_decision(item, transcript))

    def test_keeps_semantically_aligned_follow_up_call_decision(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the four of us?\n\n"
            "[00:20] **Remote**\n\n"
            "Yes, let's have that conversation with Vendor Alpha for sure."
        )
        item = {
            "decision": "Set up a follow-up call with Vendor Alpha before deciding whether to proceed.",
            "evidence": ["Speaker B, why don't you take the lead on getting a call set up for the four of us?"],
        }
        validated = ai._validate_resolved_decision(item, transcript)
        self.assertIsNotNone(validated)
        self.assertEqual(
            validated["decision"],
            "Set up a follow-up call with Vendor Alpha before deciding whether to proceed.",
        )



# v12.8 final precision cleanup regression coverage.
class PrecisionV128FinalCleanupTests(unittest.TestCase):
    def test_decision_consistency_does_not_borrow_unrelated_nearby_contract_context(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "We should get a copy of Vendor Alpha's contract and review the legal risk before moving forward.\n\n"
            "[00:25] **Remote**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the four of us?\n\n"
            "[00:45] **Mic**\n\n"
            "Yeah, the four of us, right? That's what we'll do."
        )
        item = {
            "decision": "Due diligence, including contract review and risk assessment, is necessary before engaging with a new support provider.",
            "evidence": ["Yeah, the four of us, right? That's what we'll do."],
        }
        self.assertIsNone(ai._validate_resolved_decision(item, transcript))

    def test_channel_owned_outreach_duplicate_is_dropped_when_named_action_exists(self):
        commitments = [
            {
                "owner": "Brian",
                "action": "Coordinate with Vendor Alpha to set up a call with the team",
                "status": "open",
                "evidence": "Brian, why don't you take the lead on getting something set up for the four of us?",
            },
            {
                "owner": "Remote",
                "action": "Reach out to Vendor Alpha representative, Alex Cole",
                "status": "open",
                "evidence": "Brian, as a next step, do you want us to set up that initial call?",
                "supporting_evidence": ["I'll give him a call and reach out and introduce myself."],
            },
        ]
        result = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["owner"], "Brian")

    def test_channel_owned_distinct_action_is_preserved_without_named_overlap(self):
        commitments = [
            {
                "owner": "Brian",
                "action": "Coordinate with Vendor Alpha to set up a call with the team",
                "status": "open",
                "evidence": "Brian, please set up the call with Vendor Alpha.",
            },
            {
                "owner": "Remote",
                "action": "Send the inventory report to Finance",
                "status": "open",
                "evidence": "I'll send the inventory report to Finance.",
            },
        ]
        result = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(result), 2)



    def test_precision_v12_13_rejects_function_word_removal_fragments(self):
        self.assertFalse(
            ai._decision_candidate_is_well_formed(
                "Drop to.",
                "okay they're finally smart enough to be able to have a po get cut to",
            )
        )
        self.assertFalse(
            ai._decision_candidate_is_well_formed(
                "Drop the.",
                "we cut the",
            )
        )
        transcript = (
            "[01:00] **Remote**\n\n"
            "Okay, we are going to drop to the next screen after this. "
            "Then we cut the sample text from the draft."
        )
        self.assertEqual(ai._recover_explicit_removal_decisions(transcript), [])

    def test_precision_v12_13_rejects_product_behavior_as_decision_without_settlement(self):
        transcript = (
            "[02:00] **Remote**\n\n"
            "The new Platform Beta feature will not automatically update existing workspaces. "
            "That gap will require manual cleanup for older records."
        )
        candidate = {
            "decision": "The Platform Beta feature will not automatically update existing workspaces, requiring manual intervention.",
            "evidence": [
                "The new Platform Beta feature will not automatically update existing workspaces."
            ],
        }
        self.assertIsNone(ai._validate_resolved_decision(candidate, transcript))

    def test_precision_v12_13_keeps_product_behavior_when_explicitly_decided(self):
        transcript = (
            "[02:00] **Remote**\n\n"
            "We decided the Platform Beta process will use the existing workflow for historical records."
        )
        candidate = {
            "decision": "The Platform Beta process will use the existing workflow for historical records.",
            "evidence": [
                "We decided the Platform Beta process will use the existing workflow for historical records."
            ],
        }
        result = ai._validate_resolved_decision(candidate, transcript)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["decision"],
            "The Platform Beta process will use the existing workflow for historical records.",
        )

if __name__ == "__main__":
    unittest.main()


# v12.9 final action dedupe + durable question recovery regression coverage.
class PrecisionV129FinalizationTests(unittest.TestCase):
    def test_same_named_owner_overlapping_vendor_call_actions_are_merged(self):
        commitments = [
            {
                "owner": "Brian",
                "action": "Reach out to Vendor Alpha representative to set up a call with the team",
                "status": "open",
                "evidence": "Brian, why don't you take the lead on getting something set up for the four of us?",
            },
            {
                "owner": "Brian",
                "action": "Set up an initial call with Vendor Alpha",
                "status": "open",
                "evidence": "Brian, as a next step, do you want us to set up that initial call?",
            },
        ]
        result = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["owner"], "Brian")
        self.assertIn("Vendor Alpha", result[0]["action"])
        self.assertIn("supporting_evidence", result[0])
        self.assertEqual(len(result[0]["supporting_evidence"]), 1)

    def test_same_owner_distinct_vendor_actions_are_not_merged(self):
        commitments = [
            {
                "owner": "Brian",
                "action": "Set up a call with Vendor Alpha",
                "status": "open",
                "evidence": "Brian, please set up the call with Vendor Alpha.",
            },
            {
                "owner": "Brian",
                "action": "Send the inventory to Vendor Beta",
                "status": "open",
                "evidence": "Brian, please send the inventory to Vendor Beta.",
            },
        ]
        result = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(result), 2)

    def test_high_performance_reconciliation_recovers_durable_questions_when_model_returns_none(self):
        transcript = (
            "We'd want to make sure that when we walk away from that relationship, "
            "we still have the perpetual rights to the licenses that we do today. "
            "Are we forfeiting our licenses? I think we'll need to talk to them. "
            "I'm really curious what guarantees they give a customer that when something breaks, "
            "we'll be able to fix it in the way we were expecting."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
            "risks": [],
        }
        with unittest.mock.patch.object(ai, "_memory_resolution_capable", return_value=True):
            result = ai._reconcile_meeting_memory(memory, transcript, verified_open_questions=set())
        self.assertIn(
            "Will we retain perpetual license rights if the support relationship ends?",
            result["open_questions"],
        )
        self.assertIn(
            "What guarantees does the support provider offer for resolving critical issues?",
            result["open_questions"],
        )

# v12.10 final question dedupe + follow-up decision recovery regression coverage.
class PrecisionV1210FinalPolishTests(unittest.TestCase):
    def test_support_guarantee_paraphrases_are_deduplicated(self):
        questions = [
            "What guarantees does Vendor Alpha provide for customer support when something breaks?",
            "What guarantees does the support provider offer for resolving critical issues?",
        ]
        result = ai._normalize_open_questions(questions)
        self.assertEqual(len(result), 1)
        self.assertIn("guarantees", result[0].casefold())

    def test_exploration_decision_is_not_supported_by_generic_confirmation_alone(self):
        transcript = (
            "[00:00] **Mic**\n\nWe should review Vendor Alpha's support and pricing.\n\n"
            "[00:20] **Remote**\n\nYeah, the four of us, right? That's what we'll do."
        )
        item = {
            "decision": "The team will explore Vendor Alpha to reduce costs and improve support options.",
            "evidence": ["Yeah, the four of us, right? That's what we'll do."],
        }
        self.assertIsNone(ai._validate_resolved_decision(item, transcript))

    def test_named_call_commitment_recovers_specific_followup_decision(self):
        transcript = (
            "[00:00] **Mic**\n\nBrian, why don't you take the lead on getting something set up with Vendor Alpha?\n\n"
            "[00:20] **Remote**\n\nWhatever works from schedules and let's have that conversation for sure."
        )
        memory = {
            "topics": [],
            "commitments": [{
                "owner": "Brian",
                "action": "Coordinate with Vendor Alpha to set up a call with the team",
                "status": "open",
                "evidence": "Brian, why don't you take the lead on getting something set up with Vendor Alpha?",
                "_context_resolved": True,
                "_event_verified": True,
            }],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
            "risks": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(len(result["decisions"]), 1)
        self.assertEqual(
            result["decisions"][0]["decision"],
            "Proceed with a follow-up discussion with Vendor Alpha.",
        )
        self.assertIn("let's have that conversation for sure", result["decisions"][0]["evidence"])


# v12.11 evidence fidelity regression coverage.
class PrecisionV1211EvidenceFidelityTests(unittest.TestCase):
    def test_decision_primary_evidence_prefers_business_proposition_over_generic_confirmation(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "I think we should get preliminary pricing from Vendor Alpha and review the contract if the numbers look promising.\n\n"
            "[00:20] **Remote**\n\n"
            "Yeah, that's what we'll do."
        )
        item = {
            "decision": "The team will get preliminary pricing from Vendor Alpha and review the contract if the financials look promising.",
            "evidence": [
                "I think we should get preliminary pricing from Vendor Alpha and review the contract if the numbers look promising."
            ],
        }
        validated = ai._validate_resolved_decision(item, transcript)
        self.assertIsNotNone(validated)
        self.assertIn("preliminary pricing", validated["evidence"].casefold())
        self.assertTrue(any("that's what we'll do" in value.casefold() for value in validated.get("supporting_evidence", [])))

    def test_reconciliation_preserves_grounded_decision_supporting_evidence(self):
        transcript = (
            "We will review Vendor Alpha's contract. "
            "Yes, that's what we'll do."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [{
                "decision": "Review Vendor Alpha's contract.",
                "evidence": "We will review Vendor Alpha's contract.",
                "supporting_evidence": ["Yes, that's what we'll do."],
                "_context_resolved": True,
                "_event_verified": True,
            }],
            "open_questions": [],
            "follow_ups": [],
            "risks": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(result["decisions"][0]["evidence"], "We will review Vendor Alpha's contract.")
        self.assertEqual(result["decisions"][0]["supporting_evidence"], ["Yes, that's what we'll do."])

    def test_risk_primary_evidence_prefers_quote_with_matching_failure_mode(self):
        transcript = (
            "There is a risk we do not want to entertain. "
            "Vendor Alpha could create IP infringement exposure if it redistributes patches without permission."
        )
        item = {
            "risk": "Risk of IP infringement due to third-party patch redistribution.",
            "evidence": [
                "There is a risk we do not want to entertain.",
                "Vendor Alpha could create IP infringement exposure if it redistributes patches without permission.",
            ],
        }
        validated = ai._validate_resolved_risk(item, transcript)
        self.assertIsNotNone(validated)
        self.assertIn("IP infringement", validated["evidence"])
        self.assertIn("supporting_evidence", validated)

    def test_support_risk_prefers_patch_upgrade_evidence_over_generic_risk_phrase(self):
        transcript = (
            "That's a risk to the business. "
            "We do not want to reach end of support without patches or upgrades."
        )
        item = {
            "risk": "Risk of losing access to critical patches and upgrades under an inadequate support arrangement.",
            "evidence": [
                "That's a risk to the business.",
                "We do not want to reach end of support without patches or upgrades.",
            ],
        }
        validated = ai._validate_resolved_risk(item, transcript)
        self.assertIsNotNone(validated)
        self.assertIn("patches or upgrades", validated["evidence"].casefold())

# v12.12 final evidence-fidelity regression coverage.
class PrecisionV1212FinalEvidenceFidelityTests(unittest.TestCase):
    def test_final_reconciliation_drops_event_verified_decision_with_only_generic_acknowledgement(self):
        transcript = (
            "[00:00] **Mic**\n\n"
            "We should get a copy of Vendor Alpha's contract and review the legal risk before moving forward.\n\n"
            "[00:25] **Remote**\n\n"
            "Speaker B, why don't you take the lead on getting a call set up for the four of us?\n\n"
            "[00:45] **Mic**\n\n"
            "Yeah, the four of us, right? That's what we'll do."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [{
                "decision": "Due diligence, including contract review and risk assessment, is necessary before engaging with a new support provider.",
                "evidence": "Yeah, the four of us, right? That's what we'll do.",
                "_context_resolved": True,
                "_event_verified": True,
            }],
            "open_questions": [],
            "follow_ups": [],
            "risks": [],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(result["decisions"], [])

    def test_final_reconciliation_repairs_support_risk_evidence_from_transcript(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "We do not want to reach end of support without patches or upgrades; that is a risk to the business.\n\n"
            "[03:00] **Mic**\n\n"
            "We need to make sure we retain perpetual license rights when the relationship ends."
        )
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
            "risks": [{
                "risk": "Risk of losing critical support and version upgrade access if third-party support is not structured properly",
                "evidence": "We need to make sure we retain perpetual license rights when the relationship ends.",
                "_context_resolved": True,
                "_event_verified": True,
            }],
        }
        result = ai._reconcile_meeting_memory(memory, transcript)
        self.assertEqual(len(result["risks"]), 1)
        self.assertIn("patches or upgrades", result["risks"][0]["evidence"].casefold())
        self.assertTrue(any(
            "perpetual license rights" in value.casefold()
            for value in result["risks"][0].get("supporting_evidence", [])
        ))

# v12.15 negative-decision recall + commitment specificity regression coverage.
class PrecisionV1215RecallAndCommitmentTests(unittest.TestCase):
    def test_explicit_negative_settlement_recovers_named_action_from_same_turn(self):
        transcript = (
            "[01:00] **Mic**\n\n"
            "Now that we have the new Platform Beta workflow in place, we need to go back and "
            "update all historical workspaces to match it. We're not going to do that.\n\n"
            "[01:20] **Remote**\n\nSounds good."
        )
        recovered = ai._recover_explicit_negative_settlement_decisions(transcript)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(
            recovered[0]["decision"],
            "Do not update all historical workspaces to match the new Platform Beta workflow.",
        )
        self.assertIn("We're not going to do that", recovered[0]["evidence"])

    def test_negative_settlement_without_local_antecedent_is_not_recovered(self):
        transcript = (
            "[01:00] **Mic**\n\nWe're not going to do that.\n\n"
            "[01:10] **Remote**\n\nOkay."
        )
        self.assertEqual(ai._recover_explicit_negative_settlement_decisions(transcript), [])

    def test_vague_get_involved_commitment_is_not_self_contained(self):
        self.assertFalse(ai._commitment_action_is_self_contained("I'll get involved."))
        self.assertFalse(ai._commitment_action_is_self_contained("I will help."))

    def test_concrete_first_person_commitment_remains_self_contained(self):
        self.assertTrue(
            ai._commitment_action_is_self_contained(
                "Reach out to Vendor Alpha for the four renewal quotes"
            )
        )

# v12.16 research-driven evidence retrieval + speaker attribution regression coverage.
class PrecisionV1216EvidenceAttributionTests(unittest.TestCase):
    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_1v1_identity_map_resolves_counterpart_channel(self):
        transcript = (
            "[00:00] **Remote**\n\nHey User Alpha, good morning.\n\n"
            "[00:05] **Mic**\n\nMorning."
        )
        mapping = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        self.assertEqual(mapping["mic"], "User Alpha")
        self.assertEqual(mapping["remote"], "Speaker B")

    def test_commitment_retrieval_recovers_exact_turn_from_paraphrased_evidence(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "After the planning call, I'm gonna reach out to Vendor Alpha and ask for the paperwork "
            "for all four renewals so we can review the quotes together.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        item = {
            "event_type": "commitment",
            "speaker": "Remote",
            "target": "User Alpha",
            "subject": "Reach out to Vendor Alpha for renewal paperwork for four contracts",
            "status": "accepted",
            "evidence": ["I'll reach out to Vendor Alpha for the four renewal quotes."],
        }
        recovered = ai._recover_event_evidence_from_turns(item, transcript)
        self.assertEqual(len(recovered), 1)
        self.assertIn("I'm gonna reach out to Vendor Alpha", recovered[0])
        self.assertIn("all four renewals", recovered[0])

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_first_person_commitment_owner_uses_resolved_speaker_not_model_target(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "event_type": "commitment",
            "speaker": "Remote",
            "target": "User Alpha",
            "subject": "Reach out to Vendor Alpha for renewal paperwork for four renewals",
            "status": "accepted",
            "evidence": ["I'll reach out to Vendor Alpha for all four renewal quotes."],
        }
        validated = ai._validate_memory_event(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["speaker"], "Speaker B")
        self.assertEqual(validated["target"], "Speaker B")
        self.assertIn("I'm gonna reach out", validated["evidence"][0])

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_resolved_commitment_accepts_first_person_owner_from_channel_identity(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "owner": "Speaker B",
            "action": "Request renewal paperwork from Vendor Alpha for all four renewals",
            "evidence": ["I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals."],
        }
        validated = ai._validate_resolved_commitment(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["owner"], "Speaker B")

    def test_candidate_evidence_index_surfaces_middle_first_person_commitment(self):
        transcript = (
            "[00:00] **Mic**\n\nOpening context.\n\n"
            "[15:00] **Remote**\n\nI'm gonna contact Vendor Alpha tomorrow and request the renewal package.\n\n"
            "[30:00] **Mic**\n\nClosing context."
        )
        index = ai._memory_candidate_evidence_index(transcript)
        self.assertEqual(len(index), 1)
        self.assertIn("contact Vendor Alpha tomorrow", index[0])

# v12.17 authoritative attribution + claim-level risk entailment regressions.
class PrecisionV1217AttributionRiskTests(unittest.TestCase):
    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_speaker_channel_resolves_grounded_span_that_starts_in_turn_header(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        # Lexical-exact grounding may begin after the opening '[' when the model
        # included timestamp/header text in its evidence.
        evidence = (
            "07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals"
        )
        self.assertEqual(ai._speaker_channel_for_evidence(evidence, transcript), "Remote")

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_final_first_person_owner_override_survives_header_prefixed_evidence(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "owner": "User Alpha",
            "action": "Reach out to Vendor Alpha for renewal paperwork for four renewals",
            "evidence": [
                "07:30] **Remote**\n\nI'm gonna reach out to Vendor Alpha and ask for the paperwork for all four renewals"
            ],
        }
        # Mirror the pass-2 owner correction contract: the evidence channel is
        # authoritative for a first-person commitment in a high-confidence 1v1.
        grounded = [ai._ground_evidence_quote(item["evidence"][0], transcript)]
        owners = {
            ai._participant_name_for_channel(ai._speaker_channel_for_evidence(q, transcript), identity_map)
            for q in grounded if q and ai._FIRST_PERSON_FUTURE_WORK_PATTERN.search(q)
        }
        self.assertEqual(owners, {"Speaker B"})

    def test_risk_rejects_invented_consequence_from_unrelated_local_context(self):
        transcript = (
            "[29:00] **Remote**\n\nWe have several blanket purchase orders in the cleanup list.\n\n"
            "[29:17] **Remote**\n\nand I've been deleting all of them.\n\n"
            "[29:40] **Remote**\n\nIn hindsight, we should probably keep a simple inventory for January."
        )
        item = {
            "risk": "Blanket purchase orders lack tracking, increasing the risk of overspending or mismanagement.",
            "evidence": ["and I've been deleting all of them."],
        }
        self.assertIsNone(ai._validate_resolved_risk(item, transcript))

    def test_risk_keeps_explicit_supported_failure_mode(self):
        transcript = (
            "[10:00] **Remote**\n\n"
            "There is a risk of losing access to critical patches when Vendor Alpha support ends."
        )
        item = {
            "risk": "Risk of losing access to critical patches when Vendor Alpha support ends.",
            "evidence": ["There is a risk of losing access to critical patches when Vendor Alpha support ends."],
        }
        validated = ai._validate_resolved_risk(item, transcript)
        self.assertIsNotNone(validated)
        self.assertIn("critical patches", validated["risk"])

# v12.18 evidence-authoritative owner repair + prompt-cost regression coverage.
class PrecisionV1218AuthoritativeOwnerTests(unittest.TestCase):
    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_authoritative_first_person_owner_uses_header_channel_identity(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for all four renewal packages.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        evidence = [
            "07:30] **Remote**\n\nI'm gonna reach out to Vendor Alpha and ask for all four renewal packages"
        ]
        owner = ai._authoritative_first_person_owner(evidence, transcript, identity_map)
        self.assertEqual(owner, "Speaker B")

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_resolved_commitment_repairs_conflicting_model_owner(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for all four renewal packages.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "owner": "User Alpha",
            "action": "Reach out to Vendor Alpha for four renewal packages",
            "evidence": [
                "07:30] **Remote**\n\nI'm gonna reach out to Vendor Alpha and ask for all four renewal packages"
            ],
        }
        validated = ai._validate_resolved_commitment(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["owner"], "Speaker B")

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_first_person_assignment_mislabel_repairs_target_to_evidence_speaker(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna contact Vendor Alpha tomorrow and request the renewal package.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "event_type": "assignment",
            "speaker": "Remote",
            "target": "User Alpha",
            "subject": "Contact Vendor Alpha for the renewal package",
            "status": "accepted",
            "evidence": [
                "I'm gonna contact Vendor Alpha tomorrow and request the renewal package."
            ],
        }
        validated = ai._validate_memory_event(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["speaker"], "Speaker B")
        self.assertEqual(validated["target"], "Speaker B")

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_non_first_person_assignment_keeps_explicit_assignee(self):
        transcript = (
            "[07:30] **Mic**\n\n"
            "Speaker B, can you contact Vendor Alpha tomorrow and request the renewal package?\n\n"
            "[07:50] **Remote**\n\nYes."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "event_type": "assignment",
            "speaker": "Mic",
            "target": "Speaker B",
            "subject": "Contact Vendor Alpha for the renewal package",
            "status": "proposed",
            "evidence": [
                "Speaker B, can you contact Vendor Alpha tomorrow and request the renewal package?"
            ],
        }
        validated = ai._validate_memory_event(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["speaker"], "User Alpha")
        self.assertEqual(validated["target"], "Speaker B")

# v12.19 bounded/windowed extraction resilience.
class PrecisionV1219WindowedExtractionTests(unittest.TestCase):
    def _profile(self):
        return type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_truncated_window_is_skipped_and_later_window_survives(self):
        transcript = (
            "[00:00] **Mic**\n\nWe should review Platform Beta.\n\n"
            "[05:00] **Remote**\n\nI'm gonna contact Vendor Alpha tomorrow and request the renewal package."
        )
        windows = [
            "[00:00] **Mic**\n\nWe should review Platform Beta.",
            "[05:00] **Remote**\n\nI'm gonna contact Vendor Alpha tomorrow and request the renewal package.",
        ]
        payload = {
            "events": [{
                "event_type": "commitment",
                "speaker": "Remote",
                "target": "Speaker B",
                "subject": "Contact Vendor Alpha for the renewal package",
                "status": "accepted",
                "evidence": ["I'm gonna contact Vendor Alpha tomorrow and request the renewal package."],
            }]
        }
        with patch("ai.get_execution_profile", return_value=self._profile()), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai._memory_event_windows", return_value=windows), \
             patch("ai.ask_llm", side_effect=[RuntimeError("MLX response appears truncated at the generation token ceiling."), json.dumps(payload)]):
            ai._reset_memory_resolution_diagnostics()
            events = ai._extract_memory_events("Speaker B 1v1", transcript)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["target"], "Speaker B")
        diagnostics = ai.get_last_memory_resolution_diagnostics()
        self.assertEqual(diagnostics["window_truncated_count"], 1)
        self.assertEqual(diagnostics["window_failed_count"], 1)
        self.assertEqual(diagnostics["merged_candidate_count"], 1)

    def test_overlap_duplicate_events_merge_and_keep_unique_evidence(self):
        events = [
            {
                "event_type": "decision",
                "speaker": "Mic",
                "target": "",
                "subject": "Use Platform Beta for the pilot",
                "status": "settled",
                "evidence": ["We agreed to use Platform Beta for the pilot."],
            },
            {
                "event_type": "decision",
                "speaker": "Mic",
                "target": "",
                "subject": "Use Platform Beta for the pilot",
                "status": "settled",
                "evidence": [
                    "We agreed to use Platform Beta for the pilot.",
                    "Yes, Platform Beta is the pilot choice.",
                ],
            },
        ]
        merged = ai._merge_memory_events(events)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["evidence"]), 2)

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_first_person_owner_survives_overlap_merge(self):
        transcript = (
            "[07:30] **Remote**\n\nI'm gonna contact Vendor Alpha tomorrow and request the renewal package.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        raw = {
            "event_type": "assignment",
            "speaker": "Remote",
            "target": "User Alpha",
            "subject": "Contact Vendor Alpha for the renewal package",
            "status": "accepted",
            "evidence": ["I'm gonna contact Vendor Alpha tomorrow and request the renewal package."],
        }
        validated = ai._validate_memory_event(raw, transcript, identity_map)
        self.assertIsNotNone(validated)
        merged = ai._merge_memory_events([validated, dict(validated)])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["target"], "Speaker B")
        self.assertEqual(merged[0]["speaker"], "Speaker B")

    def test_pass2_evidence_context_is_smaller_than_unrelated_full_transcript(self):
        transcript = (
            "[00:00] **Mic**\n\nUnrelated introduction about Project Delta.\n\n"
            "[05:00] **Remote**\n\nThere is a risk of losing critical support if Vendor Alpha exits.\n\n"
            "[10:00] **Mic**\n\nUnrelated closing discussion about Platform Beta."
        )
        events = [{
            "event_type": "concern",
            "speaker": "Remote",
            "target": "",
            "subject": "Loss of critical support if Vendor Alpha exits",
            "status": "stated",
            "evidence": ["There is a risk of losing critical support if Vendor Alpha exits."],
        }]
        context = ai._memory_event_evidence_context(transcript, events, neighbor_turns=0)
        self.assertIn("critical support", context)
        self.assertNotIn("Unrelated introduction", context)
        self.assertLess(ai.estimate_tokens(context), ai.estimate_tokens(transcript))

# v12.20 post-window attribution + final settlement gate regressions.
class PrecisionV1220PostWindowFinalizationTests(unittest.TestCase):
    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Legacy Alias")
    def test_native_mic_channel_remains_self_when_private_label_differs(self):
        transcript = (
            "[00:00] **Remote**\n\nUser Alpha, how are you today?\n\n"
            "[00:05] **Mic**\n\nDoing well."
        )
        mapping = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        self.assertEqual(mapping.get("mic"), "User Alpha")
        self.assertEqual(mapping.get("remote"), "Speaker B")

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Legacy Alias")
    def test_first_person_owner_repaired_after_window_merge_when_private_label_differs(self):
        transcript = (
            "[07:30] **Remote**\n\n"
            "I'm gonna reach out to Vendor Alpha and ask for all four renewal packages.\n\n"
            "[07:50] **Mic**\n\nSounds good."
        )
        identity_map = ai._meeting_participant_identity_map("Speaker B 1v1", transcript)
        item = {
            "owner": "Remote",
            "action": "Reach out to Vendor Alpha for four renewal packages",
            "evidence": ["I'm gonna reach out to Vendor Alpha and ask for all four renewal packages."],
        }
        validated = ai._validate_resolved_commitment(item, transcript, identity_map)
        self.assertIsNotNone(validated)
        self.assertEqual(validated["owner"], "Speaker B")

    def test_hypothetical_priority_proposal_is_not_a_decision(self):
        transcript = (
            "[24:00] **Remote**\n\nWe'll review the negotiation list.\n\n"
            "[24:20] **Mic**\n\nMaybe we prioritize the most critical requirements first."
        )
        item = {
            "decision": "Prioritize critical requirements in the negotiation",
            "evidence": ["Maybe we prioritize the most critical requirements first."],
        }
        self.assertIsNone(ai._validate_resolved_decision(item, transcript))

    def test_good_push_preference_is_not_promoted_by_nearby_future_language(self):
        transcript = (
            "[23:00] **Remote**\n\nWe'll continue preparing the renewal package.\n\n"
            "[23:20] **Mic**\n\nThe flexible credits idea is a good push."
        )
        item = {
            "decision": "Push for flexible credits",
            "evidence": ["The flexible credits idea is a good push."],
        }
        self.assertIsNone(ai._validate_resolved_decision(item, transcript))

    def test_explicit_unhedged_group_direction_can_still_be_a_decision(self):
        transcript = "[10:00] **Mic**\n\nWe will use Platform Beta for the pilot."
        item = {
            "decision": "Use Platform Beta for the pilot",
            "evidence": ["We will use Platform Beta for the pilot."],
        }
        self.assertIsNotNone(ai._validate_resolved_decision(item, transcript))

    def test_escalation_actions_for_same_owner_are_deduplicated(self):
        commitments = [
            {
                "owner": "Person Beta",
                "action": "Escalate with Vendor Alpha",
                "status": "open",
                "evidence": "I'll get on a call and help escalate with Vendor Alpha.",
            },
            {
                "owner": "Person Beta",
                "action": "Help escalate with Vendor Alpha",
                "status": "open",
                "evidence": "I'll help escalate with Vendor Alpha tomorrow.",
            },
        ]
        deduped = ai._deduplicate_commitments(commitments)
        self.assertEqual(len(deduped), 1)

# v12.21 priority-aware candidate recall regressions.
class PrecisionV1221PriorityAwareRecallTests(unittest.TestCase):
    def _profile(self):
        return type(
            "Profile",
            (),
            {
                "resolved_name": "High Performance",
                "direct_token_budget": 32000,
                "llm_call_timeout_seconds": 150,
            },
        )()


    def test_commitment_event_rejects_completed_review_work(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "I will review the Vendor Alpha terms.\n\n"
            "[00:10] **Remote**\n\n"
            "After I reviewed the terms, I sent my findings yesterday."
        )
        event = {
            "event_type": "commitment",
            "speaker": "Speaker B",
            "target": "Speaker B",
            "subject": "Review Vendor Alpha terms",
            "status": "settled",
            "evidence": [
                "I will review the Vendor Alpha terms.",
                "After I reviewed the terms, I sent my findings yesterday.",
            ],
        }
        self.assertFalse(ai._memory_commitment_event_is_future_work(event, transcript))

    def test_commitment_event_keeps_explicit_future_outreach(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "I'm going to reach out to Vendor Alpha and request all four renewal quotes."
        )
        event = {
            "event_type": "commitment",
            "speaker": "Speaker B",
            "target": "Speaker B",
            "subject": "Reach out to Vendor Alpha for four renewal quotes",
            "status": "settled",
            "evidence": [
                "I'm going to reach out to Vendor Alpha and request all four renewal quotes."
            ],
        }
        self.assertTrue(ai._memory_commitment_event_is_future_work(event, transcript))

    def test_protected_commitment_recovers_pass2_omission(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "I have a call tomorrow and I'll help escalate with Vendor Alpha."
        )
        events = [
            {
                "event_type": "commitment",
                "speaker": "Speaker B",
                "target": "Speaker B",
                "subject": "escalate something with Vendor Alpha",
                "status": "accepted",
                "evidence": ["I have a call tomorrow and I'll help escalate with Vendor Alpha."],
            }
        ]
        recovered = ai._protected_event_commitment_candidates(events, [], transcript)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["owner"], "Speaker B")
        self.assertEqual(recovered[0]["action"], "Escalate with Vendor Alpha")

    def test_protected_commitment_skips_opaque_escalation_fragment(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "I'll help escalate."
        )
        events = [
            {
                "event_type": "commitment",
                "speaker": "Speaker B",
                "target": "Speaker B",
                "subject": "help escalate",
                "status": "accepted",
                "evidence": ["I'll help escalate."],
            }
        ]
        self.assertEqual(ai._protected_event_commitment_candidates(events, [], transcript), [])

    def test_protected_commitment_does_not_duplicate_pass2_candidate(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "I'm going to contact Vendor Alpha about the renewal."
        )
        events = [
            {
                "event_type": "commitment",
                "speaker": "Speaker B",
                "target": "Speaker B",
                "subject": "Contact Vendor Alpha about the renewal",
                "status": "accepted",
                "evidence": ["I'm going to contact Vendor Alpha about the renewal."],
            }
        ]
        proposed = [
            {
                "owner": "Speaker B",
                "action": "Contact Vendor Alpha about the renewal",
                "evidence": ["I'm going to contact Vendor Alpha about the renewal."],
            }
        ]
        self.assertEqual(ai._protected_event_commitment_candidates(events, proposed, transcript), [])

    def test_future_work_anchor_ignores_vague_possibility(self):
        window = (
            "[00:00] **Remote**\n\nI might get involved later if they need me.\n\n"
            "[00:10] **Remote**\n\nI'll contact Vendor Alpha tomorrow and request the renewal package."
        )
        anchors = ai._memory_future_work_anchors(window)
        self.assertEqual(len(anchors), 1)
        self.assertIn("contact Vendor Alpha", anchors[0]["text"])

    def test_priority_budget_caps_uncertainty_before_commitment(self):
        events = []
        for idx in range(10):
            events.append({
                "event_type": "uncertainty",
                "speaker": "Speaker B",
                "target": "Speaker B",
                "subject": f"Unknown item {idx}",
                "status": "unresolved",
                "evidence": [f"I don't know item {idx}."],
            })
        events.extend([
            {
                "event_type": "commitment",
                "speaker": "Speaker B",
                "target": "Speaker B",
                "subject": "Contact Vendor Alpha",
                "status": "accepted",
                "evidence": ["I'll contact Vendor Alpha tomorrow."],
            },
            {
                "event_type": "proposal",
                "speaker": "User Alpha",
                "target": "User Alpha",
                "subject": "Consider Platform Beta",
                "status": "proposed",
                "evidence": ["Maybe we consider Platform Beta."],
            },
        ])
        selected = ai._prioritize_memory_event_candidates(events)
        kinds = [item["event_type"] for item in selected]
        self.assertIn("commitment", kinds)
        self.assertLessEqual(kinds.count("uncertainty"), 2)

    @patch.object(ai, "SELF_NAME", "User Alpha")
    @patch.object(ai, "SELF_SPEAKER_LABEL", "Mic")
    def test_busy_window_recovers_explicit_commitment_crowded_out_of_main_response(self):
        uncertainty_turns = []
        uncertainty_events = []
        for idx in range(1, 13):
            quote = f"I don't know detail {idx}."
            uncertainty_turns.append(f"[{idx:02d}:00] **Remote**\n\n{quote}")
            uncertainty_events.append({
                "event_type": "uncertainty",
                "speaker": "Remote",
                "target": "Remote",
                "subject": f"detail {idx}",
                "status": "unresolved",
                "evidence": [quote],
            })
        commitment_quote = "I'm gonna contact Vendor Alpha tomorrow and request all four renewal packages."
        window = "\n\n".join(uncertainty_turns + [
            f"[13:00] **Remote**\n\n{commitment_quote}",
            "[13:05] **Mic**\n\nSounds good.",
        ])
        recovery_payload = {
            "events": [{
                "event_type": "commitment",
                "speaker": "Remote",
                "target": "Speaker B",
                "subject": "Contact Vendor Alpha for all four renewal packages",
                "status": "accepted",
                "evidence": [commitment_quote],
            }]
        }
        with patch("ai.get_execution_profile", return_value=self._profile()), \
             patch("ai.get_active_llm_model_name", return_value="Qwen/Qwen3-30B-A3B-MLX-6bit"), \
             patch("ai._memory_event_windows", return_value=[window]), \
             patch("ai.ask_llm", side_effect=[
                 json.dumps({"events": uncertainty_events}),
                 json.dumps(recovery_payload),
             ]):
            ai._reset_memory_resolution_diagnostics()
            events = ai._extract_memory_events("Speaker B 1v1", window)

        commitments = [item for item in events if item.get("event_type") == "commitment"]
        uncertainties = [item for item in events if item.get("event_type") == "uncertainty"]
        self.assertEqual(len(commitments), 1)
        self.assertEqual(commitments[0]["speaker"], "Speaker B")
        self.assertEqual(commitments[0]["target"], "Speaker B")
        self.assertIn("four renewal packages", commitments[0]["subject"])
        self.assertLessEqual(len(uncertainties), ai._MEMORY_EVENT_WINDOW_MAX_UNCERTAINTIES)
        diagnostics = ai.get_last_memory_resolution_diagnostics()
        self.assertEqual(diagnostics["window_diagnostics"][0]["anchor_recovery_needed"], 1)
        self.assertEqual(diagnostics["window_diagnostics"][0]["anchor_recovered_events"], 1)


# v12.23 durable-action hygiene regressions.
class PrecisionV1223DurableActionHygieneTests(unittest.TestCase):
    def test_current_meeting_walkthrough_is_not_durable_commitment(self):
        transcript = (
            "[00:00] **Remote**\n\n"
            "Speaker Beta can show you how the workflow works going forward."
        )
        item = {
            "owner": "Speaker Beta",
            "action": "Show the workflow feature",
            "evidence": ["Speaker Beta can show you how the workflow works going forward."],
        }
        self.assertIsNone(ai._validate_resolved_commitment(item, transcript))

    def test_current_meeting_navigation_event_is_not_future_work(self):
        transcript = "[00:00] **Remote**\n\nI'll go back to the renewal screen and walk through the example."
        event = {
            "event_type": "commitment",
            "speaker": "Speaker B",
            "target": "Speaker B",
            "subject": "Show the renewal screen",
            "status": "proposed",
            "evidence": ["I'll go back to the renewal screen and walk through the example."],
        }
        self.assertFalse(ai._memory_commitment_event_is_future_work(event, transcript))

    def test_scheduled_future_demo_remains_valid_commitment(self):
        transcript = "[00:00] **Remote**\n\nI'll show the workflow to Finance tomorrow."
        item = {
            "owner": "Speaker B",
            "action": "Show the workflow to Finance",
            "evidence": ["I'll show the workflow to Finance tomorrow."],
        }
        identity_map = {"remote": "Speaker B"}
        self.assertIsNotNone(ai._validate_resolved_commitment(item, transcript, identity_map))
