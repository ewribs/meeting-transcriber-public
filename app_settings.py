from __future__ import annotations

import json
import os
from pathlib import Path


APP_SUPPORT_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Meeting Transcriber"
)

SETTINGS_PATH = APP_SUPPORT_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "performance_profile": "Auto",
    "execution_profile": "Balanced",
    "output_dir": "",
    "archive_dir": "",
    "recordings_dir": "",
    "llm_model": "qwen3:8b",
    "llm_backend": "auto",
    "mlx_model": "Qwen/Qwen3-30B-A3B-MLX-6bit",
    "mlx_max_tokens": 8000,
    "llm_context_size": 0,
    "llm_context_mode": "profile_default",
    "m4a_retention_days": 30,
    "archived_m4a_retention_days": 365,
    "prompt_favorites": [],
}


def load_app_settings(
    settings_path: Path | None = None,
) -> dict:
    path = settings_path or SETTINGS_PATH
    settings = dict(DEFAULT_SETTINGS)

    if not path.exists():
        return settings

    try:
        loaded = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return settings

    if isinstance(loaded, dict):
        settings.update(loaded)

        # Context mode makes Profile default explicit. Older settings files
        # used only llm_context_size, so preserve a positive legacy value as
        # an intentional override. New saves write both fields.
        raw_mode = str(loaded.get("llm_context_mode") or "").strip()
        if raw_mode not in {"profile_default", "override"}:
            legacy_size = int(loaded.get("llm_context_size", 0) or 0)
            settings["llm_context_mode"] = (
                "override" if legacy_size > 0 else "profile_default"
            )

        if settings.get("llm_context_mode") == "profile_default":
            settings["llm_context_size"] = 0

        # 3000 was the original MLX generation default and proved too small
        # for full narrative/polish responses. Migrate that legacy default to
        # the adaptive 8K narrative ceiling; structured JSON is independently
        # capped at 4K by MLXBackend.
        if int(loaded.get("mlx_max_tokens", 0) or 0) == 3000:
            settings["mlx_max_tokens"] = 8000

        # Migrate the earlier execution-profile preference without forcing
        # users to edit settings.json. Aggressive is the former name for
        # today's High Performance tier.
        if (
            "performance_profile" not in loaded
            and "execution_profile" in loaded
        ):
            legacy = str(
                loaded.get("execution_profile") or ""
            ).strip()
            legacy_map = {
                "Conservative": "Conservative",
                "Balanced": "Auto",
                "Aggressive": "High Performance",
            }
            settings["performance_profile"] = (
                legacy_map.get(legacy, "Auto")
            )

    return settings


def save_app_settings(
    settings: dict,
    settings_path: Path | None = None,
) -> None:
    path = settings_path or SETTINGS_PATH
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings)

    # Callers written before explicit context mode may still save only a
    # numeric llm_context_size. Preserve a positive value as an override.
    if (
        "llm_context_size" in settings
        and "llm_context_mode" not in settings
    ):
        payload["llm_context_mode"] = (
            "override"
            if int(settings.get("llm_context_size", 0) or 0) > 0
            else "profile_default"
        )

    if payload.get("llm_context_mode") == "profile_default":
        payload["llm_context_size"] = 0

    temp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp_path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    os.replace(
        temp_path,
        path,
    )


def update_app_setting(
    key: str,
    value: object,
    settings_path: Path | None = None,
) -> dict:
    settings = load_app_settings(
        settings_path
    )
    settings[key] = value
    save_app_settings(
        settings,
        settings_path,
    )
    return settings
