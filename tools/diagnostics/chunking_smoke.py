"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    from chunking import chunk_transcript

    transcript = Path(
        "output/meeting_transcript.md"
    ).read_text()

    chunks = chunk_transcript(transcript)

    print(f"Chunks: {len(chunks)}")

    for i, chunk in enumerate(chunks, start=1):
        print(
            f"Chunk {i}: "
            f"{len(chunk.split())} words"
        )


if __name__ == "__main__":
    main()
