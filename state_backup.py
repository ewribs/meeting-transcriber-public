"""Local backups of the app's own organising data.

Folders (meeting_folders.json) and saved sessions (query_sessions/*.json)
live next to the meeting archive. They are small but hold work that cannot
be regenerated (saved conversations, hand-built folders), so a copy is kept
on the local disk, away from the archive volume.

A snapshot is only written when something has changed since the last one,
and only the newest ``KEEP_SNAPSHOTS`` are kept. Backing up never changes or
deletes the originals.

Command line (from the repo root):

    python state_backup.py                 # back up now
    python state_backup.py --list          # list snapshots
    python state_backup.py --restore NAME  # show what a restore would do
    python state_backup.py --restore NAME --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

KEEP_SNAPSHOTS = 20
FOLDERS_NAME = "meeting_folders.json"
SESSIONS_NAME = "query_sessions"
MANIFEST_NAME = "manifest.json"


def _source_files(archive_dir: Path) -> dict[str, Path]:
    """Relative snapshot path -> source file, for everything worth saving."""
    files: dict[str, Path] = {}

    folders = archive_dir / FOLDERS_NAME
    if folders.is_file():
        files[FOLDERS_NAME] = folders

    sessions = archive_dir / SESSIONS_NAME
    if sessions.is_dir():
        for path in sorted(sessions.glob("*.json")):
            if path.is_file():
                files[f"{SESSIONS_NAME}/{path.name}"] = path

    return files


def _fingerprint(files: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(files[relative].read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def list_snapshots(backup_root: Path) -> list[Path]:
    """Snapshot directories, oldest first."""
    if not backup_root.is_dir():
        return []
    return sorted(
        path
        for path in backup_root.iterdir()
        if path.is_dir() and (path / MANIFEST_NAME).is_file()
    )


def _read_fingerprint(snapshot: Path) -> str | None:
    try:
        manifest = json.loads(
            (snapshot / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        return str(manifest.get("fingerprint"))
    except (OSError, ValueError):
        return None


def backup_state(
    archive_dir: Path,
    backup_root: Path,
    *,
    now: datetime | None = None,
    keep: int = KEEP_SNAPSHOTS,
) -> dict[str, Any]:
    """Snapshot folders and sessions if they changed. Never raises for a
    missing archive: that is reported as a skip so app start is not blocked.
    """
    archive_dir = Path(archive_dir).expanduser()
    backup_root = Path(backup_root).expanduser()

    if not archive_dir.is_dir():
        return {
            "schema_version": 1,
            "status": "skipped",
            "reason": "The archive folder is not available.",
            "files": 0,
            "snapshots": len(list_snapshots(backup_root)),
        }

    files = _source_files(archive_dir)

    if not files:
        return {
            "schema_version": 1,
            "status": "skipped",
            "reason": "There are no folders or sessions to back up yet.",
            "files": 0,
            "snapshots": len(list_snapshots(backup_root)),
        }

    fingerprint = _fingerprint(files)
    existing = list_snapshots(backup_root)

    if existing and _read_fingerprint(existing[-1]) == fingerprint:
        return {
            "schema_version": 1,
            "status": "unchanged",
            "reason": "Nothing has changed since the last backup.",
            "files": len(files),
            "snapshots": len(existing),
        }

    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    snapshot = backup_root / stamp
    suffix = 1
    while snapshot.exists():
        suffix += 1
        snapshot = backup_root / f"{stamp}-{suffix}"

    snapshot.mkdir(parents=True)

    for relative, source in files.items():
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # The manifest is written last, so a snapshot without one is an
    # unfinished copy and is ignored by list_snapshots.
    (snapshot / MANIFEST_NAME).write_text(
        json.dumps(
            {
                "fingerprint": fingerprint,
                "files": sorted(files),
                "created": stamp,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    existing = list_snapshots(backup_root)
    for old in existing[: max(0, len(existing) - keep)]:
        shutil.rmtree(old, ignore_errors=True)

    return {
        "schema_version": 1,
        "status": "created",
        "reason": f"Saved {len(files)} files.",
        "snapshot": snapshot.name,
        "files": len(files),
        "snapshots": len(list_snapshots(backup_root)),
    }


def restore_state(
    archive_dir: Path,
    backup_root: Path,
    name: str,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    """Copy a snapshot back over the live files.

    Dry run unless ``apply``. Before overwriting, the current state is
    snapshotted first so a restore can itself be undone.
    """
    archive_dir = Path(archive_dir).expanduser()
    backup_root = Path(backup_root).expanduser()
    snapshot = backup_root / name

    if not (snapshot / MANIFEST_NAME).is_file():
        raise FileNotFoundError(f"No backup named {name!r}.")

    manifest = json.loads(
        (snapshot / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    relatives = [str(item) for item in manifest.get("files", [])]

    result: dict[str, Any] = {
        "snapshot": name,
        "files": relatives,
        "applied": False,
    }

    if not apply:
        return result

    backup_state(archive_dir, backup_root)  # safety copy of "now"

    for relative in relatives:
        source = snapshot / relative
        target = archive_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    result["applied"] = True
    return result


def default_paths() -> tuple[Path, Path]:
    from config import ARCHIVE_DIR, PROJECT_DIR

    # Not under output/: the release audit treats every name in output/ as a
    # private meeting name, which would flag everyday words in the code.
    return Path(ARCHIVE_DIR), Path(PROJECT_DIR) / "local_backups"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Back up and restore folders and saved sessions."
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--restore", metavar="NAME")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    archive_dir, backup_root = default_paths()

    if args.list:
        snapshots = list_snapshots(backup_root)
        if not snapshots:
            print("No backups yet.")
        for snapshot in snapshots:
            print(snapshot.name)
        return 0

    if args.restore:
        try:
            result = restore_state(
                archive_dir,
                backup_root,
                args.restore,
                apply=args.apply,
            )
        except FileNotFoundError:
            print(f"No backup named {args.restore!r}.")
            print("Use one of these names (from --list):")
            for snapshot in list_snapshots(backup_root):
                print(f"  {snapshot.name}")
            return 1
        print(f"Backup: {result['snapshot']}")
        for relative in result["files"]:
            print(f"  {relative}")
        if result["applied"]:
            print("Restored. The previous state was backed up first.")
        else:
            print("Dry run only. Add --apply to restore these files.")
        return 0

    result = backup_state(archive_dir, backup_root)
    print(f"{result['status']}: {result['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
