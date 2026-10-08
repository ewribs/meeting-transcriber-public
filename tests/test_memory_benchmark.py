import json
import tempfile
import unittest
from pathlib import Path

from tools.benchmark.memory_benchmark import (
    discover_cases,
    init_case,
    score_memory,
)


class MemoryBenchmarkTests(unittest.TestCase):
    def test_scores_expected_action_and_rejects_extra_decision(self):
        memory = {
            "commitments": [
                {
                    "owner": "Speaker B",
                    "action": "Request renewal paperwork for four contracts",
                    "evidence": "I will request the paperwork",
                }
            ],
            "decisions": [
                {"decision": "Maybe prioritize the critical items"}
            ],
            "risks": [],
            "open_questions": [],
        }
        gold = {
            "expected": {
                "commitments": [
                    {
                        "owner": "Speaker B",
                        "text_contains_all": ["renewal", "four"],
                        "text_contains_any": ["paperwork", "quotes"],
                    }
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
            },
            "forbidden": {
                "owners": ["Remote", "Mic"],
                "decisions_text_contains_any": ["maybe"],
            },
        }
        score = score_memory(memory, gold)
        self.assertFalse(score["passed"])
        self.assertEqual(score["categories"]["commitments"]["recall"], 1.0)
        self.assertEqual(score["categories"]["decisions"]["precision"], 0.0)
        self.assertEqual(len(score["forbidden_violations"]), 1)


    def test_expected_terms_can_match_action_evidence_and_supporting_evidence(self):
        memory = {
            "commitments": [
                {
                    "owner": "Speaker B",
                    "action": "Reach out to Vendor Alpha",
                    "evidence": "I am going to ask for the paperwork for all four agreements",
                    "supporting_evidence": ["I will ask for all four quotes"],
                }
            ],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        gold = {
            "expected": {
                "commitments": [
                    {
                        "owner": "Speaker B",
                        "text_contains_all": ["four"],
                        "text_contains_any": ["paperwork", "quotes"],
                    }
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
            }
        }
        score = score_memory(memory, gold)
        self.assertTrue(score["passed"])
        self.assertEqual(score["categories"]["commitments"]["precision"], 1.0)
        self.assertEqual(score["categories"]["commitments"]["recall"], 1.0)

    def test_forbidden_channel_owner_fails_even_when_text_matches(self):
        memory = {
            "commitments": [
                {"owner": "Remote", "action": "Help escalate Vendor Alpha"}
            ],
            "decisions": [],
            "risks": [],
            "open_questions": [],
        }
        gold = {
            "expected": {
                "commitments": [
                    {"text_contains_all": ["escalate"]}
                ],
                "decisions": [],
                "risks": [],
                "open_questions": [],
            },
            "forbidden": {"owners": ["Remote", "Mic"]},
        }
        score = score_memory(memory, gold)
        self.assertFalse(score["passed"])
        self.assertEqual(score["categories"]["commitments"]["recall"], 1.0)
        self.assertEqual(score["forbidden_violations"][0]["type"], "forbidden_owner")

    def test_empty_expected_category_treats_prediction_as_false_positive(self):
        score = score_memory(
            {
                "commitments": [],
                "decisions": ["Adopt Platform Beta"],
                "risks": [],
                "open_questions": [],
            },
            {
                "expected": {
                    "commitments": [],
                    "decisions": [],
                    "risks": [],
                    "open_questions": [],
                }
            },
        )
        self.assertFalse(score["passed"])
        self.assertEqual(score["categories"]["decisions"]["precision"], 0.0)
        self.assertEqual(len(score["categories"]["decisions"]["unexpected"]), 1)

    def test_init_case_copies_only_source_artifacts_and_creates_gold_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            case_root = root / "private_benchmarks"
            source.mkdir()
            (source / "meeting_metadata.json").write_text(
                json.dumps({"display_title": "Speaker B 1v1", "participants": []}),
                encoding="utf-8",
            )
            (source / "meeting_summary.md").write_text("# Meeting Summary\n", encoding="utf-8")
            (source / "meeting_transcript_cleaned.md").write_text(
                "# Meeting Transcript\n\n[00:00] **Mic**\n\nHello.",
                encoding="utf-8",
            )
            destination = init_case(source, "speaker-b-1v1", case_root)
            self.assertTrue((destination / "expected_memory.json").exists())
            self.assertFalse((destination / "meeting_memory.json").exists())
            self.assertEqual(discover_cases(case_root), [destination])


if __name__ == "__main__":
    unittest.main()
