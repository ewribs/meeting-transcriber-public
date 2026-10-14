import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import backend_bridge
from meeting_selector import select_meetings
from session_criteria_ui import DEFAULT_HISTORY_LABEL, criteria_present
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


class SelectorRuleTests(unittest.TestCase):
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

    def test_no_rules_returns_everything(self):
        self.assertEqual(self.runs(), ["r1", "r2", "r3", "r4"])

    def test_people_matches_any_of(self):
        self.assertEqual(self.runs(people=["pat", "LEE"]), ["r1", "r3", "r4"])

    def test_person_and_people_must_both_hold(self):
        self.assertEqual(self.runs(person="Pat", people=["Sam"]), ["r3"])

    def test_status_filters(self):
        self.assertEqual(self.runs(status="Unpublished"), ["r1", "r2", "r3", "r4"])
        self.assertEqual(self.runs(status="published"), [])

    def test_exclude_title(self):
        self.assertEqual(self.runs(title="review", exclude_title="weekly"), ["r2"])

    def test_exclude_topic_keeps_meetings_without_topics(self):
        self.assertEqual(self.runs(exclude_topic="budget"), ["r2", "r3"])

    def test_topic_still_requires_a_match(self):
        self.assertEqual(self.runs(topic="budget"), ["r1", "r4"])


class RuleHelperTests(unittest.TestCase):
    def test_default_window_is_all_history(self):
        self.assertEqual(DEFAULT_HISTORY_LABEL, "All history")

    def test_normalize_rules_cleans_values(self):
        rules = normalize_rules(
            {
                "people": " Pat, Sam ,Pat,",
                "status": "PUBLISHED",
                "exclude_title": "  x ",
                "exclude_topic": "  ",
            }
        )
        self.assertEqual(
            rules,
            {"people": ["Pat", "Sam"], "status": "Published", "exclude_title": "x"},
        )

    def test_invalid_status_is_dropped(self):
        self.assertEqual(normalize_rules({"status": "draft"}), {})

    def test_new_rules_count_as_criteria(self):
        self.assertTrue(criteria_present({"people": ["Pat"]}))
        self.assertFalse(criteria_present({"history_days": None}))

    def test_with_rules_replaces_old_rules(self):
        merged = with_rules({"person": "A", "status": "Published"}, {"people": ["B"]})
        self.assertEqual(merged, {"person": "A", "people": ["B"]})

    def test_saved_rules_reads_only_rule_keys(self):
        self.assertEqual(
            saved_rules({"person": "A", "exclude_topic": "x"}),
            {"exclude_topic": "x"},
        )


class BridgeTests(unittest.TestCase):
    def test_preview_without_criteria_does_not_search(self):
        with mock.patch("query.session_context.select_session_meetings") as sel:
            payload = backend_bridge.preview_criteria_payload("", "", "", "All history")
        sel.assert_not_called()
        self.assertFalse(payload["has_criteria"])

    def test_preview_reports_count_and_newest_first(self):
        found = [
            {"meeting_run": f"r{i}", "display_title": f"M{i}", "participants": ["Pat"]}
            for i in range(10)
        ]
        with mock.patch(
            "query.session_context.select_session_meetings", return_value=found
        ) as sel:
            payload = backend_bridge.preview_criteria_payload(
                "", "", "", "All history", json.dumps({"people": "Pat, Sam"})
            )
        self.assertEqual(sel.call_args[0][0]["people"], ["Pat", "Sam"])
        self.assertEqual(payload["match_count"], 10)
        self.assertEqual(len(payload["meetings"]), 8)
        self.assertEqual(payload["meetings"][0]["run"], "r9")

    def test_bad_rules_json_is_rejected(self):
        with self.assertRaises(ValueError):
            backend_bridge.preview_criteria_payload("", "", "", "All history", "[1]")
        with self.assertRaises(ValueError):
            backend_bridge.preview_criteria_payload("", "", "", "All history", "{nope")

    def test_membership_add_and_remove_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            for run in ("a", "b", "c"):
                (archive / run).mkdir()
                (archive / run / "meeting_memory.json").write_text("{}")
            with mock.patch("config.ARCHIVE_DIR", archive), mock.patch(
                "query.sessions.ARCHIVE_DIR", archive
            ):
                from query.sessions import load_chat_session, save_chat_session

                save_chat_session(
                    "S", [archive / "a"], [{"role": "user", "content": "q"}], None
                )
                added = backend_bridge.add_session_meetings_payload(
                    "S", json.dumps(["b", "c"])
                )
                self.assertEqual((added["result"], added["meeting_count"]), ("added", 3))
                again = backend_bridge.add_session_meetings_payload(
                    "S", json.dumps(["b"])
                )
                self.assertEqual(again["result"], "already_current")
                removed = backend_bridge.remove_session_meetings_payload(
                    "S", json.dumps(["a"])
                )
                self.assertEqual((removed["result"], removed["meeting_count"]), ("removed", 2))
                session = load_chat_session("S")
                self.assertEqual(session["meeting_runs"], ["b", "c"])
                self.assertEqual(
                    session["conversation_history"],
                    [{"role": "user", "content": "q"}],
                )

    def test_add_refuses_unpublished(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp)
            (archive / "a").mkdir()
            (archive / "a" / "meeting_memory.json").write_text("{}")
            with mock.patch("config.ARCHIVE_DIR", archive), mock.patch(
                "query.sessions.ARCHIVE_DIR", archive
            ):
                from query.sessions import save_chat_session

                save_chat_session("S", [archive / "a"], [], None)
                with self.assertRaises(ValueError):
                    backend_bridge.add_session_meetings_payload(
                        "S", json.dumps(["not-archived"])
                    )

    def test_edit_keeps_saved_rules_unless_replaced(self):
        saved = {}

        def fake_save(name, dirs, history, criteria):
            saved["criteria"] = criteria

        session = {
            "meeting_runs": ["a"],
            "conversation_history": [],
            "selection_criteria": {
                "person": None,
                "title": "x",
                "history_days": None,
                "people": ["Pat"],
                "status": "Published",
            },
        }
        found = [{"meeting_run": "a", "meeting_dir": "/tmp/a"}]
        with mock.patch("query.sessions.load_chat_session", return_value=session), mock.patch(
            "query.sessions.save_chat_session", fake_save
        ), mock.patch(
            "query.session_context.select_session_meetings", return_value=found
        ):
            backend_bridge.edit_dynamic_session_payload("S", "", "x", "", "All history")
            self.assertEqual(saved["criteria"]["people"], ["Pat"])
            self.assertEqual(saved["criteria"]["status"], "Published")

            backend_bridge.edit_dynamic_session_payload(
                "S", "", "x", "", "All history", "{}"
            )
            self.assertNotIn("people", saved["criteria"])


if __name__ == "__main__":
    unittest.main()


class DisplayAndEditorTests(unittest.TestCase):
    def test_criteria_lines_include_new_rules(self):
        from session_browser import format_session_criteria

        lines = format_session_criteria(
            {
                "people": ["Pat", "Sam"],
                "status": "Published",
                "exclude_title": "x",
                "exclude_topic": "y",
            }
        )
        self.assertIn("Person is any of: Pat, Sam", lines)
        self.assertIn("Status: Published", lines)
        self.assertIn("Title does not contain: x", lines)
        self.assertIn("Topic does not contain: y", lines)

    def test_blank_editor_has_empty_rule_fields(self):
        payload = backend_bridge.session_editor_payload()
        self.assertEqual(payload["people"], [])
        self.assertEqual(payload["status"], "")
        self.assertEqual(payload["selected_history_label"], "All history")

    def test_edit_editor_returns_saved_rules(self):
        session = {
            "selection_criteria": {
                "title": "x",
                "people": ["Pat"],
                "status": "Published",
                "exclude_topic": "y",
                "history_days": 30,
            }
        }
        with mock.patch("query.sessions.load_chat_session", return_value=session):
            payload = backend_bridge.session_editor_payload("S")
        self.assertEqual(payload["people"], ["Pat"])
        self.assertEqual(payload["status"], "Published")
        self.assertEqual(payload["exclude_topic"], "y")
        self.assertEqual(payload["exclude_title"], "")


class PublishedOnlyTests(unittest.TestCase):
    def test_dynamic_selection_is_always_published_only(self):
        from query.session_context import select_session_meetings

        with mock.patch("query.session_context.select_meetings", return_value=[]) as sel:
            select_session_meetings({"title": "x"})
            select_session_meetings({"title": "x", "status": "Unpublished"})
        for call in sel.call_args_list:
            self.assertEqual(call.kwargs["status"], "Published")
