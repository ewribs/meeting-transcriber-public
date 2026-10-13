from __future__ import annotations

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from archive import archived_source_is_verified
from cleanup_old_m4as import (
    archive_is_complete,
    _looks_like_meeting_archive,
)
from config import (
    ARCHIVE_DIR,
    ARCHIVED_M4A_RETENTION_DAYS,
    M4A_RETENTION_DAYS,
    MEETINGS_DIR,
    OUTPUT_DIR,
)


DEVELOPMENT_OUTPUT_DIR_NAMES = {"Pilot Files"}
NAS_RECYCLE_DIR_NAMES = {"#recycle"}


def _bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _older_than(path: Path, cutoff: datetime) -> bool:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return modified <= cutoff


def _matching_archives(source_m4a: Path, archive_dirs: Iterable[Path]) -> list[Path]:
    suffix = "_" + source_m4a.stem
    return [path for path in archive_dirs if path.name.endswith(suffix)]


def _item(path: Path, *, reason: str = "", meeting: Path | None = None) -> dict:
    return {
        "path": path,
        "bytes": _bytes(path),
        "reason": reason,
        "meeting": meeting,
    }


def _is_under_named_child(path: Path, root: Path, names: set[str]) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] in names


def audit_legacy_audio(
    *,
    meetings_dir: Path = MEETINGS_DIR,
    output_dir: Path = OUTPUT_DIR,
    archive_dir: Path = ARCHIVE_DIR,
    local_retention_days: int = M4A_RETENTION_DAYS,
    archived_retention_days: int = ARCHIVED_M4A_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict:
    """Dry-run audit of audio storage and retention eligibility.

    This function never deletes or modifies files.

    NAS recycle-bin audio is reported separately because it is controlled by
    the NAS recycle-bin policy, not Meeting Transcriber's retention workflow.
    Development/pilot audio is also separated from normal meeting runs.
    """
    meetings_dir = Path(meetings_dir)
    output_dir = Path(output_dir)
    archive_dir = Path(archive_dir)
    now = now or datetime.now()

    if local_retention_days < 0:
        raise ValueError("Local M4A retention cannot be negative.")
    if archived_retention_days < 0:
        raise ValueError("Archived M4A retention cannot be negative.")

    local_cutoff = now - timedelta(days=local_retention_days)
    archived_cutoff = (
        None
        if archived_retention_days == 0
        else now - timedelta(days=archived_retention_days)
    )

    output_meeting_wavs = []
    development_wavs = []
    if output_dir.exists():
        for path in sorted(output_dir.rglob("*.wav")):
            if not path.is_file():
                continue
            if _is_under_named_child(
                path,
                output_dir,
                DEVELOPMENT_OUTPUT_DIR_NAMES,
            ):
                development_wavs.append(_item(path))
            else:
                output_meeting_wavs.append(_item(path))

    active_archive_wavs = []
    nas_recycle_wavs = []
    if archive_dir.exists():
        for path in sorted(archive_dir.rglob("*.wav")):
            if not path.is_file():
                continue
            if _is_under_named_child(
                path,
                archive_dir,
                NAS_RECYCLE_DIR_NAMES,
            ):
                nas_recycle_wavs.append(_item(path))
            else:
                active_archive_wavs.append(_item(path))

    archive_dirs = []
    if archive_dir.exists():
        archive_dirs = [
            path
            for path in archive_dir.iterdir()
            if path.is_dir() and _looks_like_meeting_archive(path.name)
        ]

    local_safe = []
    local_blocked = []
    if meetings_dir.exists():
        for m4a in sorted(meetings_dir.glob("*.m4a")):
            if not _older_than(m4a, local_cutoff):
                continue

            matches = _matching_archives(m4a, archive_dirs)
            if not matches:
                local_blocked.append(_item(m4a, reason="no matching archive"))
                continue
            if len(matches) > 1:
                local_blocked.append(
                    _item(
                        m4a,
                        reason="multiple matching archives: "
                        + ", ".join(path.name for path in matches),
                    )
                )
                continue

            meeting = matches[0]
            complete, missing = archive_is_complete(meeting)
            if not complete:
                local_blocked.append(
                    _item(
                        m4a,
                        reason="archive missing: " + ", ".join(missing),
                        meeting=meeting,
                    )
                )
                continue

            if not archived_source_is_verified(m4a, meeting):
                local_blocked.append(
                    _item(
                        m4a,
                        reason="archived source M4A missing or size mismatch",
                        meeting=meeting,
                    )
                )
                continue

            local_safe.append(_item(m4a, meeting=meeting))

    archived_eligible = []
    archived_blocked = []
    if archive_dir.exists() and archived_cutoff is not None:
        for meeting in sorted(
            path
            for path in archive_dir.iterdir()
            if path.is_dir() and _looks_like_meeting_archive(path.name)
        ):
            source_dir = meeting / "source"
            if not source_dir.exists():
                continue

            for m4a in sorted(source_dir.glob("*.m4a")):
                if not _older_than(m4a, archived_cutoff):
                    continue

                complete, missing = archive_is_complete(meeting)
                if not complete:
                    archived_blocked.append(
                        _item(
                            m4a,
                            reason="archive missing: " + ", ".join(missing),
                            meeting=meeting,
                        )
                    )
                    continue

                archived_eligible.append(_item(m4a, meeting=meeting))

    categories = {
        "output_meeting_wavs": output_meeting_wavs,
        "development_wavs": development_wavs,
        "active_archive_wavs": active_archive_wavs,
        "nas_recycle_wavs": nas_recycle_wavs,
        "local_m4as_safe": local_safe,
        "local_m4as_blocked": local_blocked,
        "archived_m4as_eligible": archived_eligible,
        "archived_m4as_blocked": archived_blocked,
    }

    totals = {
        key: {
            "count": len(items),
            "bytes": sum(item["bytes"] for item in items),
        }
        for key, items in categories.items()
    }

    # Only audio controlled by Meeting Transcriber's active lifecycle belongs
    # in this total. Synology #recycle and development/pilot files are
    # intentionally informational/manual categories.
    app_managed_reclaimable = (
        output_meeting_wavs
        + active_archive_wavs
        + local_safe
        + archived_eligible
    )
    totals["app_managed_reclaimable"] = {
        "count": len(app_managed_reclaimable),
        "bytes": sum(item["bytes"] for item in app_managed_reclaimable),
    }

    return {
        "generated_at": now,
        "local_retention_days": local_retention_days,
        "archived_retention_days": archived_retention_days,
        "archive_available": archive_dir.exists() and archive_dir.is_dir(),
        **categories,
        "totals": totals,
    }


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _print_category(title: str, items: list[dict], *, show_reason: bool = False) -> None:
    print(title)
    print("-" * len(title))
    if not items:
        print("None")
        print()
        return

    for item in items:
        print(f"{item['path']}  ({format_bytes(item['bytes'])})")
        if item.get("meeting") is not None:
            print(f"  Meeting: {item['meeting'].name}")
        if show_reason and item.get("reason"):
            print(f"  Blocked: {item['reason']}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run audit of Meeting Transcriber audio storage and retention eligibility."
    )
    parser.add_argument("--local-days", type=int, default=M4A_RETENTION_DAYS)
    parser.add_argument("--archive-days", type=int, default=ARCHIVED_M4A_RETENTION_DAYS)
    args = parser.parse_args()

    result = audit_legacy_audio(
        local_retention_days=args.local_days,
        archived_retention_days=args.archive_days,
    )

    print()
    print("Legacy Audio Storage Audit")
    print("==========================")
    print("Mode: DRY RUN — no files are modified")
    print(f"Local M4A retention: {args.local_days} days")
    print(
        "Archived M4A retention: "
        + ("Forever" if args.archive_days == 0 else f"{args.archive_days} days")
    )
    print()

    _print_category("WAVs under active local meeting runs", result["output_meeting_wavs"])
    _print_category("Development / Pilot WAVs", result["development_wavs"])
    _print_category("WAVs still present in active archive", result["active_archive_wavs"])
    _print_category(
        "Synology recycle-bin WAVs (informational only)",
        result["nas_recycle_wavs"],
    )
    _print_category("Local M4As safe to remove", result["local_m4as_safe"])
    _print_category(
        "Local M4As blocked from removal",
        result["local_m4as_blocked"],
        show_reason=True,
    )
    _print_category("Archived source M4As past retention", result["archived_m4as_eligible"])
    _print_category(
        "Archived source M4As blocked from removal",
        result["archived_m4as_blocked"],
        show_reason=True,
    )

    print("Summary")
    print("-------")
    labels = (
        ("output_meeting_wavs", "Active local meeting WAVs"),
        ("development_wavs", "Development / Pilot WAVs"),
        ("active_archive_wavs", "Active archive WAVs"),
        ("nas_recycle_wavs", "Synology recycle-bin WAVs"),
        ("local_m4as_safe", "Local M4As safe"),
        ("local_m4as_blocked", "Local M4As blocked"),
        ("archived_m4as_eligible", "Archived M4As eligible"),
        ("archived_m4as_blocked", "Archived M4As blocked"),
        ("app_managed_reclaimable", "App-managed reclaimable audio"),
    )
    for key, label in labels:
        total = result["totals"][key]
        print(f"{label}: {total['count']} files / {format_bytes(total['bytes'])}")

    print()
    print("Notes")
    print("-----")
    print("Synology #recycle contents are reported for visibility only.")
    print("Recycle-bin retention/purging is managed by Synology, not this application.")
    print("Development / Pilot WAVs are excluded from app-managed reclaimable totals.")


if __name__ == "__main__":
    main()
