from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any

from ai import ask_llm
from config import (
    LLM_CONTEXT_SIZE,
    LLM_MODEL,
)
from execution_calibration import (
    get_execution_calibration,
)
from hardware_profile import (
    detect_hardware_profile,
)
from query.execution import (
    build_execution_metadata,
    choose_execution_plan,
    get_execution_profile,
)
from query.sanitizers import (
    clean_markdown_artifacts,
)
from query.synthesis import (
    _compact_memory,
)




CHANGE_SECTION_TITLES = [
    "Executive Delta",
    "New Since Last Time",
    "Changed / Progressed",
    "New Decisions",
    "Resolved / Closed",
    "Still Open / Carried Forward",
    "New Risks / Blockers",
    "Commitments & Follow-ups",
]

_TOPIC_GENERIC_WORDS = {
    "contract",
    "deal",
    "discussion",
    "discussions",
    "initiative",
    "issue",
    "issues",
    "meeting",
    "negotiation",
    "negotiations",
    "process",
    "project",
    "renewal",
    "status",
    "topic",
    "update",
    "work",
}

_CLOSED_STATUS_WORDS = {
    "closed",
    "complete",
    "completed",
    "done",
    "resolved",
    "superseded",
    "cancelled",
    "canceled",
}

_ACTIVE_STATUS_WORDS = {
    "active",
    "blocked",
    "in progress",
    "ongoing",
    "open",
    "pending",
}

_RESOLUTION_RE = re.compile(
    r"\b(?:closed|completed?|resolved?|done|superseded|cancelled|canceled)\b",
    re.IGNORECASE,
)

_RISK_RE = re.compile(
    r"\b(?:risk|blocker|blocked|delay|delayed|problem|issue|challenge|dependency|escalat\w*|deadline|hurdle|error|lack(?:ing)?|concern)\b",
    re.IGNORECASE,
)

_DECISION_RE = re.compile(
    r"\b(?:decision|decided|agreed|approved|confirmed|selected|chose|chosen|proceed(?:ed)? with|held flat|hold\w* flat)\b",
    re.IGNORECASE,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class NotEnoughMeetingsForChangesError(ValueError):
    pass


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: Any) -> list[str]:
    return _TOKEN_RE.findall(_clean_text(value).casefold())


def _normalized_text(value: Any) -> str:
    return " ".join(_tokens(value))


def _item_text(item: Any) -> str:
    if isinstance(item, dict):
        for key in (
            "commitment",
            "follow_up",
            "question",
            "decision",
            "text",
            "summary",
            "topic",
        ):
            text = _clean_text(item.get(key))
            if text:
                return text
        return " ".join(
            _clean_text(value)
            for value in item.values()
            if _clean_text(value)
        )
    return _clean_text(item)


def _topic_name(topic: dict[str, Any]) -> str:
    return _clean_text(
        topic.get("topic")
        or topic.get("topic_key")
        or "Untitled topic"
    )


def _topic_identity_tokens(topic: dict[str, Any]) -> set[str]:
    raw = (
        _clean_text(topic.get("topic_key"))
        or _topic_name(topic)
    )
    return {
        token
        for token in _tokens(raw)
        if token not in _TOPIC_GENERIC_WORDS
    }


def _topic_match_score(
    previous: dict[str, Any],
    latest: dict[str, Any],
) -> float:
    previous_name = _normalized_text(
        _topic_name(previous)
    )
    latest_name = _normalized_text(
        _topic_name(latest)
    )

    # Displayed topic names are often more stable than generated topic_key
    # values.  If the human-readable names are identical, treat them as the
    # same thread even when an extractor regenerated a different key.
    if previous_name and previous_name == latest_name:
        return 1.0

    previous_key = _normalized_text(
        previous.get("topic_key")
    )
    latest_key = _normalized_text(
        latest.get("topic_key")
    )

    if previous_key and previous_key == latest_key:
        return 0.99

    previous_identity = _topic_identity_tokens(previous)
    latest_identity = _topic_identity_tokens(latest)

    if (
        previous_identity
        and previous_identity == latest_identity
    ):
        return 0.95

    if not previous_identity or not latest_identity:
        return 0.0

    overlap = len(
        previous_identity & latest_identity
    )
    union = len(
        previous_identity | latest_identity
    )

    if overlap == 0:
        return 0.0

    jaccard = overlap / union

    sequence = SequenceMatcher(
        None,
        previous_name,
        latest_name,
    ).ratio()

    # Avoid treating two unrelated subtopics under the same vendor/entity as
    # identical merely because one proper noun overlaps. Exact reduced
    # identities above still catch cases such as "Endpoint Renewal Process"
    # vs. "Endpoint Contract Negotiation".
    if overlap == 1 and min(
        len(previous_identity),
        len(latest_identity),
    ) == 1:
        return 0.0

    return max(jaccard, sequence * 0.75)


def _match_topics(
    previous_topics: list[dict[str, Any]],
    latest_topics: list[dict[str, Any]],
) -> tuple[
    list[tuple[dict[str, Any], dict[str, Any]]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    candidates: list[
        tuple[float, int, int]
    ] = []

    for previous_index, previous in enumerate(
        previous_topics
    ):
        for latest_index, latest in enumerate(
            latest_topics
        ):
            score = _topic_match_score(
                previous,
                latest,
            )
            if score >= 0.58:
                candidates.append(
                    (
                        score,
                        previous_index,
                        latest_index,
                    )
                )

    candidates.sort(reverse=True)

    used_previous: set[int] = set()
    used_latest: set[int] = set()
    matched: list[
        tuple[dict[str, Any], dict[str, Any]]
    ] = []

    for _score, previous_index, latest_index in candidates:
        if (
            previous_index in used_previous
            or latest_index in used_latest
        ):
            continue
        used_previous.add(previous_index)
        used_latest.add(latest_index)
        matched.append(
            (
                previous_topics[previous_index],
                latest_topics[latest_index],
            )
        )

    previous_only = [
        topic
        for index, topic in enumerate(previous_topics)
        if index not in used_previous
    ]
    latest_only = [
        topic
        for index, topic in enumerate(latest_topics)
        if index not in used_latest
    ]

    return matched, previous_only, latest_only


def _canonical_status(topic: dict[str, Any]) -> str:
    status = _normalized_text(topic.get("status"))

    if not status:
        return ""

    if any(
        word in status
        for word in _CLOSED_STATUS_WORDS
    ):
        return "closed"

    if any(
        word in status
        for word in _ACTIVE_STATUS_WORDS
    ):
        return "active"

    return status


def _topic_is_resolved(topic: dict[str, Any]) -> bool:
    if _canonical_status(topic) == "closed":
        return True

    return bool(
        _RESOLUTION_RE.search(
            " ".join(
                [
                    _clean_text(topic.get("status")),
                    _clean_text(topic.get("summary")),
                ]
            )
        )
    )


def _topic_has_risk(topic: dict[str, Any]) -> bool:
    return bool(
        _RISK_RE.search(
            " ".join(
                [
                    _clean_text(topic.get("status")),
                    _clean_text(topic.get("summary")),
                ]
            )
        )
    )


def _topic_materially_changed(
    previous: dict[str, Any],
    latest: dict[str, Any],
) -> bool:
    previous_status = _canonical_status(previous)
    latest_status = _canonical_status(latest)

    if previous_status != latest_status:
        return True

    previous_summary = _normalized_text(
        previous.get("summary")
    )
    latest_summary = _normalized_text(
        latest.get("summary")
    )

    if not previous_summary or not latest_summary:
        return previous_summary != latest_summary

    similarity = SequenceMatcher(
        None,
        previous_summary,
        latest_summary,
    ).ratio()

    return similarity < 0.82


def _normalized_items(items: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}

    for item in items:
        text = _item_text(item)
        normalized = _normalized_text(text)
        if normalized:
            result.setdefault(normalized, text)

    return result


def _action_item_text(item: Any) -> str:
    if not isinstance(item, dict):
        return _clean_text(item)

    # Grounded commitments commonly use {owner, action, evidence}.  Do not
    # fall back to joining metadata such as "Alex open" when no actual
    # action text survived extraction.
    for key in (
        "action",
        "commitment",
        "follow_up",
        "text",
        "summary",
    ):
        text = _clean_text(item.get(key))
        if text:
            return text

    return ""


def _looks_like_action_metadata(text: str) -> bool:
    normalized = _normalized_text(text)
    if not normalized:
        return True

    tokens = normalized.split()
    status_words = {
        "open",
        "closed",
        "complete",
        "completed",
        "done",
        "ongoing",
        "pending",
        "active",
        "blocked",
    }

    # Some meeting memories contain a flattened owner/status placeholder such
    # as "Alex open" rather than an actionable commitment. Suppress these
    # metadata-only fragments instead of presenting them as work.
    return (
        len(tokens) <= 3
        and tokens[-1] in status_words
    )


def _normalized_action_items(items: list[Any]) -> dict[str, str]:
    result: dict[str, str] = {}

    for item in items:
        text = _action_item_text(item)
        normalized = _normalized_text(text)
        if (
            normalized
            and not _looks_like_action_metadata(text)
        ):
            result.setdefault(normalized, text)

    return result


def _source_memory(
    prepared: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    sources = prepared.get("sources") or []
    if index >= len(sources):
        return {}
    return dict(sources[index].get("memory") or {})


def build_changes_evidence(
    prepared: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically classify source evidence before asking the LLM."""
    previous_memory = _source_memory(prepared, 0)
    latest_memory = _source_memory(prepared, 1)

    previous_topics = [
        dict(topic)
        for topic in previous_memory.get("topics", [])
        if isinstance(topic, dict)
    ]
    latest_topics = [
        dict(topic)
        for topic in latest_memory.get("topics", [])
        if isinstance(topic, dict)
    ]

    matched, previous_only, latest_only = _match_topics(
        previous_topics,
        latest_topics,
    )

    classifications = {
        "new_topics": [],
        "changed_topics": [],
        "resolved_topics": [],
        "carried_topics": [],
        "new_risks": [],
    }

    for latest in latest_only:
        entry = {
            "topic": _topic_name(latest),
            "latest_status": _clean_text(
                latest.get("status")
            ),
            "latest_summary": _clean_text(
                latest.get("summary")
            ),
        }

        # A latest-only topic can still be an explicitly resolved item when
        # extractor naming/key drift prevented a match to the prior meeting.
        # Resolution evidence is stronger than the absence of a match, so do
        # not mislabel a closed item as newly introduced.
        if _topic_is_resolved(latest):
            classifications["resolved_topics"].append(entry)
        elif _topic_has_risk(latest):
            classifications["new_risks"].append(entry)
        else:
            classifications["new_topics"].append(entry)

    for previous, latest in matched:
        entry = {
            "previous_topic": _topic_name(previous),
            "latest_topic": _topic_name(latest),
            "previous_status": _clean_text(
                previous.get("status")
            ),
            "latest_status": _clean_text(
                latest.get("status")
            ),
            "previous_summary": _clean_text(
                previous.get("summary")
            ),
            "latest_summary": _clean_text(
                latest.get("summary")
            ),
        }

        if _topic_is_resolved(latest):
            classifications["resolved_topics"].append(entry)
            continue

        changed = _topic_materially_changed(
            previous,
            latest,
        )

        if (
            changed
            and _topic_has_risk(latest)
            and not _topic_has_risk(previous)
        ):
            classifications["new_risks"].append(entry)
        elif changed:
            classifications["changed_topics"].append(entry)
        else:
            classifications["carried_topics"].append(entry)

    previous_decisions = _normalized_items(
        previous_memory.get("decisions", [])
    )
    latest_decisions = _normalized_items(
        latest_memory.get("decisions", [])
    )

    new_decisions = [
        text
        for key, text in latest_decisions.items()
        if key not in previous_decisions
    ]

    # Some meeting memories capture a decision only inside the topic summary
    # instead of the top-level decisions array.  Preserve only explicit
    # decision language from latest resolved topics; do not infer a decision
    # merely because the topic changed.
    known_decisions = {
        _normalized_text(text)
        for text in new_decisions
        if _normalized_text(text)
    }
    for entry in classifications["resolved_topics"]:
        summary = _clean_text(entry.get("latest_summary"))
        if not summary or not _DECISION_RE.search(summary):
            continue
        decision = f"{_entry_latest_topic(entry)} — {summary}"
        normalized = _normalized_text(decision)
        if normalized and normalized not in known_decisions:
            new_decisions.append(decision)
            known_decisions.add(normalized)

    previous_actions = _normalized_action_items(
        list(previous_memory.get("commitments", []))
        + list(previous_memory.get("follow_ups", []))
    )
    latest_actions = _normalized_action_items(
        list(latest_memory.get("commitments", []))
        + list(latest_memory.get("follow_ups", []))
    )

    new_actions = [
        text
        for key, text in latest_actions.items()
        if key not in previous_actions
    ]
    carried_actions = [
        text
        for key, text in latest_actions.items()
        if key in previous_actions
    ]

    return {
        "previous_label": prepared.get("previous_label"),
        "latest_label": prepared.get("latest_label"),
        **classifications,
        "new_decisions": new_decisions,
        "new_actions": new_actions,
        "carried_actions": carried_actions,
        # Previous-only topics/actions are retained solely as diagnostic
        # evidence. They are deliberately not eligible for carried-forward
        # output because absence from the latest meeting proves nothing.
        "previous_only_topics": [
            _topic_name(topic)
            for topic in previous_only
        ],
    }


def _meeting_run(memory_item: tuple[str, dict]) -> str:
    return _clean_text(memory_item[0])


def _meeting_label(
    meeting_run: str,
    selected: dict[str, Any],
) -> str:
    title = _clean_text(
        selected.get("display_title")
        or selected.get("title")
        or meeting_run
    )

    date_text = (
        meeting_run[:10]
        if len(meeting_run) >= 10
        else meeting_run
    )

    return f"{date_text} | {title}"


def _compact_changes_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item

    preferred = (
        "owner",
        "action",
        "commitment",
        "follow_up",
        "question",
        "decision",
        "text",
        "status",
        "summary",
        "topic",
        "topic_key",
    )
    compact = {
        key: item.get(key)
        for key in preferred
        if item.get(key) not in (None, "", [], {})
    }
    return compact or dict(item)


def _compact_changes_memory(memory: dict[str, Any]) -> dict[str, Any]:
    compact = _compact_memory(memory)
    for key in (
        "decisions",
        "open_questions",
        "commitments",
        "follow_ups",
    ):
        compact[key] = [
            _compact_changes_item(item)
            for item in memory.get(key, [])
        ]
    return compact


def _comparison_source(
    meeting_run: str,
    memory: dict,
    selected: dict[str, Any],
) -> dict[str, Any]:
    return {
        "meeting_run": meeting_run,
        "meeting_date": (
            meeting_run[:10]
            if len(meeting_run) >= 10
            else meeting_run
        ),
        "display_title": _clean_text(
            selected.get("display_title")
            or selected.get("title")
            or meeting_run
        ),
        "memory": _compact_changes_memory(memory),
    }


def prepare_changes_comparison(
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an independent two-meeting comparison payload."""
    memories_by_run = {
        _meeting_run(item): item
        for item in meeting_memories
        if _meeting_run(item)
    }

    selected_by_run = {
        _clean_text(item.get("meeting_run")): dict(item)
        for item in selected_meetings
        if _clean_text(item.get("meeting_run"))
    }

    available_runs = sorted(
        run
        for run in selected_by_run
        if run in memories_by_run
    )

    if len(available_runs) < 2:
        raise NotEnoughMeetingsForChangesError(
            "At least two meetings are required to compare what changed."
        )

    previous_run, latest_run = available_runs[-2:]

    previous_memory = memories_by_run[previous_run][1]
    latest_memory = memories_by_run[latest_run][1]

    previous_selected = selected_by_run[previous_run]
    latest_selected = selected_by_run[latest_run]

    return {
        "previous_run": previous_run,
        "previous_label": _meeting_label(
            previous_run,
            previous_selected,
        ),
        "latest_run": latest_run,
        "latest_label": _meeting_label(
            latest_run,
            latest_selected,
        ),
        "sources": [
            _comparison_source(
                previous_run,
                previous_memory,
                previous_selected,
            ),
            _comparison_source(
                latest_run,
                latest_memory,
                latest_selected,
            ),
        ],
    }


def build_changes_prompt(
    previous_label: str,
    latest_label: str,
    user_focus: str = "",
    *,
    sources: list[dict[str, Any]] | None = None,
    evidence: dict[str, Any] | None = None,
) -> str:
    focus = _clean_text(user_focus)

    source_text = ""
    evidence_text = ""

    if evidence is not None:
        evidence_text = (
            "\n\nDETERMINISTIC COMPARISON EVIDENCE\n\n"
            + json.dumps(
                evidence,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            + "\n\nUse these classifications as authoritative. "
            "Do not move an item into a different comparison section. "
            "Previous-only items are diagnostic only and MUST NOT be "
            "called carried forward, still open, resolved, or changed."
        )

    if sources is not None:
        source_text = (
            "\n\nSOURCE MEETINGS\n\n"
            + json.dumps(
                sources,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

    prompt = f"""
You are performing a strict chronological comparison of exactly two business meetings.

PREVIOUS MEETING:
{previous_label}

LATEST MEETING:
{latest_label}

Create a concise \"What changed since last time?\" brief by comparing the previous meeting directly against the latest meeting.

COMPARISON RULES
- Treat the two supplied meetings independently. Do not choose either meeting as a generic current-state anchor.
- Every claimed change must be supported by evidence from the supplied meeting memories.
- Explicitly distinguish information that is new from information that merely remains open.
- Do not call something resolved, closed, completed, slipped, overdue, worsened, or improved unless the latest meeting explicitly supports that conclusion.
- If an item from the previous meeting is absent from the latest meeting, its current status is unclear. Absence is not resolution and is not proof that it remains open.
- Do not invent owners, deadlines, decisions, risks, commitments, follow-ups, or status changes.
- Compare topic summaries/status, decisions, open questions, commitments, and follow-ups when the source memory contains them.
- When deterministic comparison evidence is supplied, treat its category assignments as authoritative. Do not reclassify items across New, Changed, Resolved, Carried Forward, or New Risks.
- Topic categories are mutually exclusive: a topic should appear in only one of New Since Last Time, Changed / Progressed, Resolved / Closed, Still Open / Carried Forward, or New Risks / Blockers. Executive Delta may summarize those facts.
- Do not append generic grounded questions, grounded actions, a meeting summary, recommendations, or next steps outside the requested comparison sections.
- For every substantive bullet, cite the relevant meeting date/title near the claim.
- For any section with no supported change, write exactly: None identified.

Use exactly these Markdown sections:

## Executive Delta
2-5 bullets covering the most meaningful supported differences between the previous and latest meeting.

## New Since Last Time
Topics or work that first appear in the latest meeting. Put decisions only in New Decisions, risks/blockers only in New Risks / Blockers, and actions only in Commitments & Follow-ups.

## Changed / Progressed
Items present in both meetings whose status, direction, owner, timing, scope, risk, or next step materially changed.

## New Decisions
Decisions first established in the latest meeting. Do not restate older decisions unless the latest meeting materially changes them.

## Resolved / Closed
Only include items with positive evidence in the latest meeting that they were resolved, completed, closed, superseded, or no longer apply.

## Still Open / Carried Forward
Only include previous items that the latest meeting explicitly shows remain open, active, pending, or carried forward. If an older item is simply not mentioned later, do not include it here.

## New Risks / Blockers
Risks, blockers, deadlines, dependencies, or escalation concerns that are new or materially worse in the latest meeting.

## Commitments & Follow-ups
Separate newly created commitments/follow-ups from materially changed or explicitly carried-forward ones. Do not infer action ownership.
""".strip()

    if focus:
        prompt += (
            "\n\nUSER FOCUS:\n"
            f"{focus}\n\n"
            "Use the user focus only to prioritize supported changes; "
            "do not relax the evidence rules above."
        )

    prompt += evidence_text
    prompt += source_text

    prompt += (
        "\n\nFINAL INSTRUCTION\n\n"
        "Compare the PREVIOUS MEETING directly with the LATEST MEETING and return only the eight requested comparison sections."
    )

    return prompt


def _entry_latest_topic(entry: dict[str, Any]) -> str:
    return _clean_text(
        entry.get("latest_topic")
        or entry.get("topic")
        or "Topic"
    )


def _entry_latest_summary(entry: dict[str, Any]) -> str:
    return _clean_text(entry.get("latest_summary"))


def _render_topic_bullets(
    entries: list[dict[str, Any]],
    latest_label: str,
    *,
    previous_label: str = "",
    changed: bool = False,
) -> str:
    if not entries:
        return "None identified."

    bullets: list[str] = []

    for entry in entries:
        topic = _entry_latest_topic(entry)
        summary = _entry_latest_summary(entry)
        detail_parts: list[str] = []

        if changed:
            previous_status = _clean_text(
                entry.get("previous_status")
            )
            latest_status = _clean_text(
                entry.get("latest_status")
            )
            if (
                previous_status
                and latest_status
                and previous_status.casefold()
                != latest_status.casefold()
            ):
                detail_parts.append(
                    f"status: {previous_status} → {latest_status}"
                )

        if summary:
            detail_parts.append(summary)

        details = "; ".join(detail_parts)

        if changed and previous_label:
            citation = (
                f"{previous_label} → {latest_label}"
            )
        else:
            citation = latest_label

        if details:
            bullets.append(
                f"- **{topic}** — {details} ({citation})"
            )
        else:
            bullets.append(
                f"- **{topic}** ({citation})"
            )

    return "\n\n".join(bullets)


def _render_decision_bullets(
    decisions: list[str],
    latest_label: str,
) -> str:
    if not decisions:
        return "None identified."

    return "\n\n".join(
        f"- {decision} ({latest_label})"
        for decision in decisions
    )


def _render_action_section(
    evidence: dict[str, Any],
    latest_label: str,
) -> str:
    new_actions = [
        _clean_text(item)
        for item in evidence.get("new_actions", [])
        if _clean_text(item)
    ]
    carried_actions = [
        _clean_text(item)
        for item in evidence.get("carried_actions", [])
        if _clean_text(item)
    ]

    if not new_actions and not carried_actions:
        return "None identified."

    blocks: list[str] = []

    if new_actions:
        blocks.append(
            "**New commitments / follow-ups**\n\n"
            + "\n\n".join(
                f"- {item} ({latest_label})"
                for item in new_actions
            )
        )

    if carried_actions:
        blocks.append(
            "**Explicitly carried forward**\n\n"
            + "\n\n".join(
                f"- {item} ({latest_label})"
                for item in carried_actions
            )
        )

    return "\n\n".join(blocks)


def _render_executive_delta(
    evidence: dict[str, Any],
    previous_label: str,
    latest_label: str,
) -> str:
    bullets: list[str] = []

    def add_entry(
        entry: dict[str, Any],
        label: str,
        *,
        changed: bool = False,
    ) -> None:
        if len(bullets) >= 5:
            return
        topic = _entry_latest_topic(entry)
        summary = _entry_latest_summary(entry)
        detail = summary
        if changed:
            previous_status = _clean_text(
                entry.get("previous_status")
            )
            latest_status = _clean_text(
                entry.get("latest_status")
            )
            if (
                previous_status
                and latest_status
                and previous_status.casefold()
                != latest_status.casefold()
            ):
                status = (
                    f"status: {previous_status} → "
                    f"{latest_status}"
                )
                detail = (
                    f"{status}; {summary}"
                    if summary
                    else status
                )
        if detail:
            bullets.append(
                f"- **{topic}** — {label}: {detail}"
            )
        else:
            bullets.append(
                f"- **{topic}** — {label}."
            )

    # Prioritize the categories that best answer "what materially changed?"
    for entry in evidence.get("resolved_topics", []):
        add_entry(entry, "resolved/closed")
    for entry in evidence.get("changed_topics", []):
        add_entry(entry, "changed/progressed", changed=True)
    for entry in evidence.get("new_risks", []):
        add_entry(entry, "new risk/blocker")
    for entry in evidence.get("new_topics", []):
        add_entry(entry, "new since last time")

    if not bullets:
        return "None identified."

    return "\n\n".join(bullets)


def _extract_executive_delta(result: str) -> str:
    match = re.search(
        r"(?ims)^##\s+Executive Delta\s*\n"
        r"(.*?)"
        r"(?=^##\s+|\Z)",
        result,
    )

    if not match:
        return "None identified."

    body = match.group(1).strip()
    return body or "None identified."


def apply_changes_evidence_gate(
    result: str,
    evidence: dict[str, Any],
) -> str:
    """Render evidence-sensitive sections from deterministic classifications."""
    previous_label = _clean_text(
        evidence.get("previous_label")
    )
    latest_label = _clean_text(
        evidence.get("latest_label")
    )

    sections = [
        (
            "Executive Delta",
            _render_executive_delta(
                evidence,
                previous_label,
                latest_label,
            ),
        ),
        (
            "New Since Last Time",
            _render_topic_bullets(
                evidence.get("new_topics", []),
                latest_label,
            ),
        ),
        (
            "Changed / Progressed",
            _render_topic_bullets(
                evidence.get("changed_topics", []),
                latest_label,
                previous_label=previous_label,
                changed=True,
            ),
        ),
        (
            "New Decisions",
            _render_decision_bullets(
                evidence.get("new_decisions", []),
                latest_label,
            ),
        ),
        (
            "Resolved / Closed",
            _render_topic_bullets(
                evidence.get("resolved_topics", []),
                latest_label,
            ),
        ),
        (
            "Still Open / Carried Forward",
            _render_topic_bullets(
                evidence.get("carried_topics", []),
                latest_label,
            ),
        ),
        (
            "New Risks / Blockers",
            _render_topic_bullets(
                evidence.get("new_risks", []),
                latest_label,
            ),
        ),
        (
            "Commitments & Follow-ups",
            _render_action_section(
                evidence,
                latest_label,
            ),
        ),
    ]

    return "\n\n".join(
        f"## {heading}\n\n{body.strip()}"
        for heading, body in sections
    ).strip()


def _execution_profile(
    execution_profile: str,
):
    hardware_profile = detect_hardware_profile()

    calibration = get_execution_calibration(
        profile=execution_profile,
        model_name=LLM_MODEL,
        context_size_tokens=LLM_CONTEXT_SIZE,
        hardware_label=(
            hardware_profile.display_label
        ),
    )

    return get_execution_profile(
        execution_profile,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=LLM_MODEL,
        hardware_profile=hardware_profile,
        hardware_label=(
            hardware_profile.display_label
        ),
        hardware_performance_class=(
            hardware_profile.performance_class
        ),
        hardware_budget_factor=(
            hardware_profile.budget_factor
        ),
        calibration_factor=(
            calibration.factor
        ),
        calibration_sample_count=(
            calibration.sample_count
        ),
        calibration_median_elapsed_seconds=(
            calibration.median_elapsed_seconds
        ),
        calibration_reason=(
            calibration.reason
        ),
    )


def run_changes_query(
    user_focus: str,
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict[str, Any]],
    *,
    execution_profile: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    prepared = prepare_changes_comparison(
        meeting_memories,
        selected_meetings,
    )

    evidence = build_changes_evidence(
        prepared
    )

    prompt = build_changes_prompt(
        prepared["previous_label"],
        prepared["latest_label"],
        user_focus,
        sources=prepared["sources"],
        evidence=evidence,
    )

    profile = _execution_profile(
        execution_profile
    )

    # Changes always compares exactly two compact meeting memories. Keep the
    # comparison in one inference so both sides are visible to the model at
    # the same time. The configured context/profile budget is still recorded
    # in metadata for observability.
    execution_plan = choose_execution_plan(
        prompt,
        can_chunk=False,
        direct_token_budget=(
            profile.direct_token_budget
        ),
    )

    result = clean_markdown_artifacts(
        ask_llm(
            prompt,
            timeout_seconds=getattr(profile, "llm_call_timeout_seconds", 120),
        )
    )
    result = apply_changes_evidence_gate(
        result,
        evidence,
    )

    execution_metadata = build_execution_metadata(
        execution_plan,
        chunk_count=0,
        profile_name=profile.name,
        resolved_profile_name=getattr(profile, "resolved_name", profile.name),
        profile_reason=getattr(profile, "profile_reason", ""),
        chunk_overlap_tokens=getattr(profile, "chunk_overlap_tokens", 0),
        context_size_tokens=(
            profile.context_size_tokens
        ),
        context_reserve_tokens=(
            profile.context_reserve_tokens
        ),
        model_name=profile.model_name,
        model_parameter_billions=(
            profile.model_parameter_billions
        ),
        model_budget_factor=(
            profile.model_budget_factor
        ),
        hardware_label=profile.hardware_label,
        hardware_performance_class=(
            profile.hardware_performance_class
        ),
        hardware_budget_factor=(
            profile.hardware_budget_factor
        ),
        calibration_factor=(
            profile.calibration_factor
        ),
        calibration_sample_count=(
            profile.calibration_sample_count
        ),
        calibration_median_elapsed_seconds=(
            profile.calibration_median_elapsed_seconds
        ),
        llm_call_timeout_seconds=(
            getattr(profile, "llm_call_timeout_seconds", 120)
        ),
        calibration_reason=(
            profile.calibration_reason
        ),
    )

    return result, execution_metadata, prepared
