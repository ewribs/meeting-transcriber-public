"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    from ai import clean_transcript_in_chunks

    transcript_path = Path(
        "output/meeting_transcript.md"
    )

    transcript = transcript_path.read_text(
        encoding="utf-8",
    )

    print("Cleaning transcript...\n")

    cleaned_transcript = clean_transcript_in_chunks(
        transcript,
    )

    output_path = Path(
        "output/meeting_transcript_cleaned.md"
    )

    output_path.write_text(
        cleaned_transcript,
        encoding="utf-8",
    )

    print()
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
