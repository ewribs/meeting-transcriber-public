
# Allow direct execution after repository reorganization.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path
import argparse

from ai import analyze_selected_meetings


def load_meeting_source(
    meeting_dir: Path,
) -> tuple[str, str]:
    """
    Load the meeting summary for cross-meeting analysis.
    """

    summary_path = (
        meeting_dir
        / "meeting_summary.md"
    )

    if not summary_path.exists():
        raise FileNotFoundError(
            f"Meeting summary not found: "
            f"{summary_path}"
        )

    source_text = summary_path.read_text(
        encoding="utf-8",
    )

    return (
        meeting_dir.name,
        source_text,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ask the local LLM a free-form "
            "question about one or more meetings."
        ),
    )

    parser.add_argument(
        "meeting_dirs",
        nargs="+",
        type=Path,
        help=(
            "One or more archived meeting "
            "directories."
        ),
    )

    parser.add_argument(
        "--prompt",
        required=True,
        help=(
            "Free-form request for the "
            "selected meeting material."
        ),
    )

    args = parser.parse_args()

    meeting_sources = []

    for meeting_dir in args.meeting_dirs:
        if not meeting_dir.exists():
            raise FileNotFoundError(
                f"Meeting directory not found: "
                f"{meeting_dir}"
            )

        meeting_sources.append(
            load_meeting_source(
                meeting_dir,
            )
        )

    print()
    print(
        f"Analyzing "
        f"{len(meeting_sources)} "
        f"meeting(s)..."
    )
    print()

    result = analyze_selected_meetings(
        meeting_sources=meeting_sources,
        user_prompt=args.prompt,
    )

    print(result)
    print()


if __name__ == "__main__":
    main()
