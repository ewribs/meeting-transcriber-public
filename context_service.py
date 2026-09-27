from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable


class NoMeetingsSelectedError(ValueError):
    pass


class NoLoadableMeetingsError(ValueError):
    pass


def resume_saved_session(
    session: dict,
    *,
    refresh: bool = False,
    resume_session_func: Callable[..., dict] | None = None,
) -> dict:
    """Resume or refresh a saved session through the backend session selector."""
    if resume_session_func is None:
        from query.session_context import build_resumed_session_context
        resume_session_func = build_resumed_session_context

    return resume_session_func(
        session,
        refresh=refresh,
    )


def _default_ad_hoc_dependencies():
    from merge_meeting_memories import load_memory
    from query.context import build_meeting_context
    from query.prep import build_meeting_prep

    return load_memory, build_meeting_context, build_meeting_prep


def _default_saved_dependencies():
    from merge_meeting_memories import load_memory
    from query.context import build_meeting_context
    from query.prep import build_meeting_prep
    from query.session_context import build_resumed_session_context
    from query.sessions import load_chat_session

    return (
        load_chat_session,
        build_resumed_session_context,
        load_memory,
        build_meeting_context,
        build_meeting_prep,
    )


def build_ad_hoc_context(
    meeting_runs: Iterable[str],
    meeting_index: list[dict],
    *,
    load_memory_func: Callable[[Path], dict] | None = None,
    build_context_func: Callable[..., dict] | None = None,
    build_prep_func: Callable[[dict], dict] | None = None,
) -> dict:
    runs = [run for run in meeting_runs if run]
    if not runs:
        raise NoMeetingsSelectedError("Select at least one meeting.")

    index_by_run = {
        meeting.get("meeting_run"): meeting
        for meeting in meeting_index
        if meeting.get("meeting_run")
    }

    selected: list[dict] = []
    for meeting_run in runs:
        meeting = index_by_run.get(meeting_run)
        if not meeting:
            continue

        location = meeting.get("location")
        if not location:
            continue

        selected.append(
            {
                **meeting,
                "meeting_dir": Path(location),
                "relevance_weight": 1,
            }
        )

    if not selected:
        raise NoLoadableMeetingsError(
            "Unable to load the selected meetings."
        )

    if (
        load_memory_func is None
        or build_context_func is None
        or build_prep_func is None
    ):
        defaults = _default_ad_hoc_dependencies()
        load_memory_func = load_memory_func or defaults[0]
        build_context_func = build_context_func or defaults[1]
        build_prep_func = build_prep_func or defaults[2]

    selected.sort(key=lambda item: item["meeting_run"])
    meeting_dirs = [item["meeting_dir"] for item in selected]
    meeting_memories = [
        load_memory_func(meeting_dir)
        for meeting_dir in meeting_dirs
    ]

    context = build_context_func(
        meeting_memories,
        selected,
    )
    prep = build_prep_func(context)

    session = {
        "session_name": None,
        "meeting_runs": [
            item["meeting_run"]
            for item in selected
        ],
        "conversation_history": [],
    }

    return {
        "context": context,
        "prep": prep,
        "meeting_dirs": meeting_dirs,
        "selected": selected,
        "session": session,
        "selection_criteria": {},
    }


def build_saved_session_context(
    session_name: str,
    *,
    load_session_func: Callable[[str], dict] | None = None,
    resume_session_func: Callable[..., dict] | None = None,
    load_memory_func: Callable[[Path], dict] | None = None,
    build_context_func: Callable[..., dict] | None = None,
    build_prep_func: Callable[[dict], dict] | None = None,
) -> dict:
    if (
        load_session_func is None
        or resume_session_func is None
        or load_memory_func is None
        or build_context_func is None
        or build_prep_func is None
    ):
        defaults = _default_saved_dependencies()
        load_session_func = load_session_func or defaults[0]
        resume_session_func = resume_session_func or defaults[1]
        load_memory_func = load_memory_func or defaults[2]
        build_context_func = build_context_func or defaults[3]
        build_prep_func = build_prep_func or defaults[4]

    session = load_session_func(session_name)
    resumed = resume_saved_session(
        session,
        refresh=False,
        resume_session_func=resume_session_func,
    )

    meeting_dirs = list(resumed["meeting_dirs"])
    selected = list(resumed["selected"])
    selection_criteria = resumed.get("selection_criteria") or {}

    meeting_memories = [
        load_memory_func(meeting_dir)
        for meeting_dir in meeting_dirs
    ]

    context = build_context_func(
        meeting_memories,
        selected,
        selection_criteria.get("topic"),
    )
    prep = build_prep_func(context)

    return {
        "session": session,
        "context": context,
        "prep": prep,
        "meeting_dirs": meeting_dirs,
        "selected": selected,
        "selection_criteria": selection_criteria,
    }
