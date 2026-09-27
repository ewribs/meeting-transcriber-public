from pathlib import Path
from typing import Callable

from cleanup_archived_m4as import cleanup_archived_m4as
from cleanup_old_m4as import cleanup_old_m4as
from config import (
    ARCHIVE_DIR,
    ARCHIVED_M4A_RETENTION_DAYS,
    M4A_RETENTION_DAYS,
)
from publisher import publish_meeting

ProgressCallback = Callable[[str, int], None]


def _report(
    callback: ProgressCallback | None,
    message: str,
    percent: int,
) -> None:
    if callback is None:
        return

    callback(
        message,
        max(0, min(100, int(percent))),
    )


def publish_and_archive_meeting(
    run_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """
    Publish one completed local meeting and then apply configured
    source-audio retention rules.

    The existing publisher remains the source of truth for archive copy,
    source-M4A verification, OneNote export, index/dashboard refresh,
    and WAV cleanup.
    """
    run_dir = Path(run_dir)

    _report(
        progress_callback,
        "Verifying publish prerequisites...",
        5,
    )

    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(
            f"Local meeting run not found: {run_dir}"
        )

    if not ARCHIVE_DIR.exists() or not ARCHIVE_DIR.is_dir():
        raise RuntimeError(
            f"Archive unavailable: {ARCHIVE_DIR}"
        )

    _report(
        progress_callback,
        "Publishing meeting to archive...",
        15,
    )

    archived_path = publish_meeting(
        run_dir,
    )

    _report(
        progress_callback,
        "Applying local M4A retention...",
        85,
    )

    local_retention = cleanup_old_m4as(
        days=M4A_RETENTION_DAYS,
        delete=True,
    )

    if ARCHIVED_M4A_RETENTION_DAYS == 0:
        archived_retention = {
            "deleted": 0,
            "deleted_bytes": 0,
            "skipped": [],
            "days": 0,
            "forever": True,
        }
    else:
        _report(
            progress_callback,
            "Applying archived M4A retention...",
            93,
        )

        archived_retention = cleanup_archived_m4as(
            days=ARCHIVED_M4A_RETENTION_DAYS,
            delete=True,
        )

    _report(
        progress_callback,
        "Publish & Archive complete.",
        100,
    )

    return {
        "archived_path": archived_path,
        "local_retention": local_retention,
        "archived_retention": archived_retention,
    }
