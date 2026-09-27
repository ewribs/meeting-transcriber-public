from __future__ import annotations

import unittest
from unittest.mock import patch

from query.changes import (
    NotEnoughMeetingsForChangesError,
    apply_changes_evidence_gate,
    build_changes_evidence,
    build_changes_prompt,
    prepare_changes_comparison,
    run_changes_query,
)


class _FakeHardware:
    display_label = "Test Mac"
    performance_class = "test"
    budget_factor = 1.0


class _FakeCalibration:
    factor = 1.0
    sample_count = 0
    median_elapsed_seconds = None
    reason = "test"


class QueryChangesTests(unittest.TestCase):
    def _memory(self, topic: str) -> dict:
        return {
            "topics": [
                {
                    "topic_key": topic.lower(),
                    "topic": topic,
                    "status": "open",
                    "summary": f"{topic} summary",
                }
            ],
            "decisions": [],
            "open_questions": [],
            "commitments": [],
            "follow_ups": [],
        }

    def test_prepare_changes_uses_latest_two_available_meetings(self):
        memories = [
            ("2026-09-01_old", self._memory("Old")),
            ("2026-09-17_latest", self._memory("Latest")),
            ("2026-09-08_previous", self._memory("Previous")),
        ]
        selected = [
            {
                "meeting_run": "2026-09-01_old",
                "display_title": "One on One",
            },
            {
                "meeting_run": "2026-09-08_previous",
                "display_title": "One on One",
            },
            {
                "meeting_run": "2026-09-17_latest",
                "display_title": "One on One",
            },
        ]

        prepared = prepare_changes_comparison(
            memories,
            selected,
        )

        self.assertEqual(
            prepared["previous_run"],
            "2026-09-08_previous",
        )
        self.assertEqual(
            prepared["latest_run"],
            "2026-09-17_latest",
        )
        self.assertEqual(
            prepared["previous_label"],
            "2026-09-08 | One on One",
        )
        self.assertEqual(
            prepared["latest_label"],
            "2026-09-17 | One on One",
        )
        self.assertEqual(
            [
                item["meeting_run"]
                for item in prepared["sources"]
            ],
            [
                "2026-09-08_previous",
                "2026-09-17_latest",
            ],
        )
        self.assertEqual(
            prepared["sources"][0]["memory"]["topics"][0]["topic"],
            "Previous",
        )
        self.assertEqual(
            prepared["sources"][1]["memory"]["topics"][0]["topic"],
            "Latest",
        )

    def test_prepare_changes_requires_two_meetings(self):
        with self.assertRaises(
            NotEnoughMeetingsForChangesError
        ):
            prepare_changes_comparison(
                [("2026-09-17_only", {})],
                [
                    {
                        "meeting_run":
                            "2026-09-17_only",
                    }
                ],
            )

    def test_changes_prompt_requires_evidence_for_status_changes(self):
        prompt = build_changes_prompt(
            "2026-09-08 | Previous",
            "2026-09-17 | Latest",
            "Focus on supplier commitments.",
            sources=[
                {
                    "meeting_run": "2026-09-08_previous",
                    "memory": {"topics": []},
                },
                {
                    "meeting_run": "2026-09-17_latest",
                    "memory": {"topics": []},
                },
            ],
        )

        self.assertIn(
            "## New Since Last Time",
            prompt,
        )
        self.assertIn(
            "## Changed / Progressed",
            prompt,
        )
        self.assertIn(
            "## Resolved / Closed",
            prompt,
        )
        self.assertIn(
            "## Still Open / Carried Forward",
            prompt,
        )
        self.assertIn(
            "Absence is not resolution",
            prompt,
        )
        self.assertIn(
            "Focus on supplier commitments.",
            prompt,
        )
        self.assertIn(
            "SOURCE MEETINGS",
            prompt,
        )


    def test_changes_evidence_classifies_topics_without_absence_inference(self):
        previous_memory = {
            "topics": [
                {
                    "topic_key": "endpoint platform renewal process",
                    "topic": "Endpoint Platform Renewal Process",
                    "status": "open",
                    "summary": "Pricing remains unsettled.",
                },
                {
                    "topic_key": "ram price increase",
                    "topic": "RAM Price Increase",
                    "status": "open",
                    "summary": "Pricing increase remains open.",
                },
                {
                    "topic_key": "security platform a renewal",
                    "topic": "Security Platform Renewal",
                    "status": "ongoing",
                    "summary": "Renewal remains ongoing.",
                },
                {
                    "topic_key": "security platform b renewal",
                    "topic": "Security Vendor B Renewal",
                    "status": "ongoing",
                    "summary": "Renewal work is underway.",
                },
            ],
            "decisions": [],
            "commitments": [
                {"commitment": "Prepare the old board package."},
            ],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [
                {
                    "topic_key": "endpoint platform contract negotiation",
                    "topic": "Endpoint Platform Contract Negotiation",
                    "status": "ongoing",
                    "summary": "A negotiation call is scheduled.",
                },
                {
                    "topic_key": "ram price increase",
                    "topic": "RAM Price Increase",
                    "status": "closed",
                    "summary": "Price was held flat if ordered this week.",
                },
                {
                    "topic_key": "security platform b renewal",
                    "topic": "Security Vendor B Renewal",
                    "status": "ongoing",
                    "summary": "PO split for DLP charges is now required.",
                },
                {
                    "topic_key": "procurement process controls",
                    "topic": "Procurement Process Controls",
                    "status": "open",
                    "summary": "Invoice errors exposed a controls problem.",
                },
                {
                    "topic_key": "laptop order",
                    "topic": "Three-Million-Dollar Laptop Order",
                    "status": "ongoing",
                    "summary": "A major laptop order is progressing.",
                },
            ],
            "decisions": [
                {"decision": "Hold the RAM price flat if ordered this week."},
            ],
            "commitments": [
                {"commitment": "Send the deck to Casey."},
            ],
            "follow_ups": [
                {"follow_up": "Bring in support for the Endpoint Platform call."},
            ],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        new_names = {
            item["topic"]
            for item in evidence["new_topics"]
        }
        changed_names = {
            item["latest_topic"]
            for item in evidence["changed_topics"]
        }
        resolved_names = {
            item["latest_topic"]
            for item in evidence["resolved_topics"]
        }
        risk_names = {
            item.get("latest_topic") or item.get("topic")
            for item in evidence["new_risks"]
        }
        carried_names = {
            item["latest_topic"]
            for item in evidence["carried_topics"]
        }

        self.assertEqual(
            new_names,
            {"Three-Million-Dollar Laptop Order"},
        )
        self.assertIn(
            "Endpoint Platform Contract Negotiation",
            changed_names,
        )
        self.assertIn(
            "Security Vendor B Renewal",
            changed_names,
        )
        self.assertEqual(
            resolved_names,
            {"RAM Price Increase"},
        )
        self.assertEqual(
            risk_names,
            {"Procurement Process Controls"},
        )
        self.assertNotIn(
            "Security Platform Renewal",
            carried_names,
        )
        self.assertIn(
            "Security Platform Renewal",
            evidence["previous_only_topics"],
        )
        self.assertEqual(
            evidence["carried_actions"],
            [],
        )

    def test_changes_gate_rebuilds_semantic_sections_from_evidence(self):
        evidence = {
            "previous_label": "2026-09-14 | Jordan 1v1",
            "latest_label": "2026-09-21 | Jordan 1v1",
            "new_topics": [
                {
                    "topic": "Laptop Order",
                    "latest_summary": "New order is progressing.",
                }
            ],
            "changed_topics": [
                {
                    "previous_topic": "Endpoint Platform Renewal Process",
                    "latest_topic": "Endpoint Platform Contract Negotiation",
                    "previous_status": "open",
                    "latest_status": "ongoing",
                    "latest_summary": "A negotiation call is scheduled.",
                }
            ],
            "new_decisions": [
                "Use a one-year term instead of three years."
            ],
            "resolved_topics": [
                {
                    "previous_topic": "RAM Price Increase",
                    "latest_topic": "RAM Price Increase",
                    "latest_summary": "Price was held flat.",
                }
            ],
            "carried_topics": [],
            "new_risks": [
                {
                    "topic": "Procurement Process Controls",
                    "latest_summary": "Invoice errors exposed a controls problem.",
                }
            ],
            "new_actions": ["Send the deck to Casey."],
            "carried_actions": [],
        }
        hallucinated = """
## Executive Delta
- RAM pricing was resolved and Endpoint Platform progressed.

## New Since Last Time
- RAM Price Increase was new.
- Laptop Order was new.

## Changed / Progressed
- Endpoint Platform progressed.

## New Decisions
- Something else.

## Resolved / Closed
- RAM Price Increase was closed.

## Still Open / Carried Forward
- Security Platform Renewal remains open.

## New Risks / Blockers
- Supplier Pricing Negotiations is risky.

## Commitments & Follow-ups
- Prepare the old board package.
""".strip()

        result = apply_changes_evidence_gate(
            hallucinated,
            evidence,
        )

        self.assertIn(
            "## Executive Delta",
            result,
        )
        self.assertIn(
            "**Laptop Order**",
            result,
        )
        self.assertNotIn(
            "RAM Price Increase was new",
            result,
        )
        self.assertIn(
            "**Endpoint Platform Contract Negotiation**",
            result,
        )
        self.assertIn(
            "Use a one-year term instead of three years.",
            result,
        )
        self.assertIn(
            "**RAM Price Increase**",
            result,
        )
        self.assertIn(
            "## Still Open / Carried Forward\n\nNone identified.",
            result,
        )
        self.assertNotIn(
            "Security Platform Renewal remains open",
            result,
        )
        self.assertIn(
            "**Procurement Process Controls**",
            result,
        )
        self.assertNotIn(
            "Supplier Pricing Negotiations is risky",
            result,
        )
        self.assertIn(
            "Send the deck to Casey.",
            result,
        )
        self.assertNotIn(
            "Prepare the old board package",
            result,
        )


    def test_changes_regression_ram_key_drift_resolves_and_decides(self):
        previous_memory = {
            "topics": [
                {
                    "topic_key": "memory pricing concern",
                    "topic": "RAM Price Increase",
                    "status": "open",
                    "summary": "The RAM price increase remains open.",
                }
            ],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [
                {
                    "topic_key": "ram cost management",
                    "topic": "RAM Price Increase",
                    "status": "closed",
                    "summary": (
                        "The RAM price increase was held flat if the order "
                        "could be completed by the end of the week. This "
                        "decision was confirmed in the meeting."
                    ),
                }
            ],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        self.assertEqual(evidence["new_topics"], [])
        self.assertEqual(
            [item["latest_topic"] for item in evidence["resolved_topics"]],
            ["RAM Price Increase"],
        )
        self.assertTrue(
            any(
                "RAM Price Increase" in decision
                and "held flat" in decision
                for decision in evidence["new_decisions"]
            )
        )

    def test_changes_regression_action_field_survives_without_owner_open(self):
        previous_memory = {
            "topics": [],
            "decisions": [],
            "commitments": [
                {"owner": "Jordan", "status": "open"},
            ],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [],
            "decisions": [],
            "commitments": [
                {
                    "owner": "Jordan",
                    "action": "Send the deck to Casey",
                    "status": "open",
                },
                {"owner": "Jordan", "status": "open"},
            ],
            "follow_ups": [],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        self.assertEqual(evidence["new_actions"], ["Send the deck to Casey"])
        self.assertEqual(evidence["carried_actions"], [])
        self.assertNotIn("Jordan open", str(evidence))

    def test_changes_regression_uncertainty_alone_is_not_a_risk(self):
        previous_memory = {
            "topics": [],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [
                {
                    "topic_key": "marketplace incentives ppa terms",
                    "topic": "Marketplace Incentives and PPA Terms",
                    "status": "open",
                    "summary": (
                        "The team expressed uncertainty around Marketplace "
                        "incentives and PPA terms and future cost structures."
                    ),
                }
            ],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        self.assertEqual(evidence["new_risks"], [])
        self.assertEqual(
            [item["topic"] for item in evidence["new_topics"]],
            ["Marketplace Incentives and PPA Terms"],
        )

    def test_changes_renderer_separates_deterministic_bullets(self):
        evidence = {
            "previous_label": "2026-09-14 | Jordan 1v1",
            "latest_label": "2026-09-21 | Jordan 1v1",
            "new_topics": [
                {"topic": "Topic A", "latest_summary": "First."},
                {"topic": "Topic B", "latest_summary": "Second."},
            ],
            "changed_topics": [],
            "new_decisions": [],
            "resolved_topics": [],
            "carried_topics": [],
            "new_risks": [],
            "new_actions": ["Action one", "Action two"],
            "carried_actions": [],
        }

        result = apply_changes_evidence_gate(
            "## Executive Delta\n- Delta",
            evidence,
        )

        self.assertIn("First. (2026-09-21 | Jordan 1v1)\n\n- **Topic B**", result)
        self.assertIn("Action one (2026-09-21 | Jordan 1v1)\n\n- Action two", result)


    def test_latest_only_explicit_resolution_is_not_new(self):
        previous_memory = {
            "topics": [],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [
                {
                    "topic_key": "ram pricing final",
                    "topic": "RAM Price Increase",
                    "status": "closed",
                    "summary": (
                        "The RAM price increase was held flat if the order "
                        "could be completed by the end of the week. The "
                        "decision was confirmed."
                    ),
                }
            ],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        self.assertEqual(evidence["new_topics"], [])
        self.assertEqual(
            [item["topic"] for item in evidence["resolved_topics"]],
            ["RAM Price Increase"],
        )
        self.assertTrue(
            any("held flat" in item for item in evidence["new_decisions"])
        )

    def test_flattened_owner_status_action_is_suppressed(self):
        previous_memory = {
            "topics": [],
            "decisions": [],
            "commitments": [],
            "follow_ups": [],
        }
        latest_memory = {
            "topics": [],
            "decisions": [],
            "commitments": ["Jordan open", "Send the deck to Casey"],
            "follow_ups": [],
        }
        prepared = prepare_changes_comparison(
            [
                ("2026-09-14_prev", previous_memory),
                ("2026-09-21_latest", latest_memory),
            ],
            [
                {
                    "meeting_run": "2026-09-14_prev",
                    "display_title": "Jordan 1v1",
                },
                {
                    "meeting_run": "2026-09-21_latest",
                    "display_title": "Jordan 1v1",
                },
            ],
        )

        evidence = build_changes_evidence(prepared)

        self.assertEqual(evidence["new_actions"], ["Send the deck to Casey"])
        self.assertNotIn("Jordan open", str(evidence))

    def test_executive_delta_is_rebuilt_from_evidence(self):
        evidence = {
            "previous_label": "2026-09-14 | Jordan 1v1",
            "latest_label": "2026-09-21 | Jordan 1v1",
            "new_topics": [
                {
                    "topic": "Laptop Order",
                    "latest_summary": "A new laptop order was introduced.",
                }
            ],
            "changed_topics": [],
            "new_decisions": [],
            "resolved_topics": [
                {
                    "topic": "RAM Price Increase",
                    "latest_summary": "The price was held flat.",
                }
            ],
            "carried_topics": [],
            "new_risks": [],
            "new_actions": [],
            "carried_actions": [],
        }

        result = apply_changes_evidence_gate(
            (
                "## Executive Delta\n"
                "- New risks include unsupported Marketplace uncertainty."
            ),
            evidence,
        )

        executive = result.split("## New Since Last Time", 1)[0]
        self.assertIn("RAM Price Increase", executive)
        self.assertIn("Laptop Order", executive)
        self.assertNotIn("Marketplace", executive)

    @patch(
        "query.changes.get_execution_calibration",
        return_value=_FakeCalibration(),
    )
    @patch(
        "query.changes.detect_hardware_profile",
        return_value=_FakeHardware(),
    )
    @patch(
        "query.changes.ask_llm",
        return_value=(
            "## Executive Delta\n"
            "- Real comparison\n\n"
            "## New Since Last Time\n"
            "None identified."
        ),
    )
    def test_run_changes_query_uses_dedicated_direct_prompt(
        self,
        ask_llm,
        _hardware,
        _calibration,
    ):
        memories = [
            ("2026-09-01_old", self._memory("Old")),
            ("2026-09-08_previous", self._memory("Previous")),
            ("2026-09-17_latest", self._memory("Latest")),
        ]
        selected = [
            {
                "meeting_run": run,
                "display_title": title,
            }
            for run, title in [
                ("2026-09-01_old", "Old"),
                ("2026-09-08_previous", "Previous"),
                ("2026-09-17_latest", "Latest"),
            ]
        ]

        with patch(
            "query.chat.run_query",
        ) as normal_run_query:
            response, metadata, prepared = (
                run_changes_query(
                    "Focus on pricing.",
                    memories,
                    selected,
                    execution_profile="Balanced",
                )
            )

        normal_run_query.assert_not_called()
        ask_llm.assert_called_once()

        prompt = ask_llm.call_args.args[0]

        self.assertIn(
            "strict chronological comparison",
            prompt,
        )
        self.assertIn(
            "2026-09-08_previous",
            prompt,
        )
        self.assertIn(
            "2026-09-17_latest",
            prompt,
        )
        self.assertNotIn(
            "2026-09-01_old",
            prompt,
        )
        self.assertIn(
            "Focus on pricing.",
            prompt,
        )
        self.assertNotIn(
            "Grounded Open Questions",
            response,
        )
        self.assertNotIn(
            "Grounded Actions",
            response,
        )
        self.assertEqual(
            metadata["mode"],
            "direct",
        )
        self.assertEqual(
            metadata["inference_calls"],
            1,
        )
        self.assertEqual(
            prepared["previous_run"],
            "2026-09-08_previous",
        )
        self.assertEqual(
            prepared["latest_run"],
            "2026-09-17_latest",
        )


if __name__ == "__main__":
    unittest.main()
