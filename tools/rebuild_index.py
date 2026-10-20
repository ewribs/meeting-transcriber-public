#!/usr/bin/env python3
"""Rebuild the published-meeting index and dashboard from the archive folder.

Run this after moving or renaming the archive folder (for example when moving
everything on the NAS into an Archive/ subfolder), so the index points at the
meetings' new location. It only rewrites meeting_index.json and the dashboard;
no meeting files are changed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--archive",
        type=Path,
        help="archive folder (default: the Archive folder in Preferences)",
    )
    args = parser.parse_args(argv)

    from config import ARCHIVE_DIR
    from dashboard_generator import build_meeting_dashboard
    from indexer import build_meeting_index

    archive = (args.archive or Path(ARCHIVE_DIR)).expanduser()

    if not archive.is_dir():
        print(f"The archive folder is not available: {archive}")
        return 1

    if not any(archive.glob("*/meeting_metadata.json")):
        print(f"No published meetings were found in: {archive}")
        print("Nothing was changed. Check that this is the right folder.")
        return 1

    index_path = build_meeting_index(archive)
    build_meeting_dashboard(index_path)
    print(f"Rebuilt the index and dashboard for: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
