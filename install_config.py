"""Persistent installation metadata shared by setup tooling and the native app.

This file intentionally contains no secrets.  The setup process writes the
resolved repository path to ``install.json`` under the user's Application
Support directory so the Swift app can launch the Python backend even when the
repository is not installed at ``~/Projects/meeting-transcriber``.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from app_settings import APP_SUPPORT_DIR


INSTALL_CONFIG_PATH = APP_SUPPORT_DIR / "install.json"


def load_install_config(path: Path | None = None) -> dict:
    """Return installation metadata, falling back safely when absent/invalid."""
    config_path = path or INSTALL_CONFIG_PATH

    if not config_path.exists():
        return {"schema_version": 1, "project_dir": ""}

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "project_dir": ""}

    if not isinstance(payload, dict):
        return {"schema_version": 1, "project_dir": ""}

    return {
        "schema_version": int(payload.get("schema_version", 1) or 1),
        "project_dir": str(payload.get("project_dir") or "").strip(),
    }


def save_install_config(
    project_dir: str | Path,
    path: Path | None = None,
    *,
    backup_existing: bool = True,
) -> Path:
    """Persist the repository location atomically and optionally keep a backup."""
    config_path = path or INSTALL_CONFIG_PATH
    resolved_project = Path(project_dir).expanduser().resolve()

    config_path.parent.mkdir(parents=True, exist_ok=True)

    if backup_existing and config_path.exists():
        backup_path = config_path.with_suffix(config_path.suffix + ".bak")
        shutil.copy2(config_path, backup_path)

    payload = {
        "schema_version": 1,
        "project_dir": str(resolved_project),
    }

    temp_path = config_path.with_suffix(config_path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp_path, config_path)
    return config_path
