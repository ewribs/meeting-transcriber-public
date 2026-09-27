import json

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class MeetingBrowserEntry:
    meeting_run: str
    meeting_date: str
    title: str
    publish_status: str
    participants: tuple[str, ...]
    search_text: str
    preview_markdown: str

    @property
    def label(self) -> str:
        status_suffix = (
            " · Unpublished"
            if self.publish_status == "Unpublished"
            else ""
        )
        return (
            f"{self.meeting_date}{status_suffix}\n"
            f"{self.title}"
        )


def _load_meeting_memory(meeting: dict) -> dict:
    location = meeting.get("location")
    if not location:
        return {}

    memory_path = Path(location) / "meeting_memory.json"
    if not memory_path.exists():
        return {}

    try:
        payload = json.loads(
            memory_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _topic_search_text(memory: dict) -> str:
    parts = []
    for topic in memory.get("topics", []):
        if not isinstance(topic, dict):
            continue
        parts.extend(
            [
                str(topic.get("topic_key", "")),
                str(topic.get("topic", "")),
                str(topic.get("summary", "")),
            ]
        )
    return " ".join(parts)


def _preview_topics(memory: dict) -> list[str]:
    topics = []
    for topic in memory.get("topics", [])[:5]:
        if not isinstance(topic, dict):
            continue
        value = topic.get(
            "topic",
            topic.get("topic_key", ""),
        )
        value = str(value).strip()
        if value:
            topics.append(value)
    return topics


def build_meeting_browser_entry(
    meeting: dict,
) -> MeetingBrowserEntry | None:
    meeting_run = str(
        meeting.get("meeting_run", "")
    ).strip()
    if not meeting_run:
        return None

    meeting_date = meeting_run[:10]
    title = str(
        meeting.get("display_title", meeting_run)
    )
    publish_status = str(
        meeting.get("publish_status", "Published")
    )
    participants = tuple(
        str(value).strip()
        for value in meeting.get("participants", [])
        if str(value).strip()
    )

    memory = _load_meeting_memory(meeting)
    topic_search_text = _topic_search_text(memory)

    search_text = " ".join(
        [
            meeting_run,
            meeting_date,
            title,
            publish_status,
            " ".join(participants),
            topic_search_text,
        ]
    ).lower()

    participant_text = (
        ", ".join(participants)
        if participants
        else "None identified"
    )

    lines = [
        f"### {title}",
        "",
        f"**Date:** {meeting_date}",
        "",
        f"**Status:** {publish_status}",
        "",
        f"**Participants:** {participant_text}",
    ]

    topics = _preview_topics(memory)
    if topics:
        lines.extend(
            [
                "",
                "**Top Topics**",
                "",
            ]
        )
        lines.extend(f"- {topic}" for topic in topics)

    return MeetingBrowserEntry(
        meeting_run=meeting_run,
        meeting_date=meeting_date,
        title=title,
        publish_status=publish_status,
        participants=participants,
        search_text=search_text,
        preview_markdown="\n".join(lines),
    )


def build_meeting_browser_entries(
    meetings: list[dict],
) -> list[MeetingBrowserEntry]:
    entries = []
    for meeting in meetings:
        entry = build_meeting_browser_entry(meeting)
        if entry is not None:
            entries.append(entry)
    return entries


def count_unpublished(
    entries: list[MeetingBrowserEntry],
) -> int:
    return sum(
        1
        for entry in entries
        if entry.publish_status == "Unpublished"
    )


def meeting_fields_match_filters(
    *,
    meeting_search_text: str,
    meeting_date_text: str,
    publish_status: str,
    search_text: str = "",
    date_filter: str = "All dates",
    status_filter: str = "All statuses",
    today: date | None = None,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> bool:
    normalized_search = search_text.strip().lower()
    if (
        normalized_search
        and normalized_search not in meeting_search_text
    ):
        return False

    if (
        status_filter != "All statuses"
        and publish_status != status_filter
    ):
        return False

    if date_filter == "All dates":
        return True

    try:
        meeting_date = datetime.strptime(
            meeting_date_text,
            "%Y-%m-%d",
        ).date()
    except ValueError:
        return False

    today = today or datetime.now().date()

    if date_filter == "Last 7 days":
        cutoff = today - timedelta(days=6)
        return cutoff <= meeting_date <= today

    if date_filter == "Last 30 days":
        cutoff = today - timedelta(days=29)
        return cutoff <= meeting_date <= today

    if date_filter == "This month":
        return (
            meeting_date.year == today.year
            and meeting_date.month == today.month
        )

    if date_filter == "Custom range":
        if custom_from is None or custom_to is None:
            return False
        return custom_from <= meeting_date <= custom_to

    return True


def meeting_matches_filters(
    entry: MeetingBrowserEntry,
    *,
    search_text: str = "",
    date_filter: str = "All dates",
    status_filter: str = "All statuses",
    today: date | None = None,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> bool:
    return meeting_fields_match_filters(
        meeting_search_text=entry.search_text,
        meeting_date_text=entry.meeting_date,
        publish_status=entry.publish_status,
        search_text=search_text,
        date_filter=date_filter,
        status_filter=status_filter,
        today=today,
        custom_from=custom_from,
        custom_to=custom_to,
    )


def sort_meeting_entries(
    entries: list[MeetingBrowserEntry],
    sort_mode: str,
) -> list[MeetingBrowserEntry]:
    if sort_mode == "Oldest first":
        return sorted(
            entries,
            key=lambda entry: entry.meeting_run,
        )

    if sort_mode == "Title A-Z":
        return sorted(
            entries,
            key=lambda entry: entry.title.lower(),
        )

    return sorted(
        entries,
        key=lambda entry: entry.meeting_run,
        reverse=True,
    )
