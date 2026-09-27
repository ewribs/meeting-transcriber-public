"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from config import ARCHIVE_DIR

    from dashboard_generator import (
        build_meeting_dashboard,
    )

    index_path = (
        ARCHIVE_DIR / "meeting_index.json"
    )


    dashboard_path = build_meeting_dashboard(
        index_path,
    )


    print(
        f"Created: {dashboard_path}"
    )


if __name__ == "__main__":
    main()
