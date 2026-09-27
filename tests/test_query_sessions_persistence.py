import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from query import sessions


class QuerySessionPersistenceTests(unittest.TestCase):
    def test_save_chat_session_preserves_changes_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)
            sessions_dir = archive_dir / "query_sessions"
            sessions_dir.mkdir(parents=True)
            session_path = sessions_dir / "Jordan.json"
            cache = {
                "generated_at": "2026-09-23T18:24:00-05:00",
                "previous_run": "2026-09-14_a",
                "latest_run": "2026-09-21_b",
                "markdown": "saved",
            }
            session_path.write_text(
                json.dumps(
                    {
                        "session_name": "Jordan",
                        "meeting_runs": ["2026-09-14_a"],
                        "conversation_history": [],
                        "changes_cache": cache,
                    }
                ),
                encoding="utf-8",
            )

            meeting_dir = archive_dir / "2026-09-21_b"
            with patch.object(sessions, "ARCHIVE_DIR", archive_dir):
                sessions.save_chat_session(
                    "Jordan",
                    [meeting_dir],
                    [{"role": "user", "content": "hello"}],
                    {"person": "Jordan"},
                )

            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["changes_cache"], cache)
            self.assertEqual(saved["meeting_runs"], ["2026-09-21_b"])
            self.assertEqual(saved["selection_criteria"], {"person": "Jordan"})

    def test_save_session_changes_cache_updates_only_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir)
            sessions_dir = archive_dir / "query_sessions"
            sessions_dir.mkdir(parents=True)
            session_path = sessions_dir / "Jordan.json"
            session_path.write_text(
                json.dumps(
                    {
                        "session_name": "Jordan",
                        "meeting_runs": ["2026-09-14_a", "2026-09-21_b"],
                        "conversation_history": [{"role": "user", "content": "hi"}],
                    }
                ),
                encoding="utf-8",
            )
            cache = {
                "generated_at": "2026-09-23T18:24:00-05:00",
                "markdown": "comparison",
            }

            with patch.object(sessions, "ARCHIVE_DIR", archive_dir):
                sessions.save_session_changes_cache("Jordan", cache)

            saved = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["changes_cache"], cache)
            self.assertEqual(saved["meeting_runs"], ["2026-09-14_a", "2026-09-21_b"])
            self.assertEqual(len(saved["conversation_history"]), 1)


if __name__ == "__main__":
    unittest.main()
