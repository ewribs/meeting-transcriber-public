"""Extra rule kinds for dynamic sessions (any-of people, status, excludes,
and the any/all match mode)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


RULE_KEYS = ("people", "status", "exclude_title", "exclude_topic", "match")
_STATUS_BY_FOLD = {"published": "Published", "unpublished": "Unpublished"}


def normalize_rules(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Clean the extra rule kinds; empty or invalid values are dropped."""
    raw = raw or {}
    rules: dict[str, Any] = {}

    people_raw = raw.get("people")
    if isinstance(people_raw, str):
        people_raw = people_raw.split(",")
    if isinstance(people_raw, (list, tuple)):
        people = []
        for name in people_raw:
            text = str(name).strip()
            if text and text not in people:
                people.append(text)
        if people:
            rules["people"] = people

    status = _STATUS_BY_FOLD.get(str(raw.get("status") or "").strip().casefold())
    if status:
        rules["status"] = status

    # "all" is the default and is not stored; only "any" is kept.
    if str(raw.get("match") or "").strip().casefold() == "any":
        rules["match"] = "any"

    for key in ("exclude_title", "exclude_topic"):
        text = str(raw.get(key) or "").strip()
        if text:
            rules[key] = text

    return rules


def saved_rules(selection_criteria: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_rules(
        {key: selection_criteria.get(key) for key in RULE_KEYS}
    )


def with_rules(
    criteria: Mapping[str, Any],
    rules: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return criteria with the extra rules applied (old rules replaced)."""
    merged = {k: v for k, v in criteria.items() if k not in RULE_KEYS}
    merged.update(normalize_rules(rules))
    return merged
