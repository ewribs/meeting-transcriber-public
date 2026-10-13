import json

from datetime import datetime
from pathlib import Path

from config import ARCHIVE_DIR
from meeting_selector import (
    load_meeting_index,
)


def save_chat_session(
    session_name: str,
    meeting_dirs: list[Path],
    conversation_history: list[dict],
    selection_criteria: dict | None = None,
) -> Path:
    sessions_dir = (
        ARCHIVE_DIR / "query_sessions"
    )

    sessions_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    session_path = (
        sessions_dir
        / f"{session_name}.json"
    )

    session_data = {
        "session_name": session_name,
        "meeting_runs": [
            meeting_dir.name
            for meeting_dir in meeting_dirs
        ],
        "conversation_history": (
            conversation_history
        ),
    }

    # Changes comparisons are intentionally durable per session. Preserve the
    # last generated comparison whenever other session state (conversation,
    # criteria, dynamic membership) is saved; freshness is determined later
    # from the cached meeting pair rather than by discarding the result.
    if session_path.exists():
        try:
            existing = json.loads(
                session_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            existing = {}

        changes_cache = existing.get("changes_cache")
        if isinstance(changes_cache, dict):
            session_data["changes_cache"] = changes_cache

    if selection_criteria:
        session_data[
            "selection_criteria"
        ] = selection_criteria

    session_path.write_text(
        json.dumps(
            session_data,
            indent=2,
        ),
        encoding="utf-8",
    )

    return session_path


def load_chat_session(
    session_name: str,
) -> dict:
    session_path = (
        ARCHIVE_DIR
        / "query_sessions"
        / f"{session_name}.json"
    )

    if not session_path.exists():
        raise FileNotFoundError(
            f"Chat session not found: "
            f"{session_path}"
        )

    return json.loads(
        session_path.read_text(
            encoding="utf-8"
        )
    )


def list_chat_sessions() -> None:
    sessions_dir = (
        ARCHIVE_DIR / "query_sessions"
    )

    if not sessions_dir.exists():
        print("No saved sessions.")
        return

    session_paths = sorted(
        sessions_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not session_paths:
        print("No saved sessions.")
        return

    for session_path in session_paths:
        session = json.loads(
            session_path.read_text(
                encoding="utf-8"
            )
        )

        meeting_count = len(
            session.get(
                "meeting_runs",
                [],
            )
        )

        turn_count = len(
            session.get(
                "conversation_history",
                [],
            )
        ) // 2

        updated = datetime.fromtimestamp(
            session_path.stat().st_mtime
        ).strftime(
            "%Y-%m-%d %H:%M"
        )

        print(
            f"{session_path.stem} | "
            f"meetings: {meeting_count} | "
            f"turns: {turn_count} | "
            f"updated: {updated}"
        )


def delete_chat_session(
    session_name: str,
) -> None:
    session_path = (
        ARCHIVE_DIR
        / "query_sessions"
        / f"{session_name}.json"
    )

    if not session_path.exists():
        raise FileNotFoundError(
            f"Session not found: {session_name}"
        )

    session_path.unlink()


def show_chat_session(
    session_name: str,
) -> None:
    session_path = (
        ARCHIVE_DIR
        / "query_sessions"
        / f"{session_name}.json"
    )

    if not session_path.exists():
        print(
            f"Session not found: "
            f"{session_name}"
        )
        return

    session = json.loads(
        session_path.read_text(
            encoding="utf-8"
        )
    )

    meeting_runs = session.get(
        "meeting_runs",
        [],
    )

    conversation_history = session.get(
        "conversation_history",
        [],
    )

    selection_criteria = session.get(
        "selection_criteria"
    )

    updated = datetime.fromtimestamp(
        session_path.stat().st_mtime
    ).strftime(
        "%Y-%m-%d %H:%M"
    )

    print(
        f"Session: {session_name}"
    )
    print(
        f"Meetings: {len(meeting_runs)}"
    )
    print(
        f"Turns: "
        f"{len(conversation_history) // 2}"
    )
    print(
        f"Updated: {updated}"
    )

    if selection_criteria:
        print("Selection Criteria:")

        print(
            f"- Person: "
            f"{selection_criteria.get('person') or 'Any'}"
        )
        print(
            f"- Start date: "
            f"{selection_criteria.get('start_date') or 'Any'}"
        )
        print(
            f"- End date: "
            f"{selection_criteria.get('end_date') or 'Any'}"
        )
        print(
            f"- Topic: "
            f"{selection_criteria.get('topic') or 'Any'}"
        )

    print()

    index_by_run = {
        meeting.get("meeting_run"): meeting
        for meeting in load_meeting_index()
    }

    print("Meetings:")

    for meeting_run in meeting_runs:
        meeting = index_by_run.get(
            meeting_run
        )

        if meeting:
            meeting_date = (
                meeting_run[:10]
            )

            print(
                f"- {meeting_date} | "
                f"{meeting.get('display_title', meeting_run)}"
            )
        else:
            print(
                f"- {meeting_run}"
            )

def rename_chat_session(
    old_name: str,
    new_name: str,
) -> None:
    sessions_dir = (
        ARCHIVE_DIR / "query_sessions"
    )

    old_path = (
        sessions_dir / f"{old_name}.json"
    )

    new_path = (
        sessions_dir / f"{new_name}.json"
    )

    if not old_path.exists():
        raise FileNotFoundError(
            f"Session not found: {old_name}"
        )

    case_only_rename = (
        old_name.casefold()
        == new_name.casefold()
        and old_name != new_name
    )

    if (
        new_path.exists()
        and not case_only_rename
    ):
        raise FileExistsError(
            f"Session already exists: {new_name}"
        )

    session = json.loads(
        old_path.read_text(
            encoding="utf-8"
        )
    )

    session["session_name"] = new_name

    if case_only_rename:
        temp_path = (
            sessions_dir
            / f".{old_name}.rename_tmp.json"
        )

        temp_path.write_text(
            json.dumps(
                session,
                indent=2,
            ),
            encoding="utf-8",
        )

        old_path.unlink()

        temp_path.rename(
            new_path
        )

    else:
        new_path.write_text(
            json.dumps(
                session,
                indent=2,
            ),
            encoding="utf-8",
        )

        old_path.unlink()

def save_session_changes_cache(
    session_name: str,
    changes_cache: dict,
) -> Path:
    """Persist the last generated Changes comparison inside a saved session."""
    session_path = (
        ARCHIVE_DIR
        / "query_sessions"
        / f"{session_name}.json"
    )

    if not session_path.exists():
        raise FileNotFoundError(
            f"Chat session not found: {session_path}"
        )

    session_data = json.loads(
        session_path.read_text(encoding="utf-8")
    )
    session_data["changes_cache"] = dict(changes_cache)
    session_path.write_text(
        json.dumps(session_data, indent=2),
        encoding="utf-8",
    )
    return session_path

