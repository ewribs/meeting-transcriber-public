#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import shutil

from contextlib import redirect_stdout
from pathlib import Path
from typing import Callable


_EVENT_STREAM = sys.stdout
_ACTIVE_RUN_DIR: Path | None = None



def _safe_cleanup_partial_run() -> None:
    global _ACTIVE_RUN_DIR

    run_dir = _ACTIVE_RUN_DIR

    if run_dir is None:
        return

    try:
        from config import OUTPUT_DIR

        output_root = Path(
            OUTPUT_DIR
        ).resolve()

        candidate = Path(
            run_dir
        ).resolve()

        if candidate == output_root:
            return

        if output_root not in candidate.parents:
            return

        if candidate.exists():
            shutil.rmtree(candidate)

    finally:
        _ACTIVE_RUN_DIR = None


def _handle_termination(
    signum,
    frame,
) -> None:
    _safe_cleanup_partial_run()
    raise SystemExit(130)


signal.signal(
    signal.SIGTERM,
    _handle_termination,
)


def emit_event(
    event_type: str,
    *,
    stage: str | None = None,
    message: str | None = None,
    percent: int | None = None,
    run_dir: Path | None = None,
    status: str | None = None,
    archived_path: Path | None = None,
    error: str | None = None,
) -> None:
    payload = {
        "type": event_type,
    }

    if stage is not None:
        payload["stage"] = stage

    if message is not None:
        payload["message"] = message

    if percent is not None:
        payload["percent"] = max(
            0,
            min(100, int(percent)),
        )

    if run_dir is not None:
        payload["run_dir"] = str(
            Path(run_dir)
        )

    if status is not None:
        payload["status"] = status

    if archived_path is not None:
        payload["archived_path"] = str(
            Path(archived_path)
        )

    if error is not None:
        payload["error"] = str(error)

    _EVENT_STREAM.write(
        json.dumps(
            payload,
            ensure_ascii=False,
        )
        + "\n"
    )
    _EVENT_STREAM.flush()


def _progress_callback(
    stage: str,
) -> Callable[[str, int], None]:
    def callback(
        message: str,
        percent: int,
    ) -> None:
        emit_event(
            "progress",
            stage=stage,
            message=message,
            percent=percent,
        )

    return callback


def transcribe_recording(
    source_path: Path,
    *,
    auto_publish: bool,
) -> dict:
    from transcribe import transcribe_meeting

    source_path = Path(source_path)

    emit_event(
        "started",
        stage="transcribe",
        message=(
            f"Starting {source_path.name}"
        ),
        percent=0,
    )

    marker_path = source_path.parent / (
        ".meeting_transcriber_active_run"
    )

    os.environ[
        "MEETING_TRANSCRIBER_ACTIVE_RUN_FILE"
    ] = str(marker_path)

    try:
        with open(
            os.devnull,
            "w",
            encoding="utf-8",
        ) as devnull:
            with redirect_stdout(devnull):
                run_dir = transcribe_meeting(
                    source_path,
                    progress_callback=(
                        _progress_callback(
                            "transcribe"
                        )
                    ),
                )

    except SystemExit:
        if marker_path.exists():
            try:
                active_text = marker_path.read_text(
                    encoding="utf-8"
                ).strip()

                if active_text:
                    global _ACTIVE_RUN_DIR
                    _ACTIVE_RUN_DIR = Path(
                        active_text
                    )
            except OSError:
                pass

        _safe_cleanup_partial_run()

        try:
            marker_path.unlink(
                missing_ok=True
            )
        except OSError:
            pass

        raise

    except Exception as exc:
        emit_event(
            "failed",
            stage="transcribe",
            message="Transcription failed.",
            error=str(exc),
            status="Failed",
        )
        return {
            "status": "Failed",
            "error": str(exc),
        }

    run_dir = Path(run_dir)

    try:
        marker_path.unlink(
            missing_ok=True
        )
    except OSError:
        pass

    emit_event(
        "transcribed",
        stage="transcribe",
        message=(
            f"Transcription complete: "
            f"{run_dir.name}"
        ),
        percent=100,
        run_dir=run_dir,
        status="Ready to Publish",
    )

    if not auto_publish:
        emit_event(
            "completed",
            stage="transcribe",
            message=(
                "Transcription complete. "
                "Meeting is Unpublished."
            ),
            percent=100,
            run_dir=run_dir,
            status="Ready to Publish",
        )
        return {
            "status": "Ready to Publish",
            "run_dir": run_dir,
        }

    return publish_existing_run(
        run_dir,
    )


def publish_existing_run(
    run_dir: Path,
) -> dict:
    from publish_workflow import (
        publish_and_archive_meeting,
    )

    run_dir = Path(run_dir)

    emit_event(
        "publish_started",
        stage="publish",
        message=(
            f"Publishing {run_dir.name}..."
        ),
        percent=0,
        run_dir=run_dir,
        status="Publishing",
    )

    try:
        with open(
            os.devnull,
            "w",
            encoding="utf-8",
        ) as devnull:
            with redirect_stdout(devnull):
                result = (
                    publish_and_archive_meeting(
                        run_dir,
                        progress_callback=(
                            _progress_callback(
                                "publish"
                            )
                        ),
                    )
                )

    except Exception as exc:
        emit_event(
            "publish_failed",
            stage="publish",
            message="Publish failed.",
            run_dir=run_dir,
            status="Publish Failed",
            error=str(exc),
        )
        return {
            "status": "Publish Failed",
            "run_dir": run_dir,
            "error": str(exc),
        }

    archived_path = Path(
        result["archived_path"]
    )

    emit_event(
        "completed",
        stage="publish",
        message=(
            f"Published successfully: "
            f"{archived_path.name}"
        ),
        percent=100,
        run_dir=run_dir,
        archived_path=archived_path,
        status="Published",
    )

    return {
        "status": "Published",
        "run_dir": run_dir,
        "archived_path": archived_path,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Streaming bridge for Swift "
            "transcription workflows."
        )
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    process_parser = subparsers.add_parser(
        "process",
        help=(
            "Transcribe one recording and "
            "optionally publish it."
        ),
    )
    process_parser.add_argument(
        "source_path"
    )
    process_parser.add_argument(
        "--auto-publish",
        action="store_true",
    )

    publish_parser = subparsers.add_parser(
        "publish",
        help=(
            "Retry publish for an existing "
            "completed local run."
        ),
    )
    publish_parser.add_argument(
        "run_dir"
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.command == "process":
        transcribe_recording(
            Path(args.source_path),
            auto_publish=bool(
                args.auto_publish
            ),
        )
        return 0

    if args.command == "publish":
        publish_existing_run(
            Path(args.run_dir)
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
