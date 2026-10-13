
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
from pathlib import Path

from audio_cleanup import remove_wavs
from config import ARCHIVE_DIR, OUTPUT_DIR

REQUIRED_ARTIFACTS = (
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
    "meeting_metadata.json",
    "meeting_memory.json",
)


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
            "Remove local WAV files from meetings "
            "that have been successfully archived."
        )
    )

    parser.add_argument(
        "--delete",
        action="store_true",
        help=(
            "Actually remove eligible local WAVs. "
            "Without this flag, perform a dry run."
        ),
    )

    args = parser.parse_args()

    if not ARCHIVE_DIR.exists():
        raise RuntimeError(
            f"Archive unavailable: "
            f"{ARCHIVE_DIR}"
        )

    print()
    print("Local WAV Cleanup")
    print("-----------------")
    print(
        "Mode:",
        "DELETE"
        if args.delete
        else "DRY RUN",
    )
    print()

    eligible = []
    skipped = []

    for meeting_dir in sorted(
        item
        for item in OUTPUT_DIR.iterdir()
        if item.is_dir()
        and item.name not in {
            "html_test",
            "Pilot Files",
        }
    ):
        wav_files = list(
            (
                meeting_dir / "audio"
            ).glob("*.wav")
        )

        if not wav_files:
            continue

        archived_dir = (
            ARCHIVE_DIR
            / meeting_dir.name
        )

        if not archived_dir.exists():
            skipped.append(
                (
                    meeting_dir,
                    "meeting is not archived",
                )
            )
            continue

        complete, missing = (
            meeting_is_complete(
                archived_dir
            )
        )

        if not complete:
            skipped.append(
                (
                    meeting_dir,
                    "archive missing required artifacts: "
                    + ", ".join(missing),
                )
            )
            continue

        eligible.append(
            meeting_dir
        )

    for meeting_dir in eligible:
        wav_files = sorted(
            (
                meeting_dir / "audio"
            ).glob("*.wav")
        )

        total_bytes = sum(
            wav_file.stat().st_size
            for wav_file in wav_files
        )

        action = (
            "DELETE"
            if args.delete
            else "WOULD DELETE"
        )

        print(
            f"{action} {meeting_dir.name}"
        )
        print(
            f"  WAV files: "
            f"{len(wav_files)}"
        )
        print(
            f"  Size: "
            f"{total_bytes / 1024 / 1024:.1f} MB"
        )

        if args.delete:
            remove_wavs(
                meeting_dir
            )

        print()

    for meeting_dir, reason in skipped:
        print(
            f"SKIP {meeting_dir.name}"
        )
        print(
            f"  Reason: {reason}"
        )
        print()

    print("Summary")
    print("-------")
    print(
        f"Eligible meetings: "
        f"{len(eligible)}"
    )
    print(
        f"Skipped meetings: "
        f"{len(skipped)}"
    )

    if not args.delete:
        print()
        print(
            "Dry run only. "
            "Nothing was deleted."
        )


if __name__ == "__main__":
    main()
