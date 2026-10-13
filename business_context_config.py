"""Private local business-context configuration for Meeting Transcriber.

Organization-specific aliases and topic-normalization rules belong in
``business_context.local.json`` and must not be committed. The public repository
contains only generic configuration machinery and examples.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


DEFAULT_TOPIC_NORMALIZATION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = ()


def _normalize_rules(values: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if values is None:
        return DEFAULT_TOPIC_NORMALIZATION_RULES
    if not isinstance(values, list):
        raise RuntimeError(
            "business_context.local.json topic_normalization_rules must be a JSON list."
        )

    normalized: list[tuple[str, tuple[str, ...]]] = []
    seen_keys: set[str] = set()

    for index, item in enumerate(values, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(
                "business_context.local.json topic_normalization_rules "
                f"entry {index} must be a JSON object."
            )

        key = str(item.get("key", "")).strip()
        if not key or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", key):
            raise RuntimeError(
                "business_context.local.json topic-normalization keys must use "
                "lowercase snake_case."
            )
        if key in seen_keys:
            raise RuntimeError(
                f"business_context.local.json contains duplicate topic key: {key}"
            )

        markers = item.get("markers")
        if not isinstance(markers, list) or not markers:
            raise RuntimeError(
                f"business_context.local.json topic key {key!r} must have a non-empty markers list."
            )

        cleaned_markers: list[str] = []
        seen_markers: set[str] = set()
        for marker in markers:
            value = str(marker).strip().casefold()
            if not value or value in seen_markers:
                continue
            seen_markers.add(value)
            cleaned_markers.append(value)

        if not cleaned_markers:
            raise RuntimeError(
                f"business_context.local.json topic key {key!r} must have at least one marker."
            )

        seen_keys.add(key)
        normalized.append((key, tuple(cleaned_markers)))

    return tuple(normalized)


def load_business_context_config(path: Path | None = None) -> dict[str, object]:
    """Load optional private organization-specific runtime context.

    Missing configuration intentionally yields public-safe generic behavior.
    Malformed existing configuration fails clearly instead of silently changing
    topic normalization behavior.
    """

    if path is None:
        path = Path(__file__).resolve().parent / "business_context.local.json"

    if not path.exists():
        return {
            "topic_normalization_rules": DEFAULT_TOPIC_NORMALIZATION_RULES,
            "configured": False,
        }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read business context configuration at {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("business_context.local.json must contain a JSON object.")

    return {
        "topic_normalization_rules": _normalize_rules(
            data.get("topic_normalization_rules")
        ),
        "configured": True,
    }
