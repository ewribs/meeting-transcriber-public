
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path

from config import ARCHIVE_DIR, ONENOTE_IMPORT_DIR
from pipeline import export_onenote_summary
from onenote import copy_onenote_export


def backfill_onenote_exports():
    """
    Generate missing OneNote exports for archived meetings
    and populate the OneNote import landing area.
    """

    ignored_dirs = {
        "OneNote_Import",
        "#recycle",
    }

    meetings = [
        item
        for item in ARCHIVE_DIR.iterdir()
        if item.is_dir()
        and item.name not in ignored_dirs
    ]

    ONENOTE_IMPORT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    generated = 0
    skipped = 0
    failed = 0

    print()
    print("OneNote Export Generation Backfill")
    print("---------------------------------")
    print()

    print(
        f"Meetings found: {len(meetings)}"
    )

    print()

    for meeting in sorted(meetings):

        try:
            existing = list(
                (
                    meeting / "exports"
                ).glob(
                    "OneNote_*.html"
                )
            )

            if existing:
                print(
                    f"Exists: {existing[0].name}"
                )

                copy_onenote_export(
                    meeting,
                )

                skipped += 1
                continue

            print(
                f"Generating: {meeting.name}"
            )

            export_onenote_summary(
                meeting,
            )

            copy_onenote_export(
                meeting,
            )

            generated += 1

        except Exception as e:
            print(
                f"FAILED {meeting.name}: {e}"
            )

            failed += 1

    print()
    print("Complete:")
    print(
        f"  Generated: {generated}"
    )
    print(
        f"  Existing: {skipped}"
    )
    print(
        f"  Failed: {failed}"
    )


if __name__ == "__main__":
    backfill_onenote_exports()
