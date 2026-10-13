
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
from pathlib import Path

from config import ARCHIVE_DIR


REQUIRED_ARTIFACTS = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


def format_size(size_bytes: int) -> str:
    size = float(size_bytes)

    for unit in (
        "B",
        "KB",
        "MB",
        "GB",
        "TB",
    ):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"

        size /= 1024

    return f"{size_bytes} B"


def meeting_is_complete(
    meeting_dir: Path,
) -> tuple[bool, list[str]]:
    missing = [
        artifact
        for artifact in REQUIRED_ARTIFACTS
        if not (
            meeting_dir / artifact
        ).exists()
    ]

    return (
        not missing,
        missing,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove archived WAV files from "
            "completed meeting folders."
        )
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually delete eligible WAV files. "
            "Without this flag, only perform a dry run."
        ),
    )

    args = parser.parse_args()

    if (
        not ARCHIVE_DIR.exists()
        or not ARCHIVE_DIR.is_dir()
    ):
        raise RuntimeError(
            f"Archive is unavailable: "
            f"{ARCHIVE_DIR}"
        )

    print()
    print("NAS WAV Cleanup")
    print("---------------")
    print(
        "Mode:",
        "DELETE" if args.delete else "DRY RUN",
    )
    print(
        f"Archive: {ARCHIVE_DIR}"
    )
    print()

    meetings_with_wavs = 0
    eligible_meetings = 0
    skipped_meetings = 0
    wav_count = 0
    total_bytes = 0
    deleted_count = 0
    deleted_bytes = 0

    for meeting_dir in sorted(
        item
        for item in ARCHIVE_DIR.iterdir()
        if item.is_dir()
        and not item.name.startswith(".")
        and item.name not in {
            "OneNote_Import",
            "query_sessions",
            "#recycle",
        }
    ):
        audio_dir = (
            meeting_dir / "audio"
        )

        if not audio_dir.exists():
            continue

        wav_files = sorted(
            audio_dir.glob("*.wav")
        )

        if not wav_files:
            continue

        meetings_with_wavs += 1

        complete, missing = (
            meeting_is_complete(
                meeting_dir
            )
        )

        if not complete:
            skipped_meetings += 1

            print(
                f"SKIP {meeting_dir.name}"
            )
            print(
                "  Missing: "
                + ", ".join(missing)
            )
            print()

            continue

        eligible_meetings += 1

        meeting_bytes = sum(
            wav_file.stat().st_size
            for wav_file in wav_files
        )

        wav_count += len(wav_files)
        total_bytes += meeting_bytes

        action = (
            "DELETE"
            if args.delete
            else "WOULD DELETE"
        )

        print(
            f"{action} {meeting_dir.name}"
        )

        for wav_file in wav_files:
            size = wav_file.stat().st_size

            print(
                f"  {wav_file.name}: "
                f"{format_size(size)}"
            )

            if args.delete:
                wav_file.unlink()

                deleted_count += 1
                deleted_bytes += size

        if args.delete:
            try:
                audio_dir.rmdir()

                print(
                    "  Removed empty audio/"
                )
            except OSError:
                print(
                    "  Kept audio/ "
                    "(other files remain)"
                )

        print()

    print("Summary")
    print("-------")
    print(
        f"Meetings containing WAVs: "
        f"{meetings_with_wavs}"
    )
    print(
        f"Eligible meetings: "
        f"{eligible_meetings}"
    )
    print(
        f"Skipped meetings: "
        f"{skipped_meetings}"
    )
    print(
        f"Eligible WAV files: "
        f"{wav_count}"
    )
    print(
        f"Eligible space: "
        f"{format_size(total_bytes)}"
    )

    if args.delete:
        print(
            f"Deleted WAV files: "
            f"{deleted_count}"
        )
        print(
            f"Space removed: "
            f"{format_size(deleted_bytes)}"
        )
    else:
        print()
        print(
            "Dry run only. "
            "Nothing was deleted."
        )
        print(
            "Run again with --delete "
            "to remove eligible WAVs."
        )


if __name__ == "__main__":
    main()
