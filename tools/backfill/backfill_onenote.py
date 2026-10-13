
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path
import shutil

from config import ARCHIVE_DIR, ONENOTE_IMPORT_DIR


def backfill_onenote_exports():
    """
    Find existing archived meetings and copy
    missing OneNote exports into the NAS landing area.
    """

    ONENOTE_IMPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    meetings = []

    ignored_dirs = {
        "OneNote_Import",
        "#recycle",
    }

    for item in ARCHIVE_DIR.iterdir():
        if (
            item.is_dir()
            and item.name not in ignored_dirs
        ):
        
            meetings.append(item)

    copied = 0
    skipped = 0
    missing = 0

    print()
    print("OneNote Export Backfill")
    print("----------------------")
    print()

    print(
        f"Meetings found: {len(meetings)}"
    )

    print()

    for meeting in sorted(meetings):

        export_dir = (
            meeting / "exports"
        )

        exports = list(
            export_dir.glob(
                "OneNote_*.html"
            )
        )

        if not exports:
            print(
                f"Missing: {meeting.name}"
            )

            missing += 1
            continue

        source = exports[0]

        destination = (
            ONENOTE_IMPORT_DIR /
            source.name
        )

        if destination.exists():
            print(
                f"Exists: {source.name}"
            )

            skipped += 1
            continue

        shutil.copy2(
            source,
            destination,
        )

        print(
            f"Copied: {source.name}"
        )

        copied += 1

    print()

    print(
        f"Complete:"
    )

    print(
        f"  Copied: {copied}"
    )

    print(
        f"  Skipped: {skipped}"
    )

    print(
        f"  Missing: {missing}"
    )


if __name__ == "__main__":
    backfill_onenote_exports()
