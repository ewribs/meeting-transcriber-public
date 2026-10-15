import unittest
from unittest import mock

import backend_bridge


def catalog():
    return [
        {"meeting_run": "r1", "display_title": "Alpha Planning"},
        {"meeting_run": "r2", "display_title": "Beta Planning"},
        {"meeting_run": "r3", "display_title": "Gamma Planning"},
    ]


class FakeSearch:
    """Records which meetings it was asked to search."""

    def __init__(self):
        self.seen = None

    def __call__(self, query, meetings, sessions_dir, **kwargs):
        self.seen = [m["meeting_run"] for m in meetings]
        return {
            "meetings": [{"meeting_run": run} for run in self.seen],
            "sessions": [{"session_name": "S"}],
        }


class SearchScopeTests(unittest.TestCase):
    def run_search(self, **kwargs):
        fake = FakeSearch()
        with mock.patch.object(
            backend_bridge, "load_meeting_catalog", return_value=catalog()
        ), mock.patch("global_search.global_search", fake):
            payload = backend_bridge.global_search_payload(
                "planning", **kwargs
            )
        return fake, payload

    def test_unscoped_searches_everything_and_keeps_sessions(self):
        fake, payload = self.run_search()
        self.assertEqual(fake.seen, ["r1", "r2", "r3"])
        self.assertEqual(len(payload["sessions"]), 1)

    def test_folder_scope_limits_meetings_and_hides_sessions(self):
        folders = [
            {"name": "Mine", "meeting_runs": ["r2", "r3"]},
            {"name": "Other", "meeting_runs": ["r1"]},
        ]
        with mock.patch(
            "meeting_folders.load_folders", return_value=folders
        ):
            fake, payload = self.run_search(scope_folder="Mine")
        self.assertEqual(fake.seen, ["r2", "r3"])
        self.assertEqual(payload["sessions"], [])

    def test_session_scope_limits_meetings(self):
        session = {"meeting_runs": ["r1"]}
        with mock.patch(
            "query.sessions.load_chat_session", return_value=session
        ):
            fake, payload = self.run_search(scope_session="Team")
        self.assertEqual(fake.seen, ["r1"])
        self.assertEqual(payload["sessions"], [])

    def test_missing_folder_is_an_error(self):
        with mock.patch("meeting_folders.load_folders", return_value=[]):
            with self.assertRaises(ValueError):
                self.run_search(scope_folder="Nope")

    def test_empty_folder_scope_returns_nothing(self):
        folders = [{"name": "Empty", "meeting_runs": []}]
        with mock.patch(
            "meeting_folders.load_folders", return_value=folders
        ):
            fake, payload = self.run_search(scope_folder="Empty")
        self.assertEqual(fake.seen, [])
        self.assertEqual(payload["meetings"], [])


if __name__ == "__main__":
    unittest.main()
