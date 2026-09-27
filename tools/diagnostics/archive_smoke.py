"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    from archive import archive_meeting

    run_dir = Path(
        "output/2026-08-05_1419_BrianK1v1080426"
    )

    archive_path = archive_meeting(
        run_dir,
    )

    print(
        f"Archived to: {archive_path}"
    )


if __name__ == "__main__":
    main()
