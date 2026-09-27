import unittest
from types import SimpleNamespace
from unittest.mock import patch

from query.synthesis import (
    BOSS_PREP_SECTION_TITLES,
    _compact_meeting_memories,
    _compact_memory,
    _direct_prompt,
    _source_records,
    _synthesis_budgets,
    apply_synthesis_evidence_gate,
)


class QuerySynthesisTests(
    unittest.TestCase
):
    def test_source_records_preserve_all_meetings(
        self,
    ):
        memories = [
            (
                "2026-09-01_alpha",
                {"topics": []},
            ),
            (
                "2026-09-02_beta",
                {"topics": []},
            ),
            (
                "2026-09-03_gamma",
                {"topics": []},
            ),
        ]

        selected = [
            {
                "meeting_run":
                    "2026-09-01_alpha",
                "display_title":
                    "Alex 1v1",
                "participants":
                    ["Alex"],
            },
            {
                "meeting_run":
                    "2026-09-02_beta",
                "display_title":
                    "Jordan 1v1",
                "participants":
                    ["Jordan"],
            },
            {
                "meeting_run":
                    "2026-09-03_gamma",
                "display_title":
                    "Project Check-in",
                "participants":
                    ["Alex", "Jordan"],
            },
        ]

        records = _source_records(
            memories,
            selected,
        )

        self.assertEqual(
            len(records),
            3,
        )
        self.assertEqual(
            [
                item["display_title"]
                for item in records
            ],
            [
                "Alex 1v1",
                "Jordan 1v1",
                "Project Check-in",
            ],
        )

    def test_direct_prompt_requires_full_coverage(
        self,
    ):
        sources = [
            {
                "meeting_run":
                    "2026-09-01_alpha",
                "meeting_date":
                    "2026-09-01",
                "display_title":
                    "Alex 1v1",
                "participants": ["Alex"],
                "memory": {},
            },
            {
                "meeting_run":
                    "2026-09-02_beta",
                "meeting_date":
                    "2026-09-02",
                "display_title":
                    "Jordan 1v1",
                "participants": ["Jordan"],
                "memory": {},
            },
        ]

        prompt = _direct_prompt(
            "Prepare me.",
            sources,
            [],
        )

        self.assertIn(
            "exactly 2 selected source meetings",
            prompt,
        )
        self.assertIn(
            "Do not choose one source as the anchor",
            prompt,
        )
        self.assertIn(
            "Alex 1v1",
            prompt,
        )
        self.assertIn(
            "Jordan 1v1",
            prompt,
        )


    def test_source_kind_classifies_one_on_one_and_other(
        self,
    ):
        from query.synthesis import (
            _source_kind,
        )

        self.assertEqual(
            _source_kind(
                "Alex 1v1",
                ["Alex"],
            ),
            "one_on_one",
        )

        self.assertEqual(
            _source_kind(
                "Project Steering",
                [
                    "Alex",
                    "Jordan",
                    "Taylor",
                ],
            ),
            "other",
        )

    def test_direct_prompt_has_semantic_guardrails(
        self,
    ):
        sources = [
            {
                "meeting_run":
                    "2026-09-01_alpha",
                "meeting_date":
                    "2026-09-01",
                "display_title":
                    "Alex 1v1",
                "participants":
                    ["Alex"],
                "source_kind":
                    "one_on_one",
                "memory": {},
            },
            {
                "meeting_run":
                    "2026-09-02_beta",
                "meeting_date":
                    "2026-09-02",
                "display_title":
                    "Project Steering",
                "participants":
                    [
                        "Alex",
                        "Jordan",
                    ],
                "source_kind":
                    "other",
                "memory": {},
            },
        ]

        prompt = _direct_prompt(
            "Prepare my boss 1:1.",
            sources,
            [],
        )

        self.assertIn(
            "Never relabel a one-on-one item as ad-hoc",
            prompt,
        )
        self.assertIn(
            "Do not turn ordinary open",
            prompt,
        )
        self.assertIn(
            "Do not relabel challenges or unfinished work",
            prompt,
        )


    def test_compact_memory_drops_verbose_history(
        self,
    ):
        memory = {
            "topics": [
                {
                    "topic_key": "vendor",
                    "topic": "Vendor Renewal",
                    "status": "open",
                    "summary": "Negotiation continues.",
                    "huge_internal_blob":
                        "x" * 10000,
                }
            ],
            "decisions": [
                "Use a one-year term."
            ],
            "open_questions": [
                "Will pricing hold?"
            ],
            "commitments": [
                {
                    "owner": "Alex",
                    "commitment":
                        "Send the deck.",
                }
            ],
            "follow_ups": [
                "Check pricing."
            ],
            "topic_history": {
                "vendor": [
                    {
                        "summary":
                            "x" * 10000
                    }
                ]
            },
            "anchor_topics": [
                {
                    "summary":
                        "x" * 10000
                }
            ],
            "supporting_topics": [
                {
                    "summary":
                        "x" * 10000
                }
            ],
        }

        compact = _compact_memory(
            memory
        )

        self.assertEqual(
            set(compact),
            {
                "topics",
                "decisions",
                "open_questions",
                "commitments",
                "follow_ups",
            },
        )
        self.assertNotIn(
            "huge_internal_blob",
            compact["topics"][0],
        )
        self.assertEqual(
            compact["commitments"][0][
                "owner"
            ],
            "Alex",
        )

    def test_compact_memories_preserve_each_source(
        self,
    ):
        memories = [
            (
                "2026-09-01_alpha",
                {
                    "topics": [
                        {
                            "topic":
                                "Alpha",
                            "summary":
                                "A",
                        }
                    ],
                    "topic_history": {
                        "huge":
                            ["x" * 5000]
                    },
                },
            ),
            (
                "2026-09-02_beta",
                {
                    "topics": [
                        {
                            "topic":
                                "Beta",
                            "summary":
                                "B",
                        }
                    ],
                    "topic_history": {
                        "huge":
                            ["x" * 5000]
                    },
                },
            ),
        ]

        compact = (
            _compact_meeting_memories(
                memories
            )
        )

        self.assertEqual(
            [
                run
                for run, _memory
                in compact
            ],
            [
                "2026-09-01_alpha",
                "2026-09-02_beta",
            ],
        )

        self.assertNotIn(
            "topic_history",
            compact[0][1],
        )

    def test_source_records_use_compact_memory(
        self,
    ):
        records = _source_records(
            [
                (
                    "2026-09-01_alpha",
                    {
                        "topics": [],
                        "topic_history": {
                            "huge":
                                ["x" * 5000]
                        },
                    },
                )
            ],
            [
                {
                    "meeting_run":
                        "2026-09-01_alpha",
                    "display_title":
                        "Alex 1v1",
                    "participants":
                        ["Alex"],
                }
            ],
        )

        self.assertNotIn(
            "topic_history",
            records[0]["memory"],
        )


    def test_synthesis_uses_profile_runtime_budget(
        self,
    ):
        class FakeProfile:
            direct_token_budget = 6000
            chunk_source_token_budget = 2400
            context_size_tokens = 0
            context_reserve_tokens = 0

        direct, chunk = (
            _synthesis_budgets(
                FakeProfile(),
                "Balanced",
            )
        )

        self.assertEqual(
            direct,
            6000,
        )
        self.assertEqual(
            chunk,
            2400,
        )

    def test_synthesis_budget_respects_configured_context(
        self,
    ):
        class FakeProfile:
            direct_token_budget = 6000
            chunk_source_token_budget = 2400
            context_size_tokens = 8192
            context_reserve_tokens = 2048

        direct, chunk = (
            _synthesis_budgets(
                FakeProfile(),
                "Balanced",
            )
        )

        self.assertEqual(
            direct,
            6000,
        )
        self.assertEqual(
            chunk,
            2400,
        )

    def test_evidence_gate_removes_unsupported_boss_help_and_wins(
        self,
    ):
        sources = [
            {
                "meeting_date":
                    "2026-09-21",
                "display_title":
                    "Alex 1v1",
                "source_kind":
                    "one_on_one",
                "memory": {
                    "topics": [
                        {
                            "topic":
                                "Board Review",
                            "summary":
                                "Awaiting board approval.",
                        },
                        {
                            "topic":
                                "Project Work",
                            "summary":
                                "Ongoing discussion.",
                        },
                        {
                            "topic":
                                "Savings",
                            "summary":
                                "Renewal delivered $250k savings.",
                        },
                    ]
                },
            }
        ]

        result = (
            "**6. Decisions or help I need from my boss**\n"
            "**2026-09-21 | Alex 1v1**\n"
            "• Board Review: board approval is still required.\n"
            "• Project Work: leadership guidance may be needed.\n\n"
            "**8. Worth mentioning**\n"
            "**2026-09-21 | Alex 1v1**\n"
            "• Savings: Renewal delivered $250k savings.\n"
            "• Project Work: Ongoing discussions continue."
        )

        gated = (
            apply_synthesis_evidence_gate(
                result,
                sources,
            )
        )

        self.assertIn(
            "Board Review",
            gated,
        )
        self.assertNotIn(
            "Project Work: leadership",
            gated,
        )
        self.assertIn(
            "$250k savings",
            gated,
        )
        self.assertNotIn(
            "Ongoing discussions continue",
            gated,
        )

    def test_evidence_gate_handles_markdown_heading_prefixes(
        self,
    ):
        sources = [
            {
                "meeting_date":
                    "2026-09-21",
                "display_title":
                    "Alex 1v1",
                "source_kind":
                    "one_on_one",
                "memory": {
                    "topics": [
                        {
                            "topic":
                                "Project Work",
                            "summary":
                                "Ongoing discussion.",
                        },
                        {
                            "topic":
                                "Savings",
                            "summary":
                                "Renewal delivered $250k savings.",
                        },
                    ]
                },
            }
        ]

        result = (
            "### 6. Decisions or help I need from my boss\n"
            "**2026-09-21 | Alex 1v1**\n"
            "• Project Work: leadership intervention may be required.\n\n"
            "### 8. Worth mentioning\n"
            "**2026-09-21 | Alex 1v1**\n"
            "• Savings: Renewal delivered $250k savings.\n"
            "• Project Work: Ongoing discussions continue."
        )

        gated = apply_synthesis_evidence_gate(
            result,
            sources,
        )

        self.assertNotIn(
            "leadership intervention",
            gated,
        )
        self.assertIn(
            "$250k savings",
            gated,
        )
        self.assertNotIn(
            "Ongoing discussions continue",
            gated,
        )

    def test_evidence_gate_forces_no_ad_hoc_for_only_1v1s(
        self,
    ):
        sources = [
            {
                "meeting_date":
                    "2026-09-21",
                "display_title":
                    "Alex 1v1",
                "source_kind":
                    "one_on_one",
                "memory": {},
            }
        ]

        result = (
            "**4. Ad-hoc signals**\n"
            "• Something from Alex.\n\n"
            "**5. Sensitive / escalation topics**\n"
            "None identified."
        )

        gated = (
            apply_synthesis_evidence_gate(
                result,
                sources,
            )
        )

        self.assertIn(
            "**4. Ad-hoc signals**\n\nNone identified.",
            gated,
        )
        self.assertNotIn(
            "Something from Alex",
            gated,
        )

    def test_evidence_gate_restores_missing_boss_prep_headings(self):
        sources = [
            {
                "meeting_date": "2026-09-21",
                "display_title": "Alex 1v1",
                "source_kind": "one_on_one",
                "memory": {},
            }
        ]

        result = (
            "**1. What needs attention now**\n"
            "• Urgent item.\n\n"
            "**2. Open staff items**\n"
            "• Staff follow-up.\n\n"
            "---\n\n"
            "None identified.\n\n"
            "None identified.\n\n"
            "**5. Sensitive / escalation topics**\n"
            "• Sensitive item.\n\n"
            "---\n\n"
            "None identified.\n\n"
            "**7. My commitments**\n"
            "None identified.\n\n"
            "---\n\n"
            "None identified."
        )

        gated = apply_synthesis_evidence_gate(result, sources)

        for number in range(1, 9):
            self.assertRegex(
                gated,
                rf"(?m)^\*\*{number}\. ",
            )

        self.assertIn(
            "**3. Themes across the team**\n\nNone identified.",
            gated,
        )
        self.assertIn(
            "**4. Ad-hoc signals**\n\nNone identified.",
            gated,
        )
        self.assertIn(
            "**6. Decisions or help I need from my boss**\n\nNone identified.",
            gated,
        )
        self.assertIn(
            "**8. Worth mentioning / progress / wins**\n\nNone identified.",
            gated,
        )


    def test_evidence_gate_repairs_exact_live_missing_heading_shape(self):
        sources = [
            {
                "meeting_date": "2026-09-21",
                "display_title": "Jordan 1v1",
                "source_kind": "one_on_one",
                "memory": {},
            }
        ]

        result = (
            "**1. What needs attention now — urgent, time-sensitive, or blocked items.**\n"
            "• Follow up on Endpoint Platform.\n\n"
            "**2. Open staff items — unresolved commitments, decisions, follow-ups, or questions from recent 1:1s, grouped by staff member/meeting.**\n"
            "• Jordan has open items.\n\n"
            "None identified.\n\n"
            "None identified.\n\n"
            "**5. Sensitive / escalation topics — items that may require careful handling, leadership awareness, or escalation.**\n"
            "• Procurement process issue.\n\n"
            "None identified.\n\n"
            "**7. My commitments — include only commitments supported as belonging to me. Never include a staff member's own commitments here. If my identity cannot be established safely from the selected sources, write 'None identified.'** **None identified.**\n\n"
            "None identified."
        )

        gated = apply_synthesis_evidence_gate(result, sources)

        expected_headings = [
            f"**{number}. {BOSS_PREP_SECTION_TITLES[number]}**"
            for number in range(1, 9)
        ]
        for heading in expected_headings:
            self.assertIn(heading, gated)

        self.assertNotIn(
            "include only commitments supported as belonging to me",
            gated,
        )
        self.assertEqual(
            gated.count("None identified."),
            5,
        )



    def test_boss_help_gate_strips_speculative_leadership_inference(self):
        sources = [
            {
                "meeting_date": "2026-09-14",
                "display_title": "Alex 1v1",
                "source_kind": "one_on_one",
                "memory": {
                    "topics": [
                        {
                            "topic": "Board Review Process",
                            "summary": (
                                "The board review is a key enabler for the deal, "
                                "with formal board blessing expected by Wednesday."
                            ),
                        },
                        {
                            "topic": "Vendor Alpha Presentation Review",
                            "summary": (
                                "The presentation lacked strategic clarity and "
                                "actionable insights."
                            ),
                        },
                    ]
                },
            }
        ]

        result = (
            "**6. Decisions or help I need from my boss**\n"
            "• **Vendor Alpha Presentation Review** (2026-09-14 | Alex 1v1): "
            "The presentation lacked strategic clarity, which may require leadership "
            "guidance or approval to align with business goals.\n"
            "• **Board Review Process** (2026-09-14 | Alex 1v1): "
            "The board review is a key enabler for the deal, and leadership intervention "
            "may be needed to ensure the timeline is met.\n\n"
            "**8. Worth mentioning / progress / wins**\n"
            "None identified."
        )

        gated = apply_synthesis_evidence_gate(result, sources)

        self.assertNotIn("Vendor Alpha Presentation Review", gated)
        self.assertIn("Board Review Process", gated)
        self.assertNotIn("leadership intervention may be needed", gated)
        self.assertNotIn("leadership guidance or approval", gated)

    def test_empty_boss_prep_sections_render_none_on_new_paragraph(self):
        sources = [
            {
                "meeting_date": "2026-09-21",
                "display_title": "Alex 1v1",
                "source_kind": "one_on_one",
                "memory": {},
            }
        ]

        result = (
            "**4. Ad-hoc signals** None identified.\n\n"
            "**7. My commitments** **None identified.**"
        )

        gated = apply_synthesis_evidence_gate(result, sources)

        self.assertIn(
            "**4. Ad-hoc signals**\n\nNone identified.",
            gated,
        )
        self.assertIn(
            "**7. My commitments**\n\nNone identified.",
            gated,
        )



    def test_boss_prep_rendering_separates_heading_and_body_and_removes_rules(self):
        sources = [
            {
                "meeting_date": "2026-09-14",
                "display_title": "Alex 1v1",
                "source_kind": "one_on_one",
                "memory": {},
            }
        ]

        result = (
            "**2. Open staff items — unresolved commitments, decisions, follow-ups, "
            "or questions from recent 1:1s, grouped by staff member/meeting**\n"
            "**Alex 1v1 2026-09-14**:\n"
            "• Follow-ups: Provide response to final legal terms.\n\n"
            "\\---\n\n"
            "**7. My commitments** **None identified.**\n\n"
            "\\---\n\n"
            "**8. Worth mentioning / progress / wins**\n"
            "None identified."
        )

        gated = apply_synthesis_evidence_gate(result, sources)

        self.assertIn(
            "**2. Open staff items — unresolved commitments, decisions, follow-ups, "
            "or questions from recent 1:1s, grouped by staff member/meeting**\n\n"
            "**Alex 1v1 2026-09-14**:",
            gated,
        )
        self.assertIn(
            "**7. My commitments**\n\nNone identified.",
            gated,
        )
        self.assertNotIn("\\---", gated)



    def _timeout_test_profile(self, timeout_seconds=240):
        return SimpleNamespace(
            name="Auto",
            resolved_name="Conservative",
            profile_reason="test",
            chunk_overlap_tokens=256,
            context_size_tokens=16384,
            context_reserve_tokens=3000,
            model_name="qwen3:8b",
            model_parameter_billions=8.2,
            model_budget_factor=1.0,
            hardware_label="Apple Silicon 16 GB",
            hardware_performance_class="Conservative",
            hardware_budget_factor=1.0,
            calibration_factor=1.0,
            calibration_sample_count=0,
            calibration_median_elapsed_seconds=None,
            calibration_reason="test",
            llm_call_timeout_seconds=timeout_seconds,
        )

    @patch("query.synthesis.ask_llm")
    @patch("query.synthesis.build_synthesis_plan")
    def test_run_synthesis_query_uses_profile_timeout_direct(
        self, build_plan, ask_llm_mock
    ):
        from query.synthesis import run_synthesis_query

        profile = self._timeout_test_profile(240)
        build_plan.return_value = SimpleNamespace(
            direct_prompt="prompt",
            profile=profile,
            execution_plan=SimpleNamespace(
                mode="direct",
                direct_token_budget=9000,
                estimated_prompt_tokens=5000,
            ),
            chunks=[],
            sources=[],
            compact_memories=[],
            direct_token_budget=9000,
            chunk_source_token_budget=6000,
        )
        ask_llm_mock.return_value = "None identified."

        _result, metadata = run_synthesis_query(
            "prep", [], [], return_execution_metadata=True
        )

        self.assertEqual(
            ask_llm_mock.call_args.kwargs["timeout_seconds"],
            240,
        )
        self.assertEqual(metadata["llm_call_timeout_seconds"], 240)

    @patch("query.synthesis.ask_llm")
    @patch("query.synthesis.build_synthesis_plan")
    def test_run_synthesis_query_uses_profile_timeout_chunked(
        self, build_plan, ask_llm_mock
    ):
        from query.synthesis import run_synthesis_query

        profile = self._timeout_test_profile(240)
        build_plan.return_value = SimpleNamespace(
            direct_prompt="prompt",
            profile=profile,
            execution_plan=SimpleNamespace(
                mode="chunked",
                direct_token_budget=9000,
                estimated_prompt_tokens=10449,
            ),
            chunks=[([], []), ([], [])],
            sources=[],
            compact_memories=[],
            direct_token_budget=9000,
            chunk_source_token_budget=6000,
        )
        ask_llm_mock.return_value = "None identified."

        run_synthesis_query("prep", [], [])

        self.assertEqual(ask_llm_mock.call_count, 3)
        for call in ask_llm_mock.call_args_list:
            self.assertEqual(call.kwargs["timeout_seconds"], 240)



if __name__ == "__main__":
    unittest.main()
