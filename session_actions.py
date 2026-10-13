from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


class SessionActionError(Exception):
    """Base error for session mutation operations."""


class DuplicateSessionNameError(SessionActionError):
    pass


class CriteriaRequiredError(SessionActionError):
    pass


class NoMatchingMeetingsError(SessionActionError):
    pass


class FixedSessionError(SessionActionError):
    pass


class SessionAlreadyCurrent(SessionActionError):
    def __init__(self, unchanged: int):
        super().__init__("Session already current")
        self.unchanged = unchanged


@dataclass(frozen=True)
class SessionChangeSummary:
    added: int
    removed: int
    unchanged: int
    meeting_count: int


def normalize_session_name(name: str) -> str:
    return name.strip()


def session_name_exists(
    sessions_dir: Path,
    session_name: str,
    *,
    exclude_name: str | None = None,
) -> bool:
    target = normalize_session_name(session_name).casefold()
    excluded = (
        normalize_session_name(exclude_name).casefold()
        if exclude_name
        else None
    )

    if not target:
        return False

    return any(
        path.stem.casefold() == target
        and path.stem.casefold() != excluded
        for path in sessions_dir.glob("*.json")
    )


def validate_criteria(criteria: Mapping) -> None:
    fields = (
        "person",
        "title",
        "topic",
        "history_days",
        "start_date",
        "end_date",
    )
    if not any(criteria.get(field) for field in fields):
        raise CriteriaRequiredError(
            "Choose at least one criterion or a rolling history window."
        )


def _meeting_dirs(selected: Sequence[Mapping]) -> list[Path]:
    return [Path(meeting["meeting_dir"]) for meeting in selected]


def _meeting_runs(selected: Sequence[Mapping]) -> set[str]:
    return {str(meeting["meeting_run"]) for meeting in selected}


def _change_summary(
    old_runs: Iterable[str],
    new_runs: Iterable[str],
) -> SessionChangeSummary:
    old_set = set(old_runs)
    new_set = set(new_runs)
    return SessionChangeSummary(
        added=len(new_set - old_set),
        removed=len(old_set - new_set),
        unchanged=len(old_set & new_set),
        meeting_count=len(new_set),
    )


def create_dynamic_session(
    *,
    session_name: str,
    criteria: Mapping,
    sessions_dir: Path,
    select_meetings: Callable[[Mapping], Sequence[Mapping]],
    save_session: Callable,
) -> SessionChangeSummary:
    name = normalize_session_name(session_name)
    if not name:
        raise SessionActionError("Enter a name for the dynamic session.")
    if session_name_exists(sessions_dir, name):
        raise DuplicateSessionNameError(name)

    validate_criteria(criteria)
    selected = list(select_meetings(criteria))
    if not selected:
        raise NoMatchingMeetingsError(
            "No meetings currently match those criteria."
        )

    dirs = _meeting_dirs(selected)
    save_session(name, dirs, [], dict(criteria))
    return SessionChangeSummary(
        added=len(dirs), removed=0, unchanged=0, meeting_count=len(dirs)
    )


def edit_dynamic_session(
    *,
    session_name: str,
    session: Mapping,
    criteria: Mapping,
    select_meetings: Callable[[Mapping], Sequence[Mapping]],
    save_session: Callable,
) -> SessionChangeSummary:
    if not session.get("selection_criteria"):
        raise FixedSessionError("This session does not have dynamic criteria.")

    validate_criteria(criteria)
    selected = list(select_meetings(criteria))
    if not selected:
        raise NoMatchingMeetingsError(
            "No meetings currently match the edited criteria."
        )

    dirs = _meeting_dirs(selected)
    new_runs = _meeting_runs(selected)
    old_runs = set(session.get("meeting_runs", []))

    save_session(
        session_name,
        dirs,
        list(session.get("conversation_history", [])),
        dict(criteria),
    )
    return _change_summary(old_runs, new_runs)


def rename_session(
    *,
    old_name: str,
    new_name: str,
    sessions_dir: Path,
    rename: Callable[[str, str], None],
) -> str:
    old = normalize_session_name(old_name)
    new = normalize_session_name(new_name)
    if not new or new == old:
        return old
    if session_name_exists(sessions_dir, new, exclude_name=old):
        raise DuplicateSessionNameError(new)
    rename(old, new)
    return new


def refresh_dynamic_session(
    *,
    session_name: str,
    session: Mapping,
    resume_session: Callable[..., Mapping],
    save_session: Callable,
) -> SessionChangeSummary:
    criteria = session.get("selection_criteria")
    if not criteria:
        raise FixedSessionError(
            "This is a fixed/manual session and has no saved selection criteria to refresh."
        )

    resumed = resume_session(session, refresh=True)
    meeting_dirs = list(resumed.get("meeting_dirs", []))
    summary = dict(resumed.get("refresh_summary", {}))

    if not meeting_dirs:
        raise NoMatchingMeetingsError(
            "The saved criteria currently match no meetings."
        )

    added = int(summary.get("added", 0))
    removed = int(summary.get("removed", 0))
    unchanged = int(summary.get("unchanged", 0))

    if added == 0 and removed == 0:
        raise SessionAlreadyCurrent(unchanged)

    save_session(
        session_name,
        meeting_dirs,
        list(session.get("conversation_history", [])),
        criteria,
    )
    return SessionChangeSummary(
        added=added,
        removed=removed,
        unchanged=unchanged,
        meeting_count=len(meeting_dirs),
    )


def delete_session(
    *,
    session_name: str,
    delete: Callable[[str], None],
) -> None:
    delete(normalize_session_name(session_name))


def save_fixed_session(
    *,
    session_name: str,
    meeting_dirs: Sequence[Path],
    history: Sequence[Mapping],
    sessions_dir: Path,
    save_session: Callable,
) -> str:
    name = normalize_session_name(session_name)
    if not name:
        raise SessionActionError("Session name is required.")
    if session_name_exists(sessions_dir, name):
        raise DuplicateSessionNameError(name)

    save_session(name, list(meeting_dirs), list(history), None)
    return name
