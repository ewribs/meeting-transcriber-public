
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path
import argparse
import json

from pipeline import run_meeting_memory


IGNORED_DIRS = {
    "#recycle",
    "OneNote_Import",
}


def find_meeting_dirs(
    root_dir: Path,
) -> list[Path]:
    meeting_dirs = []

    for path in root_dir.iterdir():
        if not path.is_dir():
            continue

        if path.name in IGNORED_DIRS:
            continue

        metadata_path = (
            path / "meeting_metadata.json"
        )

        cleaned_path = (
            path / "meeting_transcript_cleaned.md"
        )

        summary_path = (
            path / "meeting_summary.md"
        )

        if not metadata_path.exists():
            continue

        if not cleaned_path.exists():
            continue

        if not summary_path.exists():
            continue

        meeting_dirs.append(
            path
        )

    return sorted(
        meeting_dirs,
        key=lambda path: path.name,
    )


def backfill_meeting_memory(
    root_dir: Path,
    apply_changes: bool = False,
    force: bool = False,
) -> None:
    meeting_dirs = find_meeting_dirs(
        root_dir
    )

    created = 0
    existing = 0
    failed = 0

    print()
    print(
        f"Meetings found: {len(meeting_dirs)}"
    )

    if apply_changes:
        print("Mode: APPLY")
    else:
        print("Mode: DRY RUN")

    if force:
        print("Force overwrite: YES")

    print()

    for run_dir in meeting_dirs:
        memory_path = (
            run_dir / "meeting_memory.json"
        )

        try:
            if (
                memory_path.exists()
                and not force
            ):
                existing += 1

                print(
                    f"EXISTS: {run_dir.name}"
                )

                continue

            if apply_changes:
                metadata_path = (
                    run_dir
                    / "meeting_metadata.json"
                )

                summary_path = (
                    run_dir
                    / "meeting_summary.md"
                )

                cleaned_path = (
                    run_dir
                    / "meeting_transcript_cleaned.md"
                )

                metadata = json.loads(
                    metadata_path.read_text(
                        encoding="utf-8",
                    )
                )

                meeting_summary = (
                    summary_path.read_text(
                        encoding="utf-8",
                    )
                )

                cleaned_transcript = (
                    cleaned_path.read_text(
                        encoding="utf-8",
                    )
                )

                participants = (
                    metadata.get(
                        "participants",
                        [],
                    )
                    or []
                )

                run_meeting_memory(
                    run_dir=run_dir,
                    meeting_summary=meeting_summary,
                    cleaned_transcript=cleaned_transcript,
                    participants=participants,
                )

            created += 1

            if force and memory_path.exists():
                print(
                    f"REBUILD: {run_dir.name}"
                )
            else:
                print(
                    f"CREATE: {run_dir.name}"
                )

        except Exception as error:
            failed += 1

            print(
                f"FAILED: {run_dir.name}"
            )
            print(
                f"  Reason: {error}"
            )

    print()
    print("=" * 60)
    print("Meeting memory backfill complete")
    print("=" * 60)

    if apply_changes:
        print(
            f"Created/rebuilt: {created}"
        )
    else:
        print(
            f"Would create/rebuild: {created}"
        )

    print(
        f"Existing:          {existing}"
    )

    print(
        f"Failed:            {failed}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill meeting memory "
            "for existing meetings."
        )
    )

    parser.add_argument(
        "root",
        type=Path,
        help=(
            "Meeting archive root, for example "
            "/Volumes/Transcribe"
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Generate meeting_memory.json files. "
            "Without this flag, performs "
            "a dry run only."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Regenerate existing "
            "meeting_memory.json files."
        ),
    )

    args = parser.parse_args()

    if not args.root.exists():
        raise FileNotFoundError(
            f"Archive root not found: "
            f"{args.root}"
        )

    backfill_meeting_memory(
        root_dir=args.root,
        apply_changes=args.apply,
        force=args.force,
    )


if __name__ == "__main__":
    main()
