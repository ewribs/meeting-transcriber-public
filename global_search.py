from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meeting_detail_service import load_meeting_detail
from session_browser import format_session_criteria, load_session_browser_entries


@dataclass(frozen=True)
class GlobalSearchResult:
    id: str
    kind: str
    title: str
    subtitle: str
    date: str
    snippet: str
    score: int
    meeting_run: str = ""
    session_name: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "date": self.date,
            "snippet": self.snippet,
            "score": self.score,
            "meeting_run": self.meeting_run,
            "session_name": self.session_name,
        }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", _clean(value)).casefold()


def _terms(query: str) -> list[str]:
    return [
        term
        for term in re.findall(r"[\w$%+.-]+", query.casefold())
        if term
    ]


def _matches_all(text: str, terms: list[str]) -> bool:
    normalized = _normalize(text)
    return bool(terms) and all(term in normalized for term in terms)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"^\s*[-*•]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _summary_snippet(summary: str, terms: list[str]) -> str:
    for raw in re.split(r"\n\s*\n|\n", summary):
        candidate = _strip_markdown(raw)
        if candidate and _matches_all(candidate, terms):
            return candidate[:320]

    normalized = _strip_markdown(summary)
    return normalized[:320]


def _meeting_result(
    meeting: dict[str, Any],
    query: str,
    terms: list[str],
    *,
    detail_cache: dict[str, dict[str, Any]] | None = None,
) -> GlobalSearchResult | None:
    run = _clean(meeting.get("meeting_run") or meeting.get("run"))
    if not run:
        return None

    title = _clean(
        meeting.get("display_title")
        or meeting.get("title")
        or run
    )
    date = _clean(
        meeting.get("meeting_datetime")
        or meeting.get("date")
        or run[:10]
    )[:10]
    participants = [
        _clean(item)
        for item in meeting.get("participants", [])
        if _clean(item)
    ]
    if detail_cache is not None and run in detail_cache:
        detail = detail_cache[run]
    else:
        detail = load_meeting_detail(meeting)
        if detail_cache is not None:
            detail_cache[run] = detail

    fields: list[tuple[int, str, str]] = [
        (120, "Title", title),
        (80, "Participants", ", ".join(participants)),
    ]

    for topic in detail.get("topics", []):
        if not isinstance(topic, dict):
            continue
        topic_text = " — ".join(
            value for value in [
                _clean(topic.get("name")),
                _clean(topic.get("status")),
                _clean(topic.get("summary")),
            ] if value
        )
        fields.append((70, "Topic", topic_text))

    for decision in detail.get("decisions", []):
        fields.append((65, "Decision", _clean(decision)))

    for commitment in detail.get("commitments", []):
        if not isinstance(commitment, dict):
            continue
        text = ": ".join(
            value for value in [
                _clean(commitment.get("owner")),
                _clean(commitment.get("action")),
            ] if value
        )
        fields.append((55, "Commitment", text))

    for question in detail.get("open_questions", []):
        fields.append((60, "Open Question", _clean(question)))

    for follow_up in detail.get("follow_ups", []):
        fields.append((50, "Follow-up", _clean(follow_up)))

    summary = _clean(detail.get("summary"))
    if summary:
        fields.append((30, "Summary", summary))

    matched = [
        (weight, label, text)
        for weight, label, text in fields
        if text and _matches_all(text, terms)
    ]

    # Also support multi-term matches spread across fields.
    combined = " ".join(text for _, _, text in fields)
    if not matched and not _matches_all(combined, terms):
        return None

    phrase = _normalize(query)
    phrase_bonus = 0
    for _, _, text in fields:
        if phrase and phrase in _normalize(text):
            phrase_bonus = 40
            break

    if matched:
        best_weight, best_label, best_text = max(
            matched,
            key=lambda item: item[0],
        )
        snippet_text = (
            _summary_snippet(best_text, terms)
            if best_label == "Summary"
            else _strip_markdown(best_text)[:320]
        )
        snippet = f"{best_label}: {snippet_text}"
        score = best_weight + phrase_bonus + len(matched) * 3
    else:
        snippet = f"Summary: {_summary_snippet(summary, terms)}"
        score = 20 + phrase_bonus

    subtitle_parts = [date]
    if participants:
        subtitle_parts.append(", ".join(participants))

    return GlobalSearchResult(
        id=f"meeting:{run}",
        kind="meeting",
        title=title,
        subtitle=" · ".join(part for part in subtitle_parts if part),
        date=date,
        snippet=snippet,
        score=score,
        meeting_run=run,
    )


def _session_result(
    entry,
    query: str,
    terms: list[str],
    *,
    meetings_by_run: dict[str, dict[str, Any]],
    detail_cache: dict[str, dict[str, Any]],
) -> GlobalSearchResult | None:
    try:
        import json

        payload = json.loads(entry.path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}

    criteria_lines = [
        line
        for line in format_session_criteria(payload.get("selection_criteria"))
        if line.strip()
        and line.strip().casefold() != "criteria"
        and set(line.strip()) != {"-"}
    ]
    criteria = " · ".join(criteria_lines)

    # Sessions are first-class search results. Search not only their saved
    # name/criteria, but also their persisted conversation and the meetings
    # that make up the session. This is especially important for fixed
    # sessions, whose names/criteria may not describe the supplier/project
    # content they contain.
    fields: list[tuple[int, str, str]] = [
        (130, "Session name", entry.name),
        (85, "Criteria", criteria),
    ]

    for item in payload.get("conversation_history", []):
        if not isinstance(item, dict):
            continue
        content = _clean(item.get("content"))
        if content:
            fields.append((65, "Session conversation", content))

    for run in payload.get("meeting_runs", []):
        run_id = _clean(run)
        meeting = meetings_by_run.get(run_id)
        if not meeting:
            continue

        title = _clean(
            meeting.get("display_title")
            or meeting.get("title")
            or run_id
        )
        participants = ", ".join(
            _clean(item)
            for item in meeting.get("participants", [])
            if _clean(item)
        )
        if title:
            fields.append((75, "Included meeting", title))
        if participants:
            fields.append((45, "Included people", participants))

        if run_id in detail_cache:
            detail = detail_cache[run_id]
        else:
            detail = load_meeting_detail(meeting)
            detail_cache[run_id] = detail

        for topic in detail.get("topics", []):
            if not isinstance(topic, dict):
                continue
            topic_text = " — ".join(
                value for value in [
                    _clean(topic.get("name")),
                    _clean(topic.get("status")),
                    _clean(topic.get("summary")),
                ] if value
            )
            if topic_text:
                fields.append((60, "Included topic", topic_text))

        for decision in detail.get("decisions", []):
            text = _clean(decision)
            if text:
                fields.append((55, "Included decision", text))

        for commitment in detail.get("commitments", []):
            if not isinstance(commitment, dict):
                continue
            text = ": ".join(
                value for value in [
                    _clean(commitment.get("owner")),
                    _clean(commitment.get("action")),
                ] if value
            )
            if text:
                fields.append((45, "Included commitment", text))

        for question in detail.get("open_questions", []):
            text = _clean(question)
            if text:
                fields.append((50, "Included open question", text))

        for follow_up in detail.get("follow_ups", []):
            text = _clean(follow_up)
            if text:
                fields.append((45, "Included follow-up", text))

        summary = _clean(detail.get("summary"))
        if summary:
            fields.append((35, "Included summary", summary))

    matched = [
        (weight, label, text)
        for weight, label, text in fields
        if text and _matches_all(text, terms)
    ]

    combined = " ".join(text for _, _, text in fields if text)
    if not matched and not _matches_all(combined, terms):
        return None

    phrase = _normalize(query)
    phrase_bonus = 0
    for _, _, text in fields:
        if phrase and phrase in _normalize(text):
            phrase_bonus = 40
            break

    if matched:
        best_weight, best_label, best_text = max(
            matched,
            key=lambda item: item[0],
        )
        snippet_text = (
            _summary_snippet(best_text, terms)
            if "summary" in best_label.casefold()
            or "conversation" in best_label.casefold()
            else _strip_markdown(best_text)[:320]
        )
        snippet = f"{best_label}: {snippet_text}"
        score = best_weight + phrase_bonus + len(matched) * 3
    else:
        snippet = (
            f"Session contains matching content across {entry.meeting_count} meetings"
        )
        score = 30 + phrase_bonus

    return GlobalSearchResult(
        id=f"session:{entry.name}",
        kind="session",
        title=entry.name,
        subtitle=f"{entry.session_type} · {entry.meeting_count} meetings · {entry.turn_count} turns",
        date="",
        snippet=snippet[:320],
        score=score,
        session_name=entry.name,
    )

def global_search(
    query: str,
    meetings: list[dict[str, Any]],
    sessions_dir: Path,
    *,
    limit_per_kind: int = 40,
) -> dict[str, list[dict[str, Any]]]:
    cleaned_query = _clean(query)
    terms = _terms(cleaned_query)
    if not terms:
        return {"meetings": [], "sessions": []}

    detail_cache: dict[str, dict[str, Any]] = {}
    meetings_by_run = {
        _clean(meeting.get("meeting_run") or meeting.get("run")): meeting
        for meeting in meetings
        if _clean(meeting.get("meeting_run") or meeting.get("run"))
    }

    meeting_results = [
        result
        for meeting in meetings
        if (
            result := _meeting_result(
                meeting,
                cleaned_query,
                terms,
                detail_cache=detail_cache,
            )
        ) is not None
    ]
    meeting_results.sort(
        key=lambda item: (item.score, item.date, item.title.casefold()),
        reverse=True,
    )

    session_results = [
        result
        for entry in load_session_browser_entries(sessions_dir)
        if (
            result := _session_result(
                entry,
                cleaned_query,
                terms,
                meetings_by_run=meetings_by_run,
                detail_cache=detail_cache,
            )
        ) is not None
    ]
    session_results.sort(
        key=lambda item: (item.score, item.title.casefold()),
        reverse=True,
    )

    return {
        "meetings": [item.as_dict() for item in meeting_results[:limit_per_kind]],
        "sessions": [item.as_dict() for item in session_results[:limit_per_kind]],
    }
