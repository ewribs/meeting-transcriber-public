from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from transcription_queue import TranscriptionQueueState


@dataclass(frozen=True)
class QueueAction:
    """Next workflow action selected from queue state.

    The GUI owns rendering and worker/thread lifecycle.  This object only
    communicates the orchestration decision so queue policy remains testable
    without Qt.
    """

    kind: str
    index: int | None = None
    run_dir: Path | None = None


class TranscriptionQueueOrchestrator:
    """Behavior-neutral workflow policy for the transcription queue."""

    def __init__(self, state: TranscriptionQueueState):
        self.state = state

    def start_next_transcription(self) -> QueueAction:
        next_index = self.state.next_waiting_index()
        if next_index is None:
            return QueueAction("finish")

        entry = self.state.begin_transcription(next_index)
        return QueueAction(
            "transcribe",
            index=next_index,
            run_dir=entry.get("run_dir"),
        )

    def after_transcription(
        self,
        *,
        auto_publish: bool,
    ) -> QueueAction:
        if not self.state.active:
            return QueueAction("idle")

        if (
            auto_publish
            and 0 <= self.state.index < len(self.state.entries)
        ):
            entry = self.state.entries[self.state.index]
            run_dir = entry.get("run_dir")
            if (
                entry.get("status") == "Ready to Publish"
                and run_dir is not None
            ):
                run_dir = Path(run_dir)
                self.state.begin_publish(run_dir)
                return QueueAction(
                    "publish",
                    index=self.state.index,
                    run_dir=run_dir,
                )

        return QueueAction("continue")

    def after_publish(
        self,
        *,
        mode: str | None,
    ) -> QueueAction:
        if mode == "auto" and self.state.active:
            return QueueAction("continue")

        if mode == "bulk":
            return QueueAction("continue_bulk")

        return QueueAction("idle")
