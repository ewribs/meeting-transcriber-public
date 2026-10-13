import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai


class RuntimeSummaryIntegrationTests(unittest.TestCase):
    def test_test14_runtime_path_reconciles_memory_and_final_summary(self):
        transcript = (
            "we are going to move ahead with Orion we're going to let Pioneer down "
            "but let them know that we want them to re-engage in the next year "
            "and much later we decided as a team that pioneer timing is not right you know "
            "we definitely do want to re-engage them midterm in this 18 months "
            "on the document services work Beacon exceeded budget and Cedar was cheaper "
            "Casey said that was fine and gave me her blessing and we're going to cut Atlas loose from the list "
            "the Harbor amendment is still sitting in my inbox and I haven't looked at it "
            "Sentinel is mostly resolved but the WorkflowX administrative process is "
            "frustrating and a pain in the ass"
        )

        narrative_memory = {
            "topics": [
                {
                    "topic_key": "document_services_rfp",
                    "topic": "Document Services RFP Recommendation",
                    "status": "ongoing",
                    "summary": "Decision made to cut ties with Atlas for document services and move forward with Cedar as the preferred vendor.",
                },
                {
                    "topic_key": "vendor_beta_engagement",
                    "topic": "Pioneer Partnership Evaluation",
                    "status": "open",
                    "summary": (
                        "Engagement with Pioneer vendor may be revisited in the next 12 months. "
                        "No formal decision has been made, and further discussion is required."
                    ),
                },
                {
                    "topic_key": "colocation_contract",
                    "topic": "Harbor Contract and Invoicing",
                    "status": "closed",
                    "summary": "The Harbor amendment and invoicing issues had been resolved with minimal issues.",
                },
                {
                    "topic_key": "network_migration",
                    "topic": "Orion Migration Plan",
                    "status": "closed",
                    "summary": "The decision to move forward with the Orion migration plan was confirmed, with an 18-month agreement to lock in current rates.",
                },
                {
                    "topic_key": "device_procurement",
                    "topic": "Device Procurement",
                    "status": "ongoing",
                    "summary": "No decisions or action items identified, but work remains to finalize procurement.",
                },
            ],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
        }

        draft = """# Meeting Summary

## Executive Summary

The meeting did not result in any explicit decisions or action items. Vendor updates continued.

## Presentations and Updates

- JuniperX renewal update. - VaultX contract update. - Document services recommendation update with Beacon identified as the preferred option, though budget constraints and alternatives were noted.

## Key Themes and Takeaways

- Vendor alignment matters. - Contract clarity matters. - Budget constraints may limit options even though Beacon was identified as the preferred vendor.

## Decisions

None identified.

## Action Items

None identified.

## Open Questions

None identified.

## Topics

Old narrative topics.
"""

        # Simulate the real failure mode where structured extraction returns
        # malformed JSON. Deterministic explicit-decision recovery must still run.
        generic_rules = (
            ("document_services_rfp", ("document services", "beacon", "cedar")),
            ("vendor_beta_engagement", ("pioneer",)),
            ("colocation_contract", ("harbor", "colocation contract")),
            ("network_migration", ("orion",)),
            ("device_procurement", ("device procurement",)),
        )
        with patch("ai.TOPIC_NORMALIZATION_RULES", generic_rules), patch(
            "ai.build_meeting_memory", return_value=narrative_memory
        ), patch("ai.chunk_transcript", return_value=[transcript]), patch(
            "ai.ask_llm", return_value="{not valid json"
        ):
            memory = ai.build_complete_meeting_memory(
                meeting_label="TEST14",
                meeting_summary=draft,
                transcript=transcript,
                participants=[],
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            memory_path = run_dir / "meeting_memory.json"
            summary_path = run_dir / "meeting_summary.md"
            memory_path.write_text(json.dumps(memory, indent=2), encoding="utf-8")
            composed = ai.compose_summary_with_meeting_memory(draft, memory)
            summary_path.write_text(composed, encoding="utf-8")
            persisted = json.loads(memory_path.read_text(encoding="utf-8"))
            final_summary = summary_path.read_text(encoding="utf-8")

        decisions = [item["decision"] for item in persisted["decisions"]]
        self.assertEqual(sum("Orion" in item for item in decisions), 1, decisions)
        self.assertEqual(sum("Pioneer" in item for item in decisions), 1, decisions)
        self.assertTrue(any("Atlas" in item and "Drop" in item for item in decisions), decisions)
        self.assertFalse(any("timing is not right" in item.lower() for item in decisions), decisions)

        vendor_beta = next(item for item in persisted["topics"] if item["topic_key"] == "vendor_beta_engagement")
        self.assertNotIn("no formal decision", vendor_beta["summary"].lower())

        document_services = next(item for item in persisted["topics"] if item["topic_key"] == "document_services_rfp")
        self.assertNotIn("preferred vendor", document_services["summary"].lower())
        self.assertNotIn("move forward with cedar", document_services["summary"].lower())
        self.assertIn("cut ties with atlas", document_services["summary"].lower())
        self.assertTrue(document_services["summary"].strip())

        colocation = next(item for item in persisted["topics"] if item["topic_key"] == "colocation_contract")
        self.assertEqual(colocation["status"], "open")
        self.assertNotRegex(colocation["summary"].lower(), r"(?<!un)resolved")
        self.assertIn("unresolved", colocation["summary"].lower())

        network_topic = next(item for item in persisted["topics"] if item["topic_key"] == "network_migration")
        self.assertEqual(network_topic["status"], "ongoing")

        device = next(item for item in persisted["topics"] if item["topic_key"] == "device_procurement")
        self.assertNotIn("no decisions or action items identified", device["summary"].lower())

        self.assertNotIn("did not result in any explicit decisions", final_summary.lower())
        self.assertNotIn("beacon identified as the preferred", final_summary.lower())
        self.assertEqual(final_summary.count("## Topics"), 1)
        self.assertIn("Drop Atlas.", final_summary)
        self.assertIn("Move ahead with Orion and decline Pioneer for now.", final_summary)
        self.assertIn("- JuniperX renewal update.\n- VaultX contract update.", final_summary)
        self.assertIn("budget constraints and alternatives were noted", final_summary.lower())
        self.assertIn("- Vendor alignment matters.\n- Contract clarity matters.", final_summary)


    def test_test17_narrative_consistency_uses_authoritative_sections(self):
        draft = """# Meeting Summary

## Executive Summary

No confirmed decisions were made, and several action items were identified but lacked clear owners or due dates. Vendor work continued.

## Decisions

None identified.

## Action Items

None identified.

## Open Questions

None identified.

## Topics

Old narrative topics.
"""
        memory = {
            "topics": [],
            "commitments": [],
            "decisions": [
                {"decision": "Move ahead with Orion and decline Pioneer for now.", "evidence": "supported"},
                {"decision": "Drop Atlas.", "evidence": "supported"},
            ],
            "open_questions": [],
            "follow_ups": [],
        }

        composed = ai.compose_summary_with_meeting_memory(draft, memory)

        self.assertNotIn("no confirmed decisions were made", composed.lower())
        self.assertNotIn("action items were identified", composed.lower())
        self.assertIn("Vendor work continued.", composed)
        self.assertIn("Move ahead with Orion and decline Pioneer for now.", composed)
        self.assertIn("Drop Atlas.", composed)
        self.assertRegex(composed, r"## Action Items\s+None identified\.")

    def test_rhetorical_confirmation_question_is_not_authoritative(self):
        transcript = "there's a backup plan, right?"
        payload = json.dumps({
            "commitments": [],
            "decisions": [],
            "open_questions": [
                {"question": "there's a backup plan, right?", "evidence": "there's a backup plan, right?"}
            ],
            "follow_ups": [],
        })
        with patch("ai.chunk_transcript", return_value=[transcript]), patch("ai.ask_llm", return_value=payload):
            grounded = ai.extract_grounded_commitments_and_decisions(
                meeting_label="TEST15", transcript=transcript, participants=[]
            )
        self.assertEqual(grounded["open_questions"], [])


if __name__ == "__main__":
    unittest.main()
