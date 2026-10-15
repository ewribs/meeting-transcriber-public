import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend_bridge
from meeting_selector import select_meetings
from session_criteria_ui import criteria_present
from session_rules import normalize_rules, saved_rules, with_rules


def make_meeting(output, run, title, people, topics=(), day="2026-09-14"):
    run_dir = output / run
    run_dir.mkdir(parents=True)
    (run_dir / "meeting_metadata.json").write_text(
        json.dumps(
            {
                "meeting_run": run,
                "meeting_datetime": f"{day}T08:00:00",
                "display_title": title,
                "participants": [{"name": p} for p in people],
            }
        )
    )
    (run_dir / "meeting_memory.json").write_text(
        json.dumps({"topics": [{"topic": t, "summary": ""} for t in topics]})
    )


class MatchModeSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.archive = root / "archive"
        self.output = root / "output"
        self.archive.mkdir()
        self.output.mkdir()
        make_meeting(self.output, "r1", "Weekly Sync", ["Pat"], ["budget"], "2026-09-10")
        make_meeting(self.output, "r2", "Review", ["Sam"], ["hiring"], "2026-09-11")
        make_meeting(self.output, "r3", "Weekly Review", ["Pat", "Sam"], [], "2026-09-12")
        make_meeting(self.output, "r4", "Offsite", ["Lee"], ["budget"], "2026-09-13")

    def tearDown(self):
        self.tmp.cleanup()

    def runs(self, **kwargs):
        found = select_meetings(
            archive_dir=self.archive, output_dir=self.output, **kwargs
        )
        return [m["meeting_run"] for m in found]

    def test_default_is_all_rules_must_hold(self):
        self.assertEqual(self.runs(title="offsite", people=["Pat"]), [])

    def test_explicit_all_matches_default(self):
        self.assertEqual(
            self.runs(title="offsite", people=["Pat"], match="all"), []
        )

    def test_any_title_or_people(self):
        self.assertEqual(
            self.runs(title="offsite", people=["Pat"], match="any"),
            ["r1", "r3", "r4"],
        )

    def test_any_topic_or_person(self):
        self.assertEqual(
            self.runs(topic="hiring", person="Lee", match="any"),
            ["r2", "r4"],
        )

    def test_any_is_case_insensitive(self):
        self.assertEqual(
            self.runs(title="offsite", people=["Pat"], match="ANY"),
            ["r1", "r3", "r4"],
        )

    def test_any_still_applies_excludes(self):
        self.assertEqual(
            self.runs(
                title="review",
                people=["Lee"],
                exclude_title="weekly",
                match="any",
            ),
            ["r2", "r4"],
        )

    def test_any_still_applies_the_date_window(self):
        self.assertEqual(
            self.runs(
                title="weekly",
                people=["Lee"],
                start_date="2026-09-12",
                match="any",
            ),
            ["r3", "r4"],
        )

    def test_any_with_no_content_rules_returns_everything(self):
        self.assertEqual(
            self.runs(match="any"), ["r1", "r2", "r3", "r4"]
        )

    def test_any_with_only_excludes_keeps_the_rest(self):
        self.assertEqual(
            self.runs(exclude_title="weekly", match="any"),
            ["r2", "r4"],
        )


class MatchModeRuleTests(unittest.TestCase):
    def test_any_is_kept_and_normalised(self):
        self.assertEqual(normalize_rules({"match": " ANY "}), {"match": "any"})

    def test_all_and_junk_are_dropped(self):
        self.assertEqual(normalize_rules({"match": "all"}), {})
        self.assertEqual(normalize_rules({"match": "either"}), {})

    def test_match_is_saved_and_replaced_with_other_rules(self):
        merged = with_rules({"title": "x", "match": "any"}, {"people": ["B"]})
        self.assertEqual(merged, {"title": "x", "people": ["B"]})
        self.assertEqual(
            saved_rules({"match": "any", "person": "A"}), {"match": "any"}
        )

    def test_match_alone_is_not_a_criterion(self):
        self.assertFalse(criteria_present({"match": "any"}))


class MatchModeBridgeTests(unittest.TestCase):
    def test_new_session_payload_defaults_to_all(self):
        payload = backend_bridge.session_editor_payload("")
        self.assertEqual(payload["match"], "all")

    def test_edit_payload_reports_saved_match(self):
        session = {"selection_criteria": {"title": "x", "match": "any"}}
        with mock.patch(
            "query.sessions.load_chat_session", return_value=session
        ):
            payload = backend_bridge.session_editor_payload("S")
        self.assertEqual(payload["match"], "any")

    def test_edit_payload_defaults_to_all(self):
        session = {"selection_criteria": {"title": "x"}}
        with mock.patch(
            "query.sessions.load_chat_session", return_value=session
        ):
            payload = backend_bridge.session_editor_payload("S")
        self.assertEqual(payload["match"], "all")

    def test_session_selection_passes_match_through(self):
        from query.session_context import select_session_meetings

        with mock.patch(
            "query.session_context.select_meetings", return_value=[]
        ) as sel:
            select_session_meetings({"title": "x", "match": "any"})
        self.assertEqual(sel.call_args.kwargs["match"], "any")


if __name__ == "__main__":
    unittest.main()
