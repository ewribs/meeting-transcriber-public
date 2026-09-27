from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptionQueueState:
    """Behavior-neutral state container for the Transcribe queue.

    The GUI remains responsible for presentation and worker orchestration.
    This object owns queue entries, counters, and status transitions so those
    mutable workflow details are no longer scattered across gui.py.
    """

    entries: list[dict] = field(default_factory=list)
    active: bool = False
    index: int = -1
    successes: int = 0
    failures: int = 0
    publish_successes: int = 0
    publish_failures: int = 0
    attempted: int = 0

    def reset_counters(self) -> None:
        self.index = -1
        self.successes = 0
        self.failures = 0
        self.publish_successes = 0
        self.publish_failures = 0
        self.attempted = 0

    def clear(self) -> None:
        self.entries.clear()
        self.active = False
        self.reset_counters()

    def clear_completed_batch_if_terminal(self) -> bool:
        if not self.entries:
            return False
        terminal = {"Ready to Publish", "Failed", "Published", "Publish Failed"}
        if not all(entry.get("status") in terminal for entry in self.entries):
            return False
        self.clear()
        return True

    def add_sources(self, source_paths: list[Path]) -> int:
        existing = {
            str(Path(item["source_path"]).resolve())
            for item in self.entries
        }
        added = 0
        for source_path in source_paths:
            source_path = Path(source_path)
            resolved = str(source_path.resolve())
            if resolved in existing:
                continue
            self.entries.append(
                {
                    "source_path": source_path,
                    "status": "Waiting",
                    "run_dir": None,
                    "error": None,
                }
            )
            existing.add(resolved)
            added += 1
        return added

    def remove(self, row: int) -> bool:
        if not (0 <= row < len(self.entries)):
            return False
        self.entries.pop(row)
        self.index = -1
        return True

    def clear_completed(self) -> int:
        removable = {"Published", "Ready to Publish"}
        before = len(self.entries)
        self.entries[:] = [
            entry
            for entry in self.entries
            if entry.get("status") not in removable
        ]
        self.index = -1
        return before - len(self.entries)

    def retry_failures(self) -> tuple[int, int]:
        reset_transcription = 0
        reset_publish = 0
        for entry in self.entries:
            status = entry.get("status")
            if status == "Failed":
                entry["status"] = "Waiting"
                entry["error"] = None
                entry["run_dir"] = None
                reset_transcription += 1
            elif status == "Publish Failed":
                entry["status"] = "Ready to Publish"
                entry["error"] = None
                reset_publish += 1
        if reset_transcription or reset_publish:
            self.index = -1
            self.failures = 0
            self.publish_failures = 0
        return reset_transcription, reset_publish

    def statuses(self) -> set[str | None]:
        return {entry.get("status") for entry in self.entries}

    def has_waiting(self) -> bool:
        return any(entry.get("status") == "Waiting" for entry in self.entries)

    def waiting_entries(self) -> list[dict]:
        return [entry for entry in self.entries if entry.get("status") == "Waiting"]

    def next_waiting_index(self) -> int | None:
        for index in range(self.index + 1, len(self.entries)):
            if self.entries[index].get("status") == "Waiting":
                return index
        return None

    def begin_run(self) -> None:
        self.active = True
        self.reset_counters()

    def begin_transcription(self, index: int) -> dict:
        self.index = index
        self.attempted += 1
        entry = self.entries[index]
        entry["status"] = "Transcribing"
        entry["error"] = None
        return entry

    def mark_transcription_success(self, run_dir: Path) -> dict | None:
        if not (0 <= self.index < len(self.entries)):
            return None
        entry = self.entries[self.index]
        entry["status"] = "Ready to Publish"
        entry["run_dir"] = Path(run_dir)
        entry["error"] = None
        self.successes += 1
        return entry

    def mark_transcription_failure(self, error: str) -> dict | None:
        if not (0 <= self.index < len(self.entries)):
            return None
        entry = self.entries[self.index]
        entry["status"] = "Failed"
        entry["error"] = error
        self.failures += 1
        return entry

    def find_by_run(self, run_dir: Path) -> dict | None:
        target = str(Path(run_dir).resolve())
        for entry in self.entries:
            candidate = entry.get("run_dir")
            if candidate is None:
                continue
            if str(Path(candidate).resolve()) == target:
                return entry
        return None

    def begin_publish(self, run_dir: Path) -> dict | None:
        entry = self.find_by_run(run_dir)
        if entry is not None:
            entry["status"] = "Publishing"
            entry["error"] = None
        return entry

    def mark_publish_success(self, run_dir: Path) -> dict | None:
        entry = self.find_by_run(run_dir)
        if entry is not None:
            entry["status"] = "Published"
            entry["error"] = None
        self.publish_successes += 1
        return entry

    def mark_publish_failure(self, run_dir: Path, error: str) -> dict | None:
        entry = self.find_by_run(run_dir)
        if entry is not None:
            entry["status"] = "Publish Failed"
            entry["error"] = error
        self.publish_failures += 1
        return entry
