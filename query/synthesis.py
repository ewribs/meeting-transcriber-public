from __future__ import annotations

import json
import re
from dataclasses import dataclass

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
    chunk_meeting_sources,
    get_execution_profile,
)


SYNTHESIS_DIRECT_MULTIPLIERS = {
    "Auto": 1.00,
    "Conservative": 1.00,
    "Balanced": 1.00,
    "High Performance": 1.00,
    "Aggressive": 1.00,
}

SYNTHESIS_CHUNK_MULTIPLIERS = {
    "Auto": 1.00,
    "Conservative": 1.00,
    "Balanced": 1.00,
    "High Performance": 1.00,
    "Aggressive": 1.00,
}

LEADERSHIP_EVIDENCE_RE = re.compile(
    r"\b("
    r"approval|approve|approved|"
    r"board|blessing|"
    r"escalat\w*|leadership|"
    r"sponsor\w*|guidance|"
    r"exception|sign[- ]?off|"
    r"authoriz\w*|prioritiz\w*"
    r")\b",
    re.IGNORECASE,
)



SPECULATIVE_LEADERSHIP_CLAUSE_RE = re.compile(
    r"(?:,\s*(?:which|and)?\s*)"
    r"(?:"
    r"(?:may|might|could)\s+(?:require|need)\s+"
    r"(?:leadership|executive|management|boss)[^.]*"
    r"|"
    r"(?:leadership|executive|management|boss)[^.]{0,120}?"
    r"\b(?:may|might|could)\s+(?:be\s+)?(?:needed|required)[^.]*"
    r")"
    r"(?=\.|$)",
    re.IGNORECASE,
)
WIN_EVIDENCE_RE = re.compile(
    r"\b("
    r"savings?|saved|"
    r"cost avoidance|"
    r"reduc(?:e|ed|tion)|"
    r"held flat|flat pricing|"
    r"no (?:licensing )?increase|"
    r"no changes|"
    r"complet(?:e|ed)|"
    r"deliver(?:ed|y)|"
    r"resolv(?:e|ed)|"
    r"closed|"
    r"successful(?:ly)?|"
    r"under budget|"
    r"renewal confirmed|"
    r"confirmed at|"
    r"price hold"
    r")\b",
    re.IGNORECASE,
)


BOSS_PREP_SECTION_TITLES = {
    1: "What needs attention now — urgent, time-sensitive, or blocked items",
    2: "Open staff items — unresolved commitments, decisions, follow-ups, or questions from recent 1:1s, grouped by staff member/meeting",
    3: "Themes across the team",
    4: "Ad-hoc signals",
    5: "Sensitive / escalation topics",
    6: "Decisions or help I need from my boss",
    7: "My commitments",
    8: "Worth mentioning / progress / wins",
}

TOKEN_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9$%.-]*"
)

STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "been",
    "being",
    "could",
    "from",
    "have",
    "into",
    "need",
    "needed",
    "needs",
    "ongoing",
    "open",
    "should",
    "that",
    "their",
    "there",
    "these",
    "this",
    "with",
    "would",
}


@dataclass(frozen=True)
class SynthesisPlan:
    compact_memories: list[tuple[str, dict]]
    sources: list[dict]
    direct_prompt: str
    profile: object
    execution_plan: object
    chunks: list[
        tuple[
            list[tuple[str, dict]],
            list[dict],
        ]
    ]
    direct_token_budget: int
    chunk_source_token_budget: int


def _compact_item(item):
    if isinstance(item, dict):
        preferred = (
            "owner",
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
            if item.get(key)
            not in (None, "", [], {})
        }

        return compact or dict(item)

    return item


def _compact_memory(memory: dict) -> dict:
    """
    Keep only data materially useful to cross-meeting executive synthesis.
    """

    topics = []

    for topic in memory.get("topics", []):
        if not isinstance(topic, dict):
            continue

        compact_topic = {
            key: topic.get(key)
            for key in (
                "topic_key",
                "topic",
                "status",
                "summary",
            )
            if topic.get(key)
            not in (None, "", [], {})
        }

        if compact_topic:
            topics.append(compact_topic)

    compact = {
        "topics": topics,
        "decisions": [
            _compact_item(item)
            for item in memory.get(
                "decisions",
                [],
            )
        ],
        "open_questions": [
            _compact_item(item)
            for item in memory.get(
                "open_questions",
                [],
            )
        ],
        "commitments": [
            _compact_item(item)
            for item in memory.get(
                "commitments",
                [],
            )
        ],
        "follow_ups": [
            _compact_item(item)
            for item in memory.get(
                "follow_ups",
                [],
            )
        ],
    }

    return {
        key: value
        for key, value in compact.items()
        if value
    }


def _compact_meeting_memories(
    meeting_memories:
        list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    return [
        (
            meeting_run,
            _compact_memory(memory),
        )
        for meeting_run, memory
        in meeting_memories
    ]


def _source_kind(
    display_title: str,
    participants: list[str],
) -> str:
    title = display_title.casefold()

    one_on_one_markers = (
        "1v1",
        "1:1",
        "one on one",
        "one-on-one",
        "one to one",
        "one-to-one",
    )

    if any(
        marker in title
        for marker in one_on_one_markers
    ):
        return "one_on_one"

    if len(participants) == 1:
        return "one_on_one"

    return "other"


def _source_records(
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict],
) -> list[dict]:
    selected_by_run = {
        item.get("meeting_run"): item
        for item in selected_meetings
        if item.get("meeting_run")
    }

    records = []

    for meeting_run, memory in meeting_memories:
        selected = selected_by_run.get(
            meeting_run,
            {},
        )

        display_title = selected.get(
            "display_title",
            meeting_run,
        )

        participants = list(
            selected.get(
                "participants",
                [],
            )
            or []
        )

        records.append(
            {
                "meeting_run": meeting_run,
                "meeting_date": (
                    meeting_run[:10]
                    if len(meeting_run) >= 10
                    else meeting_run
                ),
                "display_title": display_title,
                "participants": participants,
                "source_kind": _source_kind(
                    display_title,
                    participants,
                ),
                "memory": _compact_memory(
                    memory
                ),
            }
        )

    return records


def _source_label(source: dict) -> str:
    return (
        f"{source['meeting_date']} | "
        f"{source['display_title']}"
    )


def _direct_prompt(
    user_prompt: str,
    sources: list[dict],
    conversation_history: list[dict] | None,
) -> str:
    source_labels = [
        _source_label(item)
        for item in sources
    ]

    return f"""
You are performing a cross-meeting synthesis for a business user.

USER REQUEST

{user_prompt}

SOURCE COVERAGE REQUIREMENT

There are exactly {len(sources)} selected source meetings.

You MUST consider every selected source meeting independently before
synthesizing across them.

Selected sources:
{json.dumps(source_labels, indent=2, ensure_ascii=False)}

Rules:
- Do not choose one source as the anchor or primary meeting.
- Give each selected meeting an independent pass.
- A meeting may contribute nothing material; do not force content from it.
- Look for repeated themes only after reviewing all sources.
- Preserve unique urgent or sensitive items even when they occur once.
- Distinguish recurring themes from one-off issues.
- Do not infer that silence later means an older issue was resolved.
- Use only facts from the supplied meeting memories.
- Do not invent owners, deadlines, decisions, risks, or status.
- Cite substantive items with meeting date/title when practical.
- Follow the user's requested sections and format exactly.
- Always emit all eight numbered Boss Prep section headings, even when a section has no supported content. Put `None identified.` under that heading rather than omitting the heading.
- `source_kind` is authoritative for this recipe: `one_on_one` is a likely
  staff 1:1; `other` is a non-1:1 source.
- Ad-hoc signals may come only from `source_kind = other`. Never relabel a one-on-one item as ad-hoc.
- A cross-team theme requires at least two distinct source meetings and
  must name those supporting sources.
- Boss/leadership help requires explicit evidence of approval, escalation,
  sponsorship, guidance, exception handling, sign-off, authorization, or
  comparable leadership involvement. Do not turn ordinary open work into
  a boss ask. Ordinary follow-ups are not boss asks.
- "My commitments" may not include commitments owned by the named staff
  participant(s). If the user's identity cannot be established safely,
  prefer "None identified".
- Wins / "worth mentioning" must be supported positive outcomes such as
  savings, held pricing, completed delivery, resolved risk, confirmed
  favorable renewal, or another concrete achievement. Plans and ongoing
  discussions are not wins. Do not relabel challenges or unfinished work as wins.
- Do not append a generic action list or generic meeting summary.

Conversation history is only for conversational references, never as a
meeting-fact source:

{json.dumps(conversation_history or [], indent=2, ensure_ascii=False)}

SELECTED MEETING SOURCES

{json.dumps(sources, indent=2, ensure_ascii=False, default=str)}

FINAL INSTRUCTION

First review all {len(sources)} sources separately. Then synthesize the
answer to the user's request across the full selected set.

{user_prompt}
""".strip()


def _chunk_evidence_prompt(
    user_prompt: str,
    sources: list[dict],
    chunk_number: int,
    chunk_count: int,
) -> str:
    labels = [
        _source_label(item)
        for item in sources
    ]

    return f"""
You are extracting evidence for a cross-meeting synthesis.

This is source chunk {chunk_number} of {chunk_count}.

Eventual user request:

{user_prompt}

MEETINGS IN THIS CHUNK
{json.dumps(labels, indent=2, ensure_ascii=False)}

For EACH meeting in this chunk:
- inspect it independently;
- extract only evidence relevant to the eventual request;
- preserve urgent items, open items, decisions, commitments, sensitive
  issues, blockers, progress, and recurring-theme candidates;
- preserve `source_kind`;
- preserve explicit commitment owners exactly;
- distinguish concrete wins from plans/challenges;
- distinguish explicit leadership involvement from ordinary open work;
- include meeting date/title with each evidence item;
- if nothing is relevant, write:
  <date/title>: NO MATERIAL ITEMS

Do not synthesize across meetings yet.
Do not choose an anchor meeting.
Do not invent anything.

SOURCE DATA

{json.dumps(sources, indent=2, ensure_ascii=False, default=str)}
""".strip()


def _chunk_synthesis_prompt(
    user_prompt: str,
    source_labels: list[str],
    chunk_findings: list[str],
    conversation_history: list[dict] | None,
) -> str:
    findings = "\n\n".join(
        f"===== EVIDENCE CHUNK {i} =====\n{value}"
        for i, value in enumerate(
            chunk_findings,
            start=1,
        )
    )

    return f"""
You are producing the final cross-meeting synthesis for a business user.

USER REQUEST

{user_prompt}

SOURCE COVERAGE REQUIREMENT

The selected source set contains exactly {len(source_labels)} meetings:

{json.dumps(source_labels, indent=2, ensure_ascii=False)}

Rules:
- Do not choose one meeting/person as the anchor.
- Consider all selected meetings before prioritizing.
- Preserve unique urgent/sensitive items even if they appear once.
- A cross-team theme requires at least two distinct source meetings and
  must name those supporting sources.
- Ad-hoc signals may come only from non-1:1 (`other`) sources.
- Boss-help items require explicit leadership involvement; ordinary
  follow-ups are not boss asks.
- "My commitments" excludes staff-owned commitments.
- Wins require concrete positive outcomes; plans/ongoing work are not wins.
- Do not infer resolution from omission.
- Do not invent facts, status, owners, dates, or conclusions.
- Cite meeting date/title beside substantive items.
- Follow the user's requested sections and format.
- If a requested section has nothing supported, use the user's requested
  empty-state wording.

Conversation history is only for conversational references:

{json.dumps(conversation_history or [], indent=2, ensure_ascii=False)}

MEETING-BY-MEETING EVIDENCE

{findings}

FINAL INSTRUCTION

Answer the user's request from the full selected source set:

{user_prompt}
""".strip()


def _usable_context_tokens(profile) -> int | None:
    if profile.context_size_tokens <= 0:
        return None

    return max(
        1024,
        profile.context_size_tokens
        - profile.context_reserve_tokens,
    )


def _synthesis_budgets(
    profile,
    execution_profile: str,
) -> tuple[int, int]:
    direct_multiplier = (
        SYNTHESIS_DIRECT_MULTIPLIERS.get(
            execution_profile,
            SYNTHESIS_DIRECT_MULTIPLIERS[
                "Balanced"
            ],
        )
    )

    chunk_multiplier = (
        SYNTHESIS_CHUNK_MULTIPLIERS.get(
            execution_profile,
            SYNTHESIS_CHUNK_MULTIPLIERS[
                "Balanced"
            ],
        )
    )

    direct_budget = max(
        profile.direct_token_budget,
        int(
            profile.direct_token_budget
            * direct_multiplier
        ),
    )

    chunk_budget = max(
        profile.chunk_source_token_budget,
        int(
            profile.chunk_source_token_budget
            * chunk_multiplier
        ),
    )

    usable_context = _usable_context_tokens(
        profile
    )

    if usable_context is not None:
        direct_budget = min(
            direct_budget,
            usable_context,
        )
        chunk_budget = min(
            chunk_budget,
            usable_context,
        )

    return (
        direct_budget,
        chunk_budget,
    )


def build_synthesis_plan(
    user_prompt: str,
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict],
    conversation_history: list[dict] | None = None,
    *,
    execution_profile: str = "Auto",
) -> SynthesisPlan:
    if not meeting_memories:
        raise ValueError(
            "No meeting sources are available for synthesis."
        )

    compact_memories = (
        _compact_meeting_memories(
            meeting_memories
        )
    )

    sources = _source_records(
        compact_memories,
        selected_meetings,
    )

    direct_prompt = _direct_prompt(
        user_prompt,
        sources,
        conversation_history,
    )

    hardware_profile = (
        detect_hardware_profile()
    )

    calibration = get_execution_calibration(
        profile=execution_profile,
        model_name=LLM_MODEL,
        context_size_tokens=LLM_CONTEXT_SIZE,
        hardware_label=(
            hardware_profile.display_label
        ),
    )

    profile = get_execution_profile(
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

    direct_budget, chunk_budget = (
        _synthesis_budgets(
            profile,
            execution_profile,
        )
    )

    execution_plan = choose_execution_plan(
        direct_prompt,
        can_chunk=True,
        direct_token_budget=(
            direct_budget
        ),
    )

    chunks = []

    if execution_plan.mode == "chunked":
        chunks = chunk_meeting_sources(
            compact_memories,
            selected_meetings,
            chunk_source_token_budget=(
                chunk_budget
            ),
        )

    return SynthesisPlan(
        compact_memories=compact_memories,
        sources=sources,
        direct_prompt=direct_prompt,
        profile=profile,
        execution_plan=execution_plan,
        chunks=chunks,
        direct_token_budget=direct_budget,
        chunk_source_token_budget=(
            chunk_budget
        ),
    )


def synthesis_plan_payload(
    user_prompt: str,
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict],
    conversation_history: list[dict] | None = None,
    *,
    execution_profile: str = "Auto",
) -> dict:
    plan = build_synthesis_plan(
        user_prompt,
        meeting_memories,
        selected_meetings,
        conversation_history,
        execution_profile=execution_profile,
    )

    chunk_count = len(plan.chunks)

    inference_calls = (
        1
        if plan.execution_plan.mode == "direct"
        else chunk_count + 1
    )

    estimated_tokens = (
        plan.execution_plan
        .estimated_prompt_tokens
    )

    mode_label = (
        "Direct"
        if plan.execution_plan.mode == "direct"
        else "Chunked"
    )

    meeting_count = len(
        plan.compact_memories
    )

    profile_label = (
        f"Auto→{getattr(plan.profile, 'resolved_name', plan.profile.name)}"
        if plan.profile.name == "Auto"
        else getattr(plan.profile, "resolved_name", plan.profile.name)
    )

    status_text = (
        f"Boss Prep · {profile_label} · {mode_label} · "
        f"{meeting_count} meeting"
        f"{'' if meeting_count == 1 else 's'} · "
        f"~{estimated_tokens:,} tokens · "
        f"{inference_calls} inference"
        f"{'' if inference_calls == 1 else 's'} expected"
    )

    return {
        "mode":
            plan.execution_plan.mode,
        "estimated_prompt_tokens":
            estimated_tokens,
        "direct_token_budget":
            plan.direct_token_budget,
        "chunk_source_token_budget":
            plan.chunk_source_token_budget,
        "chunk_count":
            chunk_count,
        "inference_calls":
            inference_calls,
        "meeting_count":
            meeting_count,
        "hardware_label":
            plan.profile.hardware_label,
        "profile":
            plan.profile.name,
        "resolved_profile":
            getattr(plan.profile, "resolved_name", plan.profile.name),
        "context_size_tokens":
            plan.profile.context_size_tokens,
        "profile_reason":
            getattr(plan.profile, "profile_reason", ""),
        "status_text":
            status_text,
    }


def _normalize_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_RE.findall(text)
        if (
            len(token) >= 3
            and token.casefold()
            not in STOPWORDS
        )
    }


def _memory_units(memory: dict) -> list[str]:
    units = []

    for topic in memory.get("topics", []):
        if isinstance(topic, dict):
            units.append(
                " ".join(
                    str(value)
                    for value in topic.values()
                    if value not in (
                        None,
                        "",
                        [],
                        {},
                    )
                )
            )

    for key in (
        "decisions",
        "open_questions",
        "commitments",
        "follow_ups",
    ):
        for item in memory.get(key, []):
            if isinstance(item, dict):
                units.append(
                    " ".join(
                        str(value)
                        for value in item.values()
                        if value not in (
                            None,
                            "",
                            [],
                            {},
                        )
                    )
                )
            else:
                units.append(str(item))

    return [
        unit.strip()
        for unit in units
        if unit.strip()
    ]


def _candidate_units(
    source: dict,
    pattern: re.Pattern,
) -> list[str]:
    return [
        unit
        for unit in _memory_units(
            source.get("memory", {})
        )
        if pattern.search(unit)
    ]


def _line_matches_candidates(
    line: str,
    candidates: list[str],
) -> bool:
    line_tokens = _normalize_tokens(line)

    if not line_tokens:
        return False

    for candidate in candidates:
        candidate_tokens = (
            _normalize_tokens(candidate)
        )

        overlap = (
            line_tokens
            & candidate_tokens
        )

        if len(overlap) >= 2:
            return True

        if (
            len(overlap) == 1
            and len(line_tokens) <= 4
        ):
            return True

    return False


def _split_numbered_sections(
    text: str,
) -> list[
    tuple[int | None, str, str]
]:
    matches = list(
        re.finditer(
            r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?"
            r"\*{0,2}([1-8])\.[ \t]+",
            text,
        )
    )

    if not matches:
        return [
            (
                None,
                "",
                text,
            )
        ]

    sections = []

    if matches[0].start() > 0:
        sections.append(
            (
                None,
                "",
                text[
                    :matches[0].start()
                ],
            )
        )

    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )

        block = text[
            match.start():
            end
        ]

        first_newline = block.find("\n")

        if first_newline < 0:
            heading = block
            body = ""
        else:
            heading = block[:first_newline]
            body = block[first_newline + 1:]

        sections.append(
            (
                int(match.group(1)),
                heading,
                body,
            )
        )

    return sections



def _strip_orphan_none_tail(
    body: str,
    missing_count: int,
) -> str:
    """Remove bare None-identified placeholders that belong to omitted sections."""
    if missing_count <= 0:
        return body.strip()

    lines = body.splitlines()

    def is_blank_or_rule(line: str) -> bool:
        stripped = line.strip()
        return (
            not stripped
            or bool(re.fullmatch(r"(?:\\)?-{3,}", stripped))
        )

    removed = 0
    index = len(lines) - 1

    while index >= 0 and removed < missing_count:
        while index >= 0 and is_blank_or_rule(lines[index]):
            index -= 1

        if index < 0:
            break

        if lines[index].strip().lower() != "none identified.":
            break

        removed += 1
        index -= 1

    if removed == 0:
        return body.strip()

    while index >= 0 and is_blank_or_rule(lines[index]):
        index -= 1

    return "\n".join(lines[: index + 1]).strip()


def _ensure_boss_prep_sections(
    sections: list[tuple[int | None, str, str]],
) -> list[tuple[int | None, str, str]]:
    """Guarantee all eight Boss Prep sections exist in numeric order."""
    numbered = [
        (number, heading, body)
        for number, heading, body in sections
        if number is not None
    ]

    if not numbered:
        return sections

    present_numbers = {number for number, _heading, _body in numbered}
    section_map = {}
    for number, heading, body in numbered:
        normalized_body = body
        body_without_rules = re.sub(
            r"(?m)^[ \t]*(?:\\)?-{3,}[ \t]*$",
            "",
            normalized_body,
        ).strip()
        if (
            "none identified." in heading.casefold()
            and not body_without_rules
        ):
            normalized_body = "None identified."
        section_map[number] = [heading, normalized_body]

    ordered_present = sorted(present_numbers)
    for index, number in enumerate(ordered_present):
        next_number = (
            ordered_present[index + 1]
            if index + 1 < len(ordered_present)
            else 9
        )
        gap = max(0, next_number - number - 1)
        if (
            gap
            and "none identified."
            not in section_map[number][0].casefold()
        ):
            section_map[number][1] = _strip_orphan_none_tail(
                section_map[number][1],
                gap,
            )

    rebuilt: list[tuple[int | None, str, str]] = []

    for number, heading, body in sections:
        if number is None and body.strip():
            rebuilt.append((None, heading, body))

    for number in range(1, 9):
        heading = (
            f"**{number}. {BOSS_PREP_SECTION_TITLES[number]}**"
        )

        if number in section_map:
            _original_heading, body = section_map[number]
            rebuilt.append((number, heading, body))
        else:
            rebuilt.append((
                number,
                heading,
                "None identified.",
            ))

    return rebuilt


def _find_source_for_line(
    line: str,
    sources: list[dict],
):
    for source in sources:
        if _source_label(source) in line:
            return source

    return None


def _best_matching_candidate(
    line: str,
    candidates: list[str],
) -> str | None:
    line_tokens = _normalize_tokens(line)

    if not line_tokens:
        return None

    best_candidate = None
    best_score = (0, 0.0)

    for candidate in candidates:
        candidate_tokens = _normalize_tokens(candidate)
        if not candidate_tokens:
            continue

        overlap = line_tokens & candidate_tokens
        overlap_count = len(overlap)
        coverage = overlap_count / max(1, len(candidate_tokens))
        score = (overlap_count, coverage)

        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_score[0] < 2:
        return None

    return best_candidate


def _strip_speculative_leadership_inference(
    line: str,
) -> str:
    cleaned = SPECULATIVE_LEADERSHIP_CLAUSE_RE.sub(
        "",
        line,
    )
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    return cleaned.strip()


def _filter_boss_help_section(
    body: str,
    sources: list[dict],
) -> str:
    candidate_map = {
        _source_label(source): _candidate_units(
            source,
            LEADERSHIP_EVIDENCE_RE,
        )
        for source in sources
    }

    lines = body.splitlines()
    output = []
    pending_header = None
    current_source = None
    kept_for_current = False

    def process_line(
        line: str,
        source: dict,
    ) -> str | None:
        label = _source_label(source)
        candidates = candidate_map.get(label, [])
        cleaned = _strip_speculative_leadership_inference(line)

        if not LEADERSHIP_EVIDENCE_RE.search(cleaned):
            return None

        if _best_matching_candidate(cleaned, candidates) is None:
            return None

        return cleaned

    def flush_header():
        nonlocal pending_header

        if pending_header is not None and kept_for_current:
            output.append(pending_header)

        pending_header = None

    for line in lines:
        source = _find_source_for_line(line, sources)

        if source is not None:
            flush_header()
            current_source = source
            kept_for_current = False
            label = _source_label(source)

            stripped = (
                line
                .replace(f"**{label}**", "")
                .replace(label, "")
                .strip(" •*-:\t()")
            )

            if stripped:
                kept = process_line(line, source)
                if kept is not None:
                    output.append(kept)
                    kept_for_current = True
            else:
                pending_header = line

            continue

        if current_source is None or not line.strip():
            continue

        kept = process_line(line, current_source)
        if kept is not None:
            if pending_header is not None and not kept_for_current:
                output.append(pending_header)
                pending_header = None

            output.append(kept)
            kept_for_current = True

    flush_header()

    if not any(line.strip() for line in output):
        return "None identified."

    return "\n".join(output).strip()


def _filter_gated_source_section(
    body: str,
    sources: list[dict],
    pattern: re.Pattern,
) -> str:
    candidate_map = {
        _source_label(source):
            _candidate_units(
                source,
                pattern,
            )
        for source in sources
    }

    lines = body.splitlines()
    output = []
    pending_header = None
    current_source = None
    kept_for_current = False

    def flush_header():
        nonlocal pending_header

        if (
            pending_header is not None
            and kept_for_current
        ):
            output.append(pending_header)

        pending_header = None

    for line in lines:
        source = _find_source_for_line(
            line,
            sources,
        )

        if source is not None:
            flush_header()
            current_source = source
            kept_for_current = False

            label = _source_label(source)

            stripped = (
                line
                .replace(
                    f"**{label}**",
                    "",
                )
                .replace(
                    label,
                    "",
                )
                .strip(" •*-:\t")
            )

            if stripped:
                candidates = (
                    candidate_map.get(
                        label,
                        [],
                    )
                )

                if _line_matches_candidates(
                    line,
                    candidates,
                ):
                    output.append(line)
                    kept_for_current = True
            else:
                pending_header = line

            continue

        if current_source is None:
            continue

        if not line.strip():
            continue

        candidates = candidate_map.get(
            _source_label(
                current_source
            ),
            [],
        )

        if _line_matches_candidates(
            line,
            candidates,
        ):
            if (
                pending_header is not None
                and not kept_for_current
            ):
                output.append(
                    pending_header
                )
                pending_header = None

            output.append(line)
            kept_for_current = True

    flush_header()

    if not any(
        line.strip()
        for line in output
    ):
        return "None identified."

    return "\n".join(output).strip()


def _filter_theme_section(
    body: str,
    sources: list[dict],
) -> str:
    labels = [
        _source_label(source)
        for source in sources
    ]

    lines = [
        line
        for line in body.splitlines()
        if line.strip()
    ]

    groups = []
    current = []

    for line in lines:
        contains_source = any(
            label in line
            for label in labels
        )

        is_bullet = bool(
            re.match(
                r"^\s*[•*-]\s+",
                line,
            )
        )

        if (
            is_bullet
            and not contains_source
        ):
            if current:
                groups.append(current)

            current = [line]
        elif current:
            current.append(line)

    if current:
        groups.append(current)

    valid = []

    for group in groups:
        support = {
            label
            for label in labels
            if any(
                label in line
                for line in group
            )
        }

        if len(support) >= 2:
            valid.extend(group)

    if not valid:
        return "None identified."

    return "\n".join(valid).strip()


def apply_synthesis_evidence_gate(
    result: str,
    sources: list[dict],
) -> str:
    sections = _split_numbered_sections(
        result
    )

    sections = _ensure_boss_prep_sections(
        sections
    )

    if not any(
        number is not None
        for number, _heading, _body
        in sections
    ):
        return result.strip()

    has_other_source = any(
        source.get("source_kind")
        == "other"
        for source in sources
    )

    rebuilt = []

    for number, heading, body in sections:
        if number is None:
            if body.strip():
                rebuilt.append(
                    body.strip()
                )
            continue

        new_body = body.strip()

        if number == 3:
            new_body = _filter_theme_section(
                body,
                sources,
            )

        elif (
            number == 4
            and not has_other_source
        ):
            new_body = "None identified."

        elif number == 6:
            new_body = _filter_boss_help_section(
                body,
                sources,
            )

        elif number == 8:
            new_body = (
                _filter_gated_source_section(
                    body,
                    sources,
                    WIN_EVIDENCE_RE,
                )
            )

        new_body = re.sub(
            r"(?m)^[ \t]*(?:\\)?-{3,}[ \t]*$",
            "",
            new_body,
        ).strip()

        rebuilt.append(
            (
                heading.strip()
                + (
                    "\n\n" + new_body
                    if new_body
                    else ""
                )
            ).strip()
        )

    return "\n\n".join(
        part
        for part in rebuilt
        if part
    ).strip()


def run_synthesis_query(
    user_prompt: str,
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict],
    conversation_history: list[dict] | None = None,
    *,
    return_execution_metadata: bool = False,
    execution_profile: str = "Auto",
):
    plan = build_synthesis_plan(
        user_prompt,
        meeting_memories,
        selected_meetings,
        conversation_history,
        execution_profile=execution_profile,
    )

    chunk_count = len(plan.chunks)

    if plan.execution_plan.mode == "direct":
        result = ask_llm(
            plan.direct_prompt,
            timeout_seconds=(
                getattr(plan.profile, "llm_call_timeout_seconds", 120)
            ),
        )

    else:
        findings = []

        for chunk_number, (
            chunk_memories,
            chunk_selected,
        ) in enumerate(
            plan.chunks,
            start=1,
        ):
            chunk_sources = (
                _source_records(
                    chunk_memories,
                    chunk_selected,
                )
            )

            findings.append(
                ask_llm(
                    _chunk_evidence_prompt(
                        user_prompt,
                        chunk_sources,
                        chunk_number,
                        len(plan.chunks),
                    ),
                    timeout_seconds=(
                        getattr(plan.profile, "llm_call_timeout_seconds", 120)
                    ),
                )
            )

        source_labels = [
            _source_label(item)
            for item in plan.sources
        ]

        result = ask_llm(
            _chunk_synthesis_prompt(
                user_prompt,
                source_labels,
                findings,
                conversation_history,
            ),
            timeout_seconds=(
                getattr(plan.profile, "llm_call_timeout_seconds", 120)
            ),
        )

    result = (
        apply_synthesis_evidence_gate(
            result.strip(),
            plan.sources,
        )
    )

    if not return_execution_metadata:
        return result

    metadata = build_execution_metadata(
        plan.execution_plan,
        chunk_count=chunk_count,
        profile_name=(
            plan.profile.name
        ),
        resolved_profile_name=(
            getattr(plan.profile, "resolved_name", plan.profile.name)
        ),
        profile_reason=(
            getattr(plan.profile, "profile_reason", "")
        ),
        chunk_overlap_tokens=(
            getattr(plan.profile, "chunk_overlap_tokens", 0)
        ),
        context_size_tokens=(
            plan.profile
            .context_size_tokens
        ),
        context_reserve_tokens=(
            plan.profile
            .context_reserve_tokens
        ),
        model_name=(
            plan.profile.model_name
        ),
        model_parameter_billions=(
            plan.profile
            .model_parameter_billions
        ),
        model_budget_factor=(
            plan.profile
            .model_budget_factor
        ),
        hardware_label=(
            plan.profile
            .hardware_label
        ),
        hardware_performance_class=(
            plan.profile
            .hardware_performance_class
        ),
        hardware_budget_factor=(
            plan.profile
            .hardware_budget_factor
        ),
        calibration_factor=(
            plan.profile
            .calibration_factor
        ),
        calibration_sample_count=(
            plan.profile
            .calibration_sample_count
        ),
        calibration_median_elapsed_seconds=(
            plan.profile
            .calibration_median_elapsed_seconds
        ),
        llm_call_timeout_seconds=(
            getattr(plan.profile, "llm_call_timeout_seconds", 120)
        ),
        calibration_reason=(
            plan.profile
            .calibration_reason
        ),
    )

    metadata["direct_token_budget"] = (
        plan.direct_token_budget
    )
    metadata[
        "chunk_source_token_budget"
    ] = (
        plan.chunk_source_token_budget
    )
    metadata["synthesis_source_count"] = (
        len(plan.compact_memories)
    )
    metadata["synthesis_payload"] = (
        "compact"
    )

    return result, metadata
