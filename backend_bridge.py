#!/usr/bin/env python3
"""JSON command bridge for the native SwiftUI front end.

The meeting catalog command remains intentionally lightweight.
Richer artifacts are loaded lazily for a selected meeting.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_participants(value: Any) -> list[str]:
    if not value:
        return []

    raw: Iterable[Any]
    if isinstance(value, str):
        raw = [value]
    else:
        raw = value

    participants: list[str] = []
    seen: set[str] = set()

    for item in raw:
        name = _clean_text(item)
        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue

        seen.add(key)
        participants.append(name)

    return participants


def _meeting_status(meeting: dict[str, Any]) -> str:
    explicit = _clean_text(
        meeting.get("publish_status")
        or meeting.get("status")
    )

    if explicit:
        lower = explicit.casefold()

        if lower == "published":
            return "Published"

        if lower == "unpublished":
            return "Unpublished"

        return explicit

    published = meeting.get("is_published")

    if not isinstance(published, bool):
        published = meeting.get("published")

    if isinstance(published, bool):
        return "Published" if published else "Unpublished"

    return "Published"


def normalize_meeting(
    meeting: dict[str, Any],
) -> dict[str, Any]:
    run = _clean_text(
        meeting.get("meeting_run")
        or meeting.get("run")
        or meeting.get("run_name")
        or meeting.get("directory")
        or meeting.get("id")
    )

    title = _clean_text(
        meeting.get("display_title")
        or meeting.get("title")
        or meeting.get("meeting_title")
        or run
    )

    meeting_datetime = _clean_text(
        meeting.get("meeting_datetime")
        or meeting.get("date")
        or meeting.get("meeting_date")
    )

    date = (
        meeting_datetime[:10]
        if len(meeting_datetime) >= 10
        else meeting_datetime
    )

    status = _meeting_status(meeting)

    return {
        "id": run or title,
        "run": run,
        "title": title,
        "date": date,
        "status": status,
        "is_published": status == "Published",
        "can_publish": status == "Unpublished",
        "participants": _normalize_participants(
            meeting.get("participants")
        ),
    }


def load_meeting_catalog() -> list[dict[str, Any]]:
    from meeting_selector import load_meeting_index

    return load_meeting_index()


def meetings_payload() -> dict[str, Any]:
    return {
        "schema_version": 4,
        "meetings": [
            normalize_meeting(item)
            for item in load_meeting_catalog()
        ],
    }


def meeting_detail_payload(run: str) -> dict[str, Any]:
    from meeting_detail_service import load_meeting_detail

    for meeting in load_meeting_catalog():
        meeting_run = _clean_text(
            meeting.get("meeting_run")
            or meeting.get("run")
        )

        if meeting_run != run:
            continue

        detail = load_meeting_detail(meeting)

        return {
            "schema_version": 6,
            "run": run,
            "summary": _clean_text(
                detail.get("summary")
            ),
            "topics": detail.get("topics", []),
            "decisions": detail.get("decisions", []),
            "commitments": detail.get("commitments", []),
            "open_questions": detail.get("open_questions", []),
            "follow_ups": detail.get("follow_ups", []),
            "processing": detail.get("processing"),
            "has_summary": bool(
                detail.get("has_summary")
            ),
            "has_memory": bool(
                detail.get("has_memory")
            ),
        }

    raise ValueError(
        f"Meeting run not found: {run}"
    )





def meeting_delete_plan_payload(run: str) -> dict[str, Any]:
    from meeting_delete_service import resolve_unpublished_meeting_delete_plan

    for meeting in load_meeting_catalog():
        meeting_run = _clean_text(meeting.get("meeting_run") or meeting.get("run"))
        if meeting_run != run:
            continue
        if _meeting_status(meeting) == "Published":
            raise ValueError("Published meetings cannot be deleted from the local unpublished cleanup action.")
        return resolve_unpublished_meeting_delete_plan(run)

    raise ValueError(f"Meeting run not found: {run}")


def finalize_meeting_delete_payload(run: str) -> dict[str, Any]:
    from meeting_delete_service import finalize_unpublished_meeting_delete

    return finalize_unpublished_meeting_delete(run)


def meeting_unpublish_plan_payload(run: str) -> dict[str, Any]:
    from meeting_delete_service import resolve_published_meeting_unpublish_plan

    for meeting in load_meeting_catalog():
        meeting_run = _clean_text(meeting.get("meeting_run") or meeting.get("run"))
        if meeting_run != run:
            continue
        if _meeting_status(meeting) != "Published":
            raise ValueError("Only published meetings can be unpublished.")
        return resolve_published_meeting_unpublish_plan(run)

    raise ValueError(f"Meeting run not found: {run}")


def finalize_meeting_unpublish_payload(run: str) -> dict[str, Any]:
    from meeting_delete_service import finalize_published_meeting_unpublish

    return finalize_published_meeting_unpublish(run)

def audio_contract_payload(path: str) -> dict[str, Any]:
    from audio_contract import inspect_audio_contract

    return inspect_audio_contract(path)


def finalize_audio_recording_payload(
    source_path: str,
    output_path: str,
    sample_rate: int,
    channels: int,
) -> dict[str, Any]:
    from audio_contract import finalize_recording_to_m4a

    return finalize_recording_to_m4a(
        source_path,
        output_path,
        sample_rate=sample_rate,
        channels=channels,
    )


def publish_meeting_payload(
    run: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    from pathlib import Path

    for meeting in load_meeting_catalog():
        meeting_run = _clean_text(
            meeting.get("meeting_run")
            or meeting.get("run")
        )

        if meeting_run != run:
            continue

        status = _meeting_status(meeting)

        location = _clean_text(
            meeting.get("location")
        )

        if not location:
            raise ValueError(
                f"Meeting location is unavailable: {run}"
            )

        if dry_run:
            return {
                "schema_version": 4,
                "run": run,
                "dry_run": True,
                "current_status": status,
                "location": location,
                "would_publish": status != "Published",
                "message": (
                    "Meeting is eligible for Publish & Archive."
                    if status != "Published"
                    else "Meeting is already published; no publish action would be taken."
                ),
            }

        if status == "Published":
            raise ValueError(
                f"Meeting is already published: {run}"
            )

        # Import only when an unpublished meeting is actually being
        # published. This keeps read-only bridge commands lightweight.
        from publish_workflow import publish_and_archive_meeting

        result = publish_and_archive_meeting(
            Path(location)
        )

        archived_path = result.get(
            "archived_path",
            "",
        )

        return {
            "schema_version": 4,
            "run": run,
            "dry_run": False,
            "status": "Published",
            "archived_path": str(archived_path),
        }

    raise ValueError(
        f"Meeting run not found: {run}"
    )



def _read_json_object(path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def sessions_payload() -> dict[str, Any]:
    from config import ARCHIVE_DIR
    from session_browser import (
        format_session_criteria,
        load_session_browser_entries,
    )

    sessions_dir = (
        ARCHIVE_DIR / "query_sessions"
    )

    entries = load_session_browser_entries(
        sessions_dir
    )

    sessions = []

    for entry in entries:
        payload = _read_json_object(
            entry.path
        )

        criteria_lines = [
            line
            for line in format_session_criteria(
                payload.get("selection_criteria")
            )
            if line.strip()
            and line.strip().casefold() != "criteria"
            and set(line.strip()) != {"-"}
        ]

        sessions.append(
            {
                "id": entry.name,
                "name": entry.name,
                "label": entry.label,
                "tooltip": entry.tooltip,
                "session_type": entry.session_type,
                "meeting_count": entry.meeting_count,
                "turn_count": entry.turn_count,
                "criteria": criteria_lines,
                "path": str(entry.path),
            }
        )

    return {
        "schema_version": 5,
        "sessions": sessions,
    }



def refresh_session_payload(
    session_name: str,
) -> dict[str, Any]:
    from context_service import resume_saved_session
    from query.sessions import (
        load_chat_session,
        save_chat_session,
    )
    from session_actions import (
        SessionAlreadyCurrent,
        refresh_dynamic_session,
    )

    session = load_chat_session(session_name)

    try:
        summary = refresh_dynamic_session(
            session_name=session_name,
            session=session,
            resume_session=resume_saved_session,
            save_session=save_chat_session,
        )
    except SessionAlreadyCurrent as exc:
        return {
            "schema_version": 6,
            "session_name": session_name,
            "result": "already_current",
            "added": 0,
            "removed": 0,
            "unchanged": int(exc.unchanged),
            "meeting_count": len(
                session.get("meeting_runs", [])
            ),
        }

    return {
        "schema_version": 6,
        "session_name": session_name,
        "result": "refreshed",
        "added": int(summary.added),
        "removed": int(summary.removed),
        "unchanged": int(summary.unchanged),
        "meeting_count": int(summary.meeting_count),
    }



def rename_session_payload(
    old_name: str,
    new_name: str,
) -> dict[str, Any]:
    from config import ARCHIVE_DIR
    from query.sessions import rename_chat_session
    from session_actions import rename_session

    renamed = rename_session(
        old_name=old_name,
        new_name=new_name,
        sessions_dir=(
            ARCHIVE_DIR / "query_sessions"
        ),
        rename=rename_chat_session,
    )

    return {
        "schema_version": 7,
        "old_name": old_name,
        "new_name": renamed,
        "renamed": renamed != old_name,
    }



def delete_session_payload(
    session_name: str,
) -> dict[str, Any]:
    from query.sessions import delete_chat_session
    from session_actions import delete_session

    delete_session(
        session_name=session_name,
        delete=delete_chat_session,
    )

    return {
        "schema_version": 8,
        "session_name": session_name,
        "deleted": True,
    }



def session_editor_payload(
    session_name: str | None = None,
) -> dict[str, Any]:
    from session_criteria_ui import (
        DEFAULT_HISTORY_LABEL,
        HISTORY_OPTIONS,
        edit_history_state,
    )

    if not session_name:
        return {
            "schema_version": 9,
            "mode": "create",
            "session_name": "",
            "person": "",
            "title": "",
            "topic": "",
            "history_options": list(HISTORY_OPTIONS),
            "selected_history_label":
                DEFAULT_HISTORY_LABEL,
            "custom_range_label": None,
        }

    from query.sessions import load_chat_session

    session = load_chat_session(session_name)
    criteria = dict(
        session.get("selection_criteria") or {}
    )

    if not criteria:
        raise ValueError(
            "This fixed/manual session does not "
            "have dynamic criteria to edit."
        )

    (
        history_options,
        selected_history_label,
        custom_range_label,
    ) = edit_history_state(criteria)

    return {
        "schema_version": 9,
        "mode": "edit",
        "session_name": session_name,
        "person": criteria.get("person") or "",
        "title": criteria.get("title") or "",
        "topic": criteria.get("topic") or "",
        "history_options": history_options,
        "selected_history_label":
            selected_history_label,
        "custom_range_label":
            custom_range_label,
    }


def create_dynamic_session_payload(
    session_name: str,
    person_text: str,
    title_text: str,
    topic_text: str,
    history_label: str,
) -> dict[str, Any]:
    from config import ARCHIVE_DIR
    from query.session_context import (
        select_session_meetings,
    )
    from query.sessions import save_chat_session
    from session_actions import (
        CriteriaRequiredError,
        create_dynamic_session,
    )
    from session_criteria_ui import (
        build_create_criteria,
        criteria_present,
    )

    criteria = build_create_criteria(
        person_text=person_text,
        title_text=title_text,
        topic_text=topic_text,
        history_label=history_label,
    )

    if not criteria_present(criteria):
        raise CriteriaRequiredError(
            "Choose at least one criterion or "
            "a rolling history window."
        )

    summary = create_dynamic_session(
        session_name=session_name,
        criteria=criteria,
        sessions_dir=(
            ARCHIVE_DIR / "query_sessions"
        ),
        select_meetings=select_session_meetings,
        save_session=save_chat_session,
    )

    return {
        "schema_version": 9,
        "session_name": session_name.strip(),
        "added": int(summary.added),
        "removed": int(summary.removed),
        "unchanged": int(summary.unchanged),
        "meeting_count": int(summary.meeting_count),
    }


def edit_dynamic_session_payload(
    session_name: str,
    person_text: str,
    title_text: str,
    topic_text: str,
    history_label: str,
) -> dict[str, Any]:
    from query.session_context import (
        select_session_meetings,
    )
    from query.sessions import (
        load_chat_session,
        save_chat_session,
    )
    from session_actions import (
        CriteriaRequiredError,
        edit_dynamic_session,
    )
    from session_criteria_ui import (
        build_edit_criteria,
        criteria_present,
        edit_history_state,
    )

    session = load_chat_session(session_name)
    saved_criteria = dict(
        session.get("selection_criteria") or {}
    )

    (
        _history_options,
        _selected_history_label,
        custom_range_label,
    ) = edit_history_state(saved_criteria)

    criteria = build_edit_criteria(
        person_text=person_text,
        title_text=title_text,
        topic_text=topic_text,
        selected_history_label=history_label,
        custom_range_label=custom_range_label,
        saved_start_date=(
            saved_criteria.get("start_date")
        ),
        saved_end_date=(
            saved_criteria.get("end_date")
        ),
    )

    if not criteria_present(criteria):
        raise CriteriaRequiredError(
            "Choose at least one criterion or "
            "a rolling history window."
        )

    summary = edit_dynamic_session(
        session_name=session_name,
        session=session,
        criteria=criteria,
        select_meetings=select_session_meetings,
        save_session=save_chat_session,
    )

    return {
        "schema_version": 9,
        "session_name": session_name,
        "added": int(summary.added),
        "removed": int(summary.removed),
        "unchanged": int(summary.unchanged),
        "meeting_count": int(summary.meeting_count),
    }




def meeting_context_payload(
    meeting_runs_json: str,
) -> dict[str, Any]:
    from context_service import (
        build_ad_hoc_context,
    )
    from meeting_selector import (
        load_meeting_index,
    )
    from query_presentation import (
        format_session_prep,
    )

    try:
        raw_runs = json.loads(
            meeting_runs_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Meeting selection is not valid JSON."
        ) from exc

    if not isinstance(raw_runs, list):
        raise ValueError(
            "Meeting selection must be a list."
        )

    meeting_runs = [
        str(run).strip()
        for run in raw_runs
        if str(run).strip()
    ]

    bundle = build_ad_hoc_context(
        meeting_runs,
        load_meeting_index(),
    )

    prep = dict(
        bundle["prep"]
    )

    prep_text = format_session_prep(
        prep,
        "MEETING CONTEXT",
    )

    selected = list(
        bundle["selected"]
    )

    return {
        "schema_version": 14,
        "meeting_count": int(
            prep.get(
                "meeting_count",
                len(selected),
            )
        ),
        "meeting_runs": [
            item["meeting_run"]
            for item in selected
        ],
        "meeting_labels": [
            (
                f"{item['meeting_run'][:10]} | "
                f"{item.get('display_title', item['meeting_run'])}"
            )
            for item in selected
        ],
        "prep_text": prep_text,
    }



def save_meeting_context_session_payload(
    session_name: str,
    meeting_runs_json: str,
    conversation_json: str,
) -> dict[str, Any]:
    from pathlib import Path

    from config import ARCHIVE_DIR
    from query.sessions import save_chat_session
    from session_actions import save_fixed_session

    try:
        raw_runs = json.loads(
            meeting_runs_json
        )
        raw_history = json.loads(
            conversation_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Meeting context session request contains invalid JSON."
        ) from exc

    if not isinstance(raw_runs, list):
        raise ValueError(
            "Meeting selection must be a list."
        )

    if not isinstance(raw_history, list):
        raise ValueError(
            "Conversation history must be a list."
        )

    meeting_runs = [
        str(run).strip()
        for run in raw_runs
        if str(run).strip()
    ]

    if not meeting_runs:
        raise ValueError(
            "Select at least one meeting before saving a session."
        )

    meeting_dirs = []
    unavailable_runs = []

    for meeting_run in meeting_runs:
        meeting_dir = (
            ARCHIVE_DIR
            / meeting_run
        )

        if not (
            meeting_dir.exists()
            and (
                meeting_dir
                / "meeting_memory.json"
            ).exists()
        ):
            unavailable_runs.append(
                meeting_run
            )
            continue

        meeting_dirs.append(
            meeting_dir
        )

    if unavailable_runs:
        preview = ", ".join(
            unavailable_runs[:3]
        )

        if len(unavailable_runs) > 3:
            preview += (
                f" and {len(unavailable_runs) - 3} more"
            )

        raise ValueError(
            "Save as Session requires published/archived meetings. "
            "Publish these meetings first: "
            f"{preview}"
        )

    history = []

    for item in raw_history:
        if not isinstance(item, dict):
            continue

        role = str(
            item.get("role", "")
        ).strip()
        content = str(
            item.get("content", "")
        ).strip()

        if (
            role in {"user", "assistant"}
            and content
        ):
            history.append(
                {
                    "role": role,
                    "content": content,
                }
            )

    saved_name = save_fixed_session(
        session_name=session_name,
        meeting_dirs=meeting_dirs,
        history=history,
        sessions_dir=(
            ARCHIVE_DIR
            / "query_sessions"
        ),
        save_session=save_chat_session,
    )

    return {
        "schema_version": 15,
        "session_name": saved_name,
        "meeting_count": len(
            meeting_dirs
        ),
        "turn_count": len(history) // 2,
    }



def meeting_context_query_plan_payload(
    meeting_runs_json: str,
    user_prompt: str,
    conversation_json: str,
    query_mode: str = "normal",
) -> dict[str, Any]:
    from app_settings import (
        load_app_settings,
    )
    from context_service import (
        build_ad_hoc_context,
    )
    from meeting_selector import (
        load_meeting_index,
    )
    from query.synthesis import (
        synthesis_plan_payload,
    )

    if query_mode != "synthesis":
        return {
            "schema_version": 17,
            "mode": "normal",
            "estimated_prompt_tokens": 0,
            "direct_token_budget": 0,
            "chunk_count": 0,
            "inference_calls": 1,
            "meeting_count": 0,
            "hardware_label": "",
            "profile": "",
            "status_text": "Qwen is working…",
        }

    prompt = user_prompt.strip()

    if not prompt:
        raise ValueError(
            "Enter a question for the selected meeting context."
        )

    try:
        raw_runs = json.loads(
            meeting_runs_json
        )
        raw_history = json.loads(
            conversation_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Meeting context plan contains invalid JSON."
        ) from exc

    if not isinstance(raw_runs, list):
        raise ValueError(
            "Meeting selection must be a list."
        )

    if not isinstance(raw_history, list):
        raise ValueError(
            "Conversation history must be a list."
        )

    meeting_runs = [
        str(run).strip()
        for run in raw_runs
        if str(run).strip()
    ]

    history = []

    for item in raw_history:
        if not isinstance(item, dict):
            continue

        role = str(
            item.get("role", "")
        ).strip()
        content = str(
            item.get("content", "")
        ).strip()

        if (
            role in {"user", "assistant"}
            and content
        ):
            history.append(
                {
                    "role": role,
                    "content": content,
                }
            )

    bundle = build_ad_hoc_context(
        meeting_runs,
        load_meeting_index(),
    )

    context = bundle["context"]

    settings = load_app_settings()

    execution_profile = str(
        settings.get(
            "performance_profile",
            "Auto",
        )
        or "Auto"
    )

    plan = synthesis_plan_payload(
        prompt,
        context.get(
            "meeting_memories"
        )
        or [],
        context.get(
            "selected_meetings"
        )
        or [],
        history,
        execution_profile=execution_profile,
    )

    return {
        "schema_version": 17,
        **plan,
    }


def meeting_context_query_payload(
    meeting_runs_json: str,
    user_prompt: str,
    conversation_json: str,
    query_mode: str = "normal",
) -> dict[str, Any]:
    import time

    from app_settings import (
        load_app_settings,
    )
    from context_service import (
        build_ad_hoc_context,
    )
    from execution_telemetry import (
        record_execution_telemetry,
    )
    from meeting_selector import (
        load_meeting_index,
    )
    from query.chat import run_query
    from query.changes import (
        run_changes_query,
    )
    from query.synthesis import (
        run_synthesis_query,
    )
    from query_presentation import (
        format_query_finished_status,
    )

    prompt = user_prompt.strip()

    if not prompt:
        raise ValueError(
            "Enter a question for the selected meeting context."
        )

    try:
        raw_runs = json.loads(
            meeting_runs_json
        )
        raw_history = json.loads(
            conversation_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Meeting context request contains invalid JSON."
        ) from exc

    if not isinstance(raw_runs, list):
        raise ValueError(
            "Meeting selection must be a list."
        )

    if not isinstance(raw_history, list):
        raise ValueError(
            "Conversation history must be a list."
        )

    meeting_runs = [
        str(run).strip()
        for run in raw_runs
        if str(run).strip()
    ]

    history = []

    for item in raw_history:
        if not isinstance(item, dict):
            continue

        role = str(
            item.get("role", "")
        ).strip()

        content = str(
            item.get("content", "")
        ).strip()

        if (
            role in {"user", "assistant"}
            and content
        ):
            history.append(
                {
                    "role": role,
                    "content": content,
                }
            )

    bundle = build_ad_hoc_context(
        meeting_runs,
        load_meeting_index(),
    )

    context = bundle["context"]

    settings = load_app_settings()

    execution_profile = str(
        settings.get(
            "performance_profile",
            "Auto",
        )
        or "Auto"
    )

    started_at = time.perf_counter()

    if query_mode == "synthesis":
        response, execution_metadata = (
            run_synthesis_query(
                prompt,
                context.get(
                    "meeting_memories"
                )
                or [],
                context.get(
                    "selected_meetings"
                )
                or [],
                history,
                return_execution_metadata=True,
                execution_profile=
                    execution_profile,
            )
        )
    elif query_mode == "changes":
        (
            response,
            execution_metadata,
            _changes_comparison,
        ) = run_changes_query(
            prompt,
            context.get(
                "meeting_memories"
            )
            or [],
            context.get(
                "selected_meetings"
            )
            or [],
            execution_profile=
                execution_profile,
        )
    else:
        response, execution_metadata = run_query(
            prompt,
            context["merged_memory"],
            history,
            include_grounded=True,
            print_output=False,
            meeting_memories=context.get(
                "meeting_memories"
            ),
            selected_meetings=context.get(
                "selected_meetings"
            ),
            topic_filter=context.get(
                "topic_filter"
            ),
            return_execution_metadata=True,
            execution_profile=execution_profile,
        )

    elapsed_seconds = (
        time.perf_counter()
        - started_at
    )

    record_execution_telemetry(
        execution_metadata,
        elapsed_seconds=elapsed_seconds,
    )

    return {
        "schema_version": 14,
        "assistant_response": response,
        "elapsed_seconds": round(
            elapsed_seconds,
            3,
        ),
        "status_text":
            format_query_finished_status(
                execution_metadata,
                execution_profile,
            ),
        "execution_mode":
            execution_metadata.get(
                "mode",
                "direct",
            ),
        "inference_calls": int(
            execution_metadata.get(
                "inference_calls",
                1,
            )
        ),
    }


def session_detail_payload(
    session_name: str,
) -> dict[str, Any]:
    from context_service import (
        build_saved_session_context,
    )
    from query_presentation import (
        format_session_prep,
    )

    bundle = build_saved_session_context(
        session_name
    )

    session = dict(bundle["session"])
    prep = dict(bundle["prep"])
    selection_criteria = (
        bundle.get("selection_criteria")
        or {}
    )

    history = []

    for item in session.get(
        "conversation_history",
        [],
    ):
        role = _clean_text(
            item.get("role")
        )
        content = _clean_text(
            item.get("content")
        )

        if (
            role not in {"user", "assistant"}
            or not content
        ):
            continue

        history.append(
            {
                "role": role,
                "content": content,
            }
        )

    prep_text = format_session_prep(
        prep,
        f"SESSION: {session_name}",
        selection_criteria=(
            selection_criteria
        ),
    )

    return {
        "schema_version": 10,
        "session_name": session_name,
        "meeting_count": int(
            prep.get("meeting_count", 0)
        ),
        "turn_count": len(history) // 2,
        "meeting_runs": list(
            session.get(
                "meeting_runs",
                [],
            )
        ),
        "prep_text": prep_text,
        "conversation": history,
    }



def session_query_payload(
    session_name: str,
    user_prompt: str,
    query_mode: str = "normal",
) -> dict[str, Any]:
    import time

    from app_settings import load_app_settings
    from context_service import (
        build_saved_session_context,
    )
    from conversation_service import (
        append_query_exchange,
    )
    from execution_telemetry import (
        record_execution_telemetry,
    )
    from query.chat import run_query
    from query.changes import (
        run_changes_query,
    )
    from query_presentation import (
        format_query_finished_status,
    )

    prompt = user_prompt.strip()
    if not prompt:
        raise ValueError(
            "Enter a question for the session."
        )

    bundle = build_saved_session_context(
        session_name
    )

    session = bundle["session"]
    context = bundle["context"]
    meeting_dirs = list(
        bundle["meeting_dirs"]
    )

    settings = load_app_settings()
    execution_profile = (
        settings.get(
            "performance_profile",
            "Auto",
        )
        or "Auto"
    )

    started_at = time.perf_counter()

    if query_mode == "changes":
        (
            response,
            execution_metadata,
            _changes_comparison,
        ) = run_changes_query(
            prompt,
            context.get(
                "meeting_memories"
            )
            or [],
            context.get(
                "selected_meetings"
            )
            or [],
            execution_profile=
                execution_profile,
        )
    else:
        (
            response,
            execution_metadata,
        ) = run_query(
            prompt,
            context["merged_memory"],
            session.get(
                "conversation_history",
                [],
            ),
            include_grounded=True,
            print_output=False,
            meeting_memories=context.get(
                "meeting_memories"
            ),
            selected_meetings=context.get(
                "selected_meetings"
            ),
            topic_filter=context.get(
                "topic_filter"
            ),
            return_execution_metadata=True,
            execution_profile=execution_profile,
        )

    elapsed_seconds = (
        time.perf_counter()
        - started_at
    )

    record_execution_telemetry(
        execution_metadata,
        elapsed_seconds=elapsed_seconds,
    )

    history = append_query_exchange(
        session,
        meeting_dirs,
        user_prompt=prompt,
        assistant_response=response,
    )

    return {
        "schema_version": 11,
        "session_name": session_name,
        "assistant_response": response,
        "turn_count": len(history) // 2,
        "elapsed_seconds": round(
            elapsed_seconds,
            3,
        ),
        "status_text":
            format_query_finished_status(
                execution_metadata,
                execution_profile,
            ),
        "execution_mode":
            execution_metadata.get(
                "mode",
                "direct",
            ),
        "inference_calls": int(
            execution_metadata.get(
                "inference_calls",
                1,
            )
        ),
    }




def session_changes_payload(
    session_name: str,
    force: bool = False,
) -> dict[str, Any]:
    import time
    from datetime import datetime

    from app_settings import load_app_settings
    from context_service import (
        build_saved_session_context,
    )
    from query.changes import (
        NotEnoughMeetingsForChangesError,
        prepare_changes_comparison,
        run_changes_query,
    )
    from query.sessions import (
        load_chat_session,
        save_session_changes_cache,
    )

    bundle = build_saved_session_context(
        session_name
    )
    context = bundle["context"]
    meeting_memories = (
        context.get("meeting_memories") or []
    )
    selected_meetings = (
        context.get("selected_meetings") or []
    )

    try:
        current_comparison = prepare_changes_comparison(
            meeting_memories,
            selected_meetings,
        )
    except NotEnoughMeetingsForChangesError:
        current_comparison = None

    session = load_chat_session(session_name)
    cached = session.get("changes_cache")
    if not isinstance(cached, dict):
        cached = None

    if cached is not None and not force:
        current_previous_run = (
            current_comparison.get("previous_run")
            if current_comparison
            else None
        )
        current_latest_run = (
            current_comparison.get("latest_run")
            if current_comparison
            else None
        )
        is_stale = (
            cached.get("previous_run")
            != current_previous_run
            or cached.get("latest_run")
            != current_latest_run
        )

        return {
            "schema_version": 14,
            "session_name": session_name,
            "available": bool(cached.get("available", True)),
            "previous_run": cached.get("previous_run"),
            "previous_label": cached.get("previous_label"),
            "latest_run": cached.get("latest_run"),
            "latest_label": cached.get("latest_label"),
            "markdown": str(cached.get("markdown") or ""),
            "elapsed_seconds": float(
                cached.get("elapsed_seconds") or 0.0
            ),
            "generated_at": cached.get("generated_at"),
            "is_cached": True,
            "is_stale": is_stale,
            "current_previous_run": current_previous_run,
            "current_previous_label": (
                current_comparison.get("previous_label")
                if current_comparison
                else None
            ),
            "current_latest_run": current_latest_run,
            "current_latest_label": (
                current_comparison.get("latest_label")
                if current_comparison
                else None
            ),
        }

    if current_comparison is None:
        return {
            "schema_version": 14,
            "session_name": session_name,
            "available": False,
            "previous_run": None,
            "previous_label": None,
            "latest_run": None,
            "latest_label": None,
            "markdown": (
                "At least two meetings are required "
                "to compare what changed."
            ),
            "elapsed_seconds": 0.0,
            "generated_at": None,
            "is_cached": False,
            "is_stale": False,
            "current_previous_run": None,
            "current_previous_label": None,
            "current_latest_run": None,
            "current_latest_label": None,
        }

    settings = load_app_settings()
    execution_profile = str(
        settings.get(
            "performance_profile",
            "Auto",
        )
        or "Auto"
    )

    started_at = time.perf_counter()
    response, _execution_metadata, comparison = (
        run_changes_query(
            "",
            meeting_memories,
            selected_meetings,
            execution_profile=execution_profile,
        )
    )
    elapsed_seconds = time.perf_counter() - started_at
    generated_at = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    cache = {
        "available": True,
        "previous_run": comparison["previous_run"],
        "previous_label": comparison["previous_label"],
        "latest_run": comparison["latest_run"],
        "latest_label": comparison["latest_label"],
        "markdown": response,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "generated_at": generated_at,
    }
    save_session_changes_cache(session_name, cache)

    return {
        "schema_version": 14,
        "session_name": session_name,
        **cache,
        "is_cached": False,
        "is_stale": False,
        "current_previous_run": comparison["previous_run"],
        "current_previous_label": comparison["previous_label"],
        "current_latest_run": comparison["latest_run"],
        "current_latest_label": comparison["latest_label"],
    }



def global_search_payload(query: str) -> dict[str, Any]:
    from config import ARCHIVE_DIR
    from global_search import global_search

    results = global_search(
        query,
        load_meeting_catalog(),
        ARCHIVE_DIR / "query_sessions",
    )

    return {
        "schema_version": 17,
        "query": query.strip(),
        "meetings": results["meetings"],
        "sessions": results["sessions"],
    }


def favorite_prompts_payload() -> dict[str, Any]:
    from prompt_favorites import (
        load_prompt_favorites,
    )

    return {
        "schema_version": 16,
        "favorites": load_prompt_favorites(),
    }


def save_favorite_prompts_payload(
    favorites_json: str,
) -> dict[str, Any]:
    from prompt_favorites import (
        save_custom_prompt_favorites,
    )

    try:
        raw = json.loads(
            favorites_json
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Favorite prompts are not valid JSON."
        ) from exc

    if not isinstance(raw, list):
        raise ValueError(
            "Favorite prompts must be a list."
        )

    favorites = (
        save_custom_prompt_favorites(
            raw
        )
    )

    return {
        "schema_version": 16,
        "favorites": favorites,
    }


def preferences_payload() -> dict[str, Any]:
    from app_settings import load_app_settings
    from config import ARCHIVE_DIR, OUTPUT_DIR
    from hardware_profile import detect_hardware_profile
    from ollama_models import (
        discover_installed_ollama_models,
    )
    from performance_profile import (
        PERFORMANCE_PROFILE_NAMES,
        performance_profile_options,
        resolve_performance_profile,
    )
    from preferences_ui import (
        CONTEXT_SIZE_OPTIONS,
        archive_status_text,
        merge_model_choices,
        model_status_text,
    )

    settings = load_app_settings()

    configured_model = str(
        settings.get("llm_model")
        or ""
    ).strip()

    requested_profile = str(
        settings.get("performance_profile")
        or "Auto"
    ).strip()

    context_mode = str(
        settings.get("llm_context_mode")
        or "profile_default"
    ).strip()
    context_override = (
        int(settings.get("llm_context_size", 0) or 0)
        if context_mode == "override"
        else 0
    )

    hardware = detect_hardware_profile()
    resolved = resolve_performance_profile(
        requested_profile,
        context_size_override=context_override,
        hardware=hardware,
    )

    installed_models, discovery_error = (
        discover_installed_ollama_models()
    )

    model_choices = merge_model_choices(
        installed_models,
        configured_model,
    )

    return {
        "schema_version": 15,
        "settings": {
            "performance_profile": requested_profile,
            "output_dir": str(
                settings.get("output_dir")
                or OUTPUT_DIR
            ),
            "archive_dir": str(
                settings.get("archive_dir")
                or ARCHIVE_DIR
            ),
            "recordings_dir": str(
                settings.get("recordings_dir")
                or ""
            ),
            "llm_model": configured_model,
            "llm_context_size": context_override,
            "llm_context_mode": context_mode,
            "m4a_retention_days": int(
                settings.get(
                    "m4a_retention_days",
                    30,
                )
                or 30
            ),
            "archived_m4a_retention_days": int(
                settings.get(
                    "archived_m4a_retention_days",
                    365,
                )
                if settings.get(
                    "archived_m4a_retention_days"
                )
                is not None
                else 365
            ),
        },
        "performance_profiles": list(
            PERFORMANCE_PROFILE_NAMES
        ),
        "performance_profile_options": performance_profile_options(),
        "hardware_profile": {
            "display_label": hardware.display_label,
            "chip_name": str(getattr(hardware, "chip_name", "") or ""),
            "memory_gb": int(getattr(hardware, "memory_gb", 0) or 0),
            "performance_class": str(
                getattr(hardware, "performance_class", "") or ""
            ),
        },
        "resolved_performance_profile": {
            "requested_name": resolved.requested_name,
            "resolved_name": resolved.resolved_name,
            "context_size_tokens": resolved.context_size_tokens,
            "direct_token_budget": resolved.direct_token_budget,
            "chunk_source_token_budget": resolved.chunk_source_token_budget,
            "chunk_overlap_tokens": resolved.chunk_overlap_tokens,
            "hardware_label": resolved.hardware_label,
            "reason": resolved.reason,
            "context_mode": context_mode,
            "context_override_tokens": context_override,
        },
        "context_size_options": [
            {
                "label": label,
                "value": int(value),
            }
            for label, value
            in CONTEXT_SIZE_OPTIONS
        ],
        "installed_models": model_choices,
        "model_status": model_status_text(
            configured_model,
            installed_models,
            discovery_error,
        ),
        "archive_status": archive_status_text(
            str(
                settings.get("archive_dir")
                or ARCHIVE_DIR
            )
        ),
        "model_discovery_error":
            discovery_error,
    }


def performance_profile_preview_payload(
    performance_profile: str,
    llm_context_size: int,
) -> dict[str, Any]:
    from hardware_profile import detect_hardware_profile
    from performance_profile import (
        PERFORMANCE_PROFILE_NAMES,
        resolve_performance_profile,
    )

    if performance_profile not in PERFORMANCE_PROFILE_NAMES:
        raise ValueError(
            "Unknown performance profile: "
            f"{performance_profile}"
        )

    if llm_context_size < 0:
        raise ValueError(
            "Ollama context size must be zero or a positive integer."
        )

    resolved = resolve_performance_profile(
        performance_profile,
        context_size_override=int(llm_context_size),
        hardware=detect_hardware_profile(),
    )

    return {
        "requested_name": resolved.requested_name,
        "resolved_name": resolved.resolved_name,
        "context_size_tokens": resolved.context_size_tokens,
        "direct_token_budget": resolved.direct_token_budget,
        "chunk_source_token_budget": resolved.chunk_source_token_budget,
        "chunk_overlap_tokens": resolved.chunk_overlap_tokens,
        "hardware_label": resolved.hardware_label,
        "reason": resolved.reason,
        "context_mode": "override" if llm_context_size > 0 else "profile_default",
        "context_override_tokens": int(llm_context_size) if llm_context_size > 0 else 0,
    }


def save_preferences_payload(
    performance_profile: str,
    output_dir: str,
    archive_dir: str,
    recordings_dir: str,
    llm_model: str,
    llm_context_size: int,
    m4a_retention_days: int,
    archived_m4a_retention_days: int,
) -> dict[str, Any]:
    from pathlib import Path

    from app_settings import (
        load_app_settings,
        save_app_settings,
    )
    from preferences_ui import (
        validate_preferences,
    )
    from performance_profile import (
        PERFORMANCE_PROFILE_NAMES,
    )

    validation = validate_preferences(
        output_dir,
        archive_dir,
        llm_model,
    )

    if validation is not None:
        raise ValueError(
            f"{validation.title}: "
            f"{validation.message}"
        )

    if performance_profile not in PERFORMANCE_PROFILE_NAMES:
        raise ValueError(
            "Unknown performance profile: "
            f"{performance_profile}"
        )

    if llm_context_size < 0:
        raise ValueError(
            "Ollama context size must be "
            "zero or a positive integer."
        )

    if m4a_retention_days < 0:
        raise ValueError(
            "Local M4A retention cannot "
            "be negative."
        )

    if archived_m4a_retention_days < 0:
        raise ValueError(
            "Archived M4A retention cannot "
            "be negative."
        )

    settings = load_app_settings()

    settings.update(
        {
            "performance_profile":
                performance_profile,
            "output_dir":
                output_dir.strip(),
            "archive_dir":
                archive_dir.strip(),
            "recordings_dir":
                recordings_dir.strip(),
            "llm_model":
                llm_model.strip(),
            "llm_context_size":
                int(llm_context_size) if llm_context_size > 0 else 0,
            "llm_context_mode":
                "override" if llm_context_size > 0 else "profile_default",
            "m4a_retention_days":
                int(m4a_retention_days),
            "archived_m4a_retention_days":
                int(
                    archived_m4a_retention_days
                ),
        }
    )

    save_app_settings(settings)

    archive_path = Path(
        archive_dir
    ).expanduser()

    archive_message = (
        "Archive is currently available."
        if archive_path.exists()
        and archive_path.is_dir()
        else (
            "Archive is currently unavailable "
            "or not mounted. Publishing will "
            "require that location to be "
            "available."
        )
    )

    return {
        "schema_version": 12,
        "saved": True,
        "message": (
            "Preferences saved.\n\n"
            f"{archive_message}\n\n"
            "New settings will be used by "
            "subsequent Meeting Transcriber "
            "operations. Any operation already "
            "running will continue with the "
            "settings it started with."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Meeting Transcriber backend bridge"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "meetings",
        help="Return the unified meeting catalog as JSON",
    )

    detail_parser = subparsers.add_parser(
        "meeting-detail",
        help="Return rich detail for one meeting run",
    )
    detail_parser.add_argument("run")

    publish_parser = subparsers.add_parser(
        "publish-meeting",
        help="Publish and archive one unpublished meeting run",
    )
    publish_parser.add_argument("run")
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the publish request without changing files",
    )

    delete_plan_parser = subparsers.add_parser(
        "meeting-delete-plan",
        help="Return the files associated with one unpublished meeting",
    )
    delete_plan_parser.add_argument("run")

    finalize_delete_parser = subparsers.add_parser(
        "finalize-meeting-delete",
        help="Finalize bookkeeping after an unpublished meeting has been moved to Trash",
    )
    finalize_delete_parser.add_argument("run")

    unpublish_plan_parser = subparsers.add_parser(
        "meeting-unpublish-plan",
        help="Return the archive path and references for one published meeting",
    )
    unpublish_plan_parser.add_argument("run")

    finalize_unpublish_parser = subparsers.add_parser(
        "finalize-meeting-unpublish",
        help="Refresh archive indexes after a published meeting has been moved to Trash",
    )
    finalize_unpublish_parser.add_argument("run")

    subparsers.add_parser(
        "sessions",
        help="Return saved query sessions as JSON",
    )

    refresh_parser = subparsers.add_parser(
        "refresh-session",
        help="Refresh one saved dynamic session",
    )
    refresh_parser.add_argument("session_name")

    rename_parser = subparsers.add_parser(
        "rename-session",
        help="Rename one saved session",
    )
    rename_parser.add_argument("old_name")
    rename_parser.add_argument("new_name")

    delete_parser = subparsers.add_parser(
        "delete-session",
        help="Delete one saved session",
    )
    delete_parser.add_argument("session_name")

    editor_parser = subparsers.add_parser(
        "session-editor",
        help="Return create/edit metadata for a dynamic session",
    )
    editor_parser.add_argument(
        "session_name",
        nargs="?",
        default=None,
    )

    create_parser = subparsers.add_parser(
        "create-dynamic-session",
        help="Create a saved dynamic session",
    )
    create_parser.add_argument("session_name")
    create_parser.add_argument("person_text")
    create_parser.add_argument("title_text")
    create_parser.add_argument("topic_text")
    create_parser.add_argument("history_label")

    edit_parser = subparsers.add_parser(
        "edit-dynamic-session",
        help="Edit criteria for a saved dynamic session",
    )
    edit_parser.add_argument("session_name")
    edit_parser.add_argument("person_text")
    edit_parser.add_argument("title_text")
    edit_parser.add_argument("topic_text")
    edit_parser.add_argument("history_label")

    meeting_context_parser = subparsers.add_parser(
        "meeting-context",
        help="Build ad-hoc context for selected meetings",
    )
    meeting_context_parser.add_argument(
        "meeting_runs_json"
    )

    save_meeting_context_session_parser = subparsers.add_parser(
        "save-meeting-context-session",
        help="Save the current ad-hoc meeting context as a fixed session",
    )
    save_meeting_context_session_parser.add_argument(
        "session_name"
    )
    save_meeting_context_session_parser.add_argument(
        "meeting_runs_json"
    )
    save_meeting_context_session_parser.add_argument(
        "conversation_json"
    )

    meeting_context_query_plan_parser = subparsers.add_parser(
        "meeting-context-query-plan",
        help="Plan an ad-hoc meeting context query without running the model",
    )
    meeting_context_query_plan_parser.add_argument(
        "meeting_runs_json"
    )
    meeting_context_query_plan_parser.add_argument(
        "user_prompt"
    )
    meeting_context_query_plan_parser.add_argument(
        "conversation_json"
    )
    meeting_context_query_plan_parser.add_argument(
        "query_mode",
        nargs="?",
        default="normal",
    )

    meeting_context_query_parser = subparsers.add_parser(
        "meeting-context-query",
        help="Query an ad-hoc selected meeting context",
    )
    meeting_context_query_parser.add_argument(
        "meeting_runs_json"
    )
    meeting_context_query_parser.add_argument(
        "user_prompt"
    )
    meeting_context_query_parser.add_argument(
        "conversation_json"
    )
    meeting_context_query_parser.add_argument(
        "query_mode",
        nargs="?",
        default="normal",
    )

    session_detail_parser = subparsers.add_parser(
        "session-detail",
        help="Return resumed context and conversation for one saved session",
    )
    session_detail_parser.add_argument(
        "session_name"
    )

    session_query_parser = subparsers.add_parser(
        "session-query",
        help="Run and persist one query against a saved session",
    )
    session_query_parser.add_argument(
        "session_name"
    )
    session_query_parser.add_argument(
        "user_prompt"
    )
    session_query_parser.add_argument(
        "query_mode",
        nargs="?",
        default="normal",
    )



    session_changes_parser = subparsers.add_parser(
        "session-changes",
        help=(
            "Compare the two most recent meetings "
            "in a saved session"
        ),
    )
    session_changes_parser.add_argument(
        "session_name"
    )
    session_changes_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate Changes instead of returning the saved comparison",
    )


    global_search_parser = subparsers.add_parser(
        "global-search",
        help="Search Meetings and Sessions without invoking the LLM",
    )
    global_search_parser.add_argument("query")

    audio_contract_parser = subparsers.add_parser(
        "audio-contract",
        help="Inspect a recording against the existing c0/c4 transcription channel contract",
    )
    audio_contract_parser.add_argument("path")

    finalize_audio_parser = subparsers.add_parser(
        "finalize-audio-recording",
        help="Finalize a captured 5-channel PCM recording into a compatible M4A",
    )
    finalize_audio_parser.add_argument("source_path")
    finalize_audio_parser.add_argument("output_path")
    finalize_audio_parser.add_argument("sample_rate", type=int)
    finalize_audio_parser.add_argument("channels", type=int)


    subparsers.add_parser(
        "favorite-prompts",
        help="Return built-in and custom prompt favorites",
    )

    save_favorites_parser = subparsers.add_parser(
        "save-favorite-prompts",
        help="Save the custom prompt favorites",
    )
    save_favorites_parser.add_argument(
        "favorites_json"
    )

    subparsers.add_parser(
        "preferences",
        help="Return current app preferences and model status",
    )

    preview_performance_parser = subparsers.add_parser(
        "preview-performance-profile",
        help="Resolve a performance profile without saving preferences",
    )
    preview_performance_parser.add_argument(
        "performance_profile"
    )
    preview_performance_parser.add_argument(
        "llm_context_size",
        type=int,
    )

    save_preferences_parser = subparsers.add_parser(
        "save-preferences",
        help="Validate and save app preferences",
    )
    save_preferences_parser.add_argument(
        "performance_profile"
    )
    save_preferences_parser.add_argument(
        "output_dir"
    )
    save_preferences_parser.add_argument(
        "archive_dir"
    )
    save_preferences_parser.add_argument(
        "recordings_dir"
    )
    save_preferences_parser.add_argument(
        "llm_model"
    )
    save_preferences_parser.add_argument(
        "llm_context_size",
        type=int,
    )
    save_preferences_parser.add_argument(
        "m4a_retention_days",
        type=int,
    )
    save_preferences_parser.add_argument(
        "archived_m4a_retention_days",
        type=int,
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "meetings":
            payload = meetings_payload()

        elif args.command == "meeting-detail":
            payload = meeting_detail_payload(
                args.run
            )

        elif args.command == "publish-meeting":
            payload = publish_meeting_payload(
                args.run,
                dry_run=args.dry_run,
            )


        elif args.command == "meeting-delete-plan":
            payload = meeting_delete_plan_payload(
                args.run
            )

        elif args.command == "finalize-meeting-delete":
            payload = finalize_meeting_delete_payload(
                args.run
            )

        elif args.command == "meeting-unpublish-plan":
            payload = meeting_unpublish_plan_payload(
                args.run
            )

        elif args.command == "finalize-meeting-unpublish":
            payload = finalize_meeting_unpublish_payload(
                args.run
            )

        elif args.command == "sessions":
            payload = sessions_payload()

        elif args.command == "refresh-session":
            payload = refresh_session_payload(
                args.session_name
            )

        elif args.command == "rename-session":
            payload = rename_session_payload(
                args.old_name,
                args.new_name,
            )

        elif args.command == "delete-session":
            payload = delete_session_payload(
                args.session_name
            )

        elif args.command == "session-editor":
            payload = session_editor_payload(
                args.session_name
            )

        elif args.command == "create-dynamic-session":
            payload = create_dynamic_session_payload(
                args.session_name,
                args.person_text,
                args.title_text,
                args.topic_text,
                args.history_label,
            )

        elif args.command == "edit-dynamic-session":
            payload = edit_dynamic_session_payload(
                args.session_name,
                args.person_text,
                args.title_text,
                args.topic_text,
                args.history_label,
            )

        elif args.command == "meeting-context":
            payload = meeting_context_payload(
                args.meeting_runs_json
            )

        elif args.command == "save-meeting-context-session":
            payload = save_meeting_context_session_payload(
                args.session_name,
                args.meeting_runs_json,
                args.conversation_json,
            )

        elif args.command == "meeting-context-query-plan":
            payload = meeting_context_query_plan_payload(
                args.meeting_runs_json,
                args.user_prompt,
                args.conversation_json,
                args.query_mode,
            )

        elif args.command == "meeting-context-query":
            payload = meeting_context_query_payload(
                args.meeting_runs_json,
                args.user_prompt,
                args.conversation_json,
                args.query_mode,
            )

        elif args.command == "session-detail":
            payload = session_detail_payload(
                args.session_name
            )

        elif args.command == "session-query":
            payload = session_query_payload(
                args.session_name,
                args.user_prompt,
                args.query_mode,
            )

        elif args.command == "session-changes":
            payload = session_changes_payload(
                args.session_name,
                force=args.force,
            )


        elif args.command == "global-search":
            payload = global_search_payload(
                args.query
            )

        elif args.command == "audio-contract":
            payload = audio_contract_payload(
                args.path
            )

        elif args.command == "finalize-audio-recording":
            payload = finalize_audio_recording_payload(
                args.source_path,
                args.output_path,
                args.sample_rate,
                args.channels,
            )

        elif args.command == "favorite-prompts":
            payload = favorite_prompts_payload()

        elif args.command == "save-favorite-prompts":
            payload = save_favorite_prompts_payload(
                args.favorites_json
            )

        elif args.command == "preferences":
            payload = preferences_payload()

        elif args.command == "preview-performance-profile":
            payload = performance_profile_preview_payload(
                args.performance_profile,
                args.llm_context_size,
            )

        elif args.command == "save-preferences":
            payload = save_preferences_payload(
                args.performance_profile,
                args.output_dir,
                args.archive_dir,
                args.recordings_dir,
                args.llm_model,
                args.llm_context_size,
                args.m4a_retention_days,
                args.archived_m4a_retention_days,
            )

        else:  # pragma: no cover
            raise ValueError(
                f"Unsupported command: {args.command}"
            )

        json.dump(
            payload,
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0

    except Exception as exc:
        json.dump(
            {
                "schema_version": 12,
                "error": type(exc).__name__,
                "message": str(exc),
            },
            sys.stderr,
            ensure_ascii=False,
        )
        sys.stderr.write("\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
