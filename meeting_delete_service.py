from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_settings import load_app_settings
from config import ARCHIVE_DIR, MEETINGS_DIR, OUTPUT_DIR




def _clean_optional_path_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower() in {"n/a", "na", "none", "null", "unknown", "-"}:
        return None
    return text

def _load_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "meeting_metadata.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _run_source_stem(run: str) -> str:
    parts = run.split("_", 2)
    return parts[2] if len(parts) == 3 else run


def _candidate_source_paths(
    *,
    run: str,
    metadata: dict[str, Any],
    recordings_dir: Path | None,
    meetings_dir: Path,
) -> list[Path]:
    candidates: list[Path] = []

    source_path = _clean_optional_path_text(metadata.get("source_path"))
    if source_path is not None:
        candidates.append(Path(source_path).expanduser())

    stem = _run_source_stem(run)
    for directory in (recordings_dir, meetings_dir):
        if directory is None:
            continue
        candidates.append(Path(directory).expanduser() / f"{stem}.m4a")

    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _configured_recordings_dir() -> Path | None:
    configured = _clean_optional_path_text(
        load_app_settings().get("recordings_dir")
    )
    return Path(configured).expanduser() if configured is not None else None


def _is_managed_recording(source: Path | None, recordings_dir: Path | None) -> bool:
    if source is None or recordings_dir is None:
        return False
    try:
        source.resolve().relative_to(recordings_dir.resolve())
        return True
    except (OSError, ValueError):
        return False


def _session_reference_names(run: str, *, archive_dir: Path = ARCHIVE_DIR) -> list[str]:
    sessions_dir = Path(archive_dir).expanduser() / "query_sessions"
    if not sessions_dir.exists():
        return []

    names: list[str] = []
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if run in payload.get("meeting_runs", []):
            names.append(str(payload.get("session_name") or path.stem))
    return names


def remove_meeting_from_saved_sessions(
    run: str,
    *,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict[str, Any]:
    """Remove one meeting_run from every saved Session that references it.

    Conversation history and selection criteria are preserved. Any cached
    Changes result is dropped for an affected Session because its meeting set
    has changed.
    """
    sessions_dir = Path(archive_dir).expanduser() / "query_sessions"
    changed: list[str] = []
    if not sessions_dir.exists():
        return {"updated_sessions": changed, "updated_session_count": 0}

    for path in sorted(sessions_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        runs = payload.get("meeting_runs", [])
        if not isinstance(runs, list) or run not in runs:
            continue

        payload["meeting_runs"] = [item for item in runs if item != run]
        payload.pop("changes_cache", None)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        changed.append(str(payload.get("session_name") or path.stem))

    return {
        "updated_sessions": changed,
        "updated_session_count": len(changed),
    }


def resolve_unpublished_meeting_delete_plan(
    run: str,
    *,
    output_dir: Path = OUTPUT_DIR,
    recordings_dir: Path | None = None,
    meetings_dir: Path = MEETINGS_DIR,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict[str, Any]:
    output_dir = Path(output_dir).expanduser()
    run_dir = output_dir / run

    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Unpublished meeting run not found: {run}")

    metadata = _load_metadata(run_dir)
    if metadata:
        meeting_run = str(metadata.get("meeting_run") or run).strip()
        if meeting_run != run:
            raise ValueError(
                f"Meeting metadata run mismatch: expected {run}, found {meeting_run}"
            )

    if recordings_dir is None:
        recordings_dir = _configured_recordings_dir()

    source_path: Path | None = None
    for candidate in _candidate_source_paths(
        run=run,
        metadata=metadata,
        recordings_dir=recordings_dir,
        meetings_dir=Path(meetings_dir),
    ):
        try:
            if candidate.exists() and candidate.is_file():
                source_path = candidate.resolve()
                break
        except OSError:
            continue

    session_names = _session_reference_names(run, archive_dir=archive_dir)

    return {
        "schema_version": 2,
        "run": run,
        "run_path": str(run_dir.resolve()),
        "source_path": str(source_path) if source_path else None,
        "source_found": source_path is not None,
        "source_is_managed": _is_managed_recording(source_path, recordings_dir),
        "display_title": str(metadata.get("display_title") or run).strip(),
        "session_reference_count": len(session_names),
        "session_reference_names": session_names,
    }


def finalize_unpublished_meeting_delete(
    run: str,
    *,
    output_dir: Path = OUTPUT_DIR,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict[str, Any]:
    """Finalize bookkeeping after Swift has moved the run folder to Trash."""
    run_dir = Path(output_dir).expanduser() / run
    if run_dir.exists():
        raise RuntimeError(
            "Meeting output folder still exists. Move it to the macOS Trash before finalizing deletion."
        )

    session_result = remove_meeting_from_saved_sessions(
        run,
        archive_dir=archive_dir,
    )
    return {
        "schema_version": 1,
        "run": run,
        "deleted": True,
        "run_path": str(run_dir),
        **session_result,
    }


def resolve_published_meeting_unpublish_plan(
    run: str,
    *,
    archive_dir: Path = ARCHIVE_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    archive_dir = Path(archive_dir).expanduser()
    output_dir = Path(output_dir).expanduser()
    archive_run = archive_dir / run
    local_run = output_dir / run

    if not archive_run.exists() or not archive_run.is_dir():
        raise FileNotFoundError(f"Published archive run not found: {run}")
    if not local_run.exists() or not local_run.is_dir():
        raise RuntimeError(
            "This published meeting has no local output copy to return to Unpublished status. "
            "Restore the local run before unpublishing."
        )

    metadata = _load_metadata(archive_run)
    session_names = _session_reference_names(run, archive_dir=archive_dir)
    return {
        "schema_version": 1,
        "run": run,
        "archive_path": str(archive_run.resolve()),
        "local_run_path": str(local_run.resolve()),
        "display_title": str(metadata.get("display_title") or run).strip(),
        "session_reference_count": len(session_names),
        "session_reference_names": session_names,
    }


def finalize_published_meeting_unpublish(
    run: str,
    *,
    archive_dir: Path = ARCHIVE_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    """Refresh published indexes after Swift moves the archive folder to Trash."""
    archive_dir = Path(archive_dir).expanduser()
    output_dir = Path(output_dir).expanduser()
    archive_run = archive_dir / run
    local_run = output_dir / run

    if archive_run.exists():
        raise RuntimeError(
            "Published archive folder still exists. Move it to the macOS Trash before finalizing unpublish."
        )
    if not local_run.exists() or not local_run.is_dir():
        raise RuntimeError(
            "Local meeting output is missing; refusing to finalize unpublish."
        )

    from dashboard_generator import build_meeting_dashboard
    from indexer import build_meeting_index

    index_path = build_meeting_index(archive_dir)
    build_meeting_dashboard(index_path)
    session_result = remove_meeting_from_saved_sessions(run, archive_dir=archive_dir)

    return {
        "schema_version": 1,
        "run": run,
        "unpublished": True,
        "local_run_path": str(local_run.resolve()),
        **session_result,
    }
