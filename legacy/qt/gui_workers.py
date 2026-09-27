
# Allow direct execution after repository reorganization.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os
import time

from contextlib import redirect_stdout
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from execution_telemetry import record_execution_telemetry
from publish_workflow import publish_and_archive_meeting
from query.chat import run_query
from transcribe import transcribe_meeting


class QueryWorker(QObject):
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(
        self,
        user_prompt: str,
        merged_memory: dict,
        conversation_history: list[dict],
        meeting_memories: list[tuple[str, dict]] | None = None,
        selected_meetings: list[dict] | None = None,
        topic_filter: str | None = None,
        execution_profile: str = "Balanced",
    ):
        super().__init__()

        self.user_prompt = user_prompt
        self.merged_memory = merged_memory
        self.conversation_history = conversation_history
        self.meeting_memories = meeting_memories
        self.selected_meetings = selected_meetings
        self.topic_filter = topic_filter
        self.execution_profile = execution_profile

    def run(self):
        started_at = time.perf_counter()

        try:
            response, execution_metadata = run_query(
                self.user_prompt,
                self.merged_memory,
                self.conversation_history,
                include_grounded=True,
                print_output=False,
                meeting_memories=self.meeting_memories,
                selected_meetings=self.selected_meetings,
                topic_filter=self.topic_filter,
                return_execution_metadata=True,
                execution_profile=self.execution_profile,
            )

            elapsed_seconds = time.perf_counter() - started_at

            record_execution_telemetry(
                execution_metadata,
                elapsed_seconds=elapsed_seconds,
            )

            self.finished.emit(
                response,
                execution_metadata,
            )

        except Exception as exc:
            self.failed.emit(str(exc))


class TranscriptionWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, source_path: Path):
        super().__init__()
        self.source_path = Path(source_path)

    def _report_progress(
        self,
        message: str,
        percent: int,
    ):
        self.progress.emit(message, percent)

    def run(self):
        try:
            # GUI runs keep routine pipeline logging out of Terminal.
            # Direct ``python transcribe.py`` execution remains verbose.
            with open(
                os.devnull,
                "w",
                encoding="utf-8",
            ) as devnull:
                with redirect_stdout(devnull):
                    run_dir = transcribe_meeting(
                        self.source_path,
                        progress_callback=self._report_progress,
                    )

            self.finished.emit(str(run_dir))

        except Exception as exc:
            self.failed.emit(str(exc))


class PublishWorker(QObject):
    progress = Signal(str, int)
    finished = Signal(str, object)
    failed = Signal(str)

    def __init__(self, run_dir: Path):
        super().__init__()
        self.run_dir = Path(run_dir)

    def _report_progress(
        self,
        message: str,
        percent: int,
    ):
        self.progress.emit(message, percent)

    def run(self):
        try:
            # GUI publishing stays quiet in Terminal while the existing
            # command-line publisher remains verbose.
            with open(
                os.devnull,
                "w",
                encoding="utf-8",
            ) as devnull:
                with redirect_stdout(devnull):
                    result = publish_and_archive_meeting(
                        self.run_dir,
                        progress_callback=self._report_progress,
                    )

            archived_path = Path(result["archived_path"])

            self.finished.emit(
                str(archived_path),
                result,
            )

        except Exception as exc:
            self.failed.emit(str(exc))
