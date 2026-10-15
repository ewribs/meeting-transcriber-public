"""Lightweight folders for organising meetings (no conversation, no rules).

Stored as one JSON file next to the saved sessions, keyed by meeting_run, so
meeting rebuilds (which rewrite meeting_metadata.json) never touch it.
A meeting may be in more than one folder.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

MAX_NAME_LENGTH = 80


class FolderError(Exception):
    pass


class DuplicateFolderError(FolderError):
    pass


class FolderNotFoundError(FolderError):
    pass


def _clean_name(name: str) -> str:
    cleaned = " ".join(str(name).split())

    if not cleaned:
        raise FolderError("Enter a folder name.")

    if len(cleaned) > MAX_NAME_LENGTH:
        raise FolderError(
            f"Folder names can be at most {MAX_NAME_LENGTH} characters."
        )

    return cleaned


def _clean_runs(runs: Iterable[str]) -> list[str]:
    result: list[str] = []

    for run in runs:
        text = str(run).strip()
        if text and text not in result:
            result.append(text)

    return result


def load_folders(path: Path) -> list[dict]:
    """Return [{"name", "meeting_runs"}]. Missing file means no folders.

    An unreadable file raises, so a later write can never overwrite it.
    """
    path = Path(path)

    if not path.exists():
        return []

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload["folders"]
        folders = [
            {
                "name": str(item["name"]),
                "meeting_runs": _clean_runs(item.get("meeting_runs", [])),
            }
            for item in raw
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FolderError(
            f"The folders file could not be read ({path.name}). "
            "It was left untouched."
        ) from exc

    return folders


def _save(path: Path, folders: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handle, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=".folders-", suffix=".tmp"
    )

    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump({"folders": folders}, file, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _find(folders: list[dict], name: str) -> dict:
    target = name.strip().casefold()

    for folder in folders:
        if folder["name"].casefold() == target:
            return folder

    raise FolderNotFoundError(f"Folder not found: {name}")


def _exists(folders: list[dict], name: str, *, ignore: str | None = None) -> bool:
    target = name.casefold()
    skip = ignore.casefold() if ignore else None

    return any(
        folder["name"].casefold() == target
        and folder["name"].casefold() != skip
        for folder in folders
    )


def create_folder(path: Path, name: str) -> list[dict]:
    folders = load_folders(path)
    clean = _clean_name(name)

    if _exists(folders, clean):
        raise DuplicateFolderError(f"A folder named “{clean}” already exists.")

    folders.append({"name": clean, "meeting_runs": []})
    _save(path, folders)
    return folders


def rename_folder(path: Path, old_name: str, new_name: str) -> list[dict]:
    folders = load_folders(path)
    folder = _find(folders, old_name)
    clean = _clean_name(new_name)

    if _exists(folders, clean, ignore=folder["name"]):
        raise DuplicateFolderError(f"A folder named “{clean}” already exists.")

    folder["name"] = clean
    _save(path, folders)
    return folders


def delete_folder(path: Path, name: str) -> list[dict]:
    """Delete the folder only; the meetings themselves are untouched."""
    folders = load_folders(path)
    folder = _find(folders, name)
    folders.remove(folder)
    _save(path, folders)
    return folders


def reorder_folders(path: Path, names: Iterable[str]) -> list[dict]:
    """Put folders in the given order. Names not listed keep their relative
    order after the listed ones; unknown names are ignored."""
    folders = load_folders(path)
    by_key = {folder["name"].casefold(): folder for folder in folders}

    ordered: list[dict] = []
    seen: set[str] = set()

    for name in names:
        key = str(name).strip().casefold()
        folder = by_key.get(key)

        if folder is not None and key not in seen:
            ordered.append(folder)
            seen.add(key)

    ordered.extend(
        folder for folder in folders if folder["name"].casefold() not in seen
    )

    if ordered != folders:
        _save(path, ordered)

    return ordered


def add_meetings(path: Path, name: str, runs: Iterable[str]) -> list[dict]:
    folders = load_folders(path)
    folder = _find(folders, name)

    for run in _clean_runs(runs):
        if run not in folder["meeting_runs"]:
            folder["meeting_runs"].append(run)

    _save(path, folders)
    return folders


def remove_meetings(path: Path, name: str, runs: Iterable[str]) -> list[dict]:
    folders = load_folders(path)
    folder = _find(folders, name)
    drop = set(_clean_runs(runs))
    folder["meeting_runs"] = [
        run for run in folder["meeting_runs"] if run not in drop
    ]
    _save(path, folders)
    return folders
