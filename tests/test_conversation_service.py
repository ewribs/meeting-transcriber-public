import unittest
from pathlib import Path

from conversation_service import (
    UnsavedSessionError,
    append_query_exchange,
)


class ConversationServiceTests(unittest.TestCase):
    def test_appends_user_and_assistant_and_persists(self):
        session = {
            "session_name": "Alex",
            "conversation_history": [],
            "selection_criteria": {"person": "Alex"},
        }
        calls = []

        def fake_save(name, meeting_dirs, history, criteria):
            calls.append((name, meeting_dirs, list(history), criteria))
            return Path("/tmp/Alex.json")

        meeting_dirs = [Path("/archive/meeting-1")]
        history = append_query_exchange(
            session,
            meeting_dirs,
            user_prompt="What should I prepare?",
            assistant_response="Prepare the renewal discussion.",
            save_session_func=fake_save,
        )

        self.assertEqual(
            history,
            [
                {"role": "user", "content": "What should I prepare?"},
                {
                    "role": "assistant",
                    "content": "Prepare the renewal discussion.",
                },
            ],
        )
        self.assertIs(history, session["conversation_history"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Alex")
        self.assertEqual(calls[0][1], meeting_dirs)
        self.assertEqual(calls[0][3], {"person": "Alex"})

    def test_preserves_existing_history(self):
        session = {
            "session_name": "Alex",
            "conversation_history": [
                {"role": "user", "content": "Earlier"},
                {"role": "assistant", "content": "Earlier answer"},
            ],
        }

        append_query_exchange(
            session,
            [],
            user_prompt="Next",
            assistant_response="Next answer",
            save_session_func=lambda *args: Path("/tmp/test.json"),
        )

        self.assertEqual(len(session["conversation_history"]), 4)
        self.assertEqual(session["conversation_history"][-2]["content"], "Next")
        self.assertEqual(
            session["conversation_history"][-1]["content"],
            "Next answer",
        )

    def test_blank_pending_prompt_only_appends_assistant(self):
        session = {
            "session_name": "Alex",
            "conversation_history": [],
        }

        append_query_exchange(
            session,
            [],
            user_prompt="   ",
            assistant_response="Answer",
            save_session_func=lambda *args: Path("/tmp/test.json"),
        )

        self.assertEqual(
            session["conversation_history"],
            [{"role": "assistant", "content": "Answer"}],
        )

    def test_unsaved_session_is_rejected(self):
        with self.assertRaises(UnsavedSessionError):
            append_query_exchange(
                {"session_name": None, "conversation_history": []},
                [],
                user_prompt="Question",
                assistant_response="Answer",
                save_session_func=lambda *args: Path("/tmp/test.json"),
            )


if __name__ == "__main__":
    unittest.main()
