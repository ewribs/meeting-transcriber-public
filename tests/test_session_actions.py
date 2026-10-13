import tempfile
import unittest
from pathlib import Path

from session_actions import (
    CriteriaRequiredError,
    DuplicateSessionNameError,
    FixedSessionError,
    NoMatchingMeetingsError,
    SessionAlreadyCurrent,
    create_dynamic_session,
    edit_dynamic_session,
    refresh_dynamic_session,
    rename_session,
    save_fixed_session,
    validate_criteria,
)


class SessionActionTests(unittest.TestCase):
    def test_person_only_criteria_is_valid(self):
        validate_criteria({"person": "Alex", "title": None, "topic": None})

    def test_empty_criteria_is_rejected(self):
        with self.assertRaises(CriteriaRequiredError):
            validate_criteria({})

    def test_create_dynamic_session_rejects_duplicate_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            (sessions / "Alex.json").write_text("{}")
            with self.assertRaises(DuplicateSessionNameError):
                create_dynamic_session(
                    session_name="alex",
                    criteria={"person": "Alex"},
                    sessions_dir=sessions,
                    select_meetings=lambda _: [],
                    save_session=lambda *args: None,
                )

    def test_edit_preserves_history_and_reports_changes(self):
        saved = []
        session = {
            "selection_criteria": {"person": "Alex"},
            "meeting_runs": ["old", "same"],
            "conversation_history": [{"role": "user", "content": "hi"}],
        }
        selected = [
            {"meeting_run": "same", "meeting_dir": "/tmp/same"},
            {"meeting_run": "new", "meeting_dir": "/tmp/new"},
        ]
        summary = edit_dynamic_session(
            session_name="Alex",
            session=session,
            criteria={"person": "Alex"},
            select_meetings=lambda _: selected,
            save_session=lambda *args: saved.append(args),
        )
        self.assertEqual((summary.added, summary.removed, summary.unchanged), (1, 1, 1))
        self.assertEqual(saved[0][2], session["conversation_history"])

    def test_refresh_current_raises_specific_result(self):
        session = {
            "selection_criteria": {"person": "Alex"},
            "conversation_history": [],
        }
        with self.assertRaises(SessionAlreadyCurrent) as ctx:
            refresh_dynamic_session(
                session_name="Alex",
                session=session,
                resume_session=lambda *_args, **_kwargs: {
                    "meeting_dirs": [Path("/tmp/a")],
                    "refresh_summary": {"added": 0, "removed": 0, "unchanged": 5},
                },
                save_session=lambda *args: None,
            )
        self.assertEqual(ctx.exception.unchanged, 5)

    def test_save_fixed_session_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            sessions = Path(tmp)
            (sessions / "Fixed.json").write_text("{}")
            with self.assertRaises(DuplicateSessionNameError):
                save_fixed_session(
                    session_name="fixed",
                    meeting_dirs=[],
                    history=[],
                    sessions_dir=sessions,
                    save_session=lambda *args: None,
                )


if __name__ == "__main__":
    unittest.main()
