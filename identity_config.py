"""Private local identity configuration for Meeting Transcriber.

The public repository must never contain a real user's identity. Runtime
self-identification is loaded from ``identity.local.json`` when present.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SELF_NAME = "User"
DEFAULT_SELF_REFERENCE_NAMES = ("User",)
DEFAULT_SELF_SPEAKER_LABEL = "Mic"


def _clean_name_list(values: Any, *, self_name: str) -> tuple[str, ...]:
    if values is None:
        values = []
    if not isinstance(values, list):
        raise RuntimeError(
            "identity.local.json self_reference_names must be a JSON list."
        )

    ordered = [self_name]
    ordered.extend(str(value).strip() for value in values if str(value).strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for value in ordered:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)

    return tuple(deduped)


def load_identity_config(path: Path | None = None) -> dict[str, object]:
    """Load local identity settings without requiring them in source control.

    Missing configuration intentionally falls back to generic public-safe
    values. A malformed existing file raises a clear error instead of silently
    changing participant/self attribution behavior.
    """

    if path is None:
        path = Path(__file__).resolve().parent / "identity.local.json"

    if not path.exists():
        return {
            "self_name": DEFAULT_SELF_NAME,
            "self_reference_names": DEFAULT_SELF_REFERENCE_NAMES,
            "self_speaker_label": DEFAULT_SELF_SPEAKER_LABEL,
            "configured": False,
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read identity configuration at {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("identity.local.json must contain a JSON object.")

    self_name = str(data.get("self_name", "")).strip()
    if not self_name:
        raise RuntimeError("identity.local.json self_name must not be blank.")

    self_speaker_label = str(
        data.get("self_speaker_label", DEFAULT_SELF_SPEAKER_LABEL)
    ).strip()
    if not self_speaker_label:
        raise RuntimeError(
            "identity.local.json self_speaker_label must not be blank."
        )

    references = _clean_name_list(
        data.get("self_reference_names"),
        self_name=self_name,
    )

    return {
        "self_name": self_name,
        "self_reference_names": references,
        "self_speaker_label": self_speaker_label,
        "configured": True,
    }
