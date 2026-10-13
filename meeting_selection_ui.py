from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class MeetingSelectionRow:
    meeting_run: str | None
    checked: bool
    visible: bool = True


def selected_runs(
    rows: Iterable[MeetingSelectionRow],
) -> list[str]:
    return [
        row.meeting_run
        for row in rows
        if row.checked and row.meeting_run
    ]


def visible_runs(
    rows: Iterable[MeetingSelectionRow],
) -> list[str]:
    return [
        row.meeting_run
        for row in rows
        if row.visible and row.meeting_run
    ]


def selected_count_label(
    rows: Iterable[MeetingSelectionRow],
) -> str:
    count = sum(1 for row in rows if row.checked)
    return f"Selected: {count}"


def context_status_label(
    context_runs: Sequence[str],
    checked_runs: Sequence[str],
) -> str:
    if set(context_runs) == set(checked_runs):
        return "Selected Meetings Context"

    return "Selected Meetings Context — REBUILD REQUIRED"


def in_context(
    meeting_run: str | None,
    context_runs: Sequence[str] | set[str],
) -> bool:
    return bool(
        meeting_run
        and meeting_run in set(context_runs)
    )
