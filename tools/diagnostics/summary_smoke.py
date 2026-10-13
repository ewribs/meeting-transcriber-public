"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    from ai import summarize_meeting_in_chunks

    transcript = Path(
        "output/meeting_transcript_cleaned.md"
    ).read_text(encoding="utf-8")

    print("Generating hierarchical summary...\n")

    summary = summarize_meeting_in_chunks(transcript)

    summary_path = Path("output/meeting_summary.md")
    summary_path.write_text(summary, encoding="utf-8")

    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
