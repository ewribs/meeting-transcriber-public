"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from ai import clean_transcript

    TEXT = """
    okay does it start next week do we know i don't know what the start date is
    we did a retro on monday i think it probably started on monday okay cool
    that's good i'm sure more people will roll in but we will get started
    """.strip()

    response = clean_transcript(TEXT)

    print("\nCleaned transcript:\n")
    print(response)


if __name__ == "__main__":
    main()
