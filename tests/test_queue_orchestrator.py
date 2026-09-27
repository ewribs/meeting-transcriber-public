import tempfile
import unittest
from pathlib import Path

from queue_orchestrator import TranscriptionQueueOrchestrator
from transcription_queue import TranscriptionQueueState


class TranscriptionQueueOrchestratorTests(unittest.TestCase):
    def _state_with_sources(self, count=2):
        state = TranscriptionQueueState()
        paths = [Path(f"meeting-{index}.m4a") for index in range(count)]
        state.add_sources(paths)
        return state

    def test_start_next_transcription_begins_next_waiting_entry(self):
        state = self._state_with_sources(2)
        state.begin_run()
        orchestrator = TranscriptionQueueOrchestrator(state)

        action = orchestrator.start_next_transcription()

        self.assertEqual(action.kind, "transcribe")
        self.assertEqual(action.index, 0)
        self.assertEqual(state.entries[0]["status"], "Transcribing")
        self.assertEqual(state.attempted, 1)

    def test_start_next_transcription_finishes_when_none_waiting(self):
        state = self._state_with_sources(1)
        state.entries[0]["status"] = "Published"
        orchestrator = TranscriptionQueueOrchestrator(state)

        action = orchestrator.start_next_transcription()

        self.assertEqual(action.kind, "finish")

    def test_after_transcription_auto_publish_starts_publish(self):
        state = self._state_with_sources(1)
        state.begin_run()
        orchestrator = TranscriptionQueueOrchestrator(state)
        orchestrator.start_next_transcription()
        run_dir = Path("output/run-1")
        state.mark_transcription_success(run_dir)

        action = orchestrator.after_transcription(auto_publish=True)

        self.assertEqual(action.kind, "publish")
        self.assertEqual(action.run_dir, run_dir)
        self.assertEqual(state.entries[0]["status"], "Publishing")

    def test_after_transcription_without_auto_publish_continues(self):
        state = self._state_with_sources(1)
        state.begin_run()
        orchestrator = TranscriptionQueueOrchestrator(state)
        orchestrator.start_next_transcription()
        state.mark_transcription_success(Path("output/run-1"))

        action = orchestrator.after_transcription(auto_publish=False)

        self.assertEqual(action.kind, "continue")
        self.assertEqual(state.entries[0]["status"], "Ready to Publish")

    def test_after_failed_transcription_continues_to_next_item(self):
        state = self._state_with_sources(2)
        state.begin_run()
        orchestrator = TranscriptionQueueOrchestrator(state)
        orchestrator.start_next_transcription()
        state.mark_transcription_failure("boom")

        action = orchestrator.after_transcription(auto_publish=True)

        self.assertEqual(action.kind, "continue")

    def test_after_publish_auto_continues_active_queue(self):
        state = self._state_with_sources(1)
        state.begin_run()
        orchestrator = TranscriptionQueueOrchestrator(state)

        action = orchestrator.after_publish(mode="auto")

        self.assertEqual(action.kind, "continue")

    def test_after_publish_bulk_keeps_legacy_bulk_flow(self):
        state = self._state_with_sources(1)
        orchestrator = TranscriptionQueueOrchestrator(state)

        action = orchestrator.after_publish(mode="bulk")

        self.assertEqual(action.kind, "continue_bulk")

    def test_inactive_queue_does_nothing_after_transcription(self):
        state = self._state_with_sources(1)
        orchestrator = TranscriptionQueueOrchestrator(state)

        action = orchestrator.after_transcription(auto_publish=True)

        self.assertEqual(action.kind, "idle")


if __name__ == "__main__":
    unittest.main()
