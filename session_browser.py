import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class SessionBrowserEntry:
    name: str
    label: str
    tooltip: str
    path: Path
    session_type: str
    meeting_count: int
    turn_count: int


def load_session_browser_entries(
    sessions_dir: Path,
) -> list[SessionBrowserEntry]:
    """Load saved-session metadata for display in the Sessions browser."""
    sessions_dir = Path(sessions_dir)

    if not sessions_dir.exists():
        return []

    session_paths = sorted(
        sessions_dir.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    entries: list[SessionBrowserEntry] = []

    for session_path in session_paths:
        try:
            session = json.loads(
                session_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            continue

        meeting_count = len(
            session.get("meeting_runs", [])
        )
        turn_count = len(
            session.get("conversation_history", [])
        ) // 2

        session_type = (
            "Dynamic"
            if session.get("selection_criteria")
            else "Fixed"
        )

        meeting_word = (
            "meeting" if meeting_count == 1 else "meetings"
        )
        turn_word = (
            "turn" if turn_count == 1 else "turns"
        )

        label = (
            f"{session_path.stem}\n"
            f"{session_type} · "
            f"{meeting_count} {meeting_word} · "
            f"{turn_count} {turn_word}"
        )

        updated = datetime.fromtimestamp(
            session_path.stat().st_mtime
        ).strftime("%m/%d %H:%M")

        entries.append(
            SessionBrowserEntry(
                name=session_path.stem,
                label=label,
                tooltip=f"Updated {updated}",
                path=session_path,
                session_type=session_type,
                meeting_count=meeting_count,
                turn_count=turn_count,
            )
        )

    return entries


def format_session_criteria(
    selection_criteria: dict | None,
) -> list[str]:
    """Render saved dynamic-session criteria for the context preview."""
    if not selection_criteria:
        return []

    lines = [
        "CRITERIA",
        "--------",
    ]

    person = selection_criteria.get("person")
    if person:
        lines.append(f"Person: {person}")

    title = selection_criteria.get("title")
    if title:
        lines.append(f"Title contains: {title}")

    topic = selection_criteria.get("topic")
    if topic:
        lines.append(f"Topic contains: {topic}")

    history_days = selection_criteria.get("history_days")
    if history_days:
        lines.append(f"Window: Last {history_days} days")
    else:
        start_date = selection_criteria.get("start_date")
        end_date = selection_criteria.get("end_date")

        if start_date or end_date:
            lines.append(
                "Window: "
                f"{start_date or 'Any'} to "
                f"{end_date or 'Present'}"
            )
        else:
            lines.append("Window: All history")

    return lines
