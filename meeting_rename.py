"""Rename how a meeting is displayed, without touching its identity.

A meeting's folder name (its "run") is its stable ID: folders, sessions,
the archive and the search index all refer to it. So renaming only changes
the ``display_title`` stored in ``meeting_metadata.json``. The title is
marked as custom so later rebuilds of the metadata do not overwrite it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_TITLE_LENGTH = 200


class MeetingRenameError(ValueError):
    pass


def clean_title(title: str) -> str:
    text = " ".join(str(title or "").split())

    if not text:
        raise MeetingRenameError("Enter a meeting name.")

    if len(text) > MAX_TITLE_LENGTH:
        raise MeetingRenameError(
            f"Meeting names are limited to {MAX_TITLE_LENGTH} characters."
        )

    return text


def _write_json_atomically(path: Path, payload: Any) -> None:
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".rename-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _rename_in(run_dir: Path, title: str) -> bool:
    path = run_dir / "meeting_metadata.json"

    if not path.is_file():
        return False

    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MeetingRenameError(
            f"Could not read the meeting's metadata: {exc}"
        ) from exc

    if not isinstance(metadata, dict):
        raise MeetingRenameError("The meeting's metadata is not valid.")

    metadata["display_title"] = title
    metadata["title_custom"] = True
    _write_json_atomically(path, metadata)
    return True


def rename_meeting(
    run: str,
    new_title: str,
    *,
    archive_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Set the display title of a meeting everywhere it is stored."""
    title = clean_title(new_title)
    run = str(run or "").strip()

    if not run or "/" in run or run in {".", ".."}:
        raise MeetingRenameError("Unknown meeting.")

    archive_run = Path(archive_dir).expanduser() / run
    local_run = Path(output_dir).expanduser() / run

    in_archive = _rename_in(archive_run, title)
    in_local = _rename_in(local_run, title)

    if not in_archive and not in_local:
        raise MeetingRenameError("That meeting could not be found.")

    if in_archive:
        from dashboard_generator import build_meeting_dashboard
        from indexer import build_meeting_index

        index_path = build_meeting_index(Path(archive_dir).expanduser())
        build_meeting_dashboard(index_path)

    return {
        "schema_version": 1,
        "run": run,
        "title": title,
        "published": in_archive,
    }
