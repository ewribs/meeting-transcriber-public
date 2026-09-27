from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


CONTEXT_SIZE_OPTIONS: tuple[tuple[str, int], ...] = (
    ("Profile default", 0),
    ("8K", 8192),
    ("16K", 16384),
    ("24K", 24576),
    ("32K", 32768),
    ("40K", 40960),
    ("64K", 65536),
    ("Custom…", -1),
)


@dataclass(frozen=True)
class PreferenceValidationError:
    title: str
    message: str


def merge_model_choices(
    installed_models: Iterable[str],
    current_model: str,
) -> list[str]:
    models = list(installed_models)
    current = current_model.strip()
    if current and current not in models:
        models.append(current)
    return models


def model_status_text(
    configured_model: str,
    installed_models: Iterable[str],
    discovery_error: str | None,
) -> str:
    configured = configured_model.strip()
    installed = set(installed_models)

    if configured and configured in installed:
        return "Installed"
    if discovery_error:
        return discovery_error
    if configured:
        return "Configured model not detected"
    return "No model selected"


def archive_status_text(raw_path: str) -> str:
    value = raw_path.strip()
    if not value:
        return "No archive folder configured"

    path = Path(value).expanduser()
    if path.exists() and path.is_dir():
        return "Available"
    return "Unavailable / not mounted"


def context_size_state(
    configured_size: int,
) -> tuple[int, int, bool]:
    known_sizes = {
        data
        for _, data in CONTEXT_SIZE_OPTIONS
        if data >= 0
    }
    if configured_size in known_sizes:
        return configured_size, max(configured_size, 16384), False
    return -1, configured_size if configured_size > 0 else 16384, True


def selected_context_size(
    selected_data: int,
    custom_value: int,
) -> int:
    if selected_data == -1:
        return int(custom_value)
    return int(selected_data)


def validate_preferences(
    raw_output: str,
    raw_archive: str,
    model_name: str,
) -> PreferenceValidationError | None:
    output_value = raw_output.strip()
    archive_value = raw_archive.strip()
    model_value = model_name.strip()

    if not output_value or not archive_value:
        return PreferenceValidationError(
            "Storage Paths Required",
            "Both storage paths are required.",
        )
    if not model_value:
        return PreferenceValidationError(
            "Ollama Model Required",
            "Choose or enter an Ollama model name, such as qwen3:8b.",
        )

    output_path = Path(output_value).expanduser()
    archive_path = Path(archive_value).expanduser()

    if not output_path.is_absolute():
        return PreferenceValidationError(
            "Invalid Output Folder",
            "Choose an absolute output folder path.",
        )
    if not archive_path.is_absolute():
        return PreferenceValidationError(
            "Invalid Archive Folder",
            "Choose an absolute archive folder path.",
        )
    if output_path == archive_path:
        return PreferenceValidationError(
            "Storage Paths Must Differ",
            "The working folder and archive folder must be different locations.",
        )
    return None


def preferences_saved_message(archive_path: Path) -> str:
    archive_message = (
        "Archive is currently available."
        if archive_path.exists() and archive_path.is_dir()
        else (
            "Archive is currently unavailable or not mounted. "
            "Publishing will require that location to be available."
        )
    )
    return (
        "Storage preferences were saved.\n\n"
        f"{archive_message}\n\n"
        "Restart Meeting Transcriber before using changed storage paths, "
        "Ollama model, or Ollama context override. Local and archived M4A "
        "retention values will be used by the next cleanup or publish run."
    )
