import tempfile
import unittest
from pathlib import Path

from transcription_queue import TranscriptionQueueState


class TranscriptionQueueStateTests(unittest.TestCase):
    def test_add_sources_deduplicates_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "one.m4a"
            source.touch()
            state = TranscriptionQueueState()
            self.assertEqual(state.add_sources([source, source]), 1)
            self.assertEqual(len(state.entries), 1)
            self.assertEqual(state.entries[0]["status"], "Waiting")

    def test_retry_publish_failure_does_not_retranscribe(self):
        state = TranscriptionQueueState(
            entries=[{
                "source_path": Path("one.m4a"),
                "status": "Publish Failed",
                "run_dir": Path("run"),
                "error": "NAS unavailable",
            }]
        )
        transcription, publish = state.retry_failures()
        self.assertEqual((transcription, publish), (0, 1))
        self.assertEqual(state.entries[0]["status"], "Ready to Publish")
        self.assertEqual(state.entries[0]["run_dir"], Path("run"))

    def test_transcription_transitions_update_counters(self):
        state = TranscriptionQueueState(
            entries=[{
                "source_path": Path("one.m4a"),
                "status": "Waiting",
                "run_dir": None,
                "error": None,
            }]
        )
        state.begin_run()
        state.begin_transcription(0)
        self.assertEqual(state.attempted, 1)
        state.mark_transcription_success(Path("run"))
        self.assertEqual(state.successes, 1)
        self.assertEqual(state.entries[0]["status"], "Ready to Publish")

    def test_publish_failure_and_success_are_run_scoped(self):
        state = TranscriptionQueueState(
            entries=[
                {"source_path": Path("a.m4a"), "status": "Ready to Publish", "run_dir": Path("run-a"), "error": None},
                {"source_path": Path("b.m4a"), "status": "Ready to Publish", "run_dir": Path("run-b"), "error": None},
            ]
        )
        state.mark_publish_failure(Path("run-a"), "fail")
        state.mark_publish_success(Path("run-b"))
        self.assertEqual(state.entries[0]["status"], "Publish Failed")
        self.assertEqual(state.entries[1]["status"], "Published")
        self.assertEqual(state.publish_failures, 1)
        self.assertEqual(state.publish_successes, 1)


if __name__ == "__main__":
    unittest.main()
