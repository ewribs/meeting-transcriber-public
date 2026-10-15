import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import backend_bridge


def entry(name, kind):
    return SimpleNamespace(name=name, session_type=kind)


class RefreshAllSessionsTests(unittest.TestCase):
    def run_with(self, entries, results):
        def fake_refresh(name):
            value = results[name]
            if isinstance(value, Exception):
                raise value
            return value

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("config.ARCHIVE_DIR", Path(tmp)), \
                mock.patch(
                    "session_browser.load_session_browser_entries",
                    return_value=entries,
                ), \
                mock.patch.object(
                    backend_bridge,
                    "refresh_session_payload",
                    side_effect=fake_refresh,
                ):
                return backend_bridge.refresh_all_sessions_payload()

    def test_only_dynamic_sessions_are_refreshed(self):
        out = self.run_with(
            [entry("A", "Dynamic"), entry("B", "Fixed")],
            {"A": {"result": "refreshed", "added": 2, "removed": 1}},
        )
        self.assertEqual(
            out["refreshed"],
            [{"session_name": "A", "added": 2, "removed": 1}],
        )
        self.assertEqual(out["failed"], 0)

    def test_current_and_failing_sessions_do_not_block_others(self):
        out = self.run_with(
            [entry("A", "Dynamic"), entry("B", "Dynamic"), entry("C", "Dynamic")],
            {
                "A": {"result": "already_current"},
                "B": RuntimeError("no matches"),
                "C": {"result": "refreshed", "added": 1, "removed": 0},
            },
        )
        self.assertEqual([r["session_name"] for r in out["refreshed"]], ["C"])
        self.assertEqual(out["failed"], 1)


if __name__ == "__main__":
    unittest.main()
