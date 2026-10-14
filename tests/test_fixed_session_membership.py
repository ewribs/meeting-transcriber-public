import unittest
from pathlib import Path

from session_actions import (
    FixedSessionError,
    SessionActionError,
    SessionAlreadyCurrent,
    add_meetings_to_fixed_session,
    remove_meetings_from_fixed_session,
)


def _session(runs, criteria=None):
    return {
        "meeting_runs": list(runs),
        "conversation_history": [{"role": "user", "content": "hi"}],
        "selection_criteria": criteria,
    }


class FixedSessionMembershipTests(unittest.TestCase):
    def test_add_appends_new_and_skips_existing(self):
        saved = []
        summary = add_meetings_to_fixed_session(
            session_name="S",
            session=_session(["a", "b"]),
            meeting_dirs=[Path("/x/b"), Path("/x/c"), Path("/x/c")],
            save_session=lambda *args: saved.append(args),
        )
        self.assertEqual(
            (summary.added, summary.removed, summary.unchanged, summary.meeting_count),
            (1, 0, 2, 3),
        )
        name, dirs, history, criteria = saved[0]
        self.assertEqual([d.name for d in dirs], ["a", "b", "c"])
        self.assertEqual(history, [{"role": "user", "content": "hi"}])
        self.assertIsNone(criteria)

    def test_add_nothing_new_is_already_current(self):
        with self.assertRaises(SessionAlreadyCurrent):
            add_meetings_to_fixed_session(
                session_name="S",
                session=_session(["a"]),
                meeting_dirs=[Path("/x/a")],
                save_session=lambda *args: self.fail("must not save"),
            )

    def test_dynamic_session_is_refused(self):
        dynamic = _session(["a"], {"person": "Pat"})
        with self.assertRaises(FixedSessionError):
            add_meetings_to_fixed_session(
                session_name="S", session=dynamic,
                meeting_dirs=[Path("/x/b")], save_session=lambda *a: None,
            )
        with self.assertRaises(FixedSessionError):
            remove_meetings_from_fixed_session(
                session_name="S", session=dynamic,
                meeting_runs=["a"], save_session=lambda *a: None,
            )

    def test_remove_drops_listed_runs(self):
        saved = []
        summary = remove_meetings_from_fixed_session(
            session_name="S",
            session=_session(["a", "b", "c"]),
            meeting_runs=["b", "zzz"],
            save_session=lambda *args: saved.append(args),
        )
        self.assertEqual((summary.removed, summary.unchanged), (1, 2))
        self.assertEqual([d.name for d in saved[0][1]], ["a", "c"])

    def test_remove_unknown_is_already_current(self):
        with self.assertRaises(SessionAlreadyCurrent):
            remove_meetings_from_fixed_session(
                session_name="S", session=_session(["a"]),
                meeting_runs=["nope"], save_session=lambda *a: None,
            )

    def test_cannot_remove_last_meeting(self):
        with self.assertRaises(SessionActionError):
            remove_meetings_from_fixed_session(
                session_name="S", session=_session(["a"]),
                meeting_runs=["a"],
                save_session=lambda *a: self.fail("must not save"),
            )


if __name__ == "__main__":
    unittest.main()
