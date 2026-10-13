from __future__ import annotations

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import hashlib
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from archive import archived_source_path
from cleanup_old_m4as import archive_is_complete, _looks_like_meeting_archive
from config import ARCHIVE_DIR, M4A_RETENTION_DAYS, MEETINGS_DIR


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _older_than(path: Path, cutoff: datetime) -> bool:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return False
    return modified <= cutoff


def plan_legacy_archive_repairs(
    *,
    meetings_dir: Path = MEETINGS_DIR,
    archive_dir: Path = ARCHIVE_DIR,
    local_retention_days: int = M4A_RETENTION_DAYS,
    now: datetime | None = None,
) -> dict:
    meetings_dir = Path(meetings_dir)
    archive_dir = Path(archive_dir)
    now = now or datetime.now()

    if local_retention_days < 0:
        raise ValueError("Local M4A retention cannot be negative.")

    if not archive_dir.exists() or not archive_dir.is_dir():
        raise RuntimeError(f"Archive unavailable: {archive_dir}")

    cutoff = now - timedelta(days=local_retention_days)
    archive_dirs = [
        path
        for path in archive_dir.iterdir()
        if path.is_dir() and _looks_like_meeting_archive(path.name)
    ]

    repairable: list[dict] = []
    blocked: list[dict] = []

    if not meetings_dir.exists():
        return {
            "repairable": repairable,
            "blocked": blocked,
            "days": local_retention_days,
        }

    for source in sorted(meetings_dir.glob("*.m4a")):
        if not _older_than(source, cutoff):
            continue

        matches = [
            candidate
            for candidate in archive_dirs
            if candidate.name.endswith("_" + source.stem)
        ]

        if not matches:
            blocked.append({"source": source, "reason": "no matching archive"})
            continue

        if len(matches) > 1:
            blocked.append(
                {
                    "source": source,
                    "reason": "multiple matching archives: "
                    + ", ".join(path.name for path in matches),
                }
            )
            continue

        meeting = matches[0]
        complete, missing = archive_is_complete(meeting)
        if not complete:
            blocked.append(
                {
                    "source": source,
                    "meeting": meeting,
                    "reason": "archive missing: " + ", ".join(missing),
                }
            )
            continue

        destination = archived_source_path(meeting, source)
        if destination.exists():
            if destination.stat().st_size == source.stat().st_size:
                # Already verified by the normal retention rule; no repair needed.
                continue
            blocked.append(
                {
                    "source": source,
                    "meeting": meeting,
                    "destination": destination,
                    "reason": "archived source exists but size differs; refusing to overwrite",
                }
            )
            continue

        repairable.append(
            {
                "source": source,
                "meeting": meeting,
                "destination": destination,
                "bytes": source.stat().st_size,
            }
        )

    return {
        "repairable": repairable,
        "blocked": blocked,
        "days": local_retention_days,
    }


def apply_legacy_archive_repairs(plan: dict) -> dict:
    repaired: list[dict] = []
    failed: list[dict] = []

    for item in plan["repairable"]:
        source = Path(item["source"])
        destination = Path(item["destination"])
        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            if destination.exists():
                raise RuntimeError("destination appeared after planning; refusing to overwrite")

            shutil.copy2(source, destination)

            if destination.stat().st_size != source.stat().st_size:
                raise RuntimeError("copied M4A size does not match source")

            if _sha256(destination) != _sha256(source):
                raise RuntimeError("copied M4A SHA-256 does not match source")

            repaired.append(item)
        except Exception as exc:
            try:
                if destination.exists():
                    destination.unlink()
            except OSError:
                pass

            failed.append(
                {
                    **item,
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "repaired": repaired,
        "failed": failed,
        "blocked": plan["blocked"],
        "days": plan["days"],
    }


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Safely backfill original M4As into legacy meeting archives so "
            "normal local-retention verification can succeed."
        )
    )
    parser.add_argument("--local-days", type=int, default=M4A_RETENTION_DAYS)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Copy repairable M4As into their single complete archive. Default is dry run.",
    )
    args = parser.parse_args()

    plan = plan_legacy_archive_repairs(local_retention_days=args.local_days)

    print()
    print("Legacy M4A Archive Repair")
    print("=========================")
    print("Mode:", "APPLY" if args.apply else "DRY RUN — no files are modified")
    print(f"Local M4A retention: {args.local_days} days")
    print()

    print("Repairable")
    print("----------")
    if not plan["repairable"]:
        print("None")
    for item in plan["repairable"]:
        print(f"{item['source']}  ({format_bytes(item['bytes'])})")
        print(f"  Archive: {item['meeting'].name}")
        print(f"  Copy to: {item['destination']}")
    print()

    print("Blocked")
    print("-------")
    if not plan["blocked"]:
        print("None")
    for item in plan["blocked"]:
        print(item["source"])
        print(f"  Reason: {item['reason']}")
    print()

    if not args.apply:
        print("Summary")
        print("-------")
        print(f"Repairable: {len(plan['repairable'])}")
        print(f"Blocked: {len(plan['blocked'])}")
        return

    result = apply_legacy_archive_repairs(plan)

    print("Apply Summary")
    print("-------------")
    print(f"Repaired: {len(result['repaired'])}")
    print(f"Failed: {len(result['failed'])}")
    print(f"Still blocked: {len(result['blocked'])}")
    print()
    print(
        "The local originals were not deleted. Restart Meeting Transcriber "
        "or run the normal retention cleanup after reviewing the repair."
    )


if __name__ == "__main__":
    main()
