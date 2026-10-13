from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

ANY_PERSON_LABEL = "Any person"
HISTORY_OPTIONS = (
    "Last 30 days",
    "Last 90 days",
    "Last 180 days",
    "All history",
)
DEFAULT_HISTORY_LABEL = "Last 90 days"

_HISTORY_DAYS_BY_LABEL = {
    "Last 30 days": 30,
    "Last 90 days": 90,
    "Last 180 days": 180,
    "All history": None,
}
_HISTORY_LABEL_BY_DAYS = {
    30: "Last 30 days",
    90: "Last 90 days",
    180: "Last 180 days",
    None: "All history",
}


def available_people(
    meetings: Iterable[Mapping[str, Any]],
    *,
    current_person: str | None = None,
) -> list[str]:
    people = {
        str(participant).strip()
        for meeting in meetings
        for participant in meeting.get("participants", [])
        if str(participant).strip()
    }

    if current_person and current_person.strip():
        people.add(current_person.strip())

    return sorted(people, key=lambda value: (value.casefold(), value))


def normalize_person(person_text: str) -> str | None:
    person = person_text.strip()
    if not person or person == ANY_PERSON_LABEL:
        return None
    return person


def history_days_for_label(label: str) -> int | None:
    return _HISTORY_DAYS_BY_LABEL[label]


def history_label_for_days(days: int | None) -> str:
    return _HISTORY_LABEL_BY_DAYS.get(days, "All history")


def saved_range_label(
    start_date: str | None,
    end_date: str | None,
) -> str:
    return (
        "Keep saved date range: "
        f"{start_date or 'Any'} to {end_date or 'Any'}"
    )


def edit_history_state(
    selection_criteria: Mapping[str, Any],
) -> tuple[list[str], str, str | None]:
    options = list(HISTORY_OPTIONS)
    history_days = selection_criteria.get("history_days")
    start_date = selection_criteria.get("start_date")
    end_date = selection_criteria.get("end_date")

    if not history_days and (start_date or end_date):
        custom_label = saved_range_label(start_date, end_date)
        options.append(custom_label)
        return options, custom_label, custom_label

    return options, history_label_for_days(history_days), None


def build_create_criteria(
    *,
    person_text: str,
    title_text: str,
    topic_text: str,
    history_label: str,
) -> dict[str, Any]:
    return {
        "person": normalize_person(person_text),
        "title": title_text.strip() or None,
        "topic": topic_text.strip() or None,
        "history_days": history_days_for_label(history_label),
        "start_date": None,
        "end_date": None,
    }


def build_edit_criteria(
    *,
    person_text: str,
    title_text: str,
    topic_text: str,
    selected_history_label: str,
    custom_range_label: str | None,
    saved_start_date: str | None,
    saved_end_date: str | None,
) -> dict[str, Any]:
    keep_saved_range = (
        custom_range_label is not None
        and selected_history_label == custom_range_label
    )

    return {
        "person": normalize_person(person_text),
        "title": title_text.strip() or None,
        "topic": topic_text.strip() or None,
        "history_days": (
            None
            if keep_saved_range
            else history_days_for_label(selected_history_label)
        ),
        "start_date": saved_start_date if keep_saved_range else None,
        "end_date": saved_end_date if keep_saved_range else None,
    }


def criteria_present(criteria: Mapping[str, Any]) -> bool:
    return any(
        criteria.get(key)
        for key in (
            "person",
            "title",
            "topic",
            "history_days",
            "start_date",
            "end_date",
        )
    )
