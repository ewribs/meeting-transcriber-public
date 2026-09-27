from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _normalize_topics(memory: dict[str, Any]) -> list[dict[str, str]]:
    topics: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in memory.get("topics", []):
        if not isinstance(item, dict):
            continue

        name = _clean_text(
            item.get("topic")
            or item.get("topic_key")
        )
        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)

        topics.append(
            {
                "name": name,
                "status": _clean_text(item.get("status")),
                "summary": _clean_text(item.get("summary")),
            }
        )

    return topics


def _normalize_commitments(memory: dict[str, Any]) -> list[dict[str, str]]:
    commitments: list[dict[str, str]] = []

    for item in memory.get("commitments", []):
        if not isinstance(item, dict):
            continue

        action = _clean_text(item.get("action"))
        if not action:
            continue

        commitments.append(
            {
                "owner": _clean_text(item.get("owner")),
                "action": action,
                "status": _clean_text(item.get("status")),
            }
        )

    return commitments


def _normalize_decisions(memory: dict[str, Any]) -> list[str]:
    decisions: list[str] = []

    for item in memory.get("decisions", []):
        if isinstance(item, dict):
            text = _clean_text(item.get("decision"))
        else:
            text = _clean_text(item)

        if text and text not in decisions:
            decisions.append(text)

    return decisions


def _normalize_text_list(memory: dict[str, Any], key: str) -> list[str]:
    values: list[str] = []

    for item in memory.get(key, []):
        text = _clean_text(item)
        if text and text not in values:
            values.append(text)

    return values




def _normalize_processing(metadata: dict[str, Any]) -> dict[str, Any] | None:
    processing = metadata.get("processing")
    if not isinstance(processing, dict) or not processing:
        return None

    return {
        "ai_model": _clean_text(processing.get("ai_model")),
        "profile_display": _clean_text(processing.get("profile_display")),
        "mode": _clean_text(processing.get("mode")),
        "context_size_tokens": int(processing.get("context_size_tokens") or 0),
        "estimated_prompt_tokens": int(processing.get("estimated_prompt_tokens") or 0),
        "whisper_model": _clean_text(processing.get("whisper_model")),
        "whisper_chunk_minutes": int(processing.get("whisper_chunk_minutes") or 0),
    }


def load_meeting_detail(meeting: dict[str, Any]) -> dict[str, Any]:
    """Load normalized detail for one catalog meeting.

    Missing/invalid optional artifacts are treated as absent detail instead
    of making the whole meeting catalog unavailable.
    """
    location = _clean_text(meeting.get("location"))

    if not location:
        return {
            "summary": "",
            "topics": [],
            "decisions": [],
            "commitments": [],
            "open_questions": [],
            "follow_ups": [],
            "processing": None,
            "has_summary": False,
            "has_memory": False,
        }

    meeting_dir = Path(location)
    summary_path = meeting_dir / "meeting_summary.md"
    memory_path = meeting_dir / "meeting_memory.json"
    metadata_path = meeting_dir / "meeting_metadata.json"

    summary = _read_text(summary_path)
    memory = _read_json_object(memory_path)
    metadata = _read_json_object(metadata_path)

    return {
        "summary": summary,
        "topics": _normalize_topics(memory),
        "decisions": _normalize_decisions(memory),
        "commitments": _normalize_commitments(memory),
        "open_questions": _normalize_text_list(memory, "open_questions"),
        "follow_ups": _normalize_text_list(memory, "follow_ups"),
        "processing": _normalize_processing(metadata),
        "has_summary": bool(summary),
        "has_memory": bool(memory),
    }
