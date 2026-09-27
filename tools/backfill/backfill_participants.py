
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path
import argparse
import json

from pipeline import run_participant_extraction
from metadata import update_meeting_participants


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

        if not metadata_path.exists():
            continue

        if not cleaned_path.exists():
            continue

        meeting_dirs.append(
            path
        )

    return sorted(
        meeting_dirs,
        key=lambda path: path.name,
    )


def backfill_participants(
    root_dir: Path,
    apply_changes: bool = False,
) -> None:
    meeting_dirs = find_meeting_dirs(
        root_dir
    )

    updated = 0
    unchanged = 0
    failed = 0

    print()
    print(
        f"Meetings found: {len(meeting_dirs)}"
    )

    if apply_changes:
        print("Mode: APPLY")
    else:
        print("Mode: DRY RUN")

    print()

    for run_dir in meeting_dirs:
        try:
            metadata_path = (
                run_dir
                / "meeting_metadata.json"
            )

            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8",
                )
            )

            existing_participants = (
                metadata.get("participants")
                or []
            )

            participants = (
                run_participant_extraction(
                    run_dir
                )
            )

            existing_names = [
                participant.get(
                    "name",
                    "",
                )
                for participant
                in existing_participants
                if isinstance(
                    participant,
                    dict,
                )
            ]

            new_names = [
                participant.get(
                    "name",
                    "",
                )
                for participant
                in participants
            ]

            if (
                existing_participants
                == participants
            ):
                unchanged += 1

                print(
                    f"UNCHANGED: "
                    f"{run_dir.name}"
                )
                print(
                    f"  Participants: "
                    f"{', '.join(new_names) or 'None'}"
                )

                continue

            print(
                f"UPDATE: {run_dir.name}"
            )

            print(
                f"  Before: "
                f"{', '.join(existing_names) or 'None'}"
            )

            print(
                f"  After:  "
                f"{', '.join(new_names) or 'None'}"
            )

            if apply_changes:
                update_meeting_participants(
                    run_dir,
                    participants,
                )

            updated += 1

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
    print("Participant backfill complete")
    print("=" * 60)

    if apply_changes:
        print(
            f"Updated:   {updated}"
        )
    else:
        print(
            f"Would update: {updated}"
        )

    print(
        f"Unchanged: {unchanged}"
    )

    print(
        f"Failed:    {failed}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill participant metadata "
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
            "Write participant metadata. "
            "Without this flag, performs "
            "a dry run only."
        ),
    )

    args = parser.parse_args()

    if not args.root.exists():
        raise FileNotFoundError(
            f"Archive root not found: "
            f"{args.root}"
        )

    backfill_participants(
        root_dir=args.root,
        apply_changes=args.apply,
    )


if __name__ == "__main__":
    main()
