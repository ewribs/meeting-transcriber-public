import tempfile
import unittest
from pathlib import Path

from context_service import (
    NoLoadableMeetingsError,
    NoMeetingsSelectedError,
    build_ad_hoc_context,
    build_saved_session_context,
    resume_saved_session,
)


class ContextServiceTests(unittest.TestCase):
    def test_ad_hoc_requires_meetings(self):
        with self.assertRaises(NoMeetingsSelectedError):
            build_ad_hoc_context([], [])

    def test_ad_hoc_builds_sorted_session_and_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index = [
                {
                    "meeting_run": "2026-09-15_1200_B",
                    "location": str(root / "b"),
                },
                {
                    "meeting_run": "2026-09-14_1200_A",
                    "location": str(root / "a"),
                },
            ]

            result = build_ad_hoc_context(
                ["2026-09-15_1200_B", "2026-09-14_1200_A"],
                index,
                load_memory_func=lambda path: {"path": path.name},
                build_context_func=lambda memories, selected: {
                    "memories": memories,
                    "runs": [m["meeting_run"] for m in selected],
                },
                build_prep_func=lambda context: {"prep_for": context["runs"]},
            )

            self.assertEqual(
                result["session"]["meeting_runs"],
                ["2026-09-14_1200_A", "2026-09-15_1200_B"],
            )
            self.assertEqual(
                result["context"]["runs"],
                ["2026-09-14_1200_A", "2026-09-15_1200_B"],
            )
            self.assertEqual(
                [path.name for path in result["meeting_dirs"]],
                ["a", "b"],
            )

    def test_ad_hoc_rejects_unloadable_selection(self):
        with self.assertRaises(NoLoadableMeetingsError):
            build_ad_hoc_context(
                ["missing"],
                [{"meeting_run": "missing", "location": None}],
            )

    def test_saved_session_builds_topic_filtered_context(self):
        session = {
            "session_name": "Alex",
            "meeting_runs": ["run-1"],
            "conversation_history": [],
        }
        selected = [{"meeting_run": "run-1"}]
        meeting_dirs = [Path("/tmp/run-1")]

        result = build_saved_session_context(
            "Alex",
            load_session_func=lambda name: session,
            resume_session_func=lambda loaded, refresh=False: {
                "meeting_dirs": meeting_dirs,
                "selected": selected,
                "selection_criteria": {
                    "person": "Alex",
                    "topic": "Vendor Alpha",
                },
            },
            load_memory_func=lambda path: {"memory": path.name},
            build_context_func=lambda memories, chosen, topic: {
                "topic": topic,
                "memories": memories,
                "selected": chosen,
            },
            build_prep_func=lambda context: {"topic": context["topic"]},
        )

        self.assertIs(result["session"], session)
        self.assertEqual(result["context"]["topic"], "Vendor Alpha")
        self.assertEqual(result["prep"], {"topic": "Vendor Alpha"})
        self.assertEqual(result["selection_criteria"]["person"], "Alex")




class ResumeSavedSessionTests(unittest.TestCase):
    def test_resume_saved_session_forwards_refresh_true(self):
        calls = []

        def fake_resume(session, refresh=False):
            calls.append((session, refresh))
            return {"meeting_dirs": [], "selected": []}

        session = {"session_name": "Alex"}
        result = resume_saved_session(
            session,
            refresh=True,
            resume_session_func=fake_resume,
        )

        self.assertEqual(result["selected"], [])
        self.assertEqual(calls, [(session, True)])

    def test_resume_saved_session_defaults_to_refresh_false(self):
        calls = []

        def fake_resume(session, refresh=False):
            calls.append(refresh)
            return {"meeting_dirs": [], "selected": []}

        resume_saved_session(
            {"session_name": "Alex"},
            resume_session_func=fake_resume,
        )

        self.assertEqual(calls, [False])


if __name__ == "__main__":
    unittest.main()
