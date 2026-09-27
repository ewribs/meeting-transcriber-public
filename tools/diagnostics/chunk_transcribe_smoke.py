"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    from transcribe import transcribe_audio_chunk

    transcribe_audio_chunk(
        audio_path=Path("output/mic.wav"),
        output_dir=Path("output"),
        offset_ms=1_200_000,
        duration_ms=300_000,
        chunk_number=1,
        total_chunks=1,
    )


if __name__ == "__main__":
    main()
