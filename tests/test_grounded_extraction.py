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

if __name__ == "__main__":
    unittest.main()
