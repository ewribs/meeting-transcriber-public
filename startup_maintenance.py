from __future__ import annotations

from typing import Callable

from cleanup_archived_m4as import cleanup_archived_m4as
from cleanup_old_m4as import cleanup_old_m4as
from config import ARCHIVED_M4A_RETENTION_DAYS, M4A_RETENTION_DAYS

CleanupFn = Callable[..., dict]


def _summary(result: dict) -> dict:
    return {
        "days": int(result.get("days", 0)),
        "forever": bool(result.get("forever", False)),
        "eligible": len(result.get("eligible", [])),
        "skipped": len(result.get("skipped", [])),
        "deleted": int(result.get("deleted", 0)),
        "deleted_bytes": int(result.get("deleted_bytes", 0)),
    }


def run_startup_retention(
    *,
    local_days: int = M4A_RETENTION_DAYS,
    archived_days: int = ARCHIVED_M4A_RETENTION_DAYS,
    local_cleanup: CleanupFn = cleanup_old_m4as,
    archived_cleanup: CleanupFn = cleanup_archived_m4as,
) -> dict:
    """Apply configured audio retention without making app startup fail.

    The cleanup functions remain the source of truth for safety checks. This
    wrapper intentionally converts failures into warnings so a missing archive
    volume or another maintenance problem never blocks the UI from launching.
    """
    warnings: list[str] = []

    try:
        local_result = local_cleanup(
            days=local_days,
            delete=True,
        )
        local = _summary(local_result)
    except Exception as exc:  # startup maintenance must be non-fatal
        local = {
            "days": int(local_days),
            "forever": False,
            "eligible": 0,
            "skipped": 0,
            "deleted": 0,
            "deleted_bytes": 0,
        }
        warnings.append(
            f"Local M4A retention skipped: {type(exc).__name__}: {exc}"
        )

    if archived_days == 0:
        archived = {
            "days": 0,
            "forever": True,
            "eligible": 0,
            "skipped": 0,
            "deleted": 0,
            "deleted_bytes": 0,
        }
    else:
        try:
            archived_result = archived_cleanup(
                days=archived_days,
                delete=True,
            )
            archived = _summary(archived_result)
        except Exception as exc:  # startup maintenance must be non-fatal
            archived = {
                "days": int(archived_days),
                "forever": False,
                "eligible": 0,
                "skipped": 0,
                "deleted": 0,
                "deleted_bytes": 0,
            }
            warnings.append(
                f"Archived M4A retention skipped: {type(exc).__name__}: {exc}"
            )

    return {
        "schema_version": 1,
        "local": local,
        "archived": archived,
        "warnings": warnings,
    }
