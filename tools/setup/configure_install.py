#!/usr/bin/env python3
"""Write Meeting Transcriber setup paths using the application's own config.

This helper is deliberately small and reviewable.  It does not install
software, contact the network, or launch background processes.  It only:

1. records the repository path in Application Support/install.json; and
2. updates the existing Application Support/settings.json storage/model values.

Existing files are backed up before setup changes them.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_settings import SETTINGS_PATH, load_app_settings, save_app_settings
from install_config import save_install_config


def backup_if_present(path: Path) -> Path | None:
    if not path.exists():
        return None

    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup)
    return backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure Meeting Transcriber repository and storage paths."
    )
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--working-dir", required=True)
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--recordings-dir", required=True)
    parser.add_argument("--llm-model", default="qwen3:8b")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).expanduser().resolve()

    backup = backup_if_present(SETTINGS_PATH)
    if backup:
        print(f"Backed up existing app settings: {backup}")

    install_path = save_install_config(project_dir, backup_existing=True)

    settings = load_app_settings()
    settings.update(
        {
            "output_dir": str(Path(args.working_dir).expanduser()),
            "archive_dir": str(Path(args.archive_dir).expanduser()),
            "recordings_dir": str(Path(args.recordings_dir).expanduser()),
            "llm_model": args.llm_model.strip(),
        }
    )
    save_app_settings(settings)

    print(f"Install metadata: {install_path}")
    print(f"Project directory: {project_dir}")
    print(f"Working directory: {settings['output_dir']}")
    print(f"Archive directory: {settings['archive_dir']}")
    print(f"Recordings directory: {settings['recordings_dir']}")
    print(f"Ollama model: {settings['llm_model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
