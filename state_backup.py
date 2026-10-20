"""Local backups of the app's own organising data and local-only files.

Two kinds of things are saved, because neither can be regenerated and git does
not protect them:

* Folders (meeting_folders.json), the manual sidebar order and saved sessions
  (query_sessions/*.json) that live next to the meeting archive.
* Local-only project files: your private ignore list (.git/info/exclude), the
  tools/mt and release helpers, and the *.local.json settings files.

A snapshot is written to the local disk only when something has changed since
the last one, and only the newest ``KEEP_SNAPSHOTS`` are kept. Backing up never
changes or deletes the originals.

Optionally each snapshot is also copied to a second folder (for example on a
NAS) so a lost disk does not lose the backups. Set it once with --set-mirror.

Command line (from the repo root):

    python state_backup.py                 # back up now
    python state_backup.py --list          # list snapshots
    python state_backup.py --restore NAME  # show what a restore would do
    python state_backup.py --restore NAME --apply
    python state_backup.py --set-mirror PATH   # also copy snapshots there
    python state_backup.py --clear-mirror      # stop copying
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

KEEP_SNAPSHOTS = 20
KEEP_MIRROR_SNAPSHOTS = 60
FOLDERS_NAME = "meeting_folders.json"
ORDER_NAME = "sidebar_order.json"
SESSIONS_NAME = "query_sessions"
MANIFEST_NAME = "manifest.json"
PROJECT_PREFIX = "project/"

# Local-only files that live in the project folder (relative paths).
PROJECT_FILES = (
    ".git/info/exclude",
    "tools/mt",
    "tools/release_sync_local.sh",
    "tools/create_source_snapshot.py",
    "release_audit.local.json",
    "identity.local.json",
    "business_context.local.json",
    "known_people.json",
    "sanitize_names.local.json",
    "benchmark_meetings.local.json",
)
PROJECT_GLOBS = ("tools/*_local.py",)


def _source_files(
    archive_dir: Path | None,
    project_dir: Path | None = None,
) -> dict[str, Path]:
    """Relative snapshot path -> source file, for everything worth saving."""
    files: dict[str, Path] = {}

    if archive_dir is not None and Path(archive_dir).is_dir():
        archive_dir = Path(archive_dir)

        folders = archive_dir / FOLDERS_NAME
        if folders.is_file():
            files[FOLDERS_NAME] = folders

        order = archive_dir / ORDER_NAME
        if order.is_file():
            files[ORDER_NAME] = order

        sessions = archive_dir / SESSIONS_NAME
        if sessions.is_dir():
            for path in sorted(sessions.glob("*.json")):
                if path.is_file():
                    files[f"{SESSIONS_NAME}/{path.name}"] = path

    if project_dir is not None and Path(project_dir).is_dir():
        project_dir = Path(project_dir)
        wanted = list(PROJECT_FILES)

        for pattern in PROJECT_GLOBS:
            wanted.extend(
                str(path.relative_to(project_dir))
                for path in sorted(project_dir.glob(pattern))
            )

        for relative in wanted:
            path = project_dir / relative
            if path.is_file():
                files[PROJECT_PREFIX + relative] = path

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
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / MANIFEST_NAME).is_file()
    )


def _read_fingerprint(snapshot: Path) -> str | None:
    try:
        manifest = json.loads(
            (snapshot / MANIFEST_NAME).read_text(encoding="utf-8")
        )
        return str(manifest.get("fingerprint"))
    except (OSError, ValueError):
        return None


def _mirror_problem(mirror_dir: Path) -> str | None:
    """Why the mirror cannot be used right now, or None if it is ready."""
    parts = mirror_dir.parts

    # An unmounted network share leaves an empty folder behind; refuse to
    # write into that instead of silently filling the local disk.
    if len(parts) >= 3 and parts[1] == "Volumes":
        if not os.path.ismount(Path(*parts[:3])):
            return "The backup volume is not connected."

    if not mirror_dir.is_dir():
        return "The backup folder does not exist. Create it first."

    return None


def sync_mirror(
    backup_root: Path,
    mirror_dir: Path | None,
    *,
    keep: int = KEEP_MIRROR_SNAPSHOTS,
) -> dict[str, Any]:
    """Copy snapshots missing from the mirror. Never raises."""
    if not mirror_dir:
        return {"status": "off", "reason": "No second backup folder is set."}

    mirror_dir = Path(mirror_dir).expanduser()
    problem = _mirror_problem(mirror_dir)

    if problem:
        return {"status": "skipped", "reason": problem}

    try:
        existing = {path.name for path in list_snapshots(mirror_dir)}
        copied = 0

        for snapshot in list_snapshots(backup_root):
            if snapshot.name in existing:
                continue

            partial = mirror_dir / f".partial-{snapshot.name}"
            if partial.exists():
                shutil.rmtree(partial, ignore_errors=True)

            shutil.copytree(snapshot, partial)
            os.replace(partial, mirror_dir / snapshot.name)
            copied += 1

        snapshots = list_snapshots(mirror_dir)
        for old in snapshots[: max(0, len(snapshots) - keep)]:
            shutil.rmtree(old, ignore_errors=True)

        return {
            "status": "synced",
            "reason": f"Copied {copied} snapshot(s).",
            "copied": copied,
        }
    except OSError as exc:
        return {"status": "error", "reason": str(exc)}


def backup_state(
    archive_dir: Path | None,
    backup_root: Path,
    *,
    project_dir: Path | None = None,
    mirror_dir: Path | None = None,
    now: datetime | None = None,
    keep: int = KEEP_SNAPSHOTS,
    mirror_keep: int = KEEP_MIRROR_SNAPSHOTS,
) -> dict[str, Any]:
    """Snapshot folders, sessions and local files if they changed.

    Never raises for a missing archive or mirror: that is reported as a skip so
    app start is not blocked.
    """
    archive_dir = Path(archive_dir).expanduser() if archive_dir else None
    backup_root = Path(backup_root).expanduser()
    project_dir = Path(project_dir).expanduser() if project_dir else None

    files = _source_files(archive_dir, project_dir)

    if not files:
        reason = (
            "The archive folder is not available."
            if archive_dir is not None and not archive_dir.is_dir()
            else "There is nothing to back up yet."
        )
        return {
            "schema_version": 2,
            "status": "skipped",
            "reason": reason,
            "files": 0,
            "snapshots": len(list_snapshots(backup_root)),
            "mirror": sync_mirror(backup_root, mirror_dir, keep=mirror_keep),
        }

    fingerprint = _fingerprint(files)
    existing = list_snapshots(backup_root)

    if existing and _read_fingerprint(existing[-1]) == fingerprint:
        return {
            "schema_version": 2,
            "status": "unchanged",
            "reason": "Nothing has changed since the last backup.",
            "files": len(files),
            "snapshots": len(existing),
            "mirror": sync_mirror(backup_root, mirror_dir, keep=mirror_keep),
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
        "schema_version": 2,
        "status": "created",
        "reason": f"Saved {len(files)} files.",
        "snapshot": snapshot.name,
        "files": len(files),
        "snapshots": len(list_snapshots(backup_root)),
        "mirror": sync_mirror(backup_root, mirror_dir, keep=mirror_keep),
    }


def _target_for(
    relative: str,
    archive_dir: Path,
    project_dir: Path | None,
) -> Path | None:
    """Where a snapshot entry is restored to, or None if it is not allowed."""
    if relative.startswith(PROJECT_PREFIX):
        if project_dir is None:
            return None
        base = Path(project_dir)
        inner = relative[len(PROJECT_PREFIX):]
    else:
        base = Path(archive_dir)
        inner = relative

    path = Path(inner)
    if path.is_absolute() or ".." in path.parts or not inner:
        return None

    return base / path


def find_snapshot(
    backup_root: Path,
    name: str,
    mirror_dir: Path | None = None,
) -> Path | None:
    """The snapshot folder for NAME: local first, then the second folder."""
    for root in (Path(backup_root).expanduser(), mirror_dir):
        if not root:
            continue
        candidate = Path(root).expanduser() / name
        if (candidate / MANIFEST_NAME).is_file():
            return candidate
    return None


def restore_state(
    archive_dir: Path,
    backup_root: Path,
    name: str,
    *,
    project_dir: Path | None = None,
    mirror_dir: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Copy a snapshot back over the live files.

    Dry run unless ``apply``. Before overwriting, the current state is
    snapshotted first so a restore can itself be undone.
    """
    archive_dir = Path(archive_dir).expanduser()
    backup_root = Path(backup_root).expanduser()
    snapshot = find_snapshot(backup_root, name, mirror_dir)

    if snapshot is None:
        raise FileNotFoundError(f"No backup named {name!r}.")

    manifest = json.loads(
        (snapshot / MANIFEST_NAME).read_text(encoding="utf-8")
    )
    relatives = [str(item) for item in manifest.get("files", [])]

    details = []
    for relative in relatives:
        target = _target_for(relative, archive_dir, project_dir)
        if target is None:
            change = "skipped"
        elif not target.exists():
            change = "missing now"
        elif target.read_bytes() == (snapshot / relative).read_bytes():
            change = "same"
        else:
            change = "differs"
        details.append({"file": relative, "change": change})

    result: dict[str, Any] = {
        "snapshot": name,
        "files": relatives,
        "details": details,
        "applied": False,
    }

    if not apply:
        return result

    # Safety copy of "now" (local only, so a restore never touches the NAS).
    backup_state(archive_dir, backup_root, project_dir=project_dir)

    for relative in relatives:
        target = _target_for(relative, archive_dir, project_dir)
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snapshot / relative, target)

    result["applied"] = True
    return result


def default_paths() -> tuple[Path, Path]:
    from config import ARCHIVE_DIR, PROJECT_DIR

    # Not under output/: the release audit treats every name in output/ as a
    # private meeting name, which would flag everyday words in the code.
    return Path(ARCHIVE_DIR), Path(PROJECT_DIR) / "local_backups"


def default_mirror() -> Path | None:
    from app_settings import load_app_settings

    value = str(load_app_settings().get("backup_mirror_dir") or "").strip()
    return Path(value).expanduser() if value else None


def _int_setting(settings: dict, key: str, default: int) -> int:
    try:
        value = int(settings.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def default_keeps() -> tuple[int, int]:
    """How many snapshots to keep: (on this Mac, in the second folder)."""
    from app_settings import load_app_settings

    settings = load_app_settings()
    return (
        _int_setting(settings, "backup_keep_local", KEEP_SNAPSHOTS),
        _int_setting(settings, "backup_keep_mirror", KEEP_MIRROR_SNAPSHOTS),
    )


def _label_for(stamp: str) -> str:
    """'20261020-104400' -> 'Oct 20, 2026 10:44 AM'."""
    try:
        moment = datetime.strptime(stamp[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return stamp
    hour = moment.hour % 12 or 12
    return (
        f"{moment.strftime('%b')} {moment.day}, {moment.year} "
        f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"
    )


def backup_status(
    backup_root: Path,
    mirror_dir: Path | None,
) -> dict[str, Any]:
    """A plain summary for the Preferences window."""
    snapshots = list_snapshots(Path(backup_root).expanduser())
    last_label = ""
    last_files = 0

    if snapshots:
        last = snapshots[-1]
        last_label = _label_for(last.name)
        try:
            manifest = json.loads(
                (last / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            last_files = len(manifest.get("files", []))
        except (OSError, ValueError):
            pass

    if not mirror_dir:
        mirror = {"state": "off", "message": "Not set", "count": 0}
    else:
        mirror_dir = Path(mirror_dir).expanduser()
        problem = _mirror_problem(mirror_dir)
        if problem:
            mirror = {"state": "unavailable", "message": problem, "count": 0}
        else:
            count = len(list_snapshots(mirror_dir))
            mirror = {
                "state": "ready",
                "message": f"Connected, {count} backup(s) stored",
                "count": count,
            }

    return {
        "last_backup": last_label,
        "last_file_count": last_files,
        "snapshot_count": len(snapshots),
        "mirror_state": mirror["state"],
        "mirror_message": mirror["message"],
        "mirror_snapshot_count": mirror["count"],
    }


def default_project_dir() -> Path:
    from config import PROJECT_DIR

    return Path(PROJECT_DIR)


def set_mirror(value: str | None) -> str:
    """Save (or clear) the second backup folder in the app settings."""
    from app_settings import load_app_settings, save_app_settings

    settings = load_app_settings()
    settings["backup_mirror_dir"] = (
        str(Path(value).expanduser()) if value else ""
    )
    save_app_settings(settings)
    return settings["backup_mirror_dir"]


def _print_restore(result: dict[str, Any]) -> None:
    print(f"Backup: {result['snapshot']}")
    for item in result["details"]:
        print(f"  {item['change']:<12} {item['file']}")
    if result["applied"]:
        print("Restored. The previous state was backed up first.")
    else:
        print("Dry run only. Add --apply to restore these files.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Back up and restore folders, saved sessions and local-only "
            "project files, with an optional second copy on another volume."
        )
    )
    parser.add_argument("--list", action="store_true",
                        help="list saved backups")
    parser.add_argument("--restore", metavar="NAME",
                        help="show what restoring NAME would change")
    parser.add_argument("--apply", action="store_true",
                        help="with --restore: actually restore")
    parser.add_argument("--set-mirror", metavar="PATH",
                        help="also copy every backup to this folder "
                             "(for example on your NAS)")
    parser.add_argument("--clear-mirror", action="store_true",
                        help="stop copying backups to a second folder")
    args = parser.parse_args(argv)

    archive_dir, backup_root = default_paths()
    project_dir = default_project_dir()

    if args.set_mirror:
        path = Path(args.set_mirror).expanduser()
        problem = _mirror_problem(path)
        if problem:
            print(f"Not saved: {problem}")
            return 1
        print("Second backup folder set to: " + set_mirror(str(path)))
        print("It is used the next time a backup runs.")
        return 0

    if args.clear_mirror:
        set_mirror(None)
        print("Second backup folder cleared.")
        return 0

    mirror_dir = default_mirror()
    keep_local, keep_mirror = default_keeps()

    if args.list:
        local = [path.name for path in list_snapshots(backup_root)]
        remote = (
            {path.name for path in list_snapshots(mirror_dir)}
            if mirror_dir and not _mirror_problem(mirror_dir)
            else set()
        )
        names = sorted(set(local) | remote)
        if not names:
            print("No backups yet.")
        for name in names:
            where = (
                "local + second folder" if name in local and name in remote
                else "local only" if name in local
                else "second folder only"
            )
            print(f"{name}   ({where})")
        if mirror_dir:
            print(f"\nSecond folder: {mirror_dir}")
        return 0

    if args.restore:
        try:
            result = restore_state(
                archive_dir,
                backup_root,
                args.restore,
                project_dir=project_dir,
                mirror_dir=mirror_dir,
                apply=args.apply,
            )
        except FileNotFoundError:
            print(f"No backup named {args.restore!r}.")
            print("Use one of these names (from --list):")
            for snapshot in list_snapshots(backup_root):
                print(f"  {snapshot.name}")
            return 1
        _print_restore(result)
        return 0

    result = backup_state(
        archive_dir,
        backup_root,
        project_dir=project_dir,
        mirror_dir=mirror_dir,
        keep=keep_local,
        mirror_keep=keep_mirror,
    )
    print(f"{result['status']}: {result['reason']}")
    mirror = result.get("mirror", {})
    if mirror.get("status") != "off":
        print(f"second folder: {mirror.get('status')}: {mirror.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
