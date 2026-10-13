"""Copy rebuilt meeting files from the local output folder into the NAS archive.

For each meeting that exists in BOTH the local output folder and the archive:
  1. copies the archive's current versions of the files below into a backup
     folder (sync_backups/<timestamp>/<meeting>/);
  2. overwrites those files in the archive with the rebuilt local ones.
At the end it rebuilds the archive index and dashboard once.

It never touches the m4a, the transcripts, or OneNote_Import, and it skips any
meeting that is missing locally or in the archive.

Dry run by default: nothing is written unless --apply is given.
"""

import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import shutil
from datetime import datetime
from pathlib import Path

SYNC_FILES = (
    "meeting_summary.md",
    "meeting_summary.html",
    "meeting_transcript.html",
    "meeting_memory.json",
    "meeting_metadata.json",
    "processing_runtime.json",
)
SYNC_DIRS = ("exports",)


def _same(a: Path, b: Path) -> bool:
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


def plan_meeting(local: Path, archive: Path) -> list[str]:
    """Names (files or dirs) whose local copy differs from the archive."""
    changed = []
    for name in SYNC_FILES:
        if (local / name).is_file() and not _same(local / name, archive / name):
            changed.append(name)
    for name in SYNC_DIRS:
        if (local / name).is_dir():
            for f in sorted((local / name).rglob("*")):
                rel = f.relative_to(local)
                if f.is_file() and not _same(f, archive / rel):
                    changed.append(str(rel))
    return changed


def sync_meeting(local: Path, archive: Path, backup_root: Path) -> list[str]:
    changed = plan_meeting(local, archive)
    for rel in changed:
        target = archive / rel
        if target.exists():
            saved = backup_root / local.name / rel
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local / rel, target)
    return changed


def main(argv=None) -> int:
    from config import ARCHIVE_DIR, OUTPUT_DIR

    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--apply", action="store_true", help="actually write")
    p.add_argument("--only", action="append", default=[], help="meeting folder name (repeatable)")
    p.add_argument("--limit", type=int, default=0, help="stop after N meetings")
    p.add_argument("--backup-dir", default=str(_REPO_ROOT / "sync_backups"))
    args = p.parse_args(argv)

    if not ARCHIVE_DIR.exists():
        print(f"Archive not reachable: {ARCHIVE_DIR} (is the NAS mounted?)")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = Path(args.backup_dir) / stamp
    names = sorted(d.name for d in OUTPUT_DIR.iterdir() if d.is_dir())
    if args.only:
        names = [n for n in names if n in args.only]

    done = skipped = 0
    for name in names:
        local, archive = OUTPUT_DIR / name, ARCHIVE_DIR / name
        if not archive.is_dir():
            skipped += 1
            print(f"skip (not in archive): {name}")
            continue
        changed = plan_meeting(local, archive)
        if not changed:
            continue
        if args.apply:
            sync_meeting(local, archive, backup_root)
        print(f"{'synced' if args.apply else 'would sync'} {name}: {len(changed)} file(s)")
        done += 1
        if args.limit and done >= args.limit:
            break

    if args.apply and done:
        from dashboard_generator import build_meeting_dashboard
        from indexer import build_meeting_index

        build_meeting_dashboard(build_meeting_index(ARCHIVE_DIR))
        print(f"Backups: {backup_root}")
    print(f"{'Synced' if args.apply else 'Would sync'} {done} meeting(s); skipped {skipped}.")
    if not args.apply:
        print("Dry run only. Add --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
