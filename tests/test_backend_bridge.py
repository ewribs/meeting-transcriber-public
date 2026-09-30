import json
import sys
from pathlib import Path
import types
import unittest
from unittest.mock import patch

import backend_bridge


class BackendBridgeTests(unittest.TestCase):
    def test_normalize_current_catalog_shape(self):
        meeting = {
            "meeting_run": "2026-09-15_1127_PipelineUpdateTaylor091526",
            "display_title": "Pipeline Update Taylor",
            "meeting_datetime": "2026-09-15T11:27:00",
            "publish_status": "Unpublished",
            "is_published": False,
            "participants": ["Alex", " alex ", "Jordan", ""],
        }

        normalized = backend_bridge.normalize_meeting(
            meeting
        )

        self.assertEqual(
            normalized["id"],
            "2026-09-15_1127_PipelineUpdateTaylor091526",
        )
        self.assertEqual(
            normalized["status"],
            "Unpublished",
        )
        self.assertFalse(
            normalized["is_published"]
        )
        self.assertTrue(
            normalized["can_publish"]
        )
        self.assertEqual(
            normalized["participants"],
            ["Alex", "Jordan"],
        )

    @patch("backend_bridge.load_meeting_catalog")
    def test_meetings_payload_is_lightweight(
        self,
        mock_load,
    ):
        mock_load.return_value = [
            {
                "meeting_run": "run-1",
                "display_title": "One",
                "meeting_datetime": "2026-09-15T08:00:00",
                "publish_status": "Published",
            }
        ]

        payload = backend_bridge.meetings_payload()

        self.assertEqual(
            payload["schema_version"],
            4,
        )
        self.assertEqual(
            payload["meetings"][0]["id"],
            "run-1",
        )
        self.assertNotIn(
            "summary",
            payload["meetings"][0],
        )
        self.assertNotIn(
            "topics",
            payload["meetings"][0],
        )

    @patch("meeting_detail_service.load_meeting_detail")
    @patch("backend_bridge.load_meeting_catalog")
    def test_meeting_detail_loads_only_selected_run(
        self,
        mock_catalog,
        mock_detail,
    ):
        mock_catalog.return_value = [
            {
                "meeting_run": "run-1",
                "location": "/tmp/one",
            },
            {
                "meeting_run": "run-2",
                "location": "/tmp/two",
            },
        ]

        mock_detail.return_value = {
            "summary": "Selected summary",
            "topics": [
                {
                    "name": "Cloud Provider A",
                    "status": "active",
                    "summary": "Strategy",
                }
            ],
            "has_summary": True,
            "has_memory": True,
        }

        payload = backend_bridge.meeting_detail_payload(
            "run-2"
        )

        self.assertEqual(
            payload["run"],
            "run-2",
        )
        self.assertEqual(
            payload["summary"],
            "Selected summary",
        )
        self.assertEqual(
            payload["schema_version"],
            6,
        )
        self.assertEqual(payload["decisions"], [])
        self.assertEqual(payload["commitments"], [])
        self.assertEqual(payload["open_questions"], [])
        self.assertEqual(payload["follow_ups"], [])
        mock_detail.assert_called_once_with(
            mock_catalog.return_value[1]
        )

    @patch("backend_bridge.load_meeting_catalog")
    def test_missing_detail_run_errors(
        self,
        mock_catalog,
    ):
        mock_catalog.return_value = []

        with self.assertRaises(ValueError):
            backend_bridge.meeting_detail_payload(
                "missing"
            )


    @patch("backend_bridge.load_meeting_catalog")
    def test_publish_meeting_uses_existing_workflow(
        self,
        mock_catalog,
    ):
        mock_catalog.return_value = [
            {
                "meeting_run": "run-1",
                "publish_status": "Unpublished",
                "location": "/tmp/run-1",
            }
        ]

        fake_module = types.ModuleType(
            "publish_workflow"
        )
        calls = []

        def fake_publish(path):
            calls.append(path)
            return {
                "archived_path": "/archive/run-1",
            }

        fake_module.publish_and_archive_meeting = (
            fake_publish
        )

        with patch.dict(
            sys.modules,
            {"publish_workflow": fake_module},
        ):
            payload = (
                backend_bridge.publish_meeting_payload(
                    "run-1"
                )
            )

        self.assertEqual(
            str(calls[0]),
            "/tmp/run-1",
        )
        self.assertEqual(
            payload["status"],
            "Published",
        )
        self.assertEqual(
            payload["archived_path"],
            "/archive/run-1",
        )

    @patch("backend_bridge.load_meeting_catalog")
    def test_publish_rejects_already_published(
        self,
        mock_catalog,
    ):
        mock_catalog.return_value = [
            {
                "meeting_run": "run-1",
                "publish_status": "Published",
                "location": "/archive/run-1",
            }
        ]

        with self.assertRaises(ValueError):
            backend_bridge.publish_meeting_payload(
                "run-1"
            )



    @patch("backend_bridge.load_meeting_catalog")
    def test_publish_dry_run_does_not_import_workflow(
        self,
        mock_catalog,
    ):
        mock_catalog.return_value = [
            {
                "meeting_run": "run-1",
                "publish_status": "Unpublished",
                "location": "/tmp/run-1",
            }
        ]

        with patch.dict(
            sys.modules,
            {"publish_workflow": None},
        ):
            payload = (
                backend_bridge.publish_meeting_payload(
                    "run-1",
                    dry_run=True,
                )
            )

        self.assertTrue(
            payload["dry_run"]
        )
        self.assertTrue(
            payload["would_publish"]
        )
        self.assertEqual(
            payload["current_status"],
            "Unpublished",
        )
        self.assertEqual(
            payload["location"],
            "/tmp/run-1",
        )

    @patch("backend_bridge.load_meeting_catalog")
    def test_publish_dry_run_reports_already_published(
        self,
        mock_catalog,
    ):
        mock_catalog.return_value = [
            {
                "meeting_run": "run-1",
                "publish_status": "Published",
                "location": "/archive/run-1",
            }
        ]

        payload = (
            backend_bridge.publish_meeting_payload(
                "run-1",
                dry_run=True,
            )
        )

        self.assertTrue(
            payload["dry_run"]
        )
        self.assertFalse(
            payload["would_publish"]
        )
        self.assertEqual(
            payload["current_status"],
            "Published",
        )


    def test_sessions_payload_reuses_session_browser_services(
        self,
    ):
        import tempfile
        from dataclasses import dataclass

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)
            sessions_dir = archive_dir / "query_sessions"
            sessions_dir.mkdir()

            fixed_path = sessions_dir / "Fixed Session.json"
            fixed_path.write_text(
                json.dumps(
                    {
                        "selection_criteria": None,
                    }
                ),
                encoding="utf-8",
            )

            dynamic_path = sessions_dir / "Dynamic Session.json"
            dynamic_path.write_text(
                json.dumps(
                    {
                        "selection_criteria": {
                            "person": "Alex",
                            "history_days": 90,
                        }
                    }
                ),
                encoding="utf-8",
            )

            @dataclass(frozen=True)
            class FakeEntry:
                name: str
                label: str
                tooltip: str
                path: Path
                session_type: str
                meeting_count: int
                turn_count: int

            fake_config = types.ModuleType("config")
            fake_config.ARCHIVE_DIR = archive_dir

            fake_browser = types.ModuleType(
                "session_browser"
            )

            def fake_load(path):
                self.assertEqual(
                    path,
                    sessions_dir,
                )
                return [
                    FakeEntry(
                        name="Fixed Session",
                        label="Fixed Session",
                        tooltip="Fixed • 3 meetings • 4 turns",
                        path=fixed_path,
                        session_type="Fixed",
                        meeting_count=3,
                        turn_count=4,
                    ),
                    FakeEntry(
                        name="Dynamic Session",
                        label="Dynamic Session",
                        tooltip="Dynamic • 5 meetings • 2 turns",
                        path=dynamic_path,
                        session_type="Dynamic",
                        meeting_count=5,
                        turn_count=2,
                    ),
                ]

            def fake_format(criteria):
                if not criteria:
                    return []
                return [
                    "CRITERIA",
                    "--------",
                    "Person: Alex",
                    "History: Last 90 days",
                ]

            fake_browser.load_session_browser_entries = (
                fake_load
            )
            fake_browser.format_session_criteria = (
                fake_format
            )

            with patch.dict(
                sys.modules,
                {
                    "config": fake_config,
                    "session_browser": fake_browser,
                },
            ):
                payload = (
                    backend_bridge.sessions_payload()
                )

            self.assertEqual(
                payload["schema_version"],
                5,
            )
            self.assertEqual(
                len(payload["sessions"]),
                2,
            )
            self.assertEqual(
                payload["sessions"][0]["session_type"],
                "Fixed",
            )
            self.assertEqual(
                payload["sessions"][1]["criteria"],
                [
                    "Person: Alex",
                    "History: Last 90 days",
                ],
            )
            self.assertEqual(
                payload["sessions"][1]["turn_count"],
                2,
            )

    def test_sessions_payload_tolerates_invalid_session_json(
        self,
    ):
        import tempfile
        from dataclasses import dataclass

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)
            sessions_dir = archive_dir / "query_sessions"
            sessions_dir.mkdir()

            session_path = sessions_dir / "Broken.json"
            session_path.write_text(
                "{bad json",
                encoding="utf-8",
            )

            @dataclass(frozen=True)
            class FakeEntry:
                name: str
                label: str
                tooltip: str
                path: Path
                session_type: str
                meeting_count: int
                turn_count: int

            fake_config = types.ModuleType("config")
            fake_config.ARCHIVE_DIR = archive_dir

            fake_browser = types.ModuleType(
                "session_browser"
            )
            fake_browser.load_session_browser_entries = (
                lambda path: [
                    FakeEntry(
                        name="Broken",
                        label="Broken",
                        tooltip="Fixed",
                        path=session_path,
                        session_type="Fixed",
                        meeting_count=1,
                        turn_count=0,
                    )
                ]
            )
            fake_browser.format_session_criteria = (
                lambda criteria: []
            )

            with patch.dict(
                sys.modules,
                {
                    "config": fake_config,
                    "session_browser": fake_browser,
                },
            ):
                payload = (
                    backend_bridge.sessions_payload()
                )

            self.assertEqual(
                payload["sessions"][0]["criteria"],
                [],
            )


    def test_refresh_session_reuses_existing_services(self):
        from dataclasses import dataclass

        fake_query_sessions = types.ModuleType("query.sessions")
        fake_context = types.ModuleType("context_service")
        fake_actions = types.ModuleType("session_actions")

        session = {
            "meeting_runs": ["old-a", "old-b"],
            "conversation_history": [
                {"role": "user", "content": "hello"}
            ],
            "selection_criteria": {"person": "Alex"},
        }

        calls = {}

        def fake_load(name):
            calls["load_name"] = name
            return session

        def fake_resume(loaded_session, refresh=False):
            calls["resume_session"] = loaded_session
            calls["refresh"] = refresh
            return {
                "meeting_dirs": [
                    Path("/tmp/a"),
                    Path("/tmp/b"),
                    Path("/tmp/c"),
                ],
                "refresh_summary": {
                    "added": 1,
                    "removed": 0,
                    "unchanged": 2,
                },
            }

        def fake_save(*args):
            calls["save_args"] = args

        @dataclass(frozen=True)
        class Summary:
            added: int
            removed: int
            unchanged: int
            meeting_count: int

        class SessionAlreadyCurrent(Exception):
            def __init__(self, unchanged):
                super().__init__("Session already current")
                self.unchanged = unchanged

        def fake_refresh_action(
            *,
            session_name,
            session,
            resume_session,
            save_session,
        ):
            resumed = resume_session(
                session,
                refresh=True,
            )
            save_session(
                session_name,
                resumed["meeting_dirs"],
                list(session.get("conversation_history", [])),
                session.get("selection_criteria"),
            )
            return Summary(
                added=1,
                removed=0,
                unchanged=2,
                meeting_count=3,
            )

        fake_query_sessions.load_chat_session = fake_load
        fake_query_sessions.save_chat_session = fake_save
        fake_context.resume_saved_session = fake_resume
        fake_actions.refresh_dynamic_session = fake_refresh_action
        fake_actions.SessionAlreadyCurrent = SessionAlreadyCurrent

        with patch.dict(
            sys.modules,
            {
                "query.sessions": fake_query_sessions,
                "context_service": fake_context,
                "session_actions": fake_actions,
            },
        ):
            payload = backend_bridge.refresh_session_payload(
                "Alex 1v1s"
            )

        self.assertEqual(calls["load_name"], "Alex 1v1s")
        self.assertTrue(calls["refresh"])
        self.assertEqual(payload["result"], "refreshed")
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["removed"], 0)
        self.assertEqual(payload["unchanged"], 2)
        self.assertEqual(payload["meeting_count"], 3)
        self.assertEqual(
            calls["save_args"][2],
            session["conversation_history"],
        )

    def test_refresh_session_reports_already_current(self):
        fake_query_sessions = types.ModuleType("query.sessions")
        fake_context = types.ModuleType("context_service")
        fake_actions = types.ModuleType("session_actions")

        session = {
            "meeting_runs": ["a", "b", "c"],
            "selection_criteria": {"person": "Alex"},
        }

        fake_query_sessions.load_chat_session = lambda name: session
        fake_query_sessions.save_chat_session = lambda *args: None
        fake_context.resume_saved_session = lambda *args, **kwargs: {}

        class SessionAlreadyCurrent(Exception):
            def __init__(self, unchanged):
                super().__init__("Session already current")
                self.unchanged = unchanged

        def fake_refresh_action(**kwargs):
            raise SessionAlreadyCurrent(3)

        fake_actions.refresh_dynamic_session = fake_refresh_action
        fake_actions.SessionAlreadyCurrent = SessionAlreadyCurrent

        with patch.dict(
            sys.modules,
            {
                "query.sessions": fake_query_sessions,
                "context_service": fake_context,
                "session_actions": fake_actions,
            },
        ):
            payload = backend_bridge.refresh_session_payload(
                "Alex 1v1s"
            )

        self.assertEqual(
            payload["result"],
            "already_current",
        )
        self.assertEqual(payload["unchanged"], 3)
        self.assertEqual(payload["meeting_count"], 3)


    def test_rename_session_reuses_existing_action(self):
        fake_config = types.ModuleType("config")
        fake_query_sessions = types.ModuleType(
            "query.sessions"
        )
        fake_actions = types.ModuleType(
            "session_actions"
        )

        fake_config.ARCHIVE_DIR = Path("/archive")
        calls = {}

        def fake_rename_chat_session(old, new):
            calls["rename_pair"] = (old, new)

        def fake_rename_session(
            *,
            old_name,
            new_name,
            sessions_dir,
            rename,
        ):
            calls["old_name"] = old_name
            calls["new_name"] = new_name
            calls["sessions_dir"] = sessions_dir
            rename(old_name, new_name)
            return new_name.strip()

        fake_query_sessions.rename_chat_session = (
            fake_rename_chat_session
        )
        fake_actions.rename_session = (
            fake_rename_session
        )

        with patch.dict(
            sys.modules,
            {
                "config": fake_config,
                "query.sessions":
                    fake_query_sessions,
                "session_actions":
                    fake_actions,
            },
        ):
            payload = (
                backend_bridge.rename_session_payload(
                    "Old Session",
                    "New Session",
                )
            )

        self.assertEqual(
            calls["sessions_dir"],
            Path("/archive/query_sessions"),
        )
        self.assertEqual(
            calls["rename_pair"],
            ("Old Session", "New Session"),
        )
        self.assertEqual(
            payload["new_name"],
            "New Session",
        )
        self.assertTrue(payload["renamed"])

    def test_rename_session_noop_returns_unchanged(self):
        fake_config = types.ModuleType("config")
        fake_query_sessions = types.ModuleType(
            "query.sessions"
        )
        fake_actions = types.ModuleType(
            "session_actions"
        )

        fake_config.ARCHIVE_DIR = Path("/archive")
        fake_query_sessions.rename_chat_session = (
            lambda old, new: None
        )
        fake_actions.rename_session = (
            lambda **kwargs: "Same Name"
        )

        with patch.dict(
            sys.modules,
            {
                "config": fake_config,
                "query.sessions":
                    fake_query_sessions,
                "session_actions":
                    fake_actions,
            },
        ):
            payload = (
                backend_bridge.rename_session_payload(
                    "Same Name",
                    "Same Name",
                )
            )

        self.assertFalse(payload["renamed"])
        self.assertEqual(
            payload["new_name"],
            "Same Name",
        )


    def test_delete_session_reuses_existing_services(self):
        fake_query_sessions = types.ModuleType("query.sessions")
        fake_actions = types.ModuleType("session_actions")

        calls = {}

        def fake_delete_chat_session(name):
            calls["delete_name"] = name

        def fake_delete_session(*, session_name, delete):
            calls["action_name"] = session_name
            delete(session_name)

        fake_query_sessions.delete_chat_session = (
            fake_delete_chat_session
        )
        fake_actions.delete_session = (
            fake_delete_session
        )

        with patch.dict(
            sys.modules,
            {
                "query.sessions":
                    fake_query_sessions,
                "session_actions":
                    fake_actions,
            },
        ):
            payload = (
                backend_bridge.delete_session_payload(
                    "Jordan-test"
                )
            )

        self.assertEqual(
            calls["action_name"],
            "Jordan-test",
        )
        self.assertEqual(
            calls["delete_name"],
            "Jordan-test",
        )
        self.assertTrue(
            payload["deleted"]
        )
        self.assertEqual(
            payload["session_name"],
            "Jordan-test",
        )


    def test_session_editor_create_uses_shared_options(self):
        fake_ui = types.ModuleType("session_criteria_ui")
        fake_ui.DEFAULT_HISTORY_LABEL = "All history"
        fake_ui.HISTORY_OPTIONS = (
            "Last 30 days",
            "Last 90 days",
            "Last 180 days",
            "All history",
        )
        fake_ui.edit_history_state = lambda criteria: (
            list(fake_ui.HISTORY_OPTIONS),
            "All history",
            None,
        )

        with patch.dict(
            sys.modules,
            {"session_criteria_ui": fake_ui},
        ):
            payload = (
                backend_bridge.session_editor_payload()
            )

        self.assertEqual(payload["mode"], "create")
        self.assertEqual(
            payload["selected_history_label"],
            "All history",
        )
        self.assertEqual(
            payload["history_options"],
            list(fake_ui.HISTORY_OPTIONS),
        )

    def test_session_editor_edit_preserves_legacy_range_option(self):
        fake_ui = types.ModuleType("session_criteria_ui")
        fake_sessions = types.ModuleType("query.sessions")

        fake_ui.DEFAULT_HISTORY_LABEL = "All history"
        fake_ui.HISTORY_OPTIONS = (
            "Last 30 days",
            "Last 90 days",
            "Last 180 days",
            "All history",
        )
        fake_ui.edit_history_state = lambda criteria: (
            [
                *fake_ui.HISTORY_OPTIONS,
                "Jan 1, 2025 – Jan 31, 2025",
            ],
            "Jan 1, 2025 – Jan 31, 2025",
            "Jan 1, 2025 – Jan 31, 2025",
        )
        fake_sessions.load_chat_session = lambda name: {
            "selection_criteria": {
                "person": "Alex",
                "title": "1v1",
                "topic": None,
                "history_days": None,
                "start_date": "2025-01-01",
                "end_date": "2025-01-31",
            }
        }

        with patch.dict(
            sys.modules,
            {
                "session_criteria_ui": fake_ui,
                "query.sessions": fake_sessions,
            },
        ):
            payload = (
                backend_bridge.session_editor_payload(
                    "Alex 1v1s"
                )
            )

        self.assertEqual(payload["mode"], "edit")
        self.assertEqual(payload["person"], "Alex")
        self.assertEqual(payload["title"], "1v1")
        self.assertEqual(
            payload["custom_range_label"],
            "Jan 1, 2025 – Jan 31, 2025",
        )

    def test_create_dynamic_session_reuses_existing_services(self):
        from dataclasses import dataclass

        fake_config = types.ModuleType("config")
        fake_context = types.ModuleType("query.session_context")
        fake_sessions = types.ModuleType("query.sessions")
        fake_actions = types.ModuleType("session_actions")
        fake_ui = types.ModuleType("session_criteria_ui")

        fake_config.ARCHIVE_DIR = Path("/archive")
        calls = {}

        criteria = {
            "person": "Alex",
            "title": "1v1",
            "topic": None,
            "history_days": 30,
            "start_date": None,
            "end_date": None,
        }

        fake_ui.build_create_criteria = (
            lambda **kwargs: criteria
        )
        fake_ui.criteria_present = lambda value: True
        fake_context.select_session_meetings = object()

        def fake_save(*args):
            calls["save_args"] = args

        fake_sessions.save_chat_session = fake_save

        class CriteriaRequiredError(Exception):
            pass

        @dataclass(frozen=True)
        class Summary:
            added: int
            removed: int
            unchanged: int
            meeting_count: int

        def fake_create(**kwargs):
            calls["create"] = kwargs
            return Summary(4, 0, 0, 4)

        fake_actions.CriteriaRequiredError = (
            CriteriaRequiredError
        )
        fake_actions.create_dynamic_session = (
            fake_create
        )

        with patch.dict(
            sys.modules,
            {
                "config": fake_config,
                "query.session_context": fake_context,
                "query.sessions": fake_sessions,
                "session_actions": fake_actions,
                "session_criteria_ui": fake_ui,
            },
        ):
            payload = (
                backend_bridge.create_dynamic_session_payload(
                    "Alex 1v1s",
                    "Alex",
                    "1v1",
                    "",
                    "Last 30 days",
                )
            )

        self.assertEqual(
            calls["create"]["sessions_dir"],
            Path("/archive/query_sessions"),
        )
        self.assertIs(
            calls["create"]["select_meetings"],
            fake_context.select_session_meetings,
        )
        self.assertIs(
            calls["create"]["save_session"],
            fake_save,
        )
        self.assertEqual(payload["meeting_count"], 4)

    def test_edit_dynamic_session_preserves_conversation_via_action(self):
        from dataclasses import dataclass

        fake_context = types.ModuleType("query.session_context")
        fake_sessions = types.ModuleType("query.sessions")
        fake_actions = types.ModuleType("session_actions")
        fake_ui = types.ModuleType("session_criteria_ui")

        session = {
            "selection_criteria": {
                "person": "Alex",
                "history_days": 30,
                "start_date": None,
                "end_date": None,
            },
            "conversation_history": [
                {"role": "user", "content": "hello"}
            ],
        }
        calls = {}

        fake_sessions.load_chat_session = (
            lambda name: session
        )
        fake_sessions.save_chat_session = object()
        fake_context.select_session_meetings = object()

        fake_ui.edit_history_state = lambda criteria: (
            [
                "Last 30 days",
                "Last 90 days",
                "Last 180 days",
                "All history",
            ],
            "Last 30 days",
            None,
        )
        fake_ui.build_edit_criteria = (
            lambda **kwargs: {
                "person": "Alex",
                "title": "pipeline",
                "topic": None,
                "history_days": 30,
                "start_date": None,
                "end_date": None,
            }
        )
        fake_ui.criteria_present = lambda value: True

        class CriteriaRequiredError(Exception):
            pass

        @dataclass(frozen=True)
        class Summary:
            added: int
            removed: int
            unchanged: int
            meeting_count: int

        def fake_edit(**kwargs):
            calls["edit"] = kwargs
            return Summary(1, 0, 4, 5)

        fake_actions.CriteriaRequiredError = (
            CriteriaRequiredError
        )
        fake_actions.edit_dynamic_session = (
            fake_edit
        )

        with patch.dict(
            sys.modules,
            {
                "query.session_context": fake_context,
                "query.sessions": fake_sessions,
                "session_actions": fake_actions,
                "session_criteria_ui": fake_ui,
            },
        ):
            payload = (
                backend_bridge.edit_dynamic_session_payload(
                    "Alex 1v1s",
                    "Alex",
                    "pipeline",
                    "",
                    "Last 30 days",
                )
            )

        self.assertIs(
            calls["edit"]["session"],
            session,
        )
        self.assertIs(
            calls["edit"]["save_session"],
            fake_sessions.save_chat_session,
        )
        self.assertEqual(payload["added"], 1)
        self.assertEqual(payload["unchanged"], 4)
        self.assertEqual(payload["meeting_count"], 5)


    def test_session_detail_reuses_saved_context_service(self):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_presentation = types.ModuleType(
            "query_presentation"
        )

        calls = {}

        def fake_build_saved_session_context(
            session_name,
        ):
            calls["session_name"] = session_name
            return {
                "session": {
                    "session_name": session_name,
                    "meeting_runs": ["run-a", "run-b"],
                    "conversation_history": [
                        {"role": "user", "content": "What changed?"},
                        {"role": "assistant", "content": "Two items changed."},
                        {"role": "system", "content": "ignore me"},
                    ],
                },
                "prep": {"meeting_count": 2},
                "selection_criteria": {"person": "Alex"},
            }

        def fake_format_session_prep(
            prep,
            heading,
            selection_criteria=None,
        ):
            calls["prep"] = prep
            calls["heading"] = heading
            calls["criteria"] = selection_criteria
            return "SESSION PREP"

        fake_context.build_saved_session_context = fake_build_saved_session_context
        fake_presentation.format_session_prep = fake_format_session_prep

        with patch.dict(
            sys.modules,
            {
                "context_service": fake_context,
                "query_presentation": fake_presentation,
            },
        ):
            payload = backend_bridge.session_detail_payload(
                "Alex 1v1s"
            )

        self.assertEqual(calls["session_name"], "Alex 1v1s")
        self.assertEqual(calls["heading"], "SESSION: Alex 1v1s")
        self.assertEqual(calls["criteria"], {"person": "Alex"})
        self.assertEqual(payload["meeting_count"], 2)
        self.assertEqual(payload["turn_count"], 1)
        self.assertEqual(payload["meeting_runs"], ["run-a", "run-b"])
        self.assertEqual(payload["prep_text"], "SESSION PREP")
        self.assertEqual(
            payload["conversation"],
            [
                {"role": "user", "content": "What changed?"},
                {"role": "assistant", "content": "Two items changed."},
            ],
        )


    def test_session_query_reuses_query_and_persistence_services(self):
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_conversation = types.ModuleType(
            "conversation_service"
        )
        fake_telemetry = types.ModuleType(
            "execution_telemetry"
        )
        fake_chat = types.ModuleType(
            "query.chat"
        )
        fake_presentation = types.ModuleType(
            "query_presentation"
        )

        calls = {}

        session = {
            "session_name": "Alex 1v1s",
            "conversation_history": [
                {
                    "role": "user",
                    "content": "Earlier",
                },
                {
                    "role": "assistant",
                    "content": "Earlier answer",
                },
            ],
            "selection_criteria": {
                "person": "Alex",
            },
        }

        context = {
            "merged_memory": {
                "topics": [],
            },
            "meeting_memories": [
                ("2026-09-01", {}),
            ],
            "selected_meetings": [
                {"meeting_run": "run-a"},
            ],
            "topic_filter": "pipeline",
        }

        meeting_dirs = [
            Path("/archive/run-a")
        ]

        fake_settings.load_app_settings = (
            lambda: {
                "performance_profile":
                    "Balanced",
            }
        )

        fake_context.build_saved_session_context = (
            lambda name: {
                "session": session,
                "context": context,
                "meeting_dirs":
                    meeting_dirs,
            }
        )

        def fake_run_query(
            user_prompt,
            merged_memory,
            conversation_history,
            **kwargs,
        ):
            calls["query"] = {
                "user_prompt":
                    user_prompt,
                "merged_memory":
                    merged_memory,
                "conversation_history":
                    conversation_history,
                **kwargs,
            }
            return (
                "New answer",
                {
                    "profile": "Balanced",
                    "mode": "direct",
                    "inference_calls": 1,
                },
            )

        fake_chat.run_query = fake_run_query

        def fake_append(
            supplied_session,
            supplied_meeting_dirs,
            *,
            user_prompt,
            assistant_response,
        ):
            calls["append"] = {
                "session":
                    supplied_session,
                "meeting_dirs":
                    supplied_meeting_dirs,
                "user_prompt":
                    user_prompt,
                "assistant_response":
                    assistant_response,
            }
            return [
                *session[
                    "conversation_history"
                ],
                {
                    "role": "user",
                    "content": user_prompt,
                },
                {
                    "role": "assistant",
                    "content":
                        assistant_response,
                },
            ]

        fake_conversation.append_query_exchange = (
            fake_append
        )

        def fake_telemetry_record(
            metadata,
            *,
            elapsed_seconds,
        ):
            calls["telemetry"] = {
                "metadata": metadata,
                "elapsed_seconds":
                    elapsed_seconds,
            }

        fake_telemetry.record_execution_telemetry = (
            fake_telemetry_record
        )
        fake_telemetry.load_execution_telemetry = (
            lambda: []
        )

        fake_presentation.format_query_finished_status = (
            lambda metadata, fallback:
                "Qwen · Balanced · Direct"
        )

        with patch.dict(
            sys.modules,
            {
                "app_settings":
                    fake_settings,
                "context_service":
                    fake_context,
                "conversation_service":
                    fake_conversation,
                "execution_telemetry":
                    fake_telemetry,
                "query.chat":
                    fake_chat,
                "query_presentation":
                    fake_presentation,
            },
        ):
            payload = (
                backend_bridge.session_query_payload(
                    "Alex 1v1s",
                    "  What changed?  ",
                )
            )

        query_call = calls["query"]

        self.assertEqual(
            query_call["user_prompt"],
            "What changed?",
        )
        self.assertIs(
            query_call["merged_memory"],
            context["merged_memory"],
        )
        self.assertIs(
            query_call[
                "conversation_history"
            ],
            session[
                "conversation_history"
            ],
        )
        self.assertTrue(
            query_call["include_grounded"]
        )
        self.assertFalse(
            query_call["print_output"]
        )
        self.assertIs(
            query_call["meeting_memories"],
            context["meeting_memories"],
        )
        self.assertIs(
            query_call["selected_meetings"],
            context["selected_meetings"],
        )
        self.assertEqual(
            query_call["topic_filter"],
            "pipeline",
        )
        self.assertTrue(
            query_call[
                "return_execution_metadata"
            ]
        )
        self.assertEqual(
            query_call["execution_profile"],
            "Balanced",
        )

        self.assertIs(
            calls["append"]["session"],
            session,
        )
        self.assertEqual(
            calls["append"]["meeting_dirs"],
            meeting_dirs,
        )
        self.assertEqual(
            calls["append"]["user_prompt"],
            "What changed?",
        )
        self.assertEqual(
            calls["append"][
                "assistant_response"
            ],
            "New answer",
        )

        self.assertEqual(
            payload["assistant_response"],
            "New answer",
        )
        self.assertEqual(
            payload["turn_count"],
            2,
        )
        self.assertEqual(
            payload["status_text"],
            "Qwen · Balanced · Direct",
        )
        self.assertEqual(
            payload["execution_mode"],
            "direct",
        )
        self.assertEqual(
            payload["inference_calls"],
            1,
        )
        self.assertGreaterEqual(
            payload["elapsed_seconds"],
            0,
        )

    def test_session_query_rejects_blank_prompt(self):
        with self.assertRaises(ValueError):
            backend_bridge.session_query_payload(
                "Alex 1v1s",
                "   ",
            )


    def test_preferences_payload_uses_shared_settings_helpers(self):
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_config = types.ModuleType(
            "config"
        )
        fake_models = types.ModuleType(
            "ollama_models"
        )
        fake_ui = types.ModuleType(
            "preferences_ui"
        )
        fake_performance = types.ModuleType(
            "performance_profile"
        )
        fake_hardware = types.ModuleType(
            "hardware_profile"
        )

        fake_settings.load_app_settings = (
            lambda: {
                "execution_profile":
                    "Balanced",
                "output_dir": "/work",
                "archive_dir": "/archive",
                "recordings_dir": "/recordings",
                "llm_backend": "auto",
                "llm_model": "qwen3:8b",
                "mlx_model": "Qwen/Test-MLX",
                "llm_context_size": 8192,
                "llm_context_mode": "override",
                "m4a_retention_days": 30,
                "archived_m4a_retention_days":
                    365,
            }
        )
        fake_config.OUTPUT_DIR = Path(
            "/fallback-work"
        )
        fake_config.ARCHIVE_DIR = Path(
            "/fallback-archive"
        )
        fake_models.discover_installed_ollama_models = (
            lambda: (
                ["qwen3:8b"],
                None,
            )
        )
        fake_ui.CONTEXT_SIZE_OPTIONS = (
            ("Model default", 0),
            ("8K", 8192),
        )
        fake_ui.merge_model_choices = (
            lambda installed, current:
                list(installed)
        )
        fake_ui.model_status_text = (
            lambda configured, installed, error:
                "Installed"
        )
        fake_ui.archive_status_text = (
            lambda path: "Available"
        )
        fake_performance.PERFORMANCE_PROFILE_NAMES = (
            "Auto",
            "Conservative",
            "Balanced",
            "High Performance",
        )
        fake_performance.performance_profile_options = lambda: [
            {"name": "Auto", "description": "Automatic"},
            {"name": "Conservative", "description": "Conservative"},
            {"name": "Balanced", "description": "Balanced"},
            {"name": "High Performance", "description": "High Performance"},
        ]
        fake_performance.resolve_performance_profile = (
            lambda requested, context_size_override=0, hardware=None:
                types.SimpleNamespace(
                    requested_name=requested,
                    resolved_name="Balanced",
                    context_size_tokens=context_size_override or 24576,
                    direct_token_budget=18000,
                    chunk_source_token_budget=5000,
                    chunk_overlap_tokens=384,
                    hardware_label="Test Mac · 24 GB",
                    reason="test",
                )
        )
        fake_hardware.detect_hardware_profile = (
            lambda: types.SimpleNamespace(
                display_label="Test Mac · 24 GB",
                chip_name="Test Mac",
                memory_gb=24,
                performance_class="Apple Silicon Pro",
            )
        )

        with patch.dict(
            sys.modules,
            {
                "app_settings":
                    fake_settings,
                "config":
                    fake_config,
                "ollama_models":
                    fake_models,
                "preferences_ui":
                    fake_ui,
                "performance_profile":
                    fake_performance,
                "hardware_profile":
                    fake_hardware,
            },
        ):
            payload = (
                backend_bridge.preferences_payload()
            )

        self.assertEqual(
            payload["settings"][
                "output_dir"
            ],
            "/work",
        )
        self.assertEqual(
            payload["settings"][
                "llm_context_size"
            ],
            8192,
        )
        self.assertEqual(
            payload["settings"][
                "recordings_dir"
            ],
            "/recordings",
        )
        self.assertEqual(
            payload["settings"]["llm_backend"],
            "auto",
        )
        self.assertIn(
            payload["resolved_llm_backend"]["resolved_name"],
            {"ollama", "mlx"},
        )
        self.assertEqual(
            payload["model_status"],
            "Installed",
        )
        self.assertEqual(
            payload["archive_status"],
            "Available",
        )
        self.assertEqual(
            payload["performance_profiles"],
            [
                "Auto",
                "Conservative",
                "Balanced",
                "High Performance",
            ],
        )
        self.assertEqual(
            payload["hardware_profile"]["memory_gb"],
            24,
        )
        self.assertEqual(
            payload["resolved_performance_profile"]["context_mode"],
            "override",
        )
        self.assertEqual(
            payload["performance_profile_options"][0]["name"],
            "Auto",
        )

    def test_save_preferences_payload_reuses_validation_and_save(self):
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_ui = types.ModuleType(
            "preferences_ui"
        )
        fake_performance = types.ModuleType(
            "performance_profile"
        )

        saved = {}

        fake_settings.load_app_settings = (
            lambda: {}
        )

        def fake_save(settings):
            saved.update(settings)

        fake_settings.save_app_settings = (
            fake_save
        )

        fake_ui.validate_preferences = (
            lambda output, archive, model:
                None
        )
        fake_performance.PERFORMANCE_PROFILE_NAMES = (
            "Auto",
            "Conservative",
            "Balanced",
            "High Performance",
        )

        with patch.dict(
            sys.modules,
            {
                "app_settings":
                    fake_settings,
                "preferences_ui":
                    fake_ui,
                "performance_profile":
                    fake_performance,
            },
        ):
            payload = (
                backend_bridge.save_preferences_payload(
                    "Balanced",
                    "ollama",
                    "/work",
                    "/archive",
                    "/recordings",
                    "qwen3:8b",
                    8192,
                    30,
                    365,
                )
            )

        self.assertTrue(
            payload["saved"]
        )
        self.assertIn(
            "subsequent Meeting Transcriber operations",
            payload["message"],
        )
        self.assertNotIn(
            "Restart Meeting Transcriber",
            payload["message"],
        )
        self.assertEqual(
            saved["output_dir"],
            "/work",
        )
        self.assertEqual(
            saved["archive_dir"],
            "/archive",
        )
        self.assertEqual(
            saved["recordings_dir"],
            "/recordings",
        )
        self.assertEqual(
            saved["llm_backend"],
            "ollama",
        )
        self.assertEqual(
            saved["llm_model"],
            "qwen3:8b",
        )
        self.assertEqual(
            saved["llm_context_size"],
            8192,
        )
        self.assertEqual(
            saved["llm_context_mode"],
            "override",
        )

    def test_save_preferences_profile_default_clears_context_override(self):
        fake_settings = types.ModuleType("app_settings")
        fake_ui = types.ModuleType("preferences_ui")
        fake_performance = types.ModuleType("performance_profile")
        saved = {}

        fake_settings.load_app_settings = lambda: {
            "llm_context_size": 16384,
            "llm_context_mode": "override",
        }
        fake_settings.save_app_settings = lambda settings: saved.update(settings)
        fake_ui.validate_preferences = lambda output, archive, model: None
        fake_performance.PERFORMANCE_PROFILE_NAMES = (
            "Auto", "Conservative", "Balanced", "High Performance"
        )

        with patch.dict(
            sys.modules,
            {
                "app_settings": fake_settings,
                "preferences_ui": fake_ui,
                "performance_profile": fake_performance,
            },
        ):
            backend_bridge.save_preferences_payload(
                "Auto",
                "auto",
                "/work",
                "/archive",
                "/recordings",
                "qwen3:8b",
                0,
                30,
                365,
            )

        self.assertEqual(saved["llm_context_size"], 0)
        self.assertEqual(saved["llm_context_mode"], "profile_default")


    def test_session_changes_requires_two_meetings(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_context.build_saved_session_context = (
            lambda name: {
                "context": {
                    "meeting_memories": [],
                    "selected_meetings": [],
                }
            }
        )

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
            },
        ), patch(
            "query.sessions.load_chat_session",
            return_value={},
        ):
            payload = (
                backend_bridge
                .session_changes_payload(
                    "Test"
                )
            )

        self.assertFalse(
            payload["available"]
        )
        self.assertIn(
            "At least two meetings",
            payload["markdown"],
        )
        self.assertIsNone(
            payload["generated_at"]
        )

    def test_session_changes_uses_shared_changes_query_and_saves_cache(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_context.build_saved_session_context = (
            lambda name: {
                "context": {
                    "meeting_memories": [
                        (
                            "2026-09-08_previous",
                            {},
                        ),
                        (
                            "2026-09-17_latest",
                            {},
                        ),
                    ],
                    "selected_meetings": [
                        {
                            "meeting_run":
                                "2026-09-08_previous",
                        },
                        {
                            "meeting_run":
                                "2026-09-17_latest",
                        },
                    ],
                }
            }
        )

        comparison = {
            "previous_run":
                "2026-09-08_previous",
            "previous_label":
                "2026-09-08 | Previous",
            "latest_run":
                "2026-09-17_latest",
            "latest_label":
                "2026-09-17 | Latest",
        }

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
            },
        ), patch(
            "query.sessions.load_chat_session",
            return_value={},
        ), patch(
            "query.sessions.save_session_changes_cache",
        ) as mock_save, patch(
            "query.changes.run_changes_query",
            return_value=(
                "## Executive Delta\n- Changed",
                {"mode": "direct"},
                comparison,
            ),
        ) as mock_changes:
            payload = (
                backend_bridge
                .session_changes_payload(
                    "Test"
                )
            )

        self.assertTrue(
            payload["available"]
        )
        self.assertFalse(payload["is_cached"])
        self.assertFalse(payload["is_stale"])
        self.assertEqual(
            payload["latest_run"],
            "2026-09-17_latest",
        )
        self.assertIn(
            "Executive Delta",
            payload["markdown"],
        )
        self.assertTrue(payload["generated_at"])
        mock_changes.assert_called_once()
        mock_save.assert_called_once()

    def test_session_changes_returns_saved_result_and_marks_stale(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_context.build_saved_session_context = (
            lambda name: {
                "context": {
                    "meeting_memories": [
                        ("2026-09-17_previous", {}),
                        ("2026-09-21_latest", {}),
                    ],
                    "selected_meetings": [
                        {"meeting_run": "2026-09-17_previous"},
                        {"meeting_run": "2026-09-21_latest"},
                    ],
                }
            }
        )
        cached = {
            "available": True,
            "previous_run": "2026-09-08_previous",
            "previous_label": "2026-09-08 | Previous",
            "latest_run": "2026-09-17_previous",
            "latest_label": "2026-09-17 | Latest",
            "markdown": "saved comparison",
            "elapsed_seconds": 12.3,
            "generated_at": "2026-09-23T18:24:00-05:00",
        }

        with patch.dict(
            sys.modules,
            {"context_service": fake_context},
        ), patch(
            "query.sessions.load_chat_session",
            return_value={"changes_cache": cached},
        ), patch(
            "query.changes.run_changes_query",
        ) as mock_changes:
            payload = backend_bridge.session_changes_payload("Test")

        self.assertTrue(payload["is_cached"])
        self.assertTrue(payload["is_stale"])
        self.assertEqual(payload["markdown"], "saved comparison")
        self.assertEqual(
            payload["current_latest_run"],
            "2026-09-21_latest",
        )
        mock_changes.assert_not_called()

    def test_session_changes_force_regenerates_saved_result(
        self,
    ):
        fake_context = types.ModuleType("context_service")
        fake_context.build_saved_session_context = lambda name: {
            "context": {
                "meeting_memories": [
                    ("2026-09-08_previous", {}),
                    ("2026-09-17_latest", {}),
                ],
                "selected_meetings": [
                    {"meeting_run": "2026-09-08_previous"},
                    {"meeting_run": "2026-09-17_latest"},
                ],
            }
        }
        comparison = {
            "previous_run": "2026-09-08_previous",
            "previous_label": "2026-09-08 | Previous",
            "latest_run": "2026-09-17_latest",
            "latest_label": "2026-09-17 | Latest",
        }

        with patch.dict(
            sys.modules,
            {"context_service": fake_context},
        ), patch(
            "query.sessions.load_chat_session",
            return_value={"changes_cache": {"markdown": "old"}},
        ), patch(
            "query.sessions.save_session_changes_cache",
        ) as mock_save, patch(
            "query.changes.run_changes_query",
            return_value=("new", {"mode": "direct"}, comparison),
        ) as mock_changes:
            payload = backend_bridge.session_changes_payload(
                "Test",
                force=True,
            )

        self.assertEqual(payload["markdown"], "new")
        self.assertFalse(payload["is_cached"])
        mock_changes.assert_called_once()
        mock_save.assert_called_once()


    def test_meeting_context_payload_builds_ad_hoc_context(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_selector = types.ModuleType(
            "meeting_selector"
        )
        fake_presentation = types.ModuleType(
            "query_presentation"
        )

        captured = {}

        def fake_build(
            meeting_runs,
            meeting_index,
        ):
            captured["runs"] = list(
                meeting_runs
            )

            return {
                "prep": {
                    "meeting_count": 2,
                },
                "selected": [
                    {
                        "meeting_run":
                            "2026-09-01_one",
                        "display_title":
                            "One",
                    },
                    {
                        "meeting_run":
                            "2026-09-02_two",
                        "display_title":
                            "Two",
                    },
                ],
            }

        fake_context.build_ad_hoc_context = (
            fake_build
        )
        fake_selector.load_meeting_index = (
            lambda: []
        )
        fake_presentation.format_session_prep = (
            lambda prep, heading:
                "MEETING CONTEXT"
        )

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
                "meeting_selector":
                    fake_selector,
                "query_presentation":
                    fake_presentation,
            },
        ):
            payload = (
                backend_bridge
                .meeting_context_payload(
                    json.dumps(
                        [
                            "2026-09-01_one",
                            "2026-09-02_two",
                        ]
                    )
                )
            )

        self.assertEqual(
            captured["runs"],
            [
                "2026-09-01_one",
                "2026-09-02_two",
            ],
        )
        self.assertEqual(
            payload["meeting_count"],
            2,
        )
        self.assertEqual(
            payload["prep_text"],
            "MEETING CONTEXT",
        )

    def test_meeting_context_query_uses_conversation_history(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_selector = types.ModuleType(
            "meeting_selector"
        )
        fake_chat = types.ModuleType(
            "query.chat"
        )
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_telemetry = types.ModuleType(
            "execution_telemetry"
        )
        fake_presentation = types.ModuleType(
            "query_presentation"
        )
        fake_synthesis = types.ModuleType(
            "query.synthesis"
        )
        fake_changes = types.ModuleType(
            "query.changes"
        )
        fake_changes.run_changes_query = (
            lambda *args, **kwargs: ("Unused", {}, {})
        )
        fake_synthesis.run_synthesis_query = (
            lambda *args, **kwargs: (
                "Unused",
                {
                    "mode": "direct",
                    "inference_calls": 1,
                },
            )
        )

        captured = {}

        fake_context.build_ad_hoc_context = (
            lambda runs, index: {
                "context": {
                    "merged_memory": {},
                    "meeting_memories": [],
                    "selected_meetings": [],
                    "topic_filter": None,
                }
            }
        )
        fake_selector.load_meeting_index = (
            lambda: []
        )
        fake_settings.load_app_settings = (
            lambda: {
                "performance_profile":
                    "Balanced"
            }
        )
        fake_telemetry.record_execution_telemetry = (
            lambda *args, **kwargs:
                None
        )
        fake_telemetry.load_execution_telemetry = (
            lambda: []
        )
        fake_presentation.format_query_finished_status = (
            lambda metadata, profile:
                "Done"
        )

        def fake_run_query(
            prompt,
            memory,
            history,
            **kwargs,
        ):
            captured["prompt"] = prompt
            captured["history"] = history

            return (
                "Answer",
                {
                    "mode": "direct",
                    "inference_calls": 1,
                },
            )

        fake_chat.run_query = (
            fake_run_query
        )

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
                "meeting_selector":
                    fake_selector,
                "query.chat":
                    fake_chat,
                "query.synthesis":
                    fake_synthesis,
                "query.changes":
                    fake_changes,
                "app_settings":
                    fake_settings,
                "execution_telemetry":
                    fake_telemetry,
                "query_presentation":
                    fake_presentation,
            },
        ):
            payload = (
                backend_bridge
                .meeting_context_query_payload(
                    json.dumps(
                        ["2026-09-01_one"]
                    ),
                    "What changed?",
                    json.dumps(
                        [
                            {
                                "role": "user",
                                "content":
                                    "Earlier question",
                            },
                            {
                                "role":
                                    "assistant",
                                "content":
                                    "Earlier answer",
                            },
                        ]
                    ),
                )
            )

        self.assertEqual(
            captured["prompt"],
            "What changed?",
        )
        self.assertEqual(
            len(captured["history"]),
            2,
        )
        self.assertEqual(
            payload[
                "assistant_response"
            ],
            "Answer",
        )


    def test_save_meeting_context_session_payload(
        self,
    ):
        import tempfile
        from pathlib import Path

        fake_config = types.ModuleType(
            "config"
        )
        fake_sessions = types.ModuleType(
            "query.sessions"
        )
        fake_actions = types.ModuleType(
            "session_actions"
        )

        captured = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)

            for run in [
                "2026-09-01_one",
                "2026-09-02_two",
            ]:
                meeting_dir = archive_dir / run
                meeting_dir.mkdir()
                (
                    meeting_dir
                    / "meeting_memory.json"
                ).write_text(
                    "{}",
                    encoding="utf-8",
                )

            fake_config.ARCHIVE_DIR = archive_dir
            fake_sessions.save_chat_session = (
                lambda *args, **kwargs:
                    None
            )

            def fake_save_fixed_session(
                **kwargs,
            ):
                captured.update(kwargs)
                return kwargs["session_name"]

            fake_actions.save_fixed_session = (
                fake_save_fixed_session
            )

            with patch.dict(
                sys.modules,
                {
                    "config": fake_config,
                    "query.sessions":
                        fake_sessions,
                    "session_actions":
                        fake_actions,
                },
            ):
                payload = (
                    backend_bridge
                    .save_meeting_context_session_payload(
                        "Boss Prep",
                        json.dumps(
                            [
                                "2026-09-01_one",
                                "2026-09-02_two",
                            ]
                        ),
                        json.dumps(
                            [
                                {
                                    "role": "user",
                                    "content": "Question",
                                },
                                {
                                    "role": "assistant",
                                    "content": "Answer",
                                },
                            ]
                        ),
                    )
                )

        self.assertEqual(
            payload["session_name"],
            "Boss Prep",
        )
        self.assertEqual(
            payload["meeting_count"],
            2,
        )
        self.assertEqual(
            payload["turn_count"],
            1,
        )
        self.assertEqual(
            len(captured["meeting_dirs"]),
            2,
        )
        self.assertEqual(
            len(captured["history"]),
            2,
        )

    def test_save_meeting_context_requires_archived_meetings(
        self,
    ):
        import tempfile
        from pathlib import Path

        fake_config = types.ModuleType(
            "config"
        )
        fake_sessions = types.ModuleType(
            "query.sessions"
        )
        fake_actions = types.ModuleType(
            "session_actions"
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_config.ARCHIVE_DIR = Path(
                temp_dir
            )
            fake_sessions.save_chat_session = (
                lambda *args, **kwargs:
                    None
            )
            fake_actions.save_fixed_session = (
                lambda **kwargs:
                    kwargs["session_name"]
            )

            with patch.dict(
                sys.modules,
                {
                    "config": fake_config,
                    "query.sessions":
                        fake_sessions,
                    "session_actions":
                        fake_actions,
                },
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "published/archived",
                ):
                    (
                        backend_bridge
                        .save_meeting_context_session_payload(
                            "Test",
                            json.dumps(
                                [
                                    "2026-09-01_missing"
                                ]
                            ),
                            "[]",
                        )
                    )


    def test_meeting_context_query_synthesis_mode(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_selector = types.ModuleType(
            "meeting_selector"
        )
        fake_chat = types.ModuleType(
            "query.chat"
        )
        fake_synthesis = types.ModuleType(
            "query.synthesis"
        )
        fake_changes = types.ModuleType(
            "query.changes"
        )
        fake_changes.run_changes_query = (
            lambda *args, **kwargs: ("Unused", {}, {})
        )
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_telemetry = types.ModuleType(
            "execution_telemetry"
        )
        fake_presentation = types.ModuleType(
            "query_presentation"
        )

        fake_context.build_ad_hoc_context = (
            lambda runs, index: {
                "context": {
                    "merged_memory": {},
                    "meeting_memories": [
                        (
                            "2026-09-01_one",
                            {},
                        ),
                        (
                            "2026-09-02_two",
                            {},
                        ),
                    ],
                    "selected_meetings": [
                        {
                            "meeting_run":
                                "2026-09-01_one"
                        },
                        {
                            "meeting_run":
                                "2026-09-02_two"
                        },
                    ],
                    "topic_filter": None,
                }
            }
        )
        fake_selector.load_meeting_index = (
            lambda: []
        )
        fake_settings.load_app_settings = (
            lambda: {
                "performance_profile":
                    "Balanced"
            }
        )
        fake_telemetry.record_execution_telemetry = (
            lambda *args, **kwargs:
                None
        )
        fake_telemetry.load_execution_telemetry = (
            lambda: []
        )
        fake_presentation.format_query_finished_status = (
            lambda metadata, profile:
                "Done"
        )

        fake_chat.run_query = (
            lambda *args, **kwargs:
                self.fail(
                    "normal query path should not run"
                )
        )

        captured = {}

        def fake_run_synthesis(
            prompt,
            memories,
            selected,
            history,
            **kwargs,
        ):
            captured["prompt"] = prompt
            captured["memory_count"] = (
                len(memories)
            )

            return (
                "Cross-meeting answer",
                {
                    "mode": "direct",
                    "inference_calls": 1,
                },
            )

        fake_synthesis.run_synthesis_query = (
            fake_run_synthesis
        )

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
                "meeting_selector":
                    fake_selector,
                "query.chat":
                    fake_chat,
                "query.synthesis":
                    fake_synthesis,
                "query.changes":
                    fake_changes,
                "app_settings":
                    fake_settings,
                "execution_telemetry":
                    fake_telemetry,
                "query_presentation":
                    fake_presentation,
            },
        ):
            payload = (
                backend_bridge
                .meeting_context_query_payload(
                    '["2026-09-01_one",'
                    '"2026-09-02_two"]',
                    "Boss prep",
                    "[]",
                    "synthesis",
                )
            )

        self.assertEqual(
            captured["memory_count"],
            2,
        )
        self.assertEqual(
            payload["assistant_response"],
            "Cross-meeting answer",
        )


    def test_meeting_context_query_plan_payload(
        self,
    ):
        fake_context = types.ModuleType(
            "context_service"
        )
        fake_selector = types.ModuleType(
            "meeting_selector"
        )
        fake_settings = types.ModuleType(
            "app_settings"
        )
        fake_synthesis = types.ModuleType(
            "query.synthesis"
        )

        fake_context.build_ad_hoc_context = (
            lambda runs, index: {
                "context": {
                    "meeting_memories": [
                        (
                            "2026-09-01_one",
                            {},
                        )
                    ],
                    "selected_meetings": [
                        {
                            "meeting_run":
                                "2026-09-01_one"
                        }
                    ],
                }
            }
        )
        fake_selector.load_meeting_index = (
            lambda: []
        )
        fake_settings.load_app_settings = (
            lambda: {
                "execution_profile":
                    "Balanced"
            }
        )
        fake_synthesis.synthesis_plan_payload = (
            lambda *args, **kwargs: {
                "mode": "direct",
                "estimated_prompt_tokens":
                    4200,
                "direct_token_budget":
                    12000,
                "chunk_source_token_budget":
                    3480,
                "chunk_count": 0,
                "inference_calls": 1,
                "meeting_count": 1,
                "hardware_label":
                    "Test Mac · 16 GB",
                "profile": "Balanced",
                "status_text":
                    "Boss Prep · Direct",
            }
        )

        with patch.dict(
            sys.modules,
            {
                "context_service":
                    fake_context,
                "meeting_selector":
                    fake_selector,
                "app_settings":
                    fake_settings,
                "query.synthesis":
                    fake_synthesis,
            },
        ):
            payload = (
                backend_bridge
                .meeting_context_query_plan_payload(
                    '["2026-09-01_one"]',
                    "Boss prep",
                    "[]",
                    "synthesis",
                )
            )

        self.assertEqual(
            payload["mode"],
            "direct",
        )
        self.assertEqual(
            payload["inference_calls"],
            1,
        )
        self.assertEqual(
            payload["schema_version"],
            17,
        )


class GlobalSearchBridgeTests(unittest.TestCase):
    @patch("global_search.global_search")
    @patch("backend_bridge.load_meeting_catalog")
    def test_global_search_payload_uses_catalog_and_returns_groups(
        self,
        mock_catalog,
        mock_search,
    ):
        mock_catalog.return_value = [{"meeting_run": "run-1"}]
        mock_search.return_value = {
            "meetings": [{"id": "meeting:run-1"}],
            "sessions": [{"id": "session:one"}],
        }

        payload = backend_bridge.global_search_payload("  Cloud Provider A  ")

        self.assertEqual(payload["schema_version"], 17)
        self.assertEqual(payload["query"], "Cloud Provider A")
        self.assertEqual(payload["meetings"][0]["id"], "meeting:run-1")
        self.assertEqual(payload["sessions"][0]["id"], "session:one")
        mock_search.assert_called_once()

if __name__ == "__main__":
    unittest.main()
