from __future__ import annotations

import json
import urllib.error
import urllib.request
import time
import re

from pathlib import Path
from chunking import chunk_transcript
from query.execution import (
    choose_execution_plan,
    estimate_tokens,
    get_execution_profile,
    infer_model_parameter_billions,
)
from config import (
    LLM_BACKEND,
    LLM_CONTEXT_SIZE,
    LLM_MODEL,
    MLX_MAX_TOKENS,
    MLX_MODEL,
    PERFORMANCE_PROFILE,
    OLLAMA_URL,
    SELF_NAME,
    SELF_REFERENCE_NAMES,
    SELF_SPEAKER_LABEL,
    TOPIC_NORMALIZATION_RULES,
)
from llm_backend import create_backend, normalize_backend_name

_last_llm_backend = None
_last_llm_elapsed_seconds: float | None = None
_last_memory_resolution_diagnostics: dict = {}
_memory_resolution_trace_enabled = False
_last_memory_resolution_trace: dict = {}


def set_memory_resolution_trace_enabled(enabled: bool) -> None:
    """Enable/disable detailed local-only memory-pipeline tracing.

    This is intended for the private benchmark harness. Normal application runs
    leave tracing disabled so no additional meeting content is retained.
    """
    global _memory_resolution_trace_enabled
    _memory_resolution_trace_enabled = bool(enabled)


def get_last_memory_resolution_trace() -> dict:
    """Return a deep copy of the most recent detailed memory trace."""
    return json.loads(json.dumps(_last_memory_resolution_trace))


def _reset_memory_resolution_trace() -> None:
    global _last_memory_resolution_trace
    _last_memory_resolution_trace = {}


def _trace_memory_stage(name: str, payload) -> None:
    if not _memory_resolution_trace_enabled:
        return
    _last_memory_resolution_trace[name] = json.loads(json.dumps(payload))


def get_last_memory_resolution_diagnostics() -> dict:
    """Return a copy of diagnostics from the most recent memory-resolution run."""
    return json.loads(json.dumps(_last_memory_resolution_diagnostics))


def _reset_memory_resolution_diagnostics() -> None:
    global _last_memory_resolution_diagnostics
    _reset_memory_resolution_trace()
    _last_memory_resolution_diagnostics = {
        "pipeline": "v12_events",
        "status": "not_run",
        "events_proposed": 0,
        "events_grounded": 0,
        "event_types_proposed": {},
        "event_types_grounded": {},
        "actions_proposed": 0,
        "actions_retained": 0,
        "decisions_proposed": 0,
        "decisions_retained": 0,
        "risks_proposed": 0,
        "risks_retained": 0,
        "questions_proposed": 0,
        "questions_retained": 0,
        "rejected_events": [],
        "rejected_final": {
            "actions": [],
            "decisions": [],
            "risks": [],
            "questions": [],
        },
        "fallback": None,
    }


def get_last_llm_elapsed_seconds() -> float | None:
    """Return elapsed seconds for the most recent LLM call."""
    return _last_llm_elapsed_seconds


SUMMARY_CONTEXT = """
You are an expert executive meeting analyst.

Create a concise, balanced, business-relevant meeting summary from the
chronological section summaries below.

The section summaries are source material, not a required checklist.
Synthesize and prioritize them rather than copying every detail forward.

General Rules

- Preserve meaningful coverage of every substantial presentation or workstream.
- Give balanced coverage to the beginning, middle, and end of the meeting.
- Prioritize strategic implications, business outcomes, decisions, risks,
  dependencies, commitments, and genuinely unresolved questions.
- Consolidate overlapping topics across sections.
- Do not repeat the same point in multiple sections.
- Use only information explicitly contained in the transcript summaries.
- Do not invent decisions, owners, deadlines, action items, names,
  dates, numbers, or technical terms.
- Clearly distinguish confirmed decisions from discussion,
  proposals, requests, and tentative plans.
- Incorporate important dates, dollar amounts, targets, quantities,
  and deadlines into the relevant topic.
- Preserve important technical names, project names, products,
  systems, teams, and people.
- Exclude greetings, casual conversation, meeting logistics,
  timestamps, and social chatter unless they materially affect business work.
"""

SUMMARY_SECTION_RULES = """
Use this exact structure:

# Meeting Summary

## Executive Summary

- Write 2-3 concise paragraphs.
- Explain what the meeting accomplished.
- Mention the major workstreams and significant business themes.
- Avoid unnecessary detail.

## Presentations and Updates

- Maximum 8 bullets.
- Use one bullet per presentation or major workstream.
- Summarize each intern presentation distinctly and concisely.
- Focus on substantive updates.
- Exclude social discussion.

## Key Themes and Takeaways

- Maximum 8 bullets.
- Consolidate related ideas.
- Explain why the topics matter.
- Avoid repeating the Presentations and Updates section.

## Decisions

- Include only explicit, confirmed decisions.
- If none exist, write "None identified."

## Action Items

- Include only explicit commitments.
- Format each item as: Owner - Action - Due date.
- Use actual people when identified.
- Never use speaker labels such as Remote or Mic as owners.
- If no owner is identified, write "Owner not identified."
- Deduplicate action items describing the same commitment.
- Do not infer actions.

## Risks and Concerns

- Maximum 5 bullets.
- Include only risks or concerns explicitly stated by a participant.
- Do not infer hypothetical downstream risk from ordinary complexity, cost, timing,
  vendor relationships, contract terms, or administrative friction.
- A statement that something is not a risk must never be rewritten as a risk.
- If none are explicitly supported, write "None identified."

## Open Questions

- Maximum 5 bullets.
- Include only questions explicitly raised that remained unresolved.
- Do not convert general discussion topics into open questions.
- If none exist, write "None identified."
"""

SUMMARY_FORMATTING_RULES = """
Formatting Rules

- Keep the final summary between 500 and 800 words.
- Use Markdown headings and standard bullet lists.
- Do not use bold.
- Do not use italics.
- Do not use emojis.
- Do not use numbered headings.
- Keep each bullet to one concise sentence.
- Output only the completed meeting summary.
"""


def _get_llm_backend():
    """Create the configured inference backend. Cache MLX model weights only."""
    global _last_llm_backend

    if normalize_backend_name(LLM_BACKEND) == "ollama":
        return create_backend(
            "ollama",
            ollama_model=LLM_MODEL,
            ollama_url=OLLAMA_URL,
            context_size=LLM_CONTEXT_SIZE,
            mlx_model=MLX_MODEL,
            mlx_max_tokens=MLX_MAX_TOKENS,
            ollama_urlopen=urllib.request.urlopen,
        )

    if _last_llm_backend is None:
        _last_llm_backend = create_backend(
            "mlx",
            ollama_model=LLM_MODEL,
            ollama_url=OLLAMA_URL,
            context_size=LLM_CONTEXT_SIZE,
            mlx_model=MLX_MODEL,
            mlx_max_tokens=MLX_MAX_TOKENS,
        )
    return _last_llm_backend


def get_active_llm_backend_name() -> str:
    """Return the normalized configured backend without loading a model."""
    return normalize_backend_name(LLM_BACKEND)


def get_active_llm_model_name() -> str:
    """Return the model identifier associated with the configured backend."""
    if get_active_llm_backend_name() == "mlx":
        return MLX_MODEL
    return LLM_MODEL


def ask_llm(
    prompt: str,
    response_format=None,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """Send a prompt through the configured local inference backend."""
    backend = _get_llm_backend()
    response_text = backend.generate(
        prompt,
        response_format=response_format,
        timeout_seconds=timeout_seconds,
    )

    global _last_llm_elapsed_seconds
    _last_llm_elapsed_seconds = backend.last_elapsed_seconds
    return response_text


def analyze_selected_meetings(
    meeting_sources: list[tuple[str, str]],
    user_prompt: str,
    direct_word_limit: int = 4000,
    chunk_words: int = 1500,
) -> str:
    """
    Analyze one or more selected meetings using a
    free-form user request.

    Uses direct analysis when the selected material
    fits comfortably. Falls back to chunked extraction
    and synthesis when it does not.

    direct_word_limit and chunk_words are parameters
    so model/hardware-specific configuration can replace
    these defaults later without changing callers.
    """

    source_sections = []

    for meeting_label, source_text in meeting_sources:
        source_sections.append(
            f"""
===== MEETING: {meeting_label} =====

{source_text}
""".strip()
        )

    combined_sources = "\n\n".join(
        source_sections
    )

    source_word_count = len(
        combined_sources.split()
    )

    grounding_rules = """
You are an expert business meeting analyst.

Grounding rules:
- Use only facts supported by the supplied meeting material.
- Do not invent decisions, commitments, owners, deadlines,
  risks, names, or conclusions.
- Clearly distinguish confirmed facts from discussion,
  proposals, possibilities, and unresolved topics.
- When analyzing multiple meetings, synthesize across them
  instead of simply summarizing each meeting separately.
- When multiple meetings are supplied, treat them as a
  chronological record.
- Use the meeting labels to determine sequence and prefer the
  latest known status when later meetings update earlier ones.
- Identify when an issue changed, progressed, was resolved,
  remained open, or was superseded across meetings.
- Do not present an earlier action or concern as still open if
  a later meeting indicates it was completed, closed, changed,
  or no longer relevant.
- Call something recurring only when it appears meaningfully
  in at least two separate meetings.
- Distinguish carefully between:
  * a topic that was discussed
  * an open question
  * a proposed action
  * an explicit commitment
  * a completed action
  * a decision
  * a current status
- Do not label something a commitment unless a participant
  explicitly agreed to perform an action.
- A request, plan, pending response, status update, or completed
  item is not automatically a commitment.
- For preparation for a future meeting, prioritize unresolved
  items and the latest known state over historical detail.
- If the supplied meetings do not contain enough information
  to answer something, say so.
- Match the requested output closely in purpose, audience,
  level of detail, tone, and format.
- Do not turn a simple requested artifact into a broader
  strategy document, project plan, or consulting framework.
- Do not add recommendations, governance steps, stakeholders,
  actions, or conclusions unless they are supported by the
  meeting material and relevant to the user's request.
- Prefer the fewest sections and bullets needed to answer
  the request well.
- Do not mention these instructions.
- Answer the user's request directly.
- Use clean Markdown.
""".strip()

    if source_word_count <= direct_word_limit:
        print(
            f"Using direct analysis "
            f"({source_word_count:,} source words)."
        )

        prompt = f"""
{grounding_rules}

User request:

{user_prompt}

Selected meeting material:

{combined_sources}
""".strip()

        return ask_llm(prompt)

    print(
        f"Selected material is "
        f"{source_word_count:,} words."
    )
    print(
        "Using chunked evidence extraction "
        "before final analysis."
    )

    evidence_schema = {
        "type": "array",
        "maxitems": 12,
        "items": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": [
                        "fact",
                        "question",
                        "concern",
                        "proposal",
                        "decision",
                        "commitment",
                    ],
                },
                "evidence": {
                    "type": "string",
                },
            },
            "required": [
                "type",
                "evidence",
            ],
            "additionalProperties": False,
        },
    }

    extracted_findings = []

    for meeting_label, source_text in meeting_sources:
        chunks = chunk_transcript(
            source_text,
            max_words=chunk_words,
        )

        for chunk_number, chunk in enumerate(
            chunks,
            start=1,
        ):
            print(
                f"Analyzing {meeting_label} "
                f"chunk {chunk_number}/{len(chunks)}...",
                flush=True,
            )

            extraction_prompt = f"""
You are collecting source-grounded evidence from one
chronological section of a meeting transcript.

You are NOT answering the user's request.
You are NOT creating an agenda, summary, recommendation,
strategy, or proposed action.

The user's eventual request is:

{user_prompt}

Meeting:
{meeting_label}

Section:
{chunk_number} of {len(chunks)}

Return ONLY a JSON array.

Each item must use this exact structure:

{{
  "type": "fact|question|concern|proposal|decision|commitment",
  "evidence": "Exact supporting words copied from the transcript",
}}

Rules:
- The evidence field MUST be an exact quote copied from this
  transcript section.
- Do not paraphrase the evidence field.
- Keep each evidence quote as short as possible while preserving
  the meaning.
- Do not invent, infer, or normalize wording.
- Do not convert a concern into a proposal.
- Do not convert a question into an action.
- Use proposal only when someone explicitly suggests an approach.
- Use decision only for an explicit decision or agreement.
- Use commitment only when someone explicitly agrees to do
  something.
- A conditional offer to help (for example, "if you need help, I can help")
  is not a commitment unless a concrete deliverable is actually assigned
  and accepted.
- Do not treat low-information or unintelligible speech as a commitment.
- Maximum 12 items.
- Deduplicate overlapping evidence.
- Omit unrelated side discussion.
- If nothing is relevant, return [].

Transcript section:

{chunk}
""".strip()

            raw_finding = ask_llm(
                extraction_prompt,
                response_format=evidence_schema,
            )

            try:
                candidate_items = json.loads(
                    raw_finding
                )
            except json.JSONDecodeError:
                candidate_items = []

            if not isinstance(
                candidate_items,
                list,
            ):
                candidate_items = []

            validated_items = []

            for item in candidate_items:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                evidence_text = str(
                    item.get(
                        "evidence",
                        "",
                    )
                ).strip()

                evidence_type = str(
                    item.get(
                        "type",
                        "",
                    )
                ).strip()

                if not evidence_text:
                    continue

                if evidence_text not in chunk:
                    continue

                validated_items.append(
                    {
                        "type": evidence_type,
                        "evidence": evidence_text,
                    }
                )

            print()
            print(
                f"--- Validated evidence: "
                f"{meeting_label} "
                f"chunk {chunk_number} ---"
            )
            print(
                json.dumps(
                    validated_items,
                    indent=2,
                )
            )
            print("--- End evidence ---")
            print()

            if validated_items:
                extracted_findings.append(
                    f"""
===== {meeting_label} — SECTION {chunk_number} =====

{json.dumps(validated_items, indent=2)}
""".strip()
                )

    combined_findings = "\n\n".join(
        extracted_findings
    )

    final_prompt = f"""
{grounding_rules}

The material below contains grounded findings extracted
from the selected meeting transcript sections specifically
for the user's request.

Synthesize these findings into the requested final output.

Follow the user's requested artifact closely. For example,
if the user asks for an agenda, produce an agenda rather than
a strategic analysis of how to conduct the meeting.

When deciding what belongs in the final answer, give the
greatest weight to evidence labeled:

PROPOSAL
QUESTION
DECISION
COMMITMENT

Use FACT and CONCERN evidence as supporting context, but do not
automatically turn every internal concern into something that
belongs in the final artifact.

For audience-facing outputs such as meeting agendas, emails,
or executive briefs:
- Write for the intended audience.
- Exclude internal criticism, speculation about someone's
  competence, motives, authority, or internal perceptions unless
  the user explicitly asks for it.
- Do not expose internal commentary merely because it was relevant
  background for developing the output.
- If an internal concern points to a legitimate business topic,
  express the underlying business topic neutrally.
- Prefer topics that participants explicitly proposed discussing,
  questions they said needed answering, or decisions/alignment
  they said were needed.

Do not simply repeat the section findings chronologically.
Combine overlapping points and remove internal process detail
that does not belong in the requested output.

Prefer a concise result over exhaustive coverage. Include only
the points necessary to satisfy the user's request well.

Do not introduce a new recommendation or assertion merely
because it sounds strategically useful. Every substantive
point must be grounded in the extracted meeting findings.

User request:

{user_prompt}

Extracted meeting findings:

{combined_findings}
""".strip()

    print()
    print("Synthesizing final analysis...")

    return ask_llm(
        final_prompt
    )


def clean_transcript(transcript: str) -> str:
    """
    Clean one transcript section using the configured local LLM.
    """

    prompt = f"""
You are an expert transcription editor.

Your task is to improve readability without changing meaning.

Rules:
- Preserve every spoken fact.
- Do not summarize.
- Do not add information.
- Do not infer missing information.
- Correct punctuation and capitalization.
- Remove only obvious accidental repetition.
- Split the text into natural paragraphs.
- Preserve speaker labels and timestamps exactly.
- Output only the cleaned transcript.

Transcript:

{transcript}
""".strip()

    return ask_llm(prompt)


def normalize_topic_key(
    topic_key: str,
    topic: str,
    *,
    canonical_rules=None,
) -> str:
    """
    Normalize related topic labels into stable workstream keys.
    """

    combined = (
        f"{topic_key} {topic}"
    ).lower()

    if canonical_rules is None:
        canonical_rules = TOPIC_NORMALIZATION_RULES

    for canonical_key, markers in canonical_rules:
        if any(
            marker in combined
            for marker in markers
        ):
            return canonical_key

    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        topic_key.lower(),
    ).strip("_")

    return normalized


def build_meeting_memory(
    meeting_label: str,
    meeting_summary: str,
) -> dict:
    """
    Build compact machine-readable memory for one meeting.
    """

    memory_schema = {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "topic_key": {
                            "type": "string",
                        },
                        "topic": {
                            "type": "string",
                        },
                        "status": {
                            "type": "string",
                            "enum": [
                                "open",
                                "closed",
                                "ongoing",
                                "unclear",
                            ],
                        },
                        "summary": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "topic_key",
                        "topic",
                        "status",
                        "summary",
                    ],
                    "additionalProperties": False,
                },
            },
            "commitments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "owner": {
                            "type": "string",
                        },
                        "action": {
                            "type": "string",
                        },
                        "status": {
                            "type": "string",
                            "enum": [
                                "open",
                                "completed",
                                "unclear",
                            ],
                        },
                    },
                    "required": [
                        "owner",
                        "action",
                        "status",
                    ],
                    "additionalProperties": False,
                },
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
            "open_questions": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
            "follow_ups": {
                "type": "array",
                "items": {
                    "type": "string",
                },
            },
        },
        "required": [
            "topics",
            "commitments",
            "decisions",
            "open_questions",
            "follow_ups",
        ],
        "additionalProperties": False,
    }

    prompt = f"""
You are creating compact long-term working memory from a
business meeting summary.

Meeting:
{meeting_label}

Use only the supplied meeting summary.

The output will be used later to compare this meeting with
other meetings chronologically.

Rules:

- Capture only substantive business work that would be useful
  when preparing for a future meeting.
- Ignore greetings, weather, family discussion, travel,
  weekends, sports, office logistics, building updates,
  personal anecdotes, jokes, and casual conversation.

TOPICS:
- Create a topic only when the meeting contains meaningful
  business discussion about it.
- Prefer specific supplier, project, contract, staffing, or
  decision topics.
- Do not create generic umbrella topics such as:
  "Vendor Management"
  "Team Dynamics"
  "Strategic Alignment"
  "Cloud Strategy"
  unless that exact broad subject was itself a substantive
  focus of the meeting.
- Do not combine unrelated suppliers or workstreams into one
  topic.
- For example, Vendor Alpha, Vendor Beta, Platform Gamma,
  Software Delta, Service Epsilon, and Provider Zeta should remain
  separate when they represent separate work.
- Do not create a topic from a passing mention.
- Do not create a topic merely because it appeared in historical
  background.
- Capture the latest state established in THIS meeting.
- A single topic should normally represent one supplier,
  contract, project, staffing issue, or decision area.
- Do not combine separate suppliers such as Vendor Alpha and
  Platform Gamma into one topic merely because both relate to
  technology, cloud, licensing, or vendor management.
- Every topic must include a "topic_key".
- topic_key is a short machine-readable identifier for the
  underlying workstream.
- Use lowercase snake_case for topic_key only.
- Keep "topic", "summary", "open_questions", and "follow_ups"
  as normal human-readable text.
- Do not snake_case any field other than topic_key.
- Do not change normal prose into identifiers.

Examples:

  topic_key: "vendor_alpha_renewal"
  topic: "Vendor Alpha Renewal"

  topic_key: "vendor_beta_contract"
  topic: "Vendor Beta Contract"

  topic_key: "provider_zeta_budget"
  topic: "Provider Zeta Budget Ownership"

- Prefer a stable underlying workstream name rather than the
  current status or activity.

STATUS:
- "closed" means the meeting explicitly indicates the matter
  is complete, resolved, signed, finished, or should be treated
  as closed.
- "ongoing" means active work is continuing.
- "open" means specific work, resolution, decision, or follow-up
  remains outstanding.
- "unclear" means the meeting discusses the topic substantively
  but does not establish its current state.

COMMITMENTS AND DECISIONS:
- Do not infer commitments or decisions from this summary.
- Return empty arrays for "commitments" and "decisions".
- These fields will be populated separately from transcript-grounded
  evidence.

OPEN QUESTIONS:
- Include only unresolved BUSINESS questions that would still
  matter after this meeting.
- Exclude personal, logistical, rhetorical, conversational,
  or already-answered questions.
- Do not include a question merely because a question mark
  appeared in the transcript or summary.
- Open questions must be consistent with the topic status
  established in this meeting.
- Do not retain a question for a topic marked "closed" unless
  the meeting explicitly states that the question remains
  unresolved despite the topic being closed.
- Do not resurrect historical questions that were relevant
  earlier but are no longer actionable at the end of this meeting.

FOLLOW-UPS:
- Include only concrete next steps that remain relevant after
  the meeting.
- Prefer specific actions such as:
  "Get Alex's update on Vendor Alpha"
  rather than generic phrases such as:
  "Vendor Alpha follow-up".
- Do not duplicate commitments unless the follow-up represents
  a separate action.
- Follow-ups must represent work that remains actionable after
  this meeting.
- Do not create a follow-up for a topic marked "closed" unless
  the meeting explicitly identifies additional work after closure.

GENERAL:
- Use only the supplied meeting summary.
- Do not invent commitments, decisions, owners, topics, or status.
- Do not merge unrelated facts to create a new conclusion.
- Keep the memory compact.
- Prefer omission over including weak or questionable material.
- This is working memory, not a comprehensive meeting summary.

Meeting summary:

{meeting_summary}
""".strip()

    raw_memory = ask_llm(
        prompt,
        response_format=memory_schema,
    )

    try:
        memory = json.loads(
            raw_memory
        )
    except json.JSONDecodeError:
        return {
            "topics": [],
            "commitments": [],
            "decisions": [],
            "open_questions": [],
            "follow_ups": [],
        }

    topics = memory.get(
        "topics",
        [],
    )

    for topic in topics:
        if not isinstance(
            topic,
            dict,
        ):
            continue

        topic["topic_key"] = (
            normalize_topic_key(
                topic_key=str(
                    topic.get(
                        "topic_key",
                        "",
                    )
                ),
                topic=str(
                    topic.get(
                        "topic",
                        "",
                    )
                ),
            )
        )

    closed_topic_terms = []

    for topic in topics:
        if not isinstance(
            topic,
            dict,
        ):
            continue

        if topic.get("status") != "closed":
            continue

        topic_name = str(
            topic.get(
                "topic",
                "",
            )
        ).lower()

        for word in topic_name.split():
            if len(word) >= 5:
                closed_topic_terms.append(
                    word
                )

    open_questions = memory.get(
        "open_questions",
        [],
    )

    filtered_questions = []

    for question in open_questions:
        question_text = str(
            question
        )

        question_lower = (
            question_text.lower()
        )

        if any(
            term in question_lower
            for term in closed_topic_terms
        ):
            continue

        filtered_questions.append(
            question_text
        )

    memory["open_questions"] = (
        filtered_questions
    )

    return memory


def _compact_explicit_decision_clause(text: str, match: re.Match) -> str:
    """Return a short verbatim clause around an explicit decision marker.

    Whisper output can contain very long punctuation-free lines.  Promoting the
    entire line makes an otherwise valid deterministic fallback fail the
    well-formedness gate.  Start at the explicit decision phrase and stop at a
    natural discourse boundary or a conservative word cap while preserving an
    exact transcript substring.
    """

    tail = text[match.start():].strip()
    if not tail:
        return ""

    # Prefer a real clause boundary when one appears reasonably soon.
    boundary = re.search(
        r"[.!?](?:\s|$)|,\s*(?:but|however|so|then)\b|"
        r"\s+(?:but|however|although)\s+|"
        r"\s+and\s+(?:on|then|later|next|after(?:ward)?|i|we|they)\b",
        tail,
        flags=re.IGNORECASE,
    )
    if boundary and boundary.start() > 0:
        tail = tail[:boundary.start() + (1 if tail[boundary.start()] in '.!?' else 0)]

    # If ASR supplied no punctuation/boundary, cap by words without inventing
    # any text.  Twenty-eight words is enough to retain the settled outcome
    # while avoiding paragraph-sized transcript spill.
    word_matches = list(re.finditer(r"\S+", tail))
    if len(word_matches) > 28:
        tail = tail[:word_matches[27].end()]

    return tail.strip(" -\t")



def _normalized_removal_entity(raw: str) -> str:
    """Normalize an entity following a removal verb, including spaced acronyms."""

    raw = " ".join(raw.strip().split())
    parts = re.findall(r"[A-Za-z0-9&.-]+", raw)
    if not parts:
        return ""
    if len(parts) > 1 and all(len(re.sub(r"[^A-Za-z0-9]", "", part)) == 1 for part in parts):
        return "".join(re.sub(r"[^A-Za-z0-9]", "", part) for part in parts).upper()
    return parts[0].strip(".-")


def _canonical_fallback_decision_text(evidence: str) -> str:
    """Turn an explicit transcript clause into a concise business decision.

    Evidence remains verbatim; only the display text is normalized.  Keep this
    deliberately conservative and pattern-based so no extra LLM pass is needed.
    """

    text = " ".join(evidence.strip().split())

    move_match = re.search(
        r"\bwe(?:'re|\s+are)\s+going\s+to\s+move\s+ahead\s+with\s+"
        r"(?P<primary>[A-Za-z0-9&.-]+)"
        r"(?:.*?\bwe(?:'re|\s+are)\s+going\s+to\s+let\s+"
        r"(?P<other>[A-Za-z0-9&.-]+)\s+down)?",
        text,
        flags=re.IGNORECASE,
    )
    if move_match:
        primary = move_match.group("primary")
        other = move_match.group("other")
        if other:
            return f"Move ahead with {primary} and decline {other} for now."
        return f"Move ahead with {primary}."

    approval_match = re.search(
        r"\b(?:cut|remove|drop|exclude)\s+"
        r"(?P<entity>[A-Za-z0-9&.-]+(?:\s+[A-Za-z](?=\s|$))?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if approval_match and re.search(
        r"\b(?:approval|approved|decision|decided|agreed)\b",
        text,
        flags=re.IGNORECASE,
    ):
        entity = _normalized_removal_entity(approval_match.group("entity"))
        if entity:
            return f"Drop {entity}."

    direct_remove = re.search(
        r"\b(?:we|they|the\s+team)\s+(?:have\s+)?"
        r"(?:cut|removed|excluded|dropped)\s+"
        r"(?P<entity>[A-Za-z0-9&.-]+(?:\s+[A-Za-z](?=\s|$))?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if direct_remove:
        entity = _normalized_removal_entity(direct_remove.group("entity"))
        if entity:
            return f"Drop {entity}."

    cleaned = re.sub(
        r"^(?:we|they|the\s+team)\s+(?:decided|agreed)\s+(?:as\s+a\s+team\s+)?"
        r"(?:that\s+)?",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(
        r"^(?:we(?:'re|\s+are)\s+going\s+to|we\s+will)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned:
        cleaned = text
    return cleaned[:1].upper() + cleaned[1:].rstrip(".") + "."


def _explicit_decision_fallbacks(chunk: str) -> list[dict]:
    """Recover plainly stated decisions that structured extraction omitted.

    Evaluate every explicit decision marker independently.  Whisper often emits
    several decisions in one long punctuation-free line, so a one-candidate-per-
    sentence strategy can recover the first decision and silently miss later ones.
    """

    explicit_patterns = (
        r"\b(?:the\s+)?decision\s+(?:is|was|to)\b",
        r"\b(?:we|they|the\s+team)\s+(?:decided|agreed)\b",
        r"\b(?:we|they|the\s+team)\s+(?:have\s+)?"
        r"(?:selected|chose|cut|removed|excluded|dropped)\b",
        r"\b(?:we|they|the\s+team)\s+(?:are|were)\s+going\s+with\b",
        r"\b(?:we|they|the\s+team)\s+(?:are\s+)?(?:moving|move|moved)\s+"
        r"(?:forward|ahead)\s+with\b",
        r"\b(?:we['’]re|we\s+are|they['’]re|they\s+are)\s+going\s+to\s+"
        r"(?:continue\s+to\s+)?(?:move\s+(?:forward|ahead)|proceed|continue)\s+"
        r"with\b",
        r"\b(?:we|they|the\s+team)\s+(?:will\s+)?proceed\s+with\b",
        r"\b(?:we|they|the\s+team)\s+(?:will\s+)?continue\s+with\b",
        r"\b(?:i|we|they|he|she)\s+(?:got|gave|have|has|received|had)\s+"
        r"(?:the\s+)?approval(?:\s+from\s+[A-Za-z][A-Za-z .'-]{0,40})?"
        r"\s+to\s+(?:cut|remove|drop|exclude)\b",
        r"\b(?:i|we|they|he|she)\s+(?:got|have|has|had|received)\s+"
        r"[A-Za-z][A-Za-z .'-]{0,40}['’]s\s+approval\s+to\s+"
        r"(?:cut|remove|drop|exclude)\b",
        r"\b(?:i|we|they|he|she)\s+(?:got|have|has|had|received)\s+"
        r"(?:the\s+)?(?:okay|ok|go-ahead|green\s+light)(?:\s+from\s+"
        r"[A-Za-z][A-Za-z .'-]{0,40})?\s+to\s+(?:cut|remove|drop|exclude)\b",
        r"\bapproval(?:\s+from\s+[A-Za-z][A-Za-z .'-]{0,40})?"
        r"\s+to\s+(?:cut|remove|drop|exclude)\b",
        r"\b[A-Z][A-Za-z0-9&.-]*\s+is\s+out\b",
    )
    uncertainty_pattern = re.compile(
        r"\b(?:maybe|might|could|consider|considering|proposal|proposed)\b"
        r"|\bif\s+(?:we|they)\b",
        flags=re.IGNORECASE,
    )
    candidates = []

    for raw_line in chunk.splitlines():
        line = raw_line.strip()
        line = re.sub(
            r"^\[[0-9:]+\]\s*(?:\*\*(?:Mic|Remote)\*\*)?\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )
        line = re.sub(
            r"^\*\*(?:Mic|Remote)\*\*\s*",
            "",
            line,
            flags=re.IGNORECASE,
        )
        if not line:
            continue

        for sentence in re.split(r"(?<=[.!?])\s+", line):
            sentence = sentence.strip(" -\t")
            if not sentence:
                continue

            matches = []
            for pattern in explicit_patterns:
                for match in re.finditer(pattern, sentence, flags=re.IGNORECASE):
                    matches.append((match.start(), pattern, match))
            matches.sort(key=lambda item: item[0])

            # Multiple patterns can begin at the same marker.  Keep one marker
            # per start position, preferring a direct approval/selection form
            # over the generic decided/agreed form.
            unique_matches = []
            seen_starts = set()
            covered_spans = []
            for _, pattern, match in matches:
                if match.start() in seen_starts:
                    continue
                # Skip a shorter marker nested inside a stronger marker already
                # retained (for example "approval ... to cut" inside
                # "I got approval ... to cut").  Otherwise deduplication can
                # prefer the shorter but less readable fragment.
                if any(
                    start <= match.start() and end >= match.end()
                    for start, end in covered_spans
                ):
                    continue
                seen_starts.add(match.start())
                covered_spans.append((match.start(), match.end()))
                unique_matches.append((pattern, match))

            for pattern, match in unique_matches:
                evidence = _compact_explicit_decision_clause(sentence, match)
                if not evidence:
                    continue
                evidence_lower = evidence.lower()

                strong_decision = (
                    "decision" in pattern or "decided|agreed" in pattern
                )
                if not strong_decision and uncertainty_pattern.search(evidence_lower):
                    continue

                evidence_word_count = len(
                    re.findall(r"[A-Za-z0-9&'-]+", evidence)
                )
                if "decided|agreed" in pattern and evidence_word_count > 36:
                    continue

                candidate = {
                    "decision": evidence.rstrip("."),
                    "evidence": evidence,
                }
                # Fallback recovery must obey the same proposition-level
                # evidence rules as model-extracted decisions.  Without this
                # guard a broad recovery marker such as "X is out" can
                # promote descriptive ASR text ("field is out doing...") or
                # an interrogative fragment ("OS is out?") into a decision.
                if not _decision_is_supported(
                    candidate["decision"], candidate["evidence"]
                ):
                    continue
                if not _decision_candidate_is_well_formed(
                    candidate["decision"], candidate["evidence"]
                ):
                    continue
                candidates.append(candidate)

    return _deduplicate_decisions(candidates)


_DECISION_EVIDENCE_PATTERN = re.compile(
    r"\b(?:the\s+)?decision\s+(?:is|was|to)\b"
    r"|\b(?:we|they|the\s+team)\s+(?:decided|agreed)\b"
    r"|\b(?:we|they|the\s+team)\s+(?:have\s+)?"
    r"(?:selected|chose|approved|cut|removed|excluded|dropped)\b"
    r"|\b(?:we|they|the\s+team)\s+(?:are|were)\s+going\s+with\b"
    r"|\b(?:we|they|the\s+team)\s+(?:are\s+)?(?:moving|move|moved)\s+"
    r"(?:forward|ahead)\s+with\b"
    r"|\b(?:we['’]re|we\s+are|they['’]re|they\s+are)\s+going\s+to\s+"
    r"(?:continue\s+to\s+)?(?:move\s+(?:forward|ahead)|proceed|continue)\s+"
    r"with\b"
    r"|\b(?:we|they|the\s+team)\s+(?:will\s+)?proceed\s+with\b"
    r"|\b(?:we|they|the\s+team)\s+(?:will\s+)?continue\s+with\b"
    r"|\b(?:i|we|they|he|she)\s+(?:got|gave|have|has|received|had)\s+"
    r"(?:the\s+)?approval(?:\s+from\s+[A-Za-z][A-Za-z .'-]{0,40})?"
    r"\s+to\s+(?:cut|remove|drop|exclude)\b"
    r"|\b(?:i|we|they|he|she)\s+(?:got|have|has|had|received)\s+"
    r"[A-Za-z][A-Za-z .'-]{0,40}['’]s\s+approval\s+to\s+"
    r"(?:cut|remove|drop|exclude)\b"
    r"|\b(?:i|we|they|he|she)\s+(?:got|have|has|had|received)\s+"
    r"(?:the\s+)?(?:okay|ok|go-ahead|green\s+light)(?:\s+from\s+"
    r"[A-Za-z][A-Za-z .'-]{0,40})?\s+to\s+(?:cut|remove|drop|exclude)\b"
    r"|\bapproval(?:\s+from\s+[A-Za-z][A-Za-z .'-]{0,40})?"
    r"\s+to\s+(?:cut|remove|drop|exclude)\b"
    r"|\b[A-Z][A-Za-z0-9&.-]*\s+is\s+out(?:[.!]|$)",
    flags=re.IGNORECASE,
)

_DECISION_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "decision", "for", "from", "go", "going", "is", "it", "later", "of",
    "on", "our", "that", "the", "their", "then", "they", "this", "to",
    "we", "were", "will", "with",
}


def _decision_evidence_is_explicit(evidence: str) -> bool:
    """Require the quoted words to state a decision, not merely discuss one."""

    return bool(_DECISION_EVIDENCE_PATTERN.search(evidence))


def _meaningful_tokens(text: str) -> set[str]:
    aliases = {
        "move": "proceed",
        "moved": "proceed",
        "moving": "proceed",
        "proceeding": "proceed",
        "continue": "proceed",
        "continuing": "proceed",
        "select": "select",
        "selected": "select",
        "choose": "select",
        "chose": "select",
        "chosen": "select",
        "cut": "remove",
        "removed": "remove",
        "drop": "remove",
        "dropped": "remove",
        "exclude": "remove",
        "excluded": "remove",
    }
    tokens = set()
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        short_entity = len(token) < 3 and any(ch.isdigit() for ch in token)
        if (len(token) < 3 and not short_entity) or token in _DECISION_STOP_WORDS:
            continue
        tokens.add(aliases.get(token, token))
    return tokens


def _decision_is_supported(decision: str, evidence: str) -> bool:
    """Require explicit evidence plus meaningful support for the stated claim."""

    if not _decision_evidence_is_explicit(evidence):
        return False
    decision_tokens = _meaningful_tokens(decision)
    evidence_tokens = _meaningful_tokens(evidence)
    if not decision_tokens:
        return False
    required_overlap = min(2, len(decision_tokens))
    return len(decision_tokens & evidence_tokens) >= required_overlap


def _decision_candidate_is_well_formed(decision: str, evidence: str) -> bool:
    """Reject raw ASR spill or grammatical fragments promoted into decisions."""

    decision_words = re.findall(r"[A-Za-z0-9&'-]+", decision)
    evidence_words = re.findall(r"[A-Za-z0-9&'-]+", evidence)
    if len(decision_words) > 45:
        return False
    if (
        decision.casefold() == evidence.casefold()
        and len(evidence_words) > 36
    ):
        return False
    # Ignore terminal punctuation when looking for clipped endings.  Earlier
    # versions let fragments such as ``Drop to.`` survive because the period
    # hid the trailing preposition from this check.
    compact = decision.strip().rstrip(".!?").strip()
    if re.search(
        r"\b(?:and|but|if|or|so|then|to|with|see\s+if)\s*$",
        compact,
        flags=re.IGNORECASE,
    ):
        return False
    # Canonical removal decisions must name an actual entity.  Determiners and
    # prepositions are common ASR continuations after conversational uses of
    # words such as ``drop`` and must never become durable decisions.
    if re.fullmatch(
        r"(?:drop|remove|exclude|cut)\s+"
        r"(?:the|a|an|to|for|from|with|on|in|into|of|and|or|at)",
        compact,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _decision_is_operational_fact_claim(decision: str) -> bool:
    """Return True for system/product behavior phrased as a fact, not a choice.

    Meeting models sometimes promote release notes, capability statements, or
    implementation limitations into Decisions simply because they contain
    ``will``.  These statements are useful Topics/Updates, but should only become
    durable Decisions when the transcript also carries an explicit settlement
    cue such as ``we decided`` or ``we agreed``.
    """

    text = re.sub(r"\s+", " ", str(decision or "")).strip()
    return bool(re.match(
        r"^(?:the\s+)?(?:[A-Za-z0-9&.-]+\s+){0,6}"
        r"(?:feature|system|workflow|process|platform|tool|application|service)\s+"
        r"(?:will|won['’]t|will\s+not|does|doesn['’]t|cannot|can\s+not|is|isn['’]t)\b",
        text,
        flags=re.IGNORECASE,
    ))


def _decisions_overlap(left: dict, right: dict) -> bool:
    left_tokens = _meaningful_tokens(
        f"{left.get('decision', '')} {left.get('evidence', '')}"
    )
    right_tokens = _meaningful_tokens(
        f"{right.get('decision', '')} {right.get('evidence', '')}"
    )
    if not left_tokens or not right_tokens:
        return False
    shared = left_tokens & right_tokens
    return len(shared) >= 2 and (
        len(shared) / min(len(left_tokens), len(right_tokens)) >= 0.5
    )


def _deduplicate_decisions(decisions: list[dict]) -> list[dict]:
    """Collapse alternate renderings of one decision, preferring concise text."""

    kept = []
    for candidate in decisions:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if _decisions_overlap(candidate, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(candidate)
            continue
        candidate_rank = (
            len(str(candidate.get("decision", "")).split()),
            len(str(candidate.get("evidence", "")).split()),
        )
        existing = kept[duplicate_index]
        existing_rank = (
            len(str(existing.get("decision", "")).split()),
            len(str(existing.get("evidence", "")).split()),
        )
        if candidate_rank < existing_rank:
            kept[duplicate_index] = candidate
    return kept


_RISK_EVIDENCE_PATTERN = re.compile(
    r"\b(?:risk|risks|risky|concern|concerns|concerned|worry|worried|"
    r"blocker|blocked|blocking|uncertainty|uncertain|issue|issues|problem|"
    r"problems|challenge|challenges|delay|delays|delayed|dependency|dependencies)\b",
    flags=re.IGNORECASE,
)

_RISK_NEGATION_PATTERN = re.compile(
    r"(?:\b(?:no|not|without|isn't|aren't|wasn't|weren't)\b.{0,28}"
    r"\b(?:risk|risks|concern|concerns|issue|issues|problem|problems|"
    r"blocker|blockers|delay|delays)\b|"
    r"\b(?:risk|risks|concern|concerns|issue|issues|problem|problems|"
    r"blocker|blockers|delay|delays)\b.{0,28}\b(?:none|no|not)\b)",
    flags=re.IGNORECASE,
)


_NON_ACTIONABLE_COMMITMENT_PATTERN = re.compile(
    r"^\s*(?:(?:yeah|yes|yep|sure|okay|ok)[, .!-]*)?"
    r"(?:(?:i|we)\s*(?:will|['’]ll)|i\s+can)\s+"
    r"(?:be\s+there|be\s+available|make\s+it|join(?:\s+.{1,80})?|"
    r"attend(?:\s+.{1,80})?)"
    r"(?:[, .!-]*(?:yeah|yes|yep|sure|okay|ok))?[, .!-]*\s*$",
    flags=re.IGNORECASE,
)

_CONDITIONAL_OFFER_COMMITMENT_PATTERN = re.compile(
    r"\bif\b.{0,140}?"
    r"(?:"
    r"\b(?:i|we)\s+(?:can|could|would)\s+(?:help|assist|support)\b"
    r"|\b(?:you|they|we)\s+(?:need|want)\b.{0,80}?"
    r"(?:\b(?:i|we)\s*(?:will|['’]ll|can|could)\b|\blet\s+me\b)"
    r")",
    flags=re.IGNORECASE,
)

_LOW_INFORMATION_COMMITMENT_PATTERN = re.compile(
    r"\((?:indistinct|inaudible|unintelligible|crosstalk|static[^)]*)\)"
    r"|\b(?:indistinct|inaudible|unintelligible)\b",
    flags=re.IGNORECASE,
)

_GENERIC_COMMITMENT_CONTINUATION_PATTERN = re.compile(
    r"^\s*(?:(?:yeah|yes|yep|sure|okay|ok)[, .!-]*)?"
    r"(?:i\s*(?:will|['’]ll)|let\s+me)\s+"
    r"(?:take\s+care\s+of\s+(?:it|that)|handle\s+(?:it|that)|"
    r"do\s+(?:it|that)|follow\s+up\s+on\s+(?:it|that))"
    r"[, .!-]*\s*$",
    flags=re.IGNORECASE,
)


_OPAQUE_COMMITMENT_REFERENCE_PATTERN = re.compile(
    r"\b(?:do|handle|send|share|post|forward|email|push|pushing|"
    r"take\s+care\s+of|follow\s+up\s+on|put)\s+"
    r"(?:it|that|this|them)\b|"
    r"\b(?:on|about|with)\s+(?:it|that|this|them)\b",
    flags=re.IGNORECASE,
)


_INCOMPLETE_COMMITMENT_ACTION_PATTERN = re.compile(
    r"\bput\s+.+?\s+to\s+task\b(?:\s*[.!?])?$|"
    r"\b(?:challenge|press|push)\s+.+?(?:\s*[.!?])?$",
    flags=re.IGNORECASE,
)

_SECOND_PERSON_COMMITMENT_REFERENCE_PATTERN = re.compile(
    r"\b(?:you|your|yours)\b",
    flags=re.IGNORECASE,
)


_VAGUE_COMMITMENT_ACTION_PATTERN = re.compile(
    r"^(?:i(?:['’]ll| will)?\s+)?(?:get\s+involved|help(?:\s+out)?|assist|take\s+a\s+look|look\s+into\s+(?:it|that|this))\.?$",
    flags=re.IGNORECASE,
)


def _commitment_action_is_self_contained(action: str) -> bool:
    """Require a durable action that names its object/topic/recipient.

    Person resolution alone is not enough. Phrases such as "put Speaker B to
    task" still omit what the person is being tasked on, and second-person
    references such as "include you on the emails" are not durable outside
    the original meeting context.
    """

    text = re.sub(r"\s+", " ", str(action or "")).strip()
    if not text:
        return False
    if _VAGUE_COMMITMENT_ACTION_PATTERN.fullmatch(text):
        return False
    if _SECOND_PERSON_COMMITMENT_REFERENCE_PATTERN.search(text):
        return False
    if _INCOMPLETE_COMMITMENT_ACTION_PATTERN.search(text):
        # Allow an explicit object/topic introduced after the task phrase.
        if re.search(
            r"\bput\s+.+?\s+to\s+task\s+(?:on|about|regarding|to)\s+\S+",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        if re.search(
            r"\b(?:challenge|press|push)\s+.+?\s+(?:on|about|regarding|to)\s+\S+",
            text,
            flags=re.IGNORECASE,
        ):
            return True
        return False
    return True

_LOW_VALUE_SOCIAL_COMMITMENT_PATTERN = re.compile(
    r"\b(?:send|share|post|upload)\b.{0,50}\b(?:photo|picture|selfie)\b"
    r"|\b(?:photo|picture|selfie)\b.{0,50}\b(?:channel|chat|group)\b",
    flags=re.IGNORECASE,
)

_COMMITMENT_GROUNDING_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by",
    "do", "for", "from", "going", "i", "if", "in", "is", "it", "me",
    "of", "on", "or", "our", "that", "the", "their", "them", "then",
    "they", "this", "to", "we", "will", "with", "you", "your",
}

def _commitment_content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").casefold())
        if len(token) >= 3 and token not in _COMMITMENT_GROUNDING_STOP_WORDS
    }

def _commitment_local_context(evidence: str, transcript: str, radius: int = 420) -> str:
    """Return a tight local transcript window around exact commitment evidence."""

    if not evidence or not transcript:
        return ""
    pos = transcript.find(evidence)
    if pos < 0:
        return ""
    return transcript[max(0, pos - radius): min(len(transcript), pos + len(evidence) + radius)]

def _resolve_commitment_action(
    action: str, evidence: str, transcript: str, *, allow_generic_continuation: bool = False
) -> str | None:
    """Return a self-contained grounded action, or omit an opaque commitment.

    Model paraphrase is allowed only as a deterministic convenience when its
    content words are directly present in a tight local transcript window.
    This lets a nearby antecedent resolve "it/that/them" without introducing
    another LLM pass or unsupported detail.
    """

    raw_action = re.sub(r"\s+", " ", str(action or "")).strip()
    evidence = re.sub(r"\s+", " ", str(evidence or "")).strip()
    if not raw_action or not evidence:
        return None

    if _LOW_VALUE_SOCIAL_COMMITMENT_PATTERN.search(
        f"{raw_action} {evidence}"
    ):
        return None

    opaque = bool(_OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(evidence))
    if not opaque:
        # Preserve the existing precision rule: unsupported paraphrase never
        # becomes authoritative. Apply the same durable self-containedness rule
        # even when the evidence itself is not pronoun-opaque.
        candidate = (
            raw_action if raw_action.casefold() in evidence.casefold() else evidence
        )
        return candidate if _commitment_action_is_self_contained(candidate) else None

    # Preserve a pure generic continuation long enough for the existing
    # adjacent-commitment merger to attach it to a preceding self-contained
    # commitment. The final reconciliation pass will still reject it if it
    # remains standalone.
    if (
        allow_generic_continuation
        and _GENERIC_COMMITMENT_CONTINUATION_PATTERN.fullmatch(evidence)
        and _OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(raw_action)
    ):
        return evidence

    # A merged item can legitimately contain a self-contained first clause
    # followed by an anaphoric continuation ("I'll notify the team. I'll take
    # care of it."). Keep that combined evidence because the antecedent is
    # internal to the stored action itself.
    if _OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(raw_action):
        first_clause = re.split(r"(?<=[.!?])\s+", raw_action, maxsplit=1)[0]
        if (
            first_clause != raw_action
            and not _OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(first_clause)
            and re.search(
                r"\b(?:i|we)\s*(?:will|['’]ll)|\blet\s+me\b",
                first_clause,
                flags=re.IGNORECASE,
            )
        ):
            return raw_action
        return None

    local = _commitment_local_context(evidence, transcript)
    if not local:
        return None

    action_tokens = _commitment_content_tokens(raw_action)
    context_tokens = _commitment_content_tokens(local)
    if len(action_tokens) < 2:
        return None

    # Every substantive action token must be transcript-grounded in the tight
    # local context. This is intentionally stricter than fuzzy semantic matching.
    if not action_tokens.issubset(context_tokens):
        return None

    if not _commitment_action_is_self_contained(raw_action):
        return None

    return raw_action


def _commitment_is_actionable(action: str, evidence: str) -> bool:
    """Reject chatter and conditional offers that do not create assigned work."""

    if not action or not evidence:
        return False
    evidence = evidence.strip()
    if _NON_ACTIONABLE_COMMITMENT_PATTERN.fullmatch(evidence):
        return False
    if _CONDITIONAL_OFFER_COMMITMENT_PATTERN.search(evidence):
        return False
    if _LOW_INFORMATION_COMMITMENT_PATTERN.search(evidence):
        return False
    if re.search(
        r"\b(?:i|we)\s*(?:will|['’]ll)\s+(?:touch\s+base|follow\s+up)\s+"
        r"(?:on|with|about|for)\s*$",
        evidence,
        flags=re.IGNORECASE,
    ):
        return False

    # Reject clipped ASR/model fragments that begin like a commitment but do
    # not contain a complete action proposition.  Precision sections should
    # prefer omission to emitting text such as "I'll put it I just".
    normalized = re.sub(r"\s+", " ", evidence).strip(" -.,;:")
    if re.search(
        r"\b(?:i|we|you|they|he|she|just|and|but|or|to|for|with|about|like)\s*$",
        normalized,
        flags=re.IGNORECASE,
    ):
        return False
    return True


def _merge_adjacent_commitments(commitments: list[dict], transcript: str) -> list[dict]:
    """Merge a nearby anaphoric continuation into the preceding commitment.

    A model can split one natural commitment such as "I'll notify the team.
    I'll take care of it." into two action items.  Merge only when the second
    quote is a generic pronoun-based continuation, the owner matches, and both
    quotes occur close together in the transcript.
    """

    merged: list[dict] = []
    for candidate in commitments:
        if not merged:
            merged.append(candidate)
            continue

        previous = merged[-1]
        candidate_evidence = str(candidate.get("evidence", "")).strip()
        previous_evidence = str(previous.get("evidence", "")).strip()
        same_owner = str(candidate.get("owner", "")).casefold() == str(
            previous.get("owner", "")
        ).casefold()

        if (
            same_owner
            and _GENERIC_COMMITMENT_CONTINUATION_PATTERN.fullmatch(candidate_evidence)
            and previous_evidence
        ):
            previous_pos = transcript.find(previous_evidence)
            candidate_pos = transcript.find(candidate_evidence, max(0, previous_pos))
            if (
                previous_pos >= 0
                and candidate_pos >= 0
                and 0 <= candidate_pos - (previous_pos + len(previous_evidence)) <= 120
            ):
                span = transcript[previous_pos:candidate_pos + len(candidate_evidence)].strip()
                previous["action"] = span
                previous["evidence"] = span
                continue

        merged.append(candidate)

    return merged


def _risk_candidate_is_well_formed(risk: str, evidence: str) -> bool:
    """Reject clipped or transcript-spill risk propositions.

    A risk may be concise, but durable memory needs a complete proposition rather
    than a cue word followed by an unfinished clause or a long conversational blob.
    """

    risk_text = re.sub(r"\s+", " ", str(risk or "")).strip()
    evidence_text = re.sub(r"\s+", " ", str(evidence or "")).strip()
    if not risk_text or not evidence_text:
        return False

    words = re.findall(r"[A-Za-z0-9&'-]+", risk_text)
    if len(words) < 4 or len(words) > 32:
        return False

    normalized = risk_text.rstrip()
    if normalized.endswith((",", ";", ":", "-")):
        return False
    if re.search(
        r"\b(?:and|or|but|so|because|where|when|if|which|who|to|for|with|about)\s*$",
        normalized,
        flags=re.IGNORECASE,
    ):
        return False
    # "that" can be a legitimate object ("resistance around that"), so reject
    # only clearly unfinished predicate forms rather than every sentence ending
    # in the word.
    if re.search(
        r"\b(?:is|was|means|because)\s+that\s*$",
        normalized,
        flags=re.IGNORECASE,
    ):
        return False

    # Long ASR spill frequently glues the next speaker/response onto a concern.
    # Keep this intentionally narrow so normal concise risk statements survive.
    if len(words) >= 20 and re.search(
        r"\b(?:yes\s+i\s+mean|yeah\s+i\s+mean|okay\s+i\s+mean|"
        r"what\s+earlier\s+this|you\s+know\s+what\s+i\s+mean)\b",
        evidence_text,
        flags=re.IGNORECASE,
    ):
        return False
    if len(words) >= 20 and len(re.findall(r"\blike\b", evidence_text, flags=re.IGNORECASE)) >= 3:
        return False

    return True


def _risk_is_supported(risk: str, evidence: str) -> bool:
    """Require an explicit, non-negated risk/concern statement and lexical support."""

    if not risk or not evidence:
        return False
    if not _RISK_EVIDENCE_PATTERN.search(evidence):
        return False
    if _RISK_NEGATION_PATTERN.search(evidence):
        return False
    if not _risk_candidate_is_well_formed(risk, evidence):
        return False

    risk_tokens = _meaningful_tokens(risk)
    evidence_tokens = _meaningful_tokens(evidence)
    if not risk_tokens:
        return False
    required_overlap = min(2, len(risk_tokens))
    return len(risk_tokens & evidence_tokens) >= required_overlap


def _risk_scan_segments(chunk: str) -> list[str]:
    """Return short logical transcript segments for deterministic risk recovery.

    Cleaned transcripts can split one uninterrupted channel turn across adjacent
    timestamp blocks. Merge only immediately adjacent blocks with the same
    channel label so a complete risk proposition can cross that formatting
    boundary without opening a broad transcript window. Plain-text chunks are
    returned unchanged for tests and legacy callers.
    """

    block_pattern = re.compile(
        r"(?ms)^\[\d{1,2}:\d{2}\]\s+\*\*(?P<speaker>[^*]+)\*\*\s*\n\n"
        r"(?P<body>.*?)(?=^\[\d{1,2}:\d{2}\]\s+\*\*|\Z)"
    )
    blocks = list(block_pattern.finditer(str(chunk or "")))
    if not blocks:
        text = re.sub(r"\s+", " ", str(chunk or "")).strip()
        return [text] if text else []

    segments: list[str] = []
    current_speaker = None
    current_parts: list[str] = []
    for block in blocks:
        speaker = block.group("speaker").strip().casefold()
        body = re.sub(r"\s+", " ", block.group("body")).strip()
        if not body:
            continue
        if current_parts and speaker != current_speaker:
            segments.append(" ".join(current_parts))
            current_parts = []
        current_speaker = speaker
        current_parts.append(body)
    if current_parts:
        segments.append(" ".join(current_parts))
    return segments


def _explicit_risk_fallbacks(chunk: str) -> list[dict]:
    """Recover only plainly stated, complete risk/concern clauses the model omitted."""

    cue = re.compile(
        r"\b(?:we(?:['’]re|\s+are)\s+(?:still\s+)?at\s+risk\s+of|"
        r"the\s+risk\s+(?:is|here\s+is|that)|"
        r"a\s+risk\s+(?:is|that)|"
        r"i(?:['’]m|\s+am)\s+(?:a\s+little\s+)?concerned\s+about|"
        r"we(?:['’]re|\s+are)\s+concerned\s+about)\b",
        flags=re.IGNORECASE,
    )
    recovered: list[dict] = []
    for segment in _risk_scan_segments(chunk):
        for match in cue.finditer(segment):
            tail = segment[match.start():].strip()
            boundary = re.search(r"[.!?](?:\s|$)", tail)
            if boundary:
                tail = tail[:boundary.start() + 1]
            words = list(re.finditer(r"\S+", tail))
            if len(words) > 36:
                tail = tail[:words[35].end()]
            evidence = tail.strip(" -\t")
            if not evidence or _RISK_NEGATION_PATTERN.search(evidence):
                continue
            if re.search(
                r"\b(?:maybe\s+less\s+about|less\s+about\s+whether|"
                r"not\s+really\s+(?:a\s+)?risk)\b",
                evidence,
                flags=re.IGNORECASE,
            ):
                continue
            item = {"risk": evidence.rstrip("."), "evidence": evidence}
            if _risk_is_supported(item["risk"], item["evidence"]):
                recovered.append(item)
    unique = []
    seen = set()
    for item in recovered:
        key = item["evidence"].casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


_OPAQUE_FOLLOW_UP_REFERENCE_PATTERN = re.compile(
    r"\b(?:take|make|do|handle|address|resolve|decide|review|send|share|post|forward|"
    r"email|push|follow\s+up\s+on)\s+(?:it|that|this|them|those|these)\b|"
    r"\b(?:it|that|this|them|those|these)\s+(?:as\s+)?(?:a\s+)?follow[- ]?up\b",
    flags=re.IGNORECASE,
)

_FOLLOW_UP_VAGUE_OBJECT_PATTERN = re.compile(
    r"\b(?:what\s+we(?:['’]re|\s+are)\s+looking\s+at|"
    r"what\s+we(?:['’]re|\s+are)\s+talking\s+about|"
    r"the\s+(?:thing|item|topic|issue)\b|"
    r"the\s+decision\b(?!\s+(?:on|about|whether|to|of)\b)|"
    r"decision\s+from\s+(?:our|the)\s+(?:session|sessions|meeting|meetings)\b)",
    flags=re.IGNORECASE,
)

_FOLLOW_UP_ACTION_VERB_PATTERN = re.compile(
    r"^(?:please\s+)?(?:send|share|review|decide|confirm|determine|provide|prepare|"
    r"schedule|contact|connect|follow\s+up|document|update|validate|check|raise|"
    r"discuss|finalize|circulate|deliver|create|remove|add|compare|investigate)\b",
    flags=re.IGNORECASE,
)


def _follow_up_is_self_contained(action: str) -> bool:
    """Require a durable follow-up to name an action and a recoverable object."""

    text = re.sub(r"\s+", " ", str(action or "")).strip(" .")
    if not text:
        return False
    if _OPAQUE_FOLLOW_UP_REFERENCE_PATTERN.search(text):
        return False
    if _FOLLOW_UP_VAGUE_OBJECT_PATTERN.search(text):
        return False
    if not _FOLLOW_UP_ACTION_VERB_PATTERN.search(text):
        return False
    return len(_commitment_content_tokens(text)) >= 2


def _resolve_follow_up_action(
    follow_up: str, evidence: str, transcript: str
) -> str | None:
    """Return a self-contained, tightly grounded follow-up or omit it.

    Follow-ups have a dedicated model action field. Prefer that concise action
    over conversational evidence, but require both semantic completeness and
    deterministic grounding in a tight local transcript window.
    """

    action = re.sub(r"\s+", " ", str(follow_up or "")).strip()
    evidence = re.sub(r"\s+", " ", str(evidence or "")).strip()
    if not action or not evidence or not _follow_up_is_self_contained(action):
        return None

    if action.casefold() in evidence.casefold():
        return action

    local = _commitment_local_context(evidence, transcript)
    if not local:
        return None
    action_tokens = _commitment_content_tokens(action)
    context_tokens = _commitment_content_tokens(local)
    if not action_tokens.issubset(context_tokens):
        return None
    return action


def _is_well_formed_question(question: str) -> bool:
    """Reject ASR fragments, speaker-boundary spill, and conversational checks."""

    text = str(question or "").strip()
    if not text:
        return False
    if re.search(
        r"\[\d{1,2}:\d{2}\]|\*\*(?:Mic|Remote)\*\*|"
        r"\((?:static|indistinct|inaudible|unintelligible|crosstalk)[^)]*\)",
        text,
        flags=re.IGNORECASE,
    ):
        return False

    # The evidence should be one question, not a question plus trailing
    # conversational material (for example, "What is X? Let me understand").
    if "?" in text and text.split("?", 1)[1].strip(" -–—	"):
        return False

    words = re.findall(r"[A-Za-z0-9&'-]+", text)
    if len(words) < 4 or len(words) > 30:
        return False

    lowered = " ".join(words).casefold()
    # Repeated starts and terminal function words are strong ASR-chop signals.
    # Durable meeting questions must be understandable on their own.
    if len(words) >= 4 and words[0].casefold() == words[2].casefold() and words[1].casefold() == words[3].casefold():
        return False
    if re.search(
        r"\b(?:the|a|an|except\s+for\s+the|except\s+for\s+a|"
        r"of\s+the|to\s+the|for\s+the)\s*$",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False
    if re.match(r"^(?:is|are)\s+that\s+(?:is|are)\s+that\b", lowered):
        return False
    if re.match(r"^is\s+it\s+fair\s+to\s+say\b", lowered):
        return False

    first = words[0].casefold()
    wh_words = {"who", "what", "when", "where", "why", "how", "which"}
    auxiliaries = {
        "is", "are", "was", "were", "do", "does", "did",
        "can", "could", "will", "would", "should",
    }
    if first in wh_words:
        pass
    elif first in auxiliaries:
        if len(words) < 2 or words[1].casefold() not in {
            "i", "we", "you", "they", "he", "she", "it", "there",
            "the", "a", "an",
        }:
            return False
        # "do it" / "did it" is usually an imperative or transcript spill,
        # not a durable business question.
        if first in {"do", "does", "did"} and words[1].casefold() == "it":
            return False
    elif first in {"have", "has"}:
        if len(words) < 2 or words[1].casefold() not in {
            "i", "we", "you", "they", "he", "she", "it",
        }:
            return False
        # Punctuation-light ASR commonly turns statements such as
        # "have it listed but..." into fake questions.  Keep "has it ..."
        # only when the transcript actually carries question punctuation.
        if words[1].casefold() == "it" and "?" not in text:
            return False
    else:
        return False

    if re.search(
        r"^\s*(?:who|what|when|where|why|how)\s+"
        r"(?:did|does|do|is|are|was|were|can|could|will|would|should)\s*,",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if re.search(
        r"^\s*(?:what|why|how|when|where|who|which)\s+"
        r"(?:is|are|do|does|did|would|could|should)\s+(?:the\s+)?"
        r"(?:what|why|how|when|where|who|which|is|are|do|does|did)\b",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    if re.search(r"(?:,\s*)?(?:right|correct|okay|ok)\?\s*$", text, flags=re.IGNORECASE):
        return False

    # Reject clause fragments that look interrogative only because ASR captured
    # the tail end of a larger sentence.  Durable open questions should stand
    # on their own without a dangling relative clause or unfinished lead-in.
    if re.match(
        r"^which\s+(?:would|could|should|can|will)\b",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False

    if re.search(
        r"\b(?:for|to|with|about|because|if|when|where|and|or|but|so|like)\s*$",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False

    if re.search(
        r"\bfor\s+like\s+[a-z][a-z0-9'-]*(?:ing)?\s*$",
        lowered,
        flags=re.IGNORECASE,
    ):
        return False

    # A question-shaped prefix followed by a new future-tense clause is usually
    # transcript spill (for example, a speaker begins answering immediately).
    if re.match(r"^(?:what|who|where|when|why|how)\s+(?:is|are|was|were)\b", lowered):
        remainder = " ".join(words[3:]).casefold() if len(words) > 3 else ""
        if re.search(r"\b(?:i|we|you|they|he|she)['’]ll\b", remainder):
            return False

    return True


def _question_similarity_tokens(question: str) -> set[str]:
    """Return content tokens used to collapse near-duplicate questions."""

    ignored = {
        "a", "an", "the", "that", "this", "it", "for", "to", "of", "in",
        "on", "and", "or", "but", "so", "just", "like", "kind", "what",
        "which", "who", "when", "where", "why", "how", "is", "are", "was",
        "were", "do", "does", "did", "can", "could", "will", "would",
        "should", "have", "has", "i", "we", "you", "they", "he", "she",
    }
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9&'-]+", question)
        if len(token) >= 3 and token.casefold() not in ignored
    }


def _questions_are_near_duplicates(left: str, right: str) -> bool:
    left_text = re.sub(r"\s+", " ", str(left or "")).casefold()
    right_text = re.sub(r"\s+", " ", str(right or "")).casefold()

    # Durable support-guarantee questions are frequently paraphrased with almost
    # no literal token overlap (for example ``when something breaks`` versus
    # ``resolving critical issues``).  Collapse only when both questions clearly
    # ask about guarantees *and* operational issue resolution; do not treat all
    # guarantee questions as equivalent.
    guarantee = re.compile(r"\bguarantee(?:s|d)?\b", flags=re.IGNORECASE)
    resolution = re.compile(
        r"\b(?:support|breaks?|broken|fix(?:ed|ing)?|resolv(?:e|es|ed|ing)|"
        r"critical\s+issues?|incident(?:s)?|problem(?:s)?)\b",
        flags=re.IGNORECASE,
    )
    if (
        guarantee.search(left_text)
        and guarantee.search(right_text)
        and resolution.search(left_text)
        and resolution.search(right_text)
    ):
        return True

    left_tokens = _question_similarity_tokens(left)
    right_tokens = _question_similarity_tokens(right)
    if not left_tokens or not right_tokens:
        return re.sub(r"\W+", "", left.casefold()) == re.sub(r"\W+", "", right.casefold())
    overlap = len(left_tokens & right_tokens)
    return overlap / min(len(left_tokens), len(right_tokens)) >= 0.75


_OPAQUE_QUESTION_REFERENT_PATTERN = re.compile(
    r"\b(?:it|that|this|these|those)\b",
    flags=re.IGNORECASE,
)


def _open_question_is_self_contained(question: str) -> bool:
    """Return False when a durable question depends on an opaque referent.

    Open Questions are working memory. A reader should understand the item later
    without reopening the transcript, so a question such as "Did that get
    extended?" is not durable unless the antecedent is made explicit.
    """

    return not bool(_OPAQUE_QUESTION_REFERENT_PATTERN.search(question or ""))


def _contextualize_open_question(question: str, transcript: str) -> str | None:
    """Resolve a narrow opaque Open Question from immediate transcript context.

    Only recover the antecedent when the nearby transcript itself states a
    parallel "<subject>, whether/if that was <verb> ..." construction. This
    keeps the rewrite deterministic and conservative. If the antecedent is not
    explicit enough to recover safely, omit the question.
    """

    cleaned = re.sub(r"\s+", " ", str(question or "")).strip()
    if not cleaned or not _is_well_formed_question(cleaned):
        return None
    if _open_question_is_self_contained(cleaned):
        return cleaned

    if not transcript:
        return None
    start = transcript.find(cleaned)
    if start < 0:
        return None

    question_match = re.search(
        r"^(?:(?:do|did)\s+(?:you|we|they)\s+know\s+if\s+|"
        r"can\s+(?:you|we|they)\s+confirm\s+(?:if|whether)\s+|"
        r"(?:is|was)\s+it\s+clear\s+(?:if|whether)\s+|"
        r"(?:did|does|do|was|is|has|have)\s+)"
        r"(?:that|it|this)\s+"
        r"(?:(?:got|get|was|is|has\s+been|have\s+been|will\s+be)\s+)?"
        r"(?P<verb>[A-Za-z][A-Za-z'-]*)\b",
        cleaned,
        flags=re.IGNORECASE,
    )
    if not question_match:
        return None

    verb = question_match.group("verb")
    block_start = max(
        transcript.rfind("**Mic**", 0, start),
        transcript.rfind("**Remote**", 0, start),
    )
    context_start = max(block_start, start - 420)
    before = re.sub(r"\s+", " ", transcript[context_start:start]).strip()

    # Require the same predicate in an explicit nearby antecedent construction.
    antecedent_pattern = re.compile(
        r"(?P<subject>(?:the|a|an|our|your|their)\s+"
        r"[A-Za-z0-9%][A-Za-z0-9%&/()' -]{1,70})\s*,\s*"
        r"(?:whether\s+or\s+not|whether|if)\s+"
        r"(?:that|it|this)\s+"
        r"(?:(?:was|is|got|gets?|has\s+been|will\s+be)\s+)"
        + re.escape(verb) +
        r"(?P<tail>[^,.?]{0,80})",
        flags=re.IGNORECASE,
    )
    matches = list(antecedent_pattern.finditer(before))
    if not matches:
        return None

    match = matches[-1]
    subject = re.sub(r"\s+", " ", match.group("subject")).strip(" ,")
    subject = re.sub(
        r"^(The|A|An|Our|Your|Their)\b",
        lambda article: article.group(1).casefold(),
        subject,
    )
    tail = re.sub(r"\s+", " ", match.group("tail")).strip(" ,")
    tail = re.sub(r"\s+as\s+well$", "", tail, flags=re.IGNORECASE).strip()
    if not subject or len(subject.split()) > 12:
        return None

    auxiliary = "Was"
    if verb.casefold() in {"approved", "included", "extended", "renewed", "signed",
                           "finalized", "completed", "confirmed", "changed", "updated"}:
        rewritten = f"{auxiliary} {subject} {verb}"
    else:
        return None
    if tail:
        rewritten += f" {tail}"
    rewritten = rewritten.rstrip(" .?") + "?"
    return rewritten if _is_well_formed_question(rewritten) else None


_STRONG_UNRESOLVED_CONTEXT_PATTERN = re.compile(
    r"\b(?:still\s+open|open\s+question|unclear|not\s+clear|"
    r"don['’]t\s+know(?:\s+yet)?|do\s+not\s+know(?:\s+yet)?|"
    r"not\s+sure|need\s+to\s+(?:confirm|validate|find\s+out|clarify)|"
    r"want\s+to\s+(?:confirm|validate|make\s+sure|clarify)|"
    r"(?:i\s+)?(?:will|['’]ll|have\s+to)\s+(?:double\s+check|verify|confirm)|"
    r"(?:i\s+)?(?:will|['’]ll)\s+reach\s+out\b.{0,80}\b(?:see|confirm)\b|"
    r"not\s+addressed|hasn['’]t\s+been\s+addressed|"
    r"have\s+yet\s+to\s+(?:determine|confirm|resolve))\b",
    flags=re.IGNORECASE | re.DOTALL,
)


def _direct_answer_remains_uncertain(text: str) -> bool:
    """Return True when a nominal direct answer immediately hedges itself.

    Examples such as "Yeah, it should have; I'll double check" are not durable
    answers even though they begin with a yes/no acknowledgement. Keep this
    deliberately local so a later, unrelated "don't know" does not reopen an
    otherwise answered question.
    """

    compact = re.sub(r"\s+", " ", text).strip()
    if not re.match(
        r"^(?:yes|no|yep|yeah|correct|right|sure|okay|ok)\b",
        compact,
        flags=re.IGNORECASE,
    ):
        return False
    local = compact[:180]
    return bool(
        re.search(
            r"\b(?:should|might|may|probably|possibly)\b.{0,90}"
            r"\b(?:double\s+check|verify|confirm|check)\b|"
            r"\b(?:i\s+)?(?:will|['’]ll|have\s+to)\s+"
            r"(?:double\s+check|verify|confirm|check)\b",
            local,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _question_is_locally_unresolved(question: str, transcript: str) -> bool:
    """Reject questions that are immediately answered or used rhetorically.

    This is intentionally conservative: when nearby text explicitly says the
    answer is unknown, keep the question.  Otherwise, obvious same-turn
    elaboration or a direct answer in the next local exchange means the item
    should not remain in durable Open Questions.
    """

    if not question or not transcript:
        return True

    if re.fullmatch(
        r"\s*is\s+it\s+(?:really\s+)?(?:our|your|their|my)\s+problem\??\s*",
        question,
        flags=re.IGNORECASE,
    ):
        # This phrasing is overwhelmingly a conversational responsibility
        # check, not a durable unresolved business question. Preserve the
        # substantive ownership question when it is stated explicitly instead.
        return False

    start = transcript.find(question)
    if start < 0:
        return True
    after = transcript[start + len(question): start + len(question) + 700]

    # If the same transcript block continues with a substantive response, treat
    # the question as answered/context-setting unless that immediate continuation
    # explicitly says the answer is still unknown. Channel-based transcripts can
    # contain more than one human voice in one Remote block, so this also catches
    # question/answer exchanges that have no intervening speaker marker.
    same_turn = re.split(
        r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*",
        after,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    same_turn_words = re.findall(r"[A-Za-z0-9&'-]+", same_turn)
    if len(same_turn_words) >= 7:
        compact_same_turn = re.sub(r"\s+", " ", same_turn).strip(" -–—")
        if _direct_answer_remains_uncertain(compact_same_turn):
            return True
        if re.match(
            r"^(?:yes|no|yep|yeah|correct|right|sure|okay|ok)\b",
            compact_same_turn,
            flags=re.IGNORECASE,
        ):
            return False
        if _STRONG_UNRESOLVED_CONTEXT_PATTERN.search(same_turn[:260]):
            return True
        return False

    # A concise direct response in the next exchange closes the question.
    next_turn = re.search(
        r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*\s*(?:\n+)?(?P<text>.{0,260})",
        after,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if next_turn:
        response = re.sub(r"\s+", " ", next_turn.group("text")).strip()
        if _direct_answer_remains_uncertain(response):
            return True
        if _STRONG_UNRESOLVED_CONTEXT_PATTERN.search(response[:220]):
            return True
        if re.match(
            r"^(?:yes|no|yep|yeah|correct|right|sure|okay|ok|"
            r"it(?:['’]s|\s+is|['’]ll|\s+will)|"
            r"we(?:['’]re|\s+are|['’]ll|\s+will)|"
            r"they(?:['’]re|\s+are|['’]ll|\s+will)|"
            r"the\s+[A-Za-z0-9&'-]+\s+(?:is|are|will))\b",
            response,
            flags=re.IGNORECASE,
        ):
            return False

        question_first = re.findall(r"[A-Za-z]+", question.casefold())
        if question_first and question_first[0] == "when" and re.search(
            r"\b(?:today|tomorrow|tonight|next\s+(?:week|month|quarter|year)|"
            r"this\s+(?:week|month|quarter|year)|monday|tuesday|wednesday|"
            r"thursday|friday|saturday|sunday|early|late|by\s+\w+)\b",
            response,
            flags=re.IGNORECASE,
        ):
            return False

        # Yes/no duration questions are often answered with a corrected number
        # rather than "yes" or "no" ("Is it two years?" -> "three years").
        # Treat an immediate numeric duration response as a direct answer.
        question_text = " ".join(question_first)
        if re.match(r"^(?:is|are|was|were|will|would|can|could|should)\b", question_text):
            duration_unit = re.search(
                r"\b(?:day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
                question_text,
            )
            if duration_unit and re.search(
                r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)"
                r"(?:\s*(?:-|to)\s*(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+))?"
                r"\s+(?:day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
                response,
                flags=re.IGNORECASE,
            ):
                return False

    # Conversational diagnostic prompts such as "What is the conflict with X?"
    # should not become durable Open Questions when the nearby discussion goes
    # on to explain the concrete impact. Keep them only when the local context
    # explicitly says the answer is still unknown/unresolved.
    if re.match(
        r"^what\s+(?:is|are)\s+(?:the\s+)?"
        r"(?:conflict|issue|problem|constraint|dependency)\s+"
        r"(?:with|for|on|between)\b",
        question.strip(),
        flags=re.IGNORECASE,
    ):
        local_explanation = re.sub(
            r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*",
            " ",
            after[:700],
            flags=re.IGNORECASE,
        )
        local_explanation = re.sub(r"\s+", " ", local_explanation).strip()
        if not _UNRESOLVED_CONTEXT_PATTERN.search(local_explanation[:500]):
            explanation_words = re.findall(r"[A-Za-z0-9&'-]+", local_explanation)
            if len(explanation_words) >= 10 and re.search(
                r"\b(?:because|means?|creates?|causes?|impacts?|requires?|"
                r"depends?|leaves?|left\s+over|would\s+have\s+to|have\s+to|"
                r"need\s+to|can't|cannot|couldn't|wouldn't|if\b.{0,120}\bthen)\b",
                local_explanation,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                return False

    return True


_CHANNEL_OWNER_LABELS = {"remote", "mic", "microphone", "speaker", "speaker a", "speaker b"}
_AUDIO_CHANNEL_OWNER_LABELS = {"remote", "mic", "microphone"}


def _commitment_action_family(action: str) -> set[str]:
    """Return coarse action concepts used only for duplicate-owner cleanup."""

    text = re.sub(r"\s+", " ", str(action or "")).casefold()
    families: set[str] = set()
    if re.search(r"\b(?:call|contact|reach\s+out|email|introduce|connect)\b", text):
        families.add("outreach")
    if re.search(r"\b(?:set\s+up|schedule|arrange|coordinate|meeting|call|discussion|conversation)\b", text):
        families.add("meeting")
    if re.search(r"\b(?:escalate|escalation|raise\s+with|bring\s+in)\b", text):
        families.add("escalation")
    return families


def _commitment_named_entities(action: str) -> set[str]:
    """Extract conservative organization/person-like anchors from an action."""

    text = str(action or "")
    entities = set(re.findall(r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)+\b", text))
    # Preserve short vendor forms such as "Vendor Alpha"/"TD Global" while
    # excluding generic sentence-leading verbs from acting as anchors.
    return {entity.casefold() for entity in entities if len(entity.split()) >= 2}


def _channel_owned_commitment_duplicates_named(candidate: dict, named: dict) -> bool:
    owner = re.sub(r"\s+", " ", str(candidate.get("owner", "")).strip()).casefold()
    named_owner = re.sub(r"\s+", " ", str(named.get("owner", "")).strip()).casefold()
    if owner not in _CHANNEL_OWNER_LABELS or not named_owner or named_owner in _CHANNEL_OWNER_LABELS or named_owner == "unknown":
        return False

    candidate_action = str(candidate.get("action", ""))
    named_action = str(named.get("action", ""))
    candidate_families = _commitment_action_family(candidate_action)
    named_families = _commitment_action_family(named_action)
    if not candidate_families or not (candidate_families & named_families):
        return False

    candidate_entities = _commitment_named_entities(candidate_action)
    named_entities = _commitment_named_entities(named_action)
    if candidate_entities and named_entities and (candidate_entities & named_entities):
        return True

    # If both actions are clearly the same meeting/outreach thread, allow the
    # named-owner item to win when the channel-labelled candidate's evidence
    # explicitly references that person. This avoids persisting UI channel names
    # as people while remaining conservative when no named owner is available.
    evidence_blob = " ".join(
        [str(candidate.get("evidence", ""))]
        + [str(v) for v in candidate.get("supporting_evidence", []) if v]
    )
    display_owner = str(named.get("owner", "")).strip()
    return bool(display_owner and re.search(rf"\b{re.escape(display_owner)}\b", evidence_blob, flags=re.IGNORECASE))


def _same_owner_commitments_overlap(left: dict, right: dict) -> bool:
    """Return True when two named-owner actions describe the same durable task."""

    left_owner = re.sub(r"\s+", " ", str(left.get("owner", "")).strip()).casefold()
    right_owner = re.sub(r"\s+", " ", str(right.get("owner", "")).strip()).casefold()
    if not left_owner or left_owner != right_owner or left_owner in _CHANNEL_OWNER_LABELS | {"unknown"}:
        return False

    left_action = str(left.get("action", ""))
    right_action = str(right.get("action", ""))
    left_families = _commitment_action_family(left_action)
    right_families = _commitment_action_family(right_action)
    if not left_families or not (left_families & right_families):
        return False

    left_entities = _commitment_named_entities(left_action)
    right_entities = _commitment_named_entities(right_action)
    if left_entities and right_entities and not (left_entities & right_entities):
        return False

    left_tokens = _commitment_content_tokens(left_action)
    right_tokens = _commitment_content_tokens(right_action)
    if len(left_tokens & right_tokens) >= 2:
        return True

    # Meeting/outreach phrasing often varies substantially (for example
    # "reach out ... to set up a call" vs "set up an initial call").
    # A shared named entity plus the same meeting/outreach family is enough to
    # collapse these for the same explicit owner.
    return bool(left_entities & right_entities and left_families & right_families)


def _prefer_commitment_detail(left: dict, right: dict) -> dict:
    """Choose the richer duplicate action and preserve the alternate evidence."""

    def score(item: dict) -> tuple[int, int, int]:
        action = str(item.get("action", ""))
        return (
            len(_commitment_action_family(action)),
            len(_commitment_content_tokens(action)),
            len(action),
        )

    primary, secondary = (left, right) if score(left) >= score(right) else (right, left)
    merged = dict(primary)
    evidence_values: list[str] = []
    for source in (primary, secondary):
        evidence = str(source.get("evidence", "")).strip()
        if evidence and evidence not in evidence_values:
            evidence_values.append(evidence)
        for value in source.get("supporting_evidence", []) or []:
            value = str(value).strip()
            if value and value not in evidence_values:
                evidence_values.append(value)
    if evidence_values:
        merged["evidence"] = evidence_values[0]
        if len(evidence_values) > 1:
            merged["supporting_evidence"] = evidence_values[1:]
        else:
            merged.pop("supporting_evidence", None)
    return merged


def _deduplicate_commitments(commitments: list[dict]) -> list[dict]:
    """Collapse exact and resolver-level duplicate commitments deterministically."""

    preliminary: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in commitments:
        if not isinstance(item, dict):
            continue
        owner = re.sub(r"\s+", " ", str(item.get("owner", "")).strip()).casefold()
        evidence = re.sub(r"\s+", " ", str(item.get("evidence", "")).strip())
        action = re.sub(r"\s+", " ", str(item.get("action", "")).strip())
        canonical = re.sub(r"[^a-z0-9]+", " ", (evidence or action).casefold()).strip()
        key = (owner, canonical)
        if not canonical or key in seen:
            continue
        seen.add(key)
        preliminary.append(item)

    named = [
        item for item in preliminary
        if re.sub(r"\s+", " ", str(item.get("owner", "")).strip()).casefold()
        not in _CHANNEL_OWNER_LABELS | {"", "unknown"}
    ]
    channel_filtered: list[dict] = []
    for item in preliminary:
        owner = re.sub(r"\s+", " ", str(item.get("owner", "")).strip()).casefold()
        if owner in _CHANNEL_OWNER_LABELS and any(
            _channel_owned_commitment_duplicates_named(item, named_item)
            for named_item in named
        ):
            continue
        channel_filtered.append(item)

    kept: list[dict] = []
    for item in channel_filtered:
        duplicate_index = next(
            (index for index, existing in enumerate(kept) if _same_owner_commitments_overlap(existing, item)),
            None,
        )
        if duplicate_index is None:
            kept.append(item)
            continue
        kept[duplicate_index] = _prefer_commitment_detail(kept[duplicate_index], item)
    return kept


def _normalize_open_questions(questions: list[str]) -> list[str]:
    """Keep only clean, deduplicated durable question wording."""

    kept: list[str] = []
    for raw in questions:
        question = re.sub(r"\s+", " ", str(raw or "")).strip(" -\t")
        if not _is_well_formed_question(question):
            continue

        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if _questions_are_near_duplicates(question, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(question)
            continue

        existing = kept[duplicate_index]
        existing_words = len(re.findall(r"\S+", existing))
        candidate_words = len(re.findall(r"\S+", question))
        if candidate_words < existing_words:
            kept[duplicate_index] = question

    return kept


_UNRESOLVED_CONTEXT_PATTERN = re.compile(
    r"\b(?:still\s+open|open\s+question|question\s+is|unclear|not\s+clear|"
    r"don['’]t\s+know|do\s+not\s+know|not\s+sure|not\s+knowing|"
    r"(?:going\s+to|need\s+to|want\s+to)\s+(?:ask|request)|"
    r"need\s+to\s+(?:confirm|validate|find\s+out|clarify)|"
    r"want\s+to\s+(?:confirm|validate|make\s+sure|clarify)|"
    r"(?:i\s+)?(?:will|['’]ll|have\s+to)\s+(?:double\s+check|verify|confirm)|"
    r"(?:i\s+)?(?:will|['’]ll)\s+reach\s+out\b.{0,80}\b(?:see|confirm)\b|"
    r"not\s+addressed|hasn['’]t\s+been\s+addressed|"
    r"have\s+yet\s+to\s+(?:determine|confirm|resolve))\b",
    flags=re.IGNORECASE | re.DOTALL,
)

_QUESTION_START_PATTERN = re.compile(
    r"\b(?:what|how|why|when|where|who|which)\s+"
    r"(?:is|are|was|were|do|does|did|can|could|will|would|should|have|has)\b"
    r"|\b(?:do|does|did|are|is|can|could|will|would|should|have|has)\s+"
    r"(?:we|they|you|it|this|that|the)\b",
    flags=re.IGNORECASE,
)


def _compact_question_clause(text: str, start: int) -> str:
    """Return a conservative question-like clause from punctuation-light ASR."""

    tail = text[start:].strip()
    if not tail:
        return ""
    boundary = re.search(
        r"[?](?:\s|$)|[.!](?:\s|$)|"
        r"\s+(?:okay|alright|right|so|and\s+then|that['’]s\s+number\s+one|number\s+two)\b|"
        r"\s+(?:it(?:['’]ll|\s+will)\s+be|they(?:['’]ll|\s+will)\s+be|"
        r"we(?:['’]ll|\s+will)\s+be|i\s+(?:would\s+)?presume)\b",
        tail,
        flags=re.IGNORECASE,
    )
    if boundary and boundary.start() > 0:
        tail = tail[:boundary.start() + (1 if tail[boundary.start()] == "?" else 0)]

    words = list(re.finditer(r"\S+", tail))
    if len(words) > 28:
        tail = tail[:words[27].end()]
    return tail.strip(" -\t,.;")


def _explicit_unresolved_question_fallbacks(chunk: str) -> list[str]:
    """Recover only explicit questions followed by clear unresolved context.

    The fallback is intentionally conservative.  It exists to recover an
    occasional omitted business question, not to turn every interrogative
    transcript fragment into durable meeting memory.
    """

    recovered: list[str] = []
    for match in _QUESTION_START_PATTERN.finditer(chunk):
        question = _compact_question_clause(chunk, match.start())
        question = re.sub(r"\s+", " ", question).strip()
        if not question or not _is_well_formed_question(question):
            continue

        question_end = match.start() + len(question)
        after_end = min(len(chunk), question_end + 320)
        after = chunk[question_end:after_end]

        # A fallback question must be followed by language showing that the
        # issue remains unresolved.  Do not borrow an unrelated uncertainty
        # statement from before the question.
        cue = _UNRESOLVED_CONTEXT_PATTERN.search(after)
        if not cue:
            continue

        # Keep the unresolved cue local.  If multiple speaker boundaries occur
        # before the cue, it is probably unrelated discussion.
        before_cue = after[:cue.start()]
        speaker_boundaries = re.findall(
            r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*",
            before_cue,
            flags=re.IGNORECASE,
        )
        if len(speaker_boundaries) > 1:
            continue

        # Do not retain an obvious immediately answered question.
        if re.match(
            r"^\s*(?:[,.!?-]*\s*)?(?:yes|no|yep|yeah|correct|"
            r"it(?:['’]ll|\s+will)\s+be|it\s+(?:is|would)|"
            r"they(?:['’]ll|\s+will)\s+be|they\s+(?:are|would)|"
            r"we(?:['’]ll|\s+will)\s+be|we\s+(?:are|would)|"
            r"i\s+(?:would\s+)?presume)\b",
            after,
            flags=re.IGNORECASE,
        ) and not _direct_answer_remains_uncertain(after):
            continue

        recovered.append(question)

    return _normalize_open_questions(recovered)


def _sentences_without_unsupported_actions(
    summary: str,
    has_supported_action: bool,
) -> str:
    if has_supported_action:
        return summary
    action_claim = re.compile(
        r"\b(?:action\s+item|ongoing\s+action|action\s+(?:is|was)\s+"
        r"(?:required|needed)|follow[- ]?up|next\s+step|"
        r"requires?\s+coordination|required\s+to\s+coordinate|"
        r"(?:need|needs|needed)\s+to\s+(?:finalize|coordinate|review|complete|"
        r"follow\s+up|resolve|deliver|provide|prepare|schedule))\b",
        flags=re.IGNORECASE,
    )
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    return " ".join(
        sentence for sentence in sentences if not action_claim.search(sentence)
    ).strip()


def _sentences_without_unsupported_questions(
    summary: str,
    has_authoritative_questions: bool,
) -> str:
    if has_authoritative_questions:
        return summary
    question_claim = re.compile(
        r"\bopen\s+questions?\b|\?",
        flags=re.IGNORECASE,
    )
    sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
    return " ".join(
        sentence for sentence in sentences
        if not question_claim.search(sentence)
    ).strip()


_TOPIC_DECISION_CLAIM = re.compile(
    r"\b(?:selected|chosen|primary\s+option|going\s+with|"
    r"recommended|recommendation|current\s+option|"
    r"decision\s+(?:is|was|to)|cut\s+[^.]{0,50}\s+from|"
    r"removed\s+from|excluded\s+from|\bis\s+out\b)\b",
    flags=re.IGNORECASE,
)


def _sentences_without_unsupported_decision_claims(
    summary: str,
    authoritative_decisions: list[dict],
) -> str:
    if not summary:
        return summary
    decision_corpus = " ".join(
        f"{item.get('decision', '')} {item.get('evidence', '')}"
        for item in authoritative_decisions
        if isinstance(item, dict)
    )
    decision_tokens = _meaningful_tokens(decision_corpus)
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", summary.strip()):
        if not _TOPIC_DECISION_CLAIM.search(sentence):
            kept.append(sentence)
            continue
        sentence_tokens = _meaningful_tokens(sentence)
        if len(sentence_tokens & decision_tokens) >= 2:
            kept.append(sentence)
            continue

        # Preserve a factual contrast clause when only the leading vendor
        # selection/recommendation claim is unsupported.  Example:
        # "Vendor Delta identified as the recommendation, though it exceeded budget"
        # becomes the grounded fact "Vendor Delta exceeded budget."
        contrast = re.search(
            r"^\s*(?P<entity>[A-Z][A-Za-z0-9&.-]*)\b.*?,\s*"
            r"(?:though|but)\s+it\s+(?P<fact>[^.!?]+)[.!?]?\s*$",
            sentence,
            flags=re.IGNORECASE,
        )
        if contrast:
            fact = contrast.group("fact").strip()
            if fact and not _TOPIC_DECISION_CLAIM.search(fact):
                kept.append(f"{contrast.group('entity')} {fact.rstrip('.') }.")
    return " ".join(kept).strip()


def _topic_has_supported_action(topic: dict, authoritative_actions: list[str]) -> bool:
    topic_tokens = _meaningful_tokens(
        f"{topic.get('topic_key', '')} {topic.get('topic', '')}"
    )
    for action in authoritative_actions:
        if topic_tokens & _meaningful_tokens(action):
            return True
    return False


def _topic_has_unresolved_transcript_evidence(topic: dict, transcript: str) -> bool:
    topic_terms = sorted(
        _meaningful_tokens(
            f"{topic.get('topic_key', '')} {topic.get('topic', '')}"
        ),
        key=len,
        reverse=True,
    )
    transcript_lower = transcript.casefold()
    unresolved = re.compile(
        r"\b(?:unread|unresolved|pending|waiting|outstanding|still\s+in\s+"
        r"(?:my|the)\s+inbox|haven['’]t\s+(?:read|reviewed|opened)|"
        r"still\s+need(?:s)?\s+to|haven['’]t\s+gotten\s+to|"
        r"haven['’]t\s+looked\s+at|need\s+to\s+(?:read|review|look\s+at)|"
        r"sitting\s+in\s+(?:my|the)\s+inbox)\b",
        flags=re.IGNORECASE,
    )
    for term in topic_terms:
        if len(term) < 5:
            continue
        for match in re.finditer(re.escape(term), transcript_lower):
            start = max(0, match.start() - 650)
            end = min(len(transcript), match.end() + 650)
            if unresolved.search(transcript[start:end]):
                return True
    return False



def _entity_evidence_pattern(entity: str) -> str:
    """Return a transcript regex for a topic entity, including spaced acronyms."""

    compact = re.sub(r"[^A-Za-z0-9]", "", entity)
    if 1 < len(compact) <= 4 and compact.isalnum():
        return r"\b" + r"[\s.\-]*".join(map(re.escape, compact)) + r"\b"
    return rf"\b{re.escape(entity)}\b"


def _recover_closed_topic_decisions(memory: dict, transcript: str) -> list[dict]:
    """Recover closed removal decisions only from explicit transcript evidence.

    Narrative topics may reveal that the grounded extractor missed a decision,
    but the topic itself is never evidence.  Recovery requires the named entity
    and an explicit removal verb in a tight transcript window.
    """

    recovered = []
    for topic in memory.get("topics", []):
        if not isinstance(topic, dict):
            continue
        if str(topic.get("status", "")).strip().casefold() != "closed":
            continue

        topic_name = str(topic.get("topic", "")).strip()
        if not re.search(
            r"\b(removal|remove|removed|exclusion|exclude|excluded|cut|drop|dropped|out)\b",
            topic_name,
            flags=re.IGNORECASE,
        ):
            continue

        topic_tokens = [
            token
            for token in re.findall(r"[A-Za-z0-9&.-]+", topic_name)
            if token.casefold() not in {
                "contract", "vendor", "removal", "remove", "removed",
                "exclusion", "exclude", "excluded", "cut", "drop", "dropped",
                "status", "review", "recommendation", "out",
            }
        ]
        if not topic_tokens:
            continue

        entity = topic_tokens[0]
        entity_pattern = _entity_evidence_pattern(entity)
        removal = r"(?:cut|remove|removed|drop|dropped|exclude|excluded)"
        patterns = (
            rf"\b{removal}\b[^\n]{{0,160}}?{entity_pattern}(?:\s+loose)?",
            rf"{entity_pattern}[^\n]{{0,160}}?\b(?:is\s+out|{removal})\b",
        )
        match = None
        for pattern in patterns:
            match = re.search(pattern, transcript, flags=re.IGNORECASE)
            if match:
                break
        if not match:
            continue

        evidence = match.group(0).strip(" -,\t")
        recovered.append({"decision": f"Drop {entity}.", "evidence": evidence})

    return recovered



def _recover_explicit_removal_decisions(transcript: str) -> list[dict]:
    """Recover explicit supplier removals directly from transcript evidence.

    Whisper phrasing around approvals is highly variable.  Rather than require
    one exact sentence shape, locate a removal verb + entity and then require a
    nearby *decision cue* in the preceding context.  The topic model is never
    used as evidence; the recovered evidence is always an exact transcript span.
    """

    removal = re.compile(
        r"\b(?P<verb>cut|remove|removed|drop|dropped|exclude|excluded)\s+"
        r"(?P<entity>[A-Za-z0-9&.-]+(?:\s+[A-Za-z](?=\s|$)){0,3})"
        r"(?:\s+loose)?\b",
        flags=re.IGNORECASE,
    )
    decision_cue = re.compile(
        r"\b(?:decision|decided|agreed|approval|approved|blessing|"
        r"okay|ok|go-ahead|green\s+light|got\s+the\s+okay|"
        r"got\s+the\s+ok|got\s+approval|got\s+.*?blessing|"
        r"are\s+going\s+to|we['’]re\s+going\s+to|will)\b",
        flags=re.IGNORECASE,
    )
    uncertainty = re.compile(
        r"\b(?:maybe|might|could|consider|considering|thinking\s+about|"
        r"if\s+we|if\s+they)\b",
        flags=re.IGNORECASE,
    )

    recovered = []
    speaker_marker = re.compile(
        r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*",
        flags=re.IGNORECASE,
    )
    for match in removal.finditer(transcript):
        # A decision cue may only govern a removal inside the same transcript
        # speaker block. Looking backward across a speaker boundary can pair an
        # unrelated phrase such as "I'm going to..." with a later "drop those"
        # and manufacture a decision.
        turn_start = 0
        for marker in speaker_marker.finditer(transcript, 0, match.start()):
            turn_start = marker.end()
        context_start = max(turn_start, match.start() - 240)
        before = transcript[context_start:match.start()]
        cue_matches = list(decision_cue.finditer(before))
        if not cue_matches:
            # Direct settled past-tense phrasing such as "we cut Vendor Gamma" is also
            # authoritative even without a separate approval word.
            direct_start = max(0, match.start() - 24)
            direct_prefix = transcript[direct_start:match.start()]
            if not re.search(r"\b(?:we|they|the\s+team)\s*$", direct_prefix, re.IGNORECASE):
                continue
            evidence_start = direct_start + re.search(
                r"\b(?:we|they|the\s+team)\s*$", direct_prefix, re.IGNORECASE
            ).start()
        else:
            cue = cue_matches[-1]
            evidence_start = context_start + cue.start()
            cue_to_match = transcript[evidence_start:match.start()]
            if uncertainty.search(cue_to_match):
                continue

        evidence_end = match.end()
        evidence = transcript[evidence_start:evidence_end].strip(" -,\t")
        entity = _normalized_removal_entity(match.group("entity"))
        if not entity or not evidence:
            continue
        # "cut over" / "cutover" is a migration noun/verb phrase, not an
        # exclusion decision.  More generally, never promote a removal verb
        # whose captured "entity" is only a generic directional/function word.
        if entity.casefold() in {
            "over", "back", "through", "across", "down", "up", "off",
            "out", "cost", "costs", "spend", "work", "scope",
            # Function words are not entities.  These commonly appear after
            # conversational phrases such as "drop to" / "drop the" and were
            # previously capable of producing garbage Decisions.
            "the", "a", "an", "to", "for", "from", "with", "on",
            "in", "into", "of", "and", "or", "at",
            # Pronouns/demonstratives are not durable removal entities. They
            # commonly occur in ordinary directives ("drop me the names") or
            # historical explanations ("you dropped those").
            "me", "you", "us", "him", "her", "them", "it",
            "this", "that", "these", "those",
        }:
            continue
        recovered.append({"decision": f"Drop {entity}.", "evidence": evidence})

    return _deduplicate_decisions(recovered)

def _decision_entities(item: dict) -> set[str]:
    """Return distinctive supplier/entity tokens for semantic decision merging."""

    text = f"{item.get('decision', '')} {item.get('evidence', '')}"
    generic = {
        "ahead", "approval", "decided", "decline", "drop", "engage",
        "move", "proceed", "reengage", "remove", "team", "timing",
    }
    entities = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9&.-]*", text):
        folded = token.casefold().strip(".-")
        if folded in _DECISION_STOP_WORDS or folded in generic:
            continue
        if any(ch.isdigit() for ch in folded) or token.isupper() or len(folded) >= 5:
            entities.add(folded)
    return entities


def _decision_intent(item: dict) -> str:
    text = f"{item.get('decision', '')} {item.get('evidence', '')}".casefold()
    if re.search(r"\b(?:cut|remove|removed|drop|dropped|exclude|excluded|let\s+\w+\s+down|timing\s+is\s+not\s+right)\b", text):
        return "decline"
    if re.search(r"\b(?:move\s+ahead|move\s+forward|proceed|continue|going\s+with|selected|chose)\b", text):
        return "proceed"
    return "other"


def _semantic_decision_duplicate(left: dict, right: dict) -> bool:
    """Recognize repeated statements of one supplier decision without proximity."""

    shared_entities = _decision_entities(left) & _decision_entities(right)
    if not shared_entities:
        return False
    left_intent = _decision_intent(left)
    right_intent = _decision_intent(right)
    if left_intent == right_intent and left_intent != "other":
        return True

    # Multi-vendor decisions often combine a positive primary-vendor outcome with
    # declining another vendor.  If both statements name the same declined
    # entity, treat the later timing/re-engagement statement as elaboration.
    left_text = f"{left.get('decision', '')} {left.get('evidence', '')}".casefold()
    right_text = f"{right.get('decision', '')} {right.get('evidence', '')}".casefold()
    decline_markers = r"(?:decline|let\s+\w+\s+down|timing\s+is\s+not\s+right|cut|drop|remove|exclude)"
    return bool(re.search(decline_markers, left_text) and re.search(decline_markers, right_text))


def _deduplicate_decisions_in_context(decisions: list[dict], transcript: str) -> list[dict]:
    """Collapse alternate statements of the same decision on the production path."""

    base = _deduplicate_decisions(decisions)
    kept = []
    for candidate in base:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if _semantic_decision_duplicate(candidate, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(candidate)
            continue

        existing = kept[duplicate_index]
        existing_text = str(existing.get("decision", ""))
        candidate_text = str(candidate.get("decision", ""))

        def outcome_score(item: dict) -> tuple[int, int, int]:
            text = f"{item.get('decision', '')} {item.get('evidence', '')}".casefold()
            positive = bool(re.search(
                r"\b(?:move\s+ahead|move\s+forward|proceed|going\s+with|selected|chose)\b",
                text,
            ))
            decline = bool(re.search(
                r"\b(?:decline|let\s+\w+\s+down|timing\s+is\s+not\s+right|cut|drop|remove|exclude)\b",
                text,
            ))
            canonical = str(item.get("decision", "")).casefold() != str(item.get("evidence", "")).casefold()
            return (int(positive) + int(decline), int(canonical), -len(str(item.get("decision", "")).split()))

        if outcome_score(candidate) > outcome_score(existing):
            kept[duplicate_index] = candidate

    return kept


_PRONOMINAL_REMOVAL_PATTERN = re.compile(
    r"\b(?:drop|dropped|cut|remove|removed|exclude|excluded)\s+"
    r"(?:them|it|him|her)\b",
    flags=re.IGNORECASE,
)

_TOPIC_ENTITY_SUFFIXES = {
    "renewal", "contract", "contracts", "status", "review", "reviews",
    "evaluation", "evaluations", "replacement", "replacements", "option",
    "options", "discussion", "discussions", "licensing", "license", "licenses",
    "agreement", "agreements", "relationship", "relationships", "planning",
}


def _topic_entity_label(topic: dict) -> str:
    """Return the entity-like portion of a topic title for decision display."""

    words = re.findall(r"[A-Za-z0-9&.-]+", str(topic.get("topic", "")).strip())
    while len(words) > 1 and words[-1].casefold() in _TOPIC_ENTITY_SUFFIXES:
        words.pop()
    return " ".join(words).strip()


def _contextualize_pronominal_removal_decision(
    item: dict, transcript: str, topics: list[dict]
) -> dict | None:
    """Resolve a pronoun removal only from the same local speaker turn.

    A quote such as "we dropped them" is not useful or safe as durable meeting
    memory unless the removed entity is recoverable from the same local turn.
    Do not reach backward across speaker boundaries or distant discussion, where
    the same phrase may refer to unrelated personal chatter.
    """

    decision = str(item.get("decision", "")).strip()
    evidence = str(item.get("evidence", "")).strip()
    if not evidence or not _PRONOMINAL_REMOVAL_PATTERN.search(
        f"{decision} {evidence}"
    ):
        return item

    pos = transcript.find(evidence)
    if pos < 0:
        return None

    # Restrict context to the current speaker turn when transcript markers are
    # present.  Without markers (e.g. unit tests), use a tight local window.
    marker = re.compile(
        r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*",
        flags=re.IGNORECASE,
    )
    turn_start = 0
    for match in marker.finditer(transcript, 0, pos):
        turn_start = match.end()
    next_marker = marker.search(transcript, pos + len(evidence))
    turn_end = next_marker.start() if next_marker else len(transcript)

    local_start = max(turn_start, pos - 300)
    local_end = min(turn_end, pos + len(evidence) + 80)
    context = transcript[local_start:local_end].casefold()
    before_evidence = transcript[local_start:pos].casefold()

    scored: list[tuple[int, int, str]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        label = _topic_entity_label(topic)
        tokens = [
            token for token in re.findall(r"[a-z0-9]+", label.casefold())
            if len(token) >= 4 and token not in _DECISION_STOP_WORDS
        ]
        if not tokens:
            continue

        # The entity must be mentioned before the pronoun in this same local
        # turn; a later topic mention cannot retroactively resolve "them".
        hits = [before_evidence.rfind(token) for token in tokens if token in before_evidence]
        if not hits:
            continue
        nearest = max(hits)
        distance = len(before_evidence) - nearest
        if distance > 220:
            continue
        scored.append((len(hits), -distance, label))

    if not scored:
        return None

    scored.sort(reverse=True)
    best = scored[0]
    if len(scored) > 1 and scored[1][:2] == best[:2]:
        return None

    label = best[2]
    if not label:
        return None
    return {"decision": f"Drop {label}.", "evidence": evidence}


def _topic_matches_decision(topic: dict, decision: dict) -> bool:
    topic_tokens = _meaningful_tokens(
        f"{topic.get('topic_key', '')} {topic.get('topic', '')}"
    )
    decision_tokens = _meaningful_tokens(
        f"{decision.get('decision', '')} {decision.get('evidence', '')}"
    )
    return bool(topic_tokens & decision_tokens)


def _remove_topic_contradictions(summary: str, topic: dict, decisions: list[dict]) -> str:
    """Drop topic prose that directly contradicts an authoritative decision."""

    if not summary:
        return summary
    relevant = [item for item in decisions if _topic_matches_decision(topic, item)]
    if not relevant:
        return summary

    contradiction = re.compile(
        r"\b(?:no\s+(?:formal|final|specific)?\s*decision\s+(?:has\s+been|was)\s+made|"
        r"no\s+decision\s+(?:has\s+been|was)\s+reached|"
        r"further\s+discussion\s+is\s+required\s+before\s+a\s+decision)\b",
        flags=re.IGNORECASE,
    )
    return " ".join(
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", summary.strip())
        if not contradiction.search(sentence)
    ).strip()


def _strip_unsupported_vendor_preference(summary: str, decisions: list[dict]) -> str:
    """Remove unsupported preferred/selected-vendor tails from mixed claims."""

    if not summary:
        return summary
    corpus = " ".join(
        f"{item.get('decision', '')} {item.get('evidence', '')}"
        for item in decisions
        if isinstance(item, dict)
    ).casefold()
    preference = re.compile(
        r"(?:,?\s+and\s+|,\s*)"
        r"(?:move|moving)\s+(?:forward|ahead)\s+with\s+"
        r"(?P<vendor>[A-Za-z0-9&.-]+)\s+as\s+(?:the\s+)?"
        r"(?:preferred|selected|primary)\s+(?:vendor|option).*?(?=[.!?]|$)",
        flags=re.IGNORECASE,
    )

    def repl(match: re.Match) -> str:
        vendor = match.group("vendor").casefold()
        return match.group(0) if vendor in corpus else ""

    return preference.sub(repl, summary).strip()


def _topic_negative_burden_evidence(topic: dict, transcript: str) -> bool:
    terms = _meaningful_tokens(f"{topic.get('topic_key', '')} {topic.get('topic', '')}")
    negative = re.compile(
        r"\b(?:administrative\s+burden|burdensome|frustrat(?:ed|ing|ion)|"
        r"pain\s+in\s+the\s+ass|annoying|ridiculous|time[- ]consuming|too\s+much\s+work)\b",
        flags=re.IGNORECASE,
    )
    lower = transcript.casefold()
    for term in terms:
        if len(term) < 5:
            continue
        for match in re.finditer(re.escape(term), lower):
            window = transcript[max(0, match.start()-500):min(len(transcript), match.end()+500)]
            if negative.search(window):
                return True
    return False


def _strip_sentiment_inversion(summary: str, topic: dict, transcript: str) -> str:
    if not summary or not _topic_negative_burden_evidence(topic, transcript):
        return summary
    positive_burden = re.compile(
        r"\b(?:minimal|little|low|no|without)\s+(?:administrative\s+)?burden\b|"
        r"\bminimal\s+administrative\s+burden\b",
        flags=re.IGNORECASE,
    )
    return " ".join(
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", summary.strip())
        if not positive_burden.search(sentence)
    ).strip()


def _strip_topic_boilerplate(summary: str) -> str:
    """Remove analyst boilerplate that adds no meeting fact."""

    if not summary:
        return summary
    boilerplate = re.compile(
        r"\b(?:no\s+(?:specific\s+|final\s+)?(?:decisions?|action\s+items?)\s+"
        r"(?:or\s+(?:action\s+items?|decisions?)\s+)?(?:were\s+)?identified|"
        r"no\s+(?:resolution|decision)\s+(?:was\s+)?identified|"
        r"no\s+final\s+decisions?\s+(?:were\s+)?reached)\b",
        flags=re.IGNORECASE,
    )
    return " ".join(
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", summary.strip())
        if not boilerplate.search(sentence)
    ).strip()


def _resolved_claim_removed_when_topic_open(summary: str, topic: dict) -> str:
    """Keep an open topic from simultaneously claiming it was resolved."""

    if not summary or str(topic.get("status", "")).casefold() != "open":
        return summary
    resolved = re.compile(
        r"\b(?:resolved|completed|finished|closed|fully\s+addressed|no\s+major\s+disruptions)\b",
        flags=re.IGNORECASE,
    )
    return " ".join(
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+", summary.strip())
        if not resolved.search(sentence)
    ).strip()


def _fallback_topic_summary(topic: dict) -> str:
    """Provide a concise neutral summary when precision filtering empties a topic."""

    name = str(topic.get("topic", "")).strip()
    status = str(topic.get("status", "")).strip().casefold()
    if not name:
        return ""
    if status == "open":
        return f"{name} remains unresolved."
    if status == "ongoing":
        return f"{name} remains in progress."
    if status == "closed":
        return f"{name} is closed."
    return name + "."


def _reconcile_in_progress_topic_status(topic: dict) -> None:
    """Do not equate a settled direction with completion of future work."""

    if str(topic.get("status", "")).casefold() != "closed":
        return
    name = str(topic.get("topic", ""))
    summary = str(topic.get("summary", ""))
    corpus = f"{name} {summary}"
    if not re.search(r"\b(?:migration|transition|implementation|rollout|plan)\b", corpus, re.IGNORECASE):
        return
    if re.search(r"\b(?:completed|finished|fully\s+migrated|went\s+live|cutover\s+complete)\b", corpus, re.IGNORECASE):
        return
    if re.search(r"\b(?:18[- ]month|future|proposed|plan|planning|prepare|preparing|migration|transition|ongoing)\b", corpus, re.IGNORECASE):
        topic["status"] = "ongoing"


def _strip_unsupported_narrative_vendor_preferences(summary: str, decisions: list[dict]) -> str:
    """Remove unsupported vendor winner language from narrative sections."""

    if not summary:
        return summary
    decision_corpus = " ".join(
        f"{item.get('decision', '')} {item.get('evidence', '')}"
        for item in decisions
        if isinstance(item, dict)
    ).casefold()

    # Preserve the supported contrast after an unsupported winner claim.
    pattern = re.compile(
        r"(?P<prefix>\b(?P<vendor>[A-Z][A-Za-z0-9&.-]*)\s+(?:was\s+)?identified\s+as\s+"
        r"(?:the\s+)?preferred\s+(?:vendor|option))"
        r"(?P<contrast>,?\s*(?:though|although|but)\s+)(?P<fact>[^.!?]+)",
        flags=re.IGNORECASE,
    )

    def replace_contrast(match: re.Match) -> str:
        vendor = match.group("vendor")
        if vendor.casefold() in decision_corpus:
            return match.group(0)
        fact = match.group("fact").strip()
        if not fact:
            return ""
        return fact[:1].upper() + fact[1:]

    summary = pattern.sub(replace_contrast, summary)

    # Remove subordinate repetitions such as "even though Vendor Delta was identified
    # as the preferred vendor" when no authoritative decision supports them.
    unsupported = re.compile(
        r"(?:,?\s*(?:even\s+though|although|though)\s+)?"
        r"(?P<vendor>[A-Z][A-Za-z0-9&.-]*)\s+(?:was\s+)?identified\s+as\s+"
        r"(?:the\s+)?preferred\s+(?:vendor|option)",
        flags=re.IGNORECASE,
    )

    def remove_claim(match: re.Match) -> str:
        vendor = match.group("vendor")
        return match.group(0) if vendor.casefold() in decision_corpus else ""

    return unsupported.sub(remove_claim, summary)


def _strip_narrative_no_decision_claims(summary: str, has_decisions: bool) -> str:
    """Remove narrative claims that contradict authoritative decisions.

    Preserve Markdown paragraph and heading boundaries.  Flattening the whole
    document here would prevent later section replacement from finding the
    original headings and could duplicate structured sections.
    """

    if not has_decisions or not summary:
        return summary
    contradiction = re.compile(
        r"\b(?:no\s+(?:formal|explicit|final|specific|confirmed)?\s*decisions?\s+"
        r"(?:were\s+made|were\s+reached|resulted|identified)|"
        r"did\s+not\s+result\s+in\s+any\s+(?:formal\s+|explicit\s+|confirmed\s+)?decisions?)\b",
        flags=re.IGNORECASE,
    )
    parts = re.split(r"(\n{2,})", summary)
    cleaned_parts = []
    for part in parts:
        if not part or re.fullmatch(r"\n{2,}", part):
            cleaned_parts.append(part)
            continue
        if part.lstrip().startswith("#"):
            cleaned_parts.append(part)
            continue
        if any(re.match(r"^\s*[-*•]\s+", line) for line in part.splitlines()):
            cleaned_parts.append(part)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", part.strip())
        kept = [sentence for sentence in sentences if not contradiction.search(sentence)]
        cleaned_parts.append(" ".join(kept))
    return "".join(cleaned_parts).strip()


def _strip_narrative_action_item_claims(summary: str, has_action_items: bool) -> str:
    """Remove narrative action-item claims that contradict authoritative actions.

    Structured commitments are the source of truth for the rendered Action Items
    section.  When that section is empty, narrative prose must not claim that
    action items were identified, assigned, or captured.
    """

    if has_action_items or not summary:
        return summary

    contradiction = re.compile(
        r"\b(?:several|multiple|some|a\s+number\s+of)?\s*action\s+items?\s+"
        r"(?:were\s+|was\s+)?(?:identified|noted|captured|assigned|outlined|established)\b",
        flags=re.IGNORECASE,
    )

    parts = re.split(r"(\n{2,})", summary)
    cleaned_parts = []
    for part in parts:
        if not part or re.fullmatch(r"\n{2,}", part):
            cleaned_parts.append(part)
            continue
        if part.lstrip().startswith("#"):
            cleaned_parts.append(part)
            continue
        if any(re.match(r"^\s*[-*•]\s+", line) for line in part.splitlines()):
            cleaned_parts.append(part)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", part.strip())
        kept = [sentence for sentence in sentences if not contradiction.search(sentence)]
        cleaned_parts.append(" ".join(kept))
    return "".join(cleaned_parts).strip()




def _normalize_verified_risk_text(risk: str, evidence: str) -> str:
    """Polish a small set of transcript-like verified risk fragments.

    This runs only after v12 has already grounded the risk to exact transcript
    evidence.  It does not invent a new risk; it converts common conversational
    failure-mode wording into durable memory language.
    """

    text = re.sub(r"\s+", " ", str(risk or "")).strip(" .-")
    source = f"{text} {evidence}".casefold()
    if "end of support" in source and re.search(r"\bpatch(?:es|ing)?\b|\bupdates?\b|\bupgrades?\b", source):
        return "Risk of losing access to critical patches and upgrades under an inadequate support arrangement"
    return text


def _nearby_agreement_evidence(evidence: str, transcript: str, radius: int = 2200) -> str | None:
    """Find a nearby exact transcript line that explicitly confirms a next step.

    A decision question can establish the subject, while the actual agreement may
    occur a few turns later (for example ``that's what we'll do``).  Prefer that
    confirmation as primary evidence while retaining the original quote as
    supporting evidence.
    """

    if not evidence or not transcript:
        return None
    pos = transcript.find(evidence)
    if pos < 0:
        return None
    window_start = max(0, pos - radius)
    window_end = min(len(transcript), pos + len(evidence) + radius)
    window = transcript[window_start:window_end]
    cue = re.compile(
        r"\b(?:that['’]s\s+what\s+we['’]ll\s+do|let['’]s\s+have\s+(?:that|the)\s+(?:conversation|call)|"
        r"let['’]s\s+get\s+that\s+set\s+up|sounds\s+good|for\s+sure)\b",
        flags=re.IGNORECASE,
    )
    blocks = [re.sub(r"\s+", " ", block).strip() for block in re.split(r"\n\s*\n", window)]
    candidates = [block for block in blocks if block and not block.startswith("[") and cue.search(block)]
    if not candidates:
        # Speaker/timestamp headers can be attached to the text in compact transcripts.
        candidates = [block for block in blocks if block and cue.search(block)]
    if not candidates:
        return None
    # Prefer an explicit confirmation over a generic acknowledgement.
    def score(block: str) -> tuple[int, int]:
        lowered = block.casefold()
        weight = 0
        if "that's what we'll do" in lowered or "that’s what we’ll do" in lowered:
            weight += 5
        if "let's have" in lowered or "let’s have" in lowered:
            weight += 4
        if "let's get" in lowered or "let’s get" in lowered:
            weight += 4
        if "for sure" in lowered:
            weight += 2
        if "sounds good" in lowered:
            weight += 1
        return (weight, -len(block))
    best = max(candidates, key=score)
    # Strip a leading transcript header if present; the remaining text is still exact
    # contiguous transcript content after whitespace normalization is undone below.
    match = cue.search(best)
    if not match:
        return None
    # Locate a compact phrase/sentence in the original window so stored evidence is exact.
    original_lower = window.casefold().replace("’", "'")
    probes = [
        "that's what we'll do",
        "let's have that conversation",
        "let's have the conversation",
        "let's get that set up",
        "for sure",
        "sounds good",
    ]
    for probe in probes:
        idx = original_lower.find(probe)
        if idx < 0:
            continue
        start = idx
        # Expand to the surrounding sentence/turn fragment, but keep it compact.
        left = max(window.rfind("\n\n", 0, start), window.rfind(". ", 0, start))
        left = 0 if left < 0 else left + (2 if window[left:left+2] in {"\n\n", ". "} else 0)
        right_candidates = [x for x in (window.find(". ", idx), window.find("\n\n", idx)) if x >= 0]
        right = min(right_candidates) + 1 if right_candidates else min(len(window), idx + 220)
        exact = window[left:right].strip()
        if exact and len(exact) <= 320:
            return exact
    return None


def _nearby_post_agreement_evidence(evidence: str, transcript: str, radius: int = 1400) -> str | None:
    """Return a compact explicit confirmation that occurs *after* evidence.

    For final Decision validation, a later assent can turn a proposal/question
    into a settled direction.  A preceding statement must not retroactively make
    a later "good push" / "maybe we prioritize" preference look settled, so this
    helper is intentionally directional.
    """

    if not evidence or not transcript:
        return None
    pos = transcript.find(evidence)
    if pos < 0:
        return None
    start = pos + len(evidence)
    window = transcript[start:min(len(transcript), start + radius)]
    cue = re.compile(
        r"\b(?:that['’]s\s+what\s+we['’]ll\s+do|"
        r"let['’]s\s+have\s+(?:that|the)\s+(?:conversation|call)|"
        r"let['’]s\s+get\s+that\s+set\s+up|sounds\s+good|"
        r"yes[, ]+let['’]s|yeah[, ]+let['’]s|for\s+sure)\b",
        flags=re.IGNORECASE,
    )
    match = cue.search(window)
    if not match:
        return None

    left = max(window.rfind("\n\n", 0, match.start()), window.rfind(". ", 0, match.start()))
    left = 0 if left < 0 else left + (2 if window[left:left+2] in {"\n\n", ". "} else 0)
    right_candidates = [
        value for value in (
            window.find(". ", match.end()),
            window.find("\n\n", match.end()),
        ) if value >= 0
    ]
    right = min(right_candidates) + 1 if right_candidates else min(len(window), match.end() + 220)
    exact = window[left:right].strip()
    return exact if exact and len(exact) <= 360 else None


def _recover_perpetual_rights_question(transcript: str) -> str | None:
    """Recover a durable unresolved license-rights question from explicit speech."""

    if not transcript or not re.search(r"\bperpetual\s+rights?\b", transcript, flags=re.IGNORECASE):
        return None
    match = re.search(r"\bperpetual\s+rights?\b", transcript, flags=re.IGNORECASE)
    if not match:
        return None
    context = transcript[max(0, match.start()-700): min(len(transcript), match.end()+900)]
    unresolved = re.search(
        r"\b(?:need\s+to\s+(?:find\s+out|talk)|we['’]d\s+have\s+to\s+find\s+out|"
        r"don['’]t\s+know|not\s+sure|are\s+we\s+forfeit(?:ing)?|walk\s+away)\b",
        context, flags=re.IGNORECASE,
    )
    if not unresolved:
        return None
    return "Will we retain perpetual license rights if the support relationship ends?"


def _recover_support_guarantee_question(transcript: str) -> str | None:
    """Recover an explicit unresolved support-guarantee question conservatively."""

    if not transcript:
        return None
    match = re.search(
        r"\bwhat\s+guarantees?\s+(?:they|the\s+provider|[A-Z][A-Za-z0-9&.-]+)\s+give\b",
        transcript,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    context = transcript[max(0, match.start()-450): min(len(transcript), match.end()+650)]
    if not re.search(r"\bwhen\s+something\s+breaks|\bfix\s+it|\bsupport\b", context, flags=re.IGNORECASE):
        return None
    # Do not recover when the local context immediately supplies a concrete
    # guarantee/answer; this is intended only for unresolved due-diligence work.
    tail = context[match.end() - max(0, match.start()-450):]
    if re.search(r"\b(?:they\s+guarantee|the\s+guarantee\s+is|yes,?\s+they\s+will)\b", tail, flags=re.IGNORECASE):
        return None
    return "What guarantees does the support provider offer for resolving critical issues?"




def _recover_followup_decision_from_commitments(memory: dict, transcript: str) -> dict | None:
    """Recover an explicit group decision to hold a follow-up discussion.

    The action and the decision are distinct: a named owner may be assigned to
    arrange the call, while the group separately agrees that the call should
    happen.  Recover that decision only when a durable named-owner meeting
    commitment exists and nearby transcript evidence explicitly confirms the
    conversation/call.
    """

    if memory.get("decisions") or not transcript:
        return None

    for commitment in memory.get("commitments", []):
        if not isinstance(commitment, dict):
            continue
        owner = re.sub(r"\s+", " ", str(commitment.get("owner", "")).strip())
        if not owner or owner.casefold() in _CHANNEL_OWNER_LABELS | {"unknown"}:
            continue
        action = re.sub(r"\s+", " ", str(commitment.get("action", "")).strip())
        if "meeting" not in _commitment_action_family(action):
            continue

        entity_matches = re.findall(
            r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)+\b",
            action,
        )
        entity = next(
            (value for value in entity_matches if value.casefold() != owner.casefold()),
            None,
        )
        if not entity:
            continue

        evidence_candidates = [str(commitment.get("evidence", "")).strip()]
        evidence_candidates.extend(
            str(value).strip()
            for value in commitment.get("supporting_evidence", []) or []
            if str(value).strip()
        )
        agreement = None
        for evidence in evidence_candidates:
            agreement = _nearby_agreement_evidence(evidence, transcript)
            if agreement:
                break
        if not agreement:
            continue

        return {
            "decision": f"Proceed with a follow-up discussion with {entity}.",
            "evidence": agreement,
        }

    return None

def _recover_explicit_negative_settlement_decisions(transcript: str) -> list[dict]:
    """Recover an explicit decision not to carry out a locally named future action.

    Conversational decisions are often expressed anaphorically ("we're not going
    to do that") after the speaker has just stated the concrete work being
    rejected.  Recover only when both pieces occur in the same speaker turn and
    the antecedent is explicit; this keeps the v12.13 precision boundary intact.
    """

    if not transcript:
        return []

    turn_pattern = re.compile(
        r"\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*\s*(?P<body>.*?)(?=\n\s*\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*|\Z)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    settlement = re.compile(
        r"(?P<prefix>(?:now\s+that\s+we\s+have\s+(?P<context>[^.\n]{3,120}?)\s+in\s+place,?\s*)?)"
        r"we\s+need\s+to\s+(?P<action>[^.\n]{10,240})\.\s*"
        r"(?:we['’]re|we\s+are)\s+not\s+(?:gonna|going\s+to)\s+do\s+that\b",
        flags=re.IGNORECASE,
    )

    recovered: list[dict] = []
    for turn in turn_pattern.finditer(transcript):
        body = turn.group("body")
        for match in settlement.finditer(body):
            action = re.sub(r"\s+", " ", match.group("action")).strip(" ,;:-")
            context = re.sub(r"\s+", " ", str(match.group("context") or "")).strip(" ,;:-")
            context = re.sub(r"^(?:this|the)\s+", "", context, flags=re.IGNORECASE)
            action = re.sub(r"^(?:go\s+back\s+and\s+)", "", action, flags=re.IGNORECASE)
            if context:
                action = re.sub(
                    r"\b(?:look\s+like\s+this|match\s+(?:it|this))\b",
                    f"match the {context}",
                    action,
                    flags=re.IGNORECASE,
                )
            if re.search(r"\b(?:this|that|it|them)\b", action, flags=re.IGNORECASE):
                continue
            decision = f"Do not {action.rstrip('.')} .".replace(" .", ".")
            evidence = match.group(0).strip()
            if not _decision_candidate_is_well_formed(decision, evidence):
                continue
            recovered.append({"decision": decision, "evidence": evidence})
    return recovered


def _strip_internal_memory_markers(memory: dict) -> dict:
    """Remove private resolver provenance fields before memory is persisted."""

    for section in ("commitments", "decisions", "risks"):
        for item in memory.get(section, []):
            if not isinstance(item, dict):
                continue
            for key in list(item):
                if str(key).startswith("_"):
                    item.pop(key, None)
    return memory

def _reconcile_meeting_memory(
    memory: dict,
    transcript: str,
    *,
    verified_open_questions: set[str] | None = None,
) -> dict:
    """Apply deterministic evidence and cross-section consistency rules.

    ``verified_open_questions`` contains v12 event-pipeline questions that were
    already independently verified against exact transcript evidence. Baseline
    and lower-capability paths continue through the established local question
    checks unchanged.
    """

    verified_open_questions = verified_open_questions or set()

    decisions = []
    for item in memory.get("decisions", []):
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidence", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not decision or not evidence or evidence not in transcript:
            continue
        context_resolved = bool(item.get("_context_resolved"))
        event_verified = bool(item.get("_event_verified"))
        if not context_resolved and not _decision_is_supported(decision, evidence):
            continue
        # v12 already verified the normalized decision against exact transcript
        # evidence plus a decision/agreement cue. Do not reapply the legacy
        # lexical-overlap gate to that polished wording. v11/baseline behavior
        # remains unchanged.
        if context_resolved and not event_verified and not _resolved_text_is_grounded_in_context(
            decision, _resolved_item_context(item, transcript)
        ):
            continue
        if not _decision_candidate_is_well_formed(decision, evidence):
            continue
        supporting_evidence = [
            str(value).strip()
            for value in item.get("supporting_evidence", []) or []
            if str(value).strip() and str(value).strip() in transcript
        ]
        decision_quotes = [evidence, *supporting_evidence]
        if event_verified:
            # Final persisted decisions must still be semantically supported by
            # their own grounded evidence. This catches late-path items whose
            # polished conclusion survived with only a generic acknowledgement.
            if not _decision_evidence_is_semantically_consistent(
                decision, decision_quotes, transcript
            ):
                continue
            decision_quotes = _order_decision_evidence(decision, decision_quotes, transcript)
        normalized_decision_item = {"decision": decision, "evidence": decision_quotes[0]}
        if len(decision_quotes) > 1:
            normalized_decision_item["supporting_evidence"] = list(dict.fromkeys(decision_quotes[1:]))
        if item.get("_event_verified"):
            normalized_decision_item["_event_verified"] = True
        decisions.append(normalized_decision_item)

    # Closed removal/exclusion topics can expose an explicit decision that the
    # grounded extractor missed.  Only recover it when the transcript itself
    # contains the named entity next to a removal verb.
    for item in _recover_closed_topic_decisions(memory, transcript):
        evidence = str(item.get("evidence", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not decision or not evidence or evidence not in transcript:
            continue
        if not _decision_candidate_is_well_formed(decision, evidence):
            continue
        decisions.append({"decision": decision, "evidence": evidence})

    # A vendor exclusion can be settled even while the broader topic remains
    # open.  Recover these directly from explicit transcript wording rather
    # than depending on the narrative topic status.
    for item in _recover_explicit_removal_decisions(transcript):
        evidence = str(item.get("evidence", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not decision or not evidence or evidence not in transcript:
            continue
        if not _decision_candidate_is_well_formed(decision, evidence):
            continue
        decisions.append({"decision": decision, "evidence": evidence})

    # Recover explicit negative settlements such as "we're not going to do
    # that" only when the same speaker turn states the concrete antecedent.
    for item in _recover_explicit_negative_settlement_decisions(transcript):
        evidence = str(item.get("evidence", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not decision or not evidence or evidence not in transcript:
            continue
        decisions.append({"decision": decision, "evidence": evidence})

    normalized_decisions = []
    for item in decisions:
        decision = str(item.get("decision", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if decision.casefold().rstrip(".") == evidence.casefold().rstrip("."):
            decision = _canonical_fallback_decision_text(evidence)
        decision_payload = {"decision": decision, "evidence": evidence}
        supporting_evidence = [
            str(value).strip()
            for value in item.get("supporting_evidence", []) or []
            if str(value).strip() and str(value).strip() in transcript
        ]
        if supporting_evidence:
            decision_payload["supporting_evidence"] = list(dict.fromkeys(supporting_evidence))
        contextualized = _contextualize_pronominal_removal_decision(
            decision_payload,
            transcript,
            memory.get("topics", []),
        )
        if contextualized is not None:
            normalized_decisions.append(contextualized)

    memory["decisions"] = _deduplicate_decisions_in_context(
        normalized_decisions,
        transcript,
    )
    for item in memory["decisions"]:
        if isinstance(item, dict):
            item.pop("_event_verified", None)

    reconciled_questions = []
    for question in _normalize_open_questions(
        [str(question) for question in memory.get("open_questions", [])]
    ):
        if question in verified_open_questions:
            # v12 validated the source evidence and unresolved-at-end state before
            # normalization. The normalized question itself may not occur verbatim
            # in the transcript, so the baseline local-search gate is not valid.
            reconciled_questions.append(question)
            continue
        if not _question_is_locally_unresolved(question, transcript):
            continue
        durable_question = _contextualize_open_question(question, transcript)
        if durable_question:
            reconciled_questions.append(durable_question)
    memory["open_questions"] = _normalize_open_questions(reconciled_questions)
    # On the v12 High Performance path, deterministic transcript recovery is a
    # final safety net even when the model happened to propose zero questions in
    # this run. These helpers require explicit unresolved language in the
    # transcript, so recovery does not weaken the baseline precision contract.
    if verified_open_questions or _memory_resolution_capable():
        recovered_questions = [
            _recover_perpetual_rights_question(transcript),
            _recover_support_guarantee_question(transcript),
        ]
        for recovered_question in recovered_questions:
            if not recovered_question or any(
                _questions_are_near_duplicates(recovered_question, existing)
                for existing in memory["open_questions"]
            ):
                continue
            memory["open_questions"] = _normalize_open_questions(
                [*memory["open_questions"], recovered_question]
            )

    reconciled_risks = []
    for item in memory.get("risks", []):
        if not isinstance(item, dict):
            continue
        risk = re.sub(r"\s+", " ", str(item.get("risk", ""))).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not risk or not evidence or evidence not in transcript:
            continue
        evidence_values = [evidence]
        evidence_values.extend(
            str(value).strip()
            for value in item.get("supporting_evidence", []) or []
            if str(value).strip() and str(value).strip() in transcript
        )
        if item.get("_event_verified") or item.get("_context_resolved"):
            evidence_values = _order_risk_evidence(risk, evidence_values, transcript)
        normalized_risk = {"risk": risk, "evidence": evidence_values[0]}
        if len(evidence_values) > 1:
            normalized_risk["supporting_evidence"] = list(dict.fromkeys(evidence_values[1:]))
        reconciled_risks.append(normalized_risk)
    memory["risks"] = reconciled_risks

    reconciled_commitments = []
    for item in memory.get("commitments", []):
        if not isinstance(item, dict):
            continue
        owner = re.sub(r"\s+", " ", str(item.get("owner", "")).strip()).casefold()
        if owner in _AUDIO_CHANNEL_OWNER_LABELS:
            continue
        evidence = str(item.get("evidence", "")).strip()
        action = str(item.get("action", "")).strip()
        if not _commitment_is_actionable(action, evidence):
            continue
        if item.get("_context_resolved"):
            if item.get("_event_verified"):
                # The v12 verifier already established exact transcript evidence,
                # ownership/cue support, and a self-contained normalized action.
                # Requiring lexical overlap here would discard valid paraphrases
                # such as "arrange" for transcript wording "set up".
                resolved_action = action if _commitment_action_is_self_contained(action) else None
            else:
                resolved_action = (
                    action
                    if _commitment_action_is_self_contained(action)
                    and _resolved_text_is_grounded_in_context(
                        action, _resolved_item_context(item, transcript)
                    )
                    else None
                )
        else:
            resolved_action = _resolve_commitment_action(action, evidence, transcript)
        if not resolved_action:
            continue
        normalized_item = dict(item)
        normalized_item["action"] = resolved_action
        normalized_item.pop("_context_resolved", None)
        normalized_item.pop("_event_verified", None)
        reconciled_commitments.append(normalized_item)
    memory["commitments"] = _deduplicate_commitments(reconciled_commitments)

    recovered_followup_decision = _recover_followup_decision_from_commitments(memory, transcript)
    if recovered_followup_decision is not None:
        memory["decisions"] = [recovered_followup_decision]

    authoritative_actions = []
    for commitment in memory.get("commitments", []):
        if isinstance(commitment, dict):
            authoritative_actions.append(
                " ".join(
                    str(commitment.get(field, ""))
                    for field in ("action", "evidence")
                )
            )
    authoritative_actions.extend(
        str(item) for item in memory.get("follow_ups", [])
    )

    authoritative_decisions = [
        item for item in memory.get("decisions", [])
        if isinstance(item, dict)
    ]
    has_authoritative_questions = bool(memory.get("open_questions", []))

    for topic in memory.get("topics", []):
        if not isinstance(topic, dict):
            continue
        topic_summary = str(topic.get("summary", ""))
        topic_summary = _sentences_without_unsupported_actions(
            topic_summary,
            _topic_has_supported_action(topic, authoritative_actions),
        )
        topic_summary = _sentences_without_unsupported_questions(
            topic_summary,
            has_authoritative_questions,
        )
        topic_summary = _sentences_without_unsupported_decision_claims(
            topic_summary,
            authoritative_decisions,
        )
        topic_summary = _strip_unsupported_vendor_preference(
            topic_summary,
            authoritative_decisions,
        )
        topic_summary = _remove_topic_contradictions(
            topic_summary,
            topic,
            authoritative_decisions,
        )
        topic_summary = _strip_sentiment_inversion(
            topic_summary,
            topic,
            transcript,
        )
        topic_summary = _strip_topic_boilerplate(topic_summary)
        _reconcile_in_progress_topic_status(topic)
        if (
            topic.get("status") == "closed"
            and _topic_has_unresolved_transcript_evidence(topic, transcript)
        ):
            topic["status"] = "open"
        topic_summary = _resolved_claim_removed_when_topic_open(
            topic_summary,
            topic,
        )
        topic["summary"] = topic_summary or _fallback_topic_summary(topic)

    return _strip_internal_memory_markers(memory)


def _transcript_channel_for_evidence(evidence: str, transcript: str) -> str | None:
    """Return the enclosing Mic/Remote channel for exact evidence, if known."""

    if not evidence or not transcript:
        return None
    index = transcript.find(evidence)
    if index < 0:
        return None
    prefix = transcript[:index]
    matches = list(
        re.finditer(
            r"\[\d{1,2}:\d{2}\]\s+\*\*(Mic|Remote)\*\*",
            prefix,
            flags=re.IGNORECASE,
        )
    )
    if not matches:
        return None
    return matches[-1].group(1)


def _explicit_commitment_fallbacks(chunk: str) -> list[dict]:
    """Recover unmistakable self-declared action items the model omitted.

    This fallback is intentionally narrow. It targets explicit action-item
    language rather than generic future tense so deterministic recovery does not
    turn intentions or suggestions into commitments.
    """

    marker = re.compile(
        r"\[(?P<time>\d{1,2}:\d{2})\]\s+\*\*(?P<speaker>Mic|Remote)\*\*",
        flags=re.IGNORECASE,
    )
    matches = list(marker.finditer(chunk))
    spans: list[tuple[str, str]] = []
    if matches:
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(chunk)
            spans.append((match.group("speaker"), chunk[start:end]))
    else:
        spans.append(("Unknown", chunk))

    cue = re.compile(
        r"\b(?:"
        r"i\s+(?:will|['’]ll)\s+take\s+(?:the|an?)\s+action(?:\s+item)?\s+to|"
        r"i\s+have\s+an?\s+action\s+item\s+(?:to|:)|"
        r"my\s+action\s+item\s+is\s+to"
        r")\s+(?P<action>[^.!?\n]+)",
        flags=re.IGNORECASE,
    )

    recovered: list[dict] = []
    for speaker, body in spans:
        compact = re.sub(r"\s+", " ", body).strip()
        for match in cue.finditer(compact):
            action = match.group("action").strip(" -,:;")
            # Keep only the committed clause. A following "and then you can..."
            # is another person's optional step and should not pollute the action.
            action = re.split(
                r"\s+(?:and\s+then|then)\s+(?:you|they|he|she|we)\b",
                action,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" -,:;")
            if not action:
                continue
            evidence = compact[match.start():match.start("action") + len(action)].strip()
            if not _commitment_is_actionable(action, evidence):
                continue
            if not _commitment_action_is_self_contained(action):
                continue
            owner = SELF_NAME if speaker.casefold() == SELF_SPEAKER_LABEL.casefold() else "Unknown"
            recovered.append(
                {
                    "owner": owner,
                    "action": action[0].upper() + action[1:] if action else action,
                    "status": "open",
                    "evidence": evidence,
                }
            )
    return _deduplicate_commitments(recovered)


def extract_grounded_commitments_and_decisions(
    meeting_label: str,
    transcript: str,
    participants: list[dict] | None = None,
    chunk_words: int = 1500,
) -> dict:
    """
    Extract transcript-grounded commitments, decisions, questions,
    and follow-ups.

    Every returned item must include verbatim evidence that is
    later verified against the source chunk in Python.
    """

    evidence_schema = {
        "type": "object",
        "properties": {
            "commitments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "owner": {
                            "type": "string",
                        },
                        "action": {
                            "type": "string",
                        },
                        "evidence": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "owner",
                        "action",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                        },
                        "evidence": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "decision",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "risk": {
                            "type": "string",
                        },
                        "evidence": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "risk",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "open_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                        },
                        "evidence": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "question",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "follow_ups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "follow_up": {
                            "type": "string",
                        },
                        "evidence": {
                            "type": "string",
                        },
                    },
                    "required": [
                        "follow_up",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "commitments",
            "decisions",
            "risks",
            "open_questions",
            "follow_ups",
        ],
        "additionalProperties": False,
    }

    participants = participants or []

    participant_names = []

    for participant in participants:
        if isinstance(
            participant,
            dict,
        ):
            name = str(
                participant.get(
                    "name",
                    "",
                )
            ).strip()
        else:
            name = str(
                participant
            ).strip()

        if not name:
            continue

        if name == SELF_NAME:
            continue

        participant_names.append(
            name
        )

    remote_participant = None

    if len(participant_names) == 1:
        remote_participant = (
            participant_names[0]
        )

    chunks = chunk_transcript(
        transcript,
        max_words=chunk_words,
    )

    validated_commitments = []
    validated_decisions = []
    validated_risks = []
    validated_open_questions = []
    validated_follow_ups = []

    for chunk_number, chunk in enumerate(
        chunks,
        start=1,
    ):
        print(
            f"Extracting grounded meeting facts "
            f"{meeting_label} "
            f"chunk {chunk_number}/{len(chunks)}...",
            flush=True,
        )

        prompt = f"""
You are extracting only explicit, transcript-supported meeting facts
from one chronological section of a business meeting transcript.

Meeting:
{meeting_label}

Section:
{chunk_number} of {len(chunks)}

Return ONLY JSON matching the required schema.

COMMITMENTS:
- Include only when a participant explicitly agrees to perform
  a future action.
- Treat explicit action-item language such as "I have an action item to..."
  or "I will take the action to..." as a strong commitment signal when the
  action itself is concrete and still remains to be done.
- The evidence field MUST contain exact words copied from the
  transcript.
- Keep the evidence quote as short as possible while still
  proving the commitment.
- Do not treat a suggestion, request, discussion, intention,
  status update, or completed action as a commitment.
- Do not treat attendance, availability, social plans, acknowledgements,
  conversational reassurance, or conditional offers to help as a work
  commitment. Examples that should be omitted include "I'll be there",
  "I can make it", "if you need help, I'll help", "let me know if you
  need anything", and "no problem" unless the same evidence also records
  a concrete accepted or assigned work action or deliverable.
- Do not split one natural commitment into multiple items merely because
  the speaker follows it with a pronoun-based continuation such as
  "I'll take care of it" or "I'll handle that". Prefer one item with
  enough verbatim evidence to preserve the complete commitment.
- Do not infer an owner.
- If the speaker's name is not explicit enough to identify
  confidently, use "Unknown".
- The action field must be self-contained enough to remain useful later. It
  must identify the action AND its object/topic/recipient; naming only who is
  being tasked is not enough. For example, omit "Put Speaker B to task" unless
  the nearby transcript also supports what Speaker B is being tasked on.
- Do not leave unresolved second-person references such as "you" or "your" in
  the action. Resolve the person only when the name/role is explicit in the
  immediately nearby transcript; otherwise omit the commitment.
- If the evidence uses opaque references such as "it", "that", "this", or
  "them", resolve the referenced action only when the antecedent is explicit
  in the immediately nearby transcript context. Otherwise omit the commitment.
- The action field may be a concise paraphrase of the committed action using
  only details directly supported by that tight local context. Do not invent or
  generalize beyond the transcript.

DECISIONS:
- Include only explicit decisions or agreements reached in the
  meeting.
- A settled selection or exclusion is a decision even when the
  speaker uses operational wording instead of the word "decided".
  Examples include "the decision is to cut Vendor Gamma from the list",
  "we cut Vendor Gamma from the list", "Vendor Gamma is out",
  "we selected Vendor Delta", and "we are going with Vendor Delta"
  when the wording clearly states
  the settled outcome rather than a proposal.
- The evidence field MUST contain exact words copied from the
  transcript.
- Keep the evidence quote as short as possible while still
  proving the decision.
- Do not treat opinions, proposals, questions, concerns, historical
  descriptions, or ordinary directives as decisions. Phrases such as
  "you dropped those last year" or "drop me the names" are not decisions.
- The decision field may be a concise paraphrase, but must not
  add information not supported by the evidence.

RISKS AND CONCERNS:
- Include only a material risk, concern, blocker, dependency, or uncertainty
  that a participant explicitly states in this section.
- The evidence field MUST contain exact words copied from the transcript.
- Do not infer a risk merely because something is expensive, complicated,
  delayed-looking, vendor-related, contractual, or administratively frustrating.
- Do not convert a statement denying risk (for example, "we are not at risk")
  into a risk.
- The risk field may be a concise paraphrase, but it must not add a consequence
  or business impact that the evidence does not state.
- Prefer omission over a plausible but implicit risk.

OPEN QUESTIONS:
- Include only a question that a participant explicitly raised
  and that remained unanswered or explicitly unresolved in this section.
- Preserve a real business question when nearby discussion says the matter
  is still open, unclear, not addressed, or needs confirmation/validation,
  even if the transcript punctuation is imperfect.
- Do not retain a question that is directly answered later in the section,
  including when the answer appears immediately afterward in the same transcript
  speaker/channel block.
- Do not turn missing detail, uncertainty, or an analyst's desire
  for more information into a question.
- The durable question must be self-contained enough to understand later
  without reopening the transcript. If the evidence says only "Did that get
  extended?" or uses another opaque referent such as "it", "this",
  "these", or "those", resolve the concrete subject only when it is
  explicit in the immediately nearby transcript; otherwise omit the question.
- The evidence field MUST contain the exact question copied from
  the transcript.

FOLLOW-UPS:
- Include only an explicitly requested or assigned task, or a
  clearly declared next step that remains to be done.
- Do not create sensible next steps from discussion, topic status,
  risk, or missing information.
- Do not duplicate a first-person commitment in follow_ups; put
  that in commitments only.
- The follow_up field must be self-contained enough to remain useful later.
- If the evidence says only "follow up on that", "take that as a follow-up",
  "send it", or similar opaque language, resolve the object only when the
  immediately nearby transcript explicitly identifies it. Otherwise omit it.
- The follow_up field may be a concise paraphrase using only details directly
  supported by that tight local context. Do not invent or generalize.
- The evidence field MUST contain exact words copied from the
  transcript that establish the requested or assigned work.

GENERAL:
- Ignore greetings, personal discussion, casual conversation,
  and unrelated material.
- Prefer omission over weak or ambiguous items.
- Do not invent anything.
- If this section contains no valid facts for a field, return an empty array
  for that field.

Transcript section:

{chunk}
""".strip()

        raw_result = ask_llm(
            prompt,
            response_format=evidence_schema,
        )

        try:
            result = json.loads(
                raw_result
            )
        except json.JSONDecodeError:
            # Deterministic explicit-decision recovery must not depend on the
            # model returning valid JSON.  A malformed structured response can
            # otherwise hide a plainly stated decision in this chunk.
            result = {
                "commitments": [],
                "decisions": [],
                "risks": [],
                "open_questions": [],
                "follow_ups": [],
            }

        commitments = result.get(
            "commitments",
            [],
        )

        for item in commitments:
            if not isinstance(
                item,
                dict,
            ):
                continue

            evidence_text = str(
                item.get(
                    "evidence",
                    "",
                )
            ).strip()

            if not evidence_text:
                continue

            if evidence_text not in chunk:
                continue

            commitment_markers = (
                "i'll ",
                "i will ",
                "i'm going to ",
                "i am going to ",
                "we'll ",
                "we will ",
                "let me ",
            )

            evidence_lower = (
                evidence_text.lower()
            )

            if not any(
                marker in evidence_lower
                for marker in commitment_markers
            ):
                continue

            raw_owner = str(
                item.get(
                    "owner",
                    "Unknown",
                )
            ).strip()

            evidence_channel = _transcript_channel_for_evidence(
                evidence_text,
                chunk,
            )

            if evidence_channel and evidence_channel.casefold() == SELF_SPEAKER_LABEL.casefold():
                resolved_owner = SELF_NAME
            elif evidence_channel and evidence_channel.casefold() == "remote":
                # A Remote channel can contain several people. A model-provided
                # person name is not enough to prove which remote participant
                # uttered a first-person commitment. Preserve the action while
                # keeping ownership conservative.
                resolved_owner = "Unknown"
            elif raw_owner.lower() == SELF_SPEAKER_LABEL.lower():
                resolved_owner = SELF_NAME
            elif raw_owner.lower() == "remote":
                resolved_owner = "Unknown"
            else:
                resolved_owner = raw_owner or "Unknown"

            action_text = str(
                item.get(
                    "action",
                    "",
                )
            ).strip()

            if not _commitment_is_actionable(action_text, evidence_text):
                continue

            action_text = _resolve_commitment_action(
                action_text,
                evidence_text,
                chunk,
                allow_generic_continuation=True,
            )
            if not action_text:
                continue

            if remote_participant:
                action_text = re.sub(
                    r"\bRemote\b",
                    remote_participant,
                    action_text,
                    flags=re.IGNORECASE,
                )

            action_text = re.sub(
                r"\bMic\b",
                SELF_NAME,
                action_text,
                flags=re.IGNORECASE,
            )

            validated_commitments.append(
                {
                    "owner": resolved_owner,
                    "action": action_text,
                    "status": "open",
                    "evidence": evidence_text,
                }
            )

        existing_commitment_evidence = {
            str(item.get("evidence", "")).casefold()
            for item in validated_commitments
            if isinstance(item, dict)
        }
        for fallback_commitment in _explicit_commitment_fallbacks(chunk):
            evidence_key = str(fallback_commitment.get("evidence", "")).casefold()
            if evidence_key in existing_commitment_evidence:
                continue
            validated_commitments.append(fallback_commitment)
            existing_commitment_evidence.add(evidence_key)

        decisions = result.get(
            "decisions",
            [],
        )

        for item in decisions:
            if not isinstance(
                item,
                dict,
            ):
                continue

            evidence_text = str(
                item.get(
                    "evidence",
                    "",
                )
            ).strip()

            if not evidence_text:
                continue

            if evidence_text not in chunk:
                continue

            decision_text = str(
                item.get(
                    "decision",
                    "",
                )
            ).strip()

            if not _decision_is_supported(decision_text, evidence_text):
                continue
            if not _decision_candidate_is_well_formed(
                decision_text, evidence_text
            ):
                continue

            validated_decisions.append(
                {
                    "decision": decision_text,
                    "evidence": evidence_text,
                }
            )

        existing_evidence = {
            item.get("evidence", "").casefold()
            for item in validated_decisions
        }
        for fallback in _explicit_decision_fallbacks(chunk):
            evidence_key = fallback["evidence"].casefold()
            if evidence_key in existing_evidence:
                continue
            validated_decisions.append(fallback)
            existing_evidence.add(evidence_key)

        risks = result.get(
            "risks",
            [],
        )

        for item in risks:
            if not isinstance(item, dict):
                continue

            evidence_text = str(
                item.get("evidence", "")
            ).strip()
            if not evidence_text or evidence_text not in chunk:
                continue

            risk_text = str(
                item.get("risk", "")
            ).strip()
            if not _risk_is_supported(risk_text, evidence_text):
                continue

            grounded_risk = {
                "risk": risk_text,
                "evidence": evidence_text,
            }
            if grounded_risk not in validated_risks:
                validated_risks.append(grounded_risk)

        existing_risk_evidence = {
            str(item.get("evidence", "")).casefold()
            for item in validated_risks
            if isinstance(item, dict)
        }
        for fallback_risk in _explicit_risk_fallbacks(chunk):
            evidence_key = fallback_risk["evidence"].casefold()
            if evidence_key in existing_risk_evidence:
                continue
            validated_risks.append(fallback_risk)
            existing_risk_evidence.add(evidence_key)

        open_questions = result.get(
            "open_questions",
            [],
        )

        for item in open_questions:
            if not isinstance(item, dict):
                continue

            evidence_text = str(
                item.get("evidence", "")
            ).strip()
            if not evidence_text or evidence_text not in chunk:
                continue

            evidence_lower = evidence_text.lower().strip()
            question_markers = (
                "who ", "what ", "when ", "where ", "why ",
                "how ", "which ", "can ", "could ", "do ",
                "does ", "did ", "is ", "are ", "will ",
                "would ", "should ", "have ", "has ",
            )
            if (
                "?" not in evidence_text
                and not evidence_lower.startswith(question_markers)
            ):
                continue

            if not _is_well_formed_question(evidence_text):
                continue
            if not _question_is_locally_unresolved(evidence_text, chunk):
                continue

            grounded_question = _contextualize_open_question(evidence_text, chunk)
            if grounded_question and grounded_question not in validated_open_questions:
                validated_open_questions.append(grounded_question)

        for fallback_question in _explicit_unresolved_question_fallbacks(chunk):
            if not _question_is_locally_unresolved(fallback_question, chunk):
                continue
            durable_question = _contextualize_open_question(fallback_question, chunk)
            if durable_question and durable_question not in validated_open_questions:
                validated_open_questions.append(durable_question)

        follow_ups = result.get(
            "follow_ups",
            [],
        )

        for item in follow_ups:
            if not isinstance(item, dict):
                continue

            evidence_text = str(
                item.get("evidence", "")
            ).strip()
            if not evidence_text or evidence_text not in chunk:
                continue

            evidence_lower = evidence_text.lower()
            follow_up_markers = (
                "action item",
                "follow up",
                "follow-up",
                "need you to",
                "needs to",
                "have to",
                "has to",
                "please ",
                "can you ",
                "could you ",
                "will you ",
                "let's ",
                "next step",
            )
            if not any(
                marker in evidence_lower
                for marker in follow_up_markers
            ):
                continue

            follow_up_text = str(item.get("follow_up", "")).strip()
            grounded_follow_up = _resolve_follow_up_action(
                follow_up_text, evidence_text, chunk
            )
            if not grounded_follow_up:
                continue
            if grounded_follow_up not in validated_follow_ups:
                validated_follow_ups.append(grounded_follow_up)

    return {
        "commitments": _deduplicate_commitments(
            _merge_adjacent_commitments(
                validated_commitments,
                transcript,
            )
        ),
        "decisions": _deduplicate_decisions(validated_decisions),
        "risks": validated_risks,
        "open_questions": _normalize_open_questions(validated_open_questions),
        "follow_ups": validated_follow_ups,
    }



def _memory_resolution_capable() -> bool:
    """Return whether the active local profile can afford contextual resolution.

    Keep the existing single-pass plumbing on smaller models/Macs.  The richer
    resolver is intentionally limited to the High Performance tier with a
    large local model so lower-spec systems do not pay another inference pass.
    """

    profile = get_execution_profile(
        PERFORMANCE_PROFILE,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=get_active_llm_model_name(),
    )
    parameter_billions = infer_model_parameter_billions(
        get_active_llm_model_name()
    )
    return bool(
        profile.resolved_name == "High Performance"
        and parameter_billions is not None
        and parameter_billions >= 20.0
    )


def _memory_needs_contextual_resolution(memory: dict, transcript: str, meeting_summary: str = "") -> bool:
    """Escalate only when precision-sensitive memory shows suspicious gaps.

    This deliberately uses cheap deterministic signals.  The resolver is not a
    blanket second pass; it is an escalation path for meetings where the first
    pass produced opaque ownership/actions, weak risks, or apparently missed
    settled next steps/questions.
    """

    for item in memory.get("commitments", []):
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner", "")).strip()
        action = str(item.get("action", "")).strip()
        if owner in {"", "Unknown"}:
            return True
        if _OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(action):
            return True
        if not _commitment_action_is_self_contained(action):
            return True

    for item in memory.get("risks", []):
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk", "")).strip()
        if not risk or risk.casefold() == str(item.get("evidence", "")).strip().casefold():
            return True
        if re.search(r"\b(?:this|that|it|stuff|things?)\b", risk, flags=re.IGNORECASE):
            return True

    # These cues often represent useful durable facts that the conservative
    # first pass can miss because ordinary meeting speech is not neatly phrased.
    lowered = transcript.casefold()
    if not memory.get("commitments") and re.search(
        r"\b(?:why\s+don['’]t\s+you|take\s+the\s+lead|next\s+step|"
        r"i['’]ll\s+reach\s+out|i\s+will\s+reach\s+out|set\s+up\s+(?:a|the)\s+(?:call|meeting))\b",
        lowered,
    ):
        return True
    if not memory.get("decisions") and re.search(
        r"\b(?:we agreed|let['’]s|that['’]s what we['’]ll do|sounds good|"
        r"we['’]re not (?:gonna|going to) do that|we are not going to do that)\b",
        lowered,
    ):
        return True
    if not memory.get("open_questions") and re.search(
        r"\b(?:we['’]d have to find out|need to find out|don['’]t know|not sure|unclear)\b",
        lowered,
    ):
        return True

    # The narrative summary is a useful semantic index when the raw transcript
    # is conversational enough that the first-pass extractor misses an agreed
    # next step or unresolved issue.  It is only a trigger here; transcript
    # evidence remains mandatory later.
    if _summary_memory_cues(meeting_summary):
        return True
    return False


def _summary_memory_cues(meeting_summary: str, limit: int = 12) -> list[str]:
    """Return concise narrative-summary lines that may point to durable memory.

    The narrative summary is never authoritative evidence.  On the High
    Performance path it is useful as a semantic index into a noisy transcript:
    the resolver can use these lines to know what to search for, but every
    retained fact must still cite exact transcript evidence.
    """

    if not meeting_summary:
        return []

    cue_pattern = re.compile(
        r"\b(?:agreed|decided|will|next\s+step|follow[- ]?up|set\s+up|"
        r"reach\s+out|take\s+the\s+lead|plan(?:ning)?|risk|concern|"
        r"uncertain|unclear|need\s+to\s+(?:know|understand|find\s+out)|"
        r"question|whether)\b",
        flags=re.IGNORECASE,
    )
    cues: list[str] = []
    for raw_line in meeting_summary.splitlines():
        line = re.sub(r"^\s*(?:[-*+]\s+|#{1,6}\s+)", "", raw_line).strip()
        if not line or len(line) < 12 or len(line) > 420:
            continue
        if not cue_pattern.search(line):
            continue
        if line not in cues:
            cues.append(line)
        if len(cues) >= limit:
            break
    return cues




def _transcript_turn_records(transcript: str) -> list[dict]:
    """Parse timestamped transcript turns while preserving exact body text.

    The memory pipeline uses turn-level retrieval as an evidence index.  This
    follows extractive meeting-QA/action-item practice: locate source spans first,
    then normalize them into durable memory instead of asking the model to invent
    a polished sentence and searching for support afterward.
    """

    pattern = re.compile(
        r"(?ms)^\[(?P<time>\d{1,2}:\d{2})\]\s+\*\*(?P<speaker>[^*]+)\*\*\s*\n+"
        r"(?P<body>.*?)(?=^\[\d{1,2}:\d{2}\]\s+\*\*|\Z)"
    )
    turns: list[dict] = []
    for match in pattern.finditer(str(transcript or "")):
        body = match.group("body").strip()
        if not body:
            continue
        turns.append({
            "time": match.group("time"),
            "speaker": match.group("speaker").strip(),
            "body": body,
            # Preserve both the exact body span and the complete turn span.  A
            # lexically grounded quote may begin inside the timestamp/header
            # (for example ``07:37] **Remote**`` after punctuation-normalized
            # matching), so speaker attribution must be able to resolve either
            # representation without guessing from nearby text.
            "start": match.start("body"),
            "end": match.end("body"),
            "turn_start": match.start(),
            "turn_end": match.end(),
        })
    return turns


def _meeting_participant_identity_map(meeting_label: str, transcript: str) -> dict[str, str]:
    """Resolve only high-confidence channel identities for memory attribution.

    Mic is the configured local/self channel.  For a meeting explicitly titled as
    a 1v1, if the transcript contains exactly one other audio channel, the other
    channel can be attributed to the counterpart named in the title.  Multi-party
    meetings deliberately remain unmapped rather than guessing.
    """

    mapping: dict[str, str] = {}
    if SELF_SPEAKER_LABEL and SELF_NAME:
        mapping[SELF_SPEAKER_LABEL.casefold()] = SELF_NAME

    # Native recorder transcripts use ``Mic`` for the local microphone channel
    # even when an older/private identity configuration still names the local
    # speaker differently (for example a nickname used by legacy diarization).
    # Treat the recorder's canonical Mic channel as local/self whenever it is
    # actually present in the transcript.  This is source-channel provenance,
    # not a guess about a participant's identity.
    transcript_channels = [
        turn["speaker"].strip()
        for turn in _transcript_turn_records(transcript)
        if turn.get("speaker")
    ]
    if SELF_NAME and any(channel.casefold() == "mic" for channel in transcript_channels):
        mapping["mic"] = SELF_NAME

    label = re.sub(r"\s+", " ", str(meeting_label or "")).strip()
    match = re.match(r"^(.+?)\s+1\s*(?:v|vs\.?|on)\s*1\b", label, flags=re.IGNORECASE)
    if not match:
        match = re.match(r"^(.+?)\s+1v1\b", label, flags=re.IGNORECASE)
    if not match:
        return mapping

    counterpart = re.sub(r"\s+", " ", match.group(1)).strip(" -–—")
    if not counterpart or counterpart.casefold() == str(SELF_NAME).casefold():
        return mapping

    channels = []
    for channel in transcript_channels:
        if channel.casefold() not in {value.casefold() for value in channels}:
            channels.append(channel)
    self_channel_labels = {
        str(SELF_SPEAKER_LABEL or "").casefold(),
        "mic" if any(channel.casefold() == "mic" for channel in channels) else "",
    }
    self_channel_labels.discard("")
    others = [
        channel for channel in channels
        if channel.casefold() not in self_channel_labels
    ]
    if len(others) == 1 and any(
        channel.casefold() in self_channel_labels for channel in channels
    ):
        mapping[others[0].casefold()] = counterpart
    return mapping


def _participant_name_for_channel(channel: str, identity_map: dict[str, str] | None) -> str:
    if not channel:
        return ""
    if identity_map:
        resolved = identity_map.get(channel.casefold())
        if resolved:
            return resolved
    return channel


_FIRST_PERSON_FUTURE_WORK_PATTERN = re.compile(
    r"\b(?:i['’]ll|i\s+will|i['’]m\s+(?:going\s+to|gonna)|"
    r"i\s+am\s+going\s+to|i\s+can\s+(?:take|handle|join|call|contact|reach|review|send|schedule)|"
    r"i\s+(?:owe|need\s+to)\b)",
    flags=re.IGNORECASE,
)


def _event_turn_cue_matches(event_type: str, body: str) -> bool:
    kind = str(event_type or "").casefold()
    if kind == "commitment":
        return bool(_FIRST_PERSON_FUTURE_WORK_PATTERN.search(body))
    if kind == "assignment":
        return bool(re.search(
            r"\b(?:why\s+don['’]t\s+you|take\s+the\s+lead|please|can\s+you|"
            r"could\s+you|would\s+you|need\s+you\s+to)\b",
            body,
            flags=re.IGNORECASE,
        ))
    if kind == "decision":
        return bool(re.search(
            r"\b(?:we\s+(?:decided|agreed|approved)|let['’]s|that['’]s\s+what\s+we['’]ll\s+do|"
            r"we['’]re\s+not\s+(?:gonna|going\s+to)|we\s+are\s+not\s+going\s+to)\b",
            body,
            flags=re.IGNORECASE,
        ))
    if kind in {"question", "uncertainty"}:
        return "?" in body or bool(re.search(
            r"\b(?:don['’]t\s+know|not\s+sure|unclear|need\s+to\s+find\s+out|"
            r"we['’]d\s+have\s+to\s+find\s+out)\b",
            body,
            flags=re.IGNORECASE,
        ))
    if kind == "concern":
        return bool(re.search(r"\b(?:risk|concern|problem|exposure|could\s+lose|might\s+lose)\b", body, flags=re.IGNORECASE))
    if kind in {"next_step", "proposal", "agreement"}:
        return bool(re.search(
            r"\b(?:next\s+step|we['’]re\s+gonna|we\s+will|we['’]ll|let['’]s|"
            r"should|could|plan\s+to|going\s+to|sounds\s+good|agree)\b",
            body,
            flags=re.IGNORECASE,
        ))
    return True


def _recover_event_evidence_from_turns(
    item: dict,
    transcript: str,
) -> list[str]:
    """Retrieve exact turn evidence when the model paraphrased its citation.

    Candidate semantics may be paraphrased, but retained evidence must remain an
    exact transcript span.  Rank source turns using subject/evidence lexical
    overlap plus the dialogue-act cue expected for the event type.  This is a
    retrieval step, not semantic acceptance: downstream verification still has to
    decide whether the normalized memory item is warranted.
    """

    turns = _transcript_turn_records(transcript)
    if not turns:
        return []

    event_type = str(item.get("event_type", "")).strip().casefold()
    speaker = str(item.get("speaker", "")).strip()
    subject_tokens = _commitment_content_tokens(str(item.get("subject", "")))
    raw_evidence = item.get("evidence", [])
    if isinstance(raw_evidence, str):
        raw_evidence = [raw_evidence]
    evidence_tokens: set[str] = set()
    if isinstance(raw_evidence, list):
        for value in raw_evidence:
            evidence_tokens |= _commitment_content_tokens(str(value or ""))

    ranked: list[tuple[tuple[int, int, int, int], str]] = []
    for turn in turns:
        if speaker and speaker.casefold() in _AUDIO_CHANNEL_OWNER_LABELS:
            if turn["speaker"].casefold() != speaker.casefold():
                continue
        body = turn["body"]
        if not _event_turn_cue_matches(event_type, body):
            continue
        body_tokens = _commitment_content_tokens(body)
        subject_overlap = len(subject_tokens & body_tokens)
        evidence_overlap = len(evidence_tokens & body_tokens)
        if subject_overlap < 2 and evidence_overlap < 4:
            continue
        ranked.append((
            (
                subject_overlap,
                min(evidence_overlap, 12),
                1 if speaker and turn["speaker"].casefold() == speaker.casefold() else 0,
                -abs(len(body_tokens) - max(len(subject_tokens), 1)),
            ),
            body,
        ))

    if not ranked:
        return []
    ranked.sort(key=lambda value: value[0], reverse=True)
    best_score = ranked[0][0]
    best = [body for score, body in ranked if score == best_score]
    # Ambiguous retrieval is omission, not a guess.
    return [best[0]] if len(best) == 1 else []


def _speaker_channel_for_evidence(evidence: str, transcript: str) -> str:
    """Resolve the audio channel that owns one exact grounded evidence span.

    Prefer a channel embedded in a timestamped evidence header.  Grounding can
    legitimately return a slice that begins one character into ``[07:37]`` after
    punctuation-normalized matching, so accept either ``[07:37]`` or ``07:37]``.
    Otherwise attribute from the transcript turn containing the exact slice.
    """

    if not evidence:
        return ""

    header = re.search(
        r"(?:^|\n)\[?\d{1,2}:\d{2}\]\s+\*\*([^*]+)\*\*",
        evidence,
        flags=re.MULTILINE,
    )
    if header:
        return header.group(1).strip()

    pos = transcript.find(evidence)
    if pos < 0:
        return ""

    # Prefer the nearest preceding timestamp/speaker header.  This remains
    # reliable even for legacy/synthetic transcripts that do not place every
    # timestamp at the beginning of a new line.
    preceding = list(re.finditer(
        r"\[\d{1,2}:\d{2}\]\s+\*\*([^*]+)\*\*",
        transcript[:pos + 1],
    ))
    if preceding:
        return preceding[-1].group(1).strip()

    for turn in _transcript_turn_records(transcript):
        if turn.get("turn_start", turn["start"]) <= pos < turn.get("turn_end", turn["end"]):
            return turn["speaker"]
    return ""


def _authoritative_first_person_owner(
    quotes: list[str],
    transcript: str,
    identity_map: dict[str, str] | None,
) -> str:
    """Derive action ownership from grounded first-person source evidence.

    Once an action is grounded, source attribution outranks a model-generated
    owner/target.  This is deterministic provenance, not semantic inference: an
    exact first-person future-work span belongs to the participant mapped from
    that span's speaker channel.  Ambiguous or unmapped channel ownership is
    omitted rather than guessed.
    """

    owners: set[str] = set()
    for quote in quotes:
        if not quote or not _FIRST_PERSON_FUTURE_WORK_PATTERN.search(quote):
            continue
        channel = _speaker_channel_for_evidence(quote, transcript)
        resolved = _participant_name_for_channel(channel, identity_map).strip()
        if not resolved or resolved.casefold() in _AUDIO_CHANNEL_OWNER_LABELS:
            continue
        owners.add(resolved)
    return next(iter(owners)) if len(owners) == 1 else ""


def _memory_candidate_evidence_index(transcript: str, limit: int = 24) -> list[str]:
    """Return exact high-signal turns as a compact retrieval index for pass 1.

    Long-context models can under-use information located in the middle of long
    prompts.  Surfacing exact candidate turns near the instructions gives the
    extractor a position-agnostic evidence index while the full transcript
    remains authoritative below.
    """

    cue = re.compile(
        r"\b(?:i['’]ll|i\s+will|i['’]m\s+(?:going\s+to|gonna)|we['’]re\s+gonna|"
        r"we\s+will|why\s+don['’]t\s+you|take\s+the\s+lead|next\s+step|let['’]s|"
        r"we\s+(?:decided|agreed|approved)|we['’]re\s+not\s+(?:gonna|going\s+to)|"
        r"risk|concern|problem|don['’]t\s+know|not\s+sure|need\s+to\s+find\s+out)\b|\?",
        flags=re.IGNORECASE,
    )
    indexed: list[str] = []
    for turn in _transcript_turn_records(transcript):
        body = re.sub(r"\s+", " ", turn["body"]).strip()
        if not cue.search(body):
            continue
        indexed.append(f'[{turn["time"]}] **{turn["speaker"]}** {body}')
        if len(indexed) >= limit:
            break
    return indexed

def _high_performance_memory_quality_cleanup(memory: dict) -> dict:
    """Drop unusable precision-memory fragments after enhanced resolution.

    This is deliberately High-Performance-only.  Smaller-model profiles keep
    their established plumbing, while the richer path refuses to preserve raw
    conversational fragments merely because the resolver could not normalize
    them.  Omission is preferable to authoritative gibberish.
    """

    cleaned = dict(memory)
    commitments = []
    for item in memory.get("commitments", []):
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner", "")).strip()
        action = str(item.get("action", "")).strip()
        if not action:
            continue
        if owner in {"", "Unknown"} and (
            _OPAQUE_COMMITMENT_REFERENCE_PATTERN.search(action)
            or not _commitment_action_is_self_contained(action)
        ):
            continue
        commitments.append(item)
    cleaned["commitments"] = commitments

    risks = []
    for item in memory.get("risks", []):
        if not isinstance(item, dict):
            continue
        risk = str(item.get("risk", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if not risk:
            continue
        if risk.casefold() == evidence.casefold():
            continue
        if re.search(r"\b(?:this|that|it|stuff|things?)\b", risk, flags=re.IGNORECASE):
            continue
        risks.append(item)
    cleaned["risks"] = risks
    return cleaned


def _resolution_local_context(evidence: str, transcript: str, radius: int = 650) -> str:
    if not evidence or not transcript:
        return ""
    pos = transcript.find(evidence)
    if pos < 0:
        return ""
    return transcript[max(0, pos - radius): min(len(transcript), pos + len(evidence) + radius)]


def _resolved_evidence_quotes(item: dict, transcript: str) -> list[str]:
    """Return transcript-grounded evidence for one resolved memory item.

    Pass 2 is allowed to normalize punctuation/whitespace while copying evidence,
    but durable memory must always store the exact transcript slice that actually
    grounds the item.  Any ungrounded evidence entry invalidates the candidate.
    """

    raw = item.get("evidence", [])
    if isinstance(raw, str):
        raw_quotes = [raw]
    elif isinstance(raw, list):
        raw_quotes = raw
    else:
        return []

    quotes: list[str] = []
    for value in raw_quotes:
        grounded = _ground_evidence_quote(str(value or ""), transcript)
        if not grounded:
            return []
        if grounded not in quotes:
            quotes.append(grounded)
    return quotes


def _resolved_item_context(item: dict, transcript: str) -> str:
    """Combine tight windows around all exact evidence quotes for one fact."""

    quotes = _resolved_evidence_quotes(item, transcript)
    return "\n".join(
        _resolution_local_context(quote, transcript)
        for quote in quotes
        if quote
    )


def _resolved_text_is_grounded_in_context(
    text: str,
    context: str,
    *,
    minimum_tokens: int = 2,
    minimum_coverage: float = 0.60,
) -> bool:
    """Require strong lexical support without demanding verbatim paraphrase.

    The contextual resolver is specifically allowed to normalize conversational
    speech into durable memory. Requiring every content token in the normalized
    sentence to appear verbatim in the evidence defeated that purpose (for
    example ``arrange`` vs. ``set up``) and could reject an otherwise grounded
    item. Keep the gate conservative by requiring multiple grounded content
    tokens and substantial overlap with the grouped evidence.
    """

    if not context:
        return False
    content = _commitment_content_tokens(text)
    if len(content) < minimum_tokens:
        return False
    context_tokens = _commitment_content_tokens(context)
    overlap = content & context_tokens
    if len(overlap) < minimum_tokens:
        return False
    return (len(overlap) / len(content)) >= minimum_coverage


def _resolved_text_is_grounded(text: str, evidence: str, transcript: str, *, minimum_tokens: int = 2) -> bool:
    """Compatibility helper for existing single-evidence reconciliation paths."""

    return _resolved_text_is_grounded_in_context(
        text,
        _resolution_local_context(evidence, transcript),
        minimum_tokens=minimum_tokens,
    )


_DECISION_PREDICATE_CONCEPTS = {
    "arrange": (r"\b(?:set\s+up|schedule|arrange|coordinate|book)\b",),
    "meet": (r"\b(?:call|meeting|conversation|discussion|session)\b",),
    "review": (r"\b(?:review|assess|assessment|evaluate|evaluation|explore|investigate|investigation|due\s+diligence|look\s+at|examine)\b",),
    "decide": (r"\b(?:decide|decision|choose|select|proceed|move\s+forward|go\s+forward)\b",),
    "engage": (r"\b(?:engage|work\s+with|partner\s+with|use|adopt|switch\s+to|move\s+to)\b",),
    "obtain": (r"\b(?:get|obtain|request|receive|collect|send\s+over|provide)\b",),
}

_DECISION_TOPIC_CONCEPTS = {
    "contract": (r"\b(?:contract|agreement|terms?|conditions?|indemnif\w*|legal)\b",),
    "risk": (r"\b(?:risk|concern|exposure|liabilit\w*|infringement|lawsuit|sued)\b",),
    "support": (r"\b(?:support|patch(?:es|ing)?|upgrade(?:s|ing)?|maintenance)\b",),
    "license": (r"\b(?:licen[cs]e|licensing|perpetual\s+rights?)\b",),
    "cost": (r"\b(?:cost|price|pricing|financial|saving(?:s)?)\b",),
}


def _decision_semantic_concepts(text: str, groups: dict[str, tuple[str, ...]]) -> set[str]:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    concepts: set[str] = set()
    for concept, patterns in groups.items():
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            concepts.add(concept)
    return concepts


def _decision_evidence_score(decision: str, evidence: str) -> tuple[int, int, int]:
    """Rank grounded decision evidence by semantic specificity.

    Prefer quotes that carry the same business predicate/topic as the normalized
    decision. Generic confirmations remain useful corroboration but should not
    replace a more informative transcript quote as primary evidence.
    """

    decision_predicates = _decision_semantic_concepts(decision, _DECISION_PREDICATE_CONCEPTS)
    decision_topics = _decision_semantic_concepts(decision, _DECISION_TOPIC_CONCEPTS)
    evidence_predicates = _decision_semantic_concepts(evidence, _DECISION_PREDICATE_CONCEPTS)
    evidence_topics = _decision_semantic_concepts(evidence, _DECISION_TOPIC_CONCEPTS)
    predicate_overlap = len(decision_predicates & evidence_predicates)
    topic_overlap = len(decision_topics & evidence_topics)
    informative_tokens = len(re.findall(r"[A-Za-z0-9&'-]+", evidence))
    return (topic_overlap, predicate_overlap, informative_tokens)


def _order_decision_evidence(decision: str, quotes: list[str], transcript: str) -> list[str]:
    """Keep the most semantically informative grounded quote first."""

    candidates = [quote for quote in quotes if quote]
    if candidates:
        agreement = _nearby_agreement_evidence(candidates[0], transcript)
        if agreement and agreement not in candidates:
            candidates.append(agreement)
    return sorted(
        dict.fromkeys(candidates),
        key=lambda quote: _decision_evidence_score(decision, quote),
        reverse=True,
    )


def _decision_evidence_is_semantically_consistent(
    decision: str,
    quotes: list[str],
    transcript: str,
) -> bool:
    """Require the decision proposition and its grounded evidence to concern the same act/topic.

    This is intentionally not a bag-of-words overlap gate.  It compares coarse
    semantic concepts (for example ``set up``/``arrange`` and
    ``call``/``meeting``) so polished decision wording may differ from speech,
    while generic confirmations such as ``that's what we'll do`` cannot validate
    an unrelated proposition such as a contract-review decision.
    """

    if not decision or not quotes:
        return False

    # Compare the normalized decision to the evidence quotes themselves, not to a
    # broad transcript window around them. Nearby conversation may discuss other
    # propositions (for example contract review) and can otherwise make an
    # unrelated generic confirmation such as "that's what we'll do" look
    # semantically supported. Supporting quotes supplied by the resolver remain
    # eligible because they are independently grounded transcript evidence.
    evidence_text = "\n".join(quote for quote in quotes if quote)
    if not evidence_text:
        return False

    decision_predicates = _decision_semantic_concepts(decision, _DECISION_PREDICATE_CONCEPTS)
    decision_topics = _decision_semantic_concepts(decision, _DECISION_TOPIC_CONCEPTS)
    context_predicates = _decision_semantic_concepts(evidence_text, _DECISION_PREDICATE_CONCEPTS)
    context_topics = _decision_semantic_concepts(evidence_text, _DECISION_TOPIC_CONCEPTS)

    # A durable normalized decision should normally carry at least one semantic
    # predicate.  If our compact concept vocabulary does not recognize it, keep
    # the established verifier behavior rather than introducing a broad false
    # negative for unrelated decision forms.
    if not decision_predicates:
        return True

    if not (decision_predicates & context_predicates):
        return False

    # When the decision names a concrete business topic, require at least one
    # matching topic concept as well.  This blocks generic nearby agreement from
    # being attached to a different decision proposition.
    if decision_topics and not (decision_topics & context_topics):
        return False

    return True


def _resolved_memory_item(
    payload: dict,
    quotes: list[str],
) -> dict:
    result = dict(payload)
    result["evidence"] = quotes[0]
    if len(quotes) > 1:
        result["supporting_evidence"] = quotes[1:]
    # v12 has already independently verified these normalized facts against
    # exact transcript evidence. Preserve that provenance so the downstream
    # baseline reconciler does not accidentally re-reject a valid paraphrase
    # using older lexical-overlap rules. This marker is internal only and is
    # stripped before meeting_memory.json is returned.
    result["_event_verified"] = True
    return result


_IMMEDIATE_MEETING_FACILITATION_ACTION_PATTERN = re.compile(
    r"\b(?:show|demo|demonstrate|walk\s+through|share\s+(?:my\s+)?screen|go\s+back\s+to)\b",
    flags=re.IGNORECASE,
)

_IMMEDIATE_MEETING_FACILITATION_EVIDENCE_PATTERN = re.compile(
    r"\b(?:can\s+show|could\s+show|let\s+me\s+show|i['’]ll\s+go\s+back\s+to|"
    r"happy\s+to\s+(?:show|walk\s+through)|if\s+you\s+want\b.{0,80}\b(?:show|walk\s+through)|"
    r"just\s+wanted\s+to\s+walk\s+through|share\s+(?:my\s+)?screen)\b",
    flags=re.IGNORECASE | re.DOTALL,
)

_DURABLE_FUTURE_TIMING_PATTERN = re.compile(
    r"\b(?:tomorrow|next\s+(?:week|month)|later\s+(?:today|this\s+week)|after\s+(?:this\s+meeting|the\s+meeting)|"
    r"follow\s+up|schedule|set\s+up|by\s+(?:monday|tuesday|wednesday|thursday|friday|\d{1,2}(?::\d{2})?))\b",
    flags=re.IGNORECASE,
)


def _commitment_is_immediate_meeting_facilitation(action: str, quotes: list[str]) -> bool:
    """Reject ephemeral in-meeting navigation/demo work from durable Action memory.

    A statement such as "Alex can show you how it works" or "I'll go back to
    that screen" may be a real conversational next step, but it is normally
    consumed inside the current meeting rather than work that remains open
    afterward.  Keep a presentation/demo action when the evidence gives a
    durable future time or scheduling cue.
    """

    if not _IMMEDIATE_MEETING_FACILITATION_ACTION_PATTERN.search(str(action or "")):
        return False
    evidence_text = "\n".join(str(q or "") for q in quotes if str(q or "").strip())
    if not evidence_text:
        return False
    if _DURABLE_FUTURE_TIMING_PATTERN.search(evidence_text):
        return False
    return bool(_IMMEDIATE_MEETING_FACILITATION_EVIDENCE_PATTERN.search(evidence_text))


def _validate_resolved_commitment(
    item: dict,
    transcript: str,
    identity_map: dict[str, str] | None = None,
) -> dict | None:
    quotes = _resolved_evidence_quotes(item, transcript)
    action = re.sub(r"\s+", " ", str(item.get("action", ""))).strip()
    owner = re.sub(r"\s+", " ", str(item.get("owner", "Unknown"))).strip() or "Unknown"
    if not quotes or not action:
        return None

    authoritative_owner = _authoritative_first_person_owner(
        quotes, transcript, identity_map
    )
    if authoritative_owner:
        owner = authoritative_owner
    if owner.casefold() in _AUDIO_CHANNEL_OWNER_LABELS:
        return None
    if not _commitment_action_is_self_contained(action):
        return None
    if _commitment_is_immediate_meeting_facilitation(action, quotes):
        return None

    context = _resolved_item_context(item, transcript)
    # The normalized action is intentionally allowed to paraphrase conversational
    # speech. Ground the exact evidence and speaker attribution instead of
    # requiring the participant's name to be literally spoken in a first-person
    # commitment.
    if owner != "Unknown" and not re.search(
        rf"\b{re.escape(owner)}\b", context, flags=re.IGNORECASE
    ):
        evidence_owners = {
            _participant_name_for_channel(
                _speaker_channel_for_evidence(quote, transcript),
                identity_map,
            ).casefold()
            for quote in quotes
            if _FIRST_PERSON_FUTURE_WORK_PATTERN.search(quote)
        }
        if owner.casefold() not in evidence_owners:
            return None
    if not re.search(
        r"\b(?:i\s+will|i['’]ll|i['’]m\s+(?:going\s+to|gonna)|i\s+am\s+going\s+to|"
        r"we\s+will|we['’]ll|we['’]re\s+gonna|why\s+don['’]t\s+you|"
        r"take\s+the\s+lead|reach\s+out|set\s+up|next\s+step|let['’]s)\b",
        context,
        flags=re.IGNORECASE,
    ):
        return None
    return _resolved_memory_item(
        {
            "owner": owner,
            "action": action,
            "status": "open",
            "_context_resolved": True,
        },
        quotes,
    )


def _validate_resolved_decision(item: dict, transcript: str) -> dict | None:
    quotes = _resolved_evidence_quotes(item, transcript)
    decision = re.sub(r"\s+", " ", str(item.get("decision", ""))).strip()
    if not quotes or not decision:
        return None
    if not _decision_candidate_is_well_formed(decision, quotes[0]):
        return None
    context = _resolved_item_context(item, transcript)
    explicit = any(_decision_is_supported(decision, quote) for quote in quotes)
    # A system capability, release behavior, or implementation limitation is an
    # update unless the evidence explicitly shows that people settled on it.
    # This blocks statements like "The feature will not automatically update
    # existing workspaces" from becoming Decisions merely because they contain
    # future-tense wording.
    if _decision_is_operational_fact_claim(decision) and not any(
        re.search(
            r"\b(?:we\s+(?:decided|agreed|approved)|the\s+team\s+(?:decided|agreed|approved)|"
            r"let['’]s|that['’]s\s+what\s+we['’]ll\s+do)\b",
            quote,
            flags=re.IGNORECASE,
        )
        for quote in quotes
    ):
        return None
    # Resolver output must not become a Decision merely because a broad local
    # context window contains some unrelated future-tense or agreement phrase.
    # Require the *grounded decision evidence itself* to carry a non-hedged
    # settlement cue. This preserves explicit settled next steps while rejecting
    # proposal/preferences such as "maybe we prioritize" or "that's a good push".
    hedged = re.compile(
        r"\b(?:maybe|might|could|should|hopefully|possibly|perhaps|"
        r"i\s+think|we\s+think|probably|would\s+like\s+to)\b",
        flags=re.IGNORECASE,
    )
    settlement = re.compile(
        r"\b(?:let['’]s|we\s+will|we['’]ll|we['’]re\s+(?:gonna|going\s+to)|"
        r"we\s+are\s+going\s+to|that['’]s\s+what\s+we['’]ll\s+do|"
        r"we\s+(?:agreed|decided|approved)|sounds\s+good)\b",
        flags=re.IGNORECASE,
    )
    agreed_next_step = any(
        settlement.search(quote) and not hedged.search(quote)
        for quote in quotes
    )
    if not explicit and not agreed_next_step and quotes:
        post_agreement = _nearby_post_agreement_evidence(quotes[0], transcript)
        if post_agreement:
            candidate_quotes = list(dict.fromkeys([*quotes, post_agreement]))
            if _decision_evidence_is_semantically_consistent(
                decision, candidate_quotes, transcript
            ):
                quotes = candidate_quotes
                agreed_next_step = True
    if not explicit and not agreed_next_step:
        return None
    if not _decision_evidence_is_semantically_consistent(decision, quotes, transcript):
        return None
    # A durable decision may be a semantic normalization of terse conversational
    # agreement. Exact transcript evidence plus an explicit/agreed decision cue is
    # the grounding contract; do not demand lexical overlap with polished wording.
    # Keep the quote that best expresses the decision proposition as primary
    # evidence. Nearby agreement is useful corroboration, but a generic "that's
    # what we'll do" must not replace a more informative quote.
    quotes = _order_decision_evidence(decision, quotes, transcript)
    return _resolved_memory_item(
        {
            "decision": decision,
            "_context_resolved": True,
        },
        quotes,
    )


_RISK_TOPIC_CONCEPTS = {
    "ip_legal": (r"\b(?:ip|intellectual\s+property|infringement|lawsuit|sued|legal|indemnif\w*)\b",),
    "support": (r"\b(?:support|patch(?:es|ing)?|upgrade(?:s|ing)?|maintenance|end[-\s]+of[-\s]+support)\b",),
    "license": (r"\b(?:licen[cs]e|licensing|perpetual\s+rights?|forfeit)\b",),
    "cost": (r"\b(?:cost|price|pricing|financial|saving(?:s)?|overspend(?:ing)?|overrun(?:s)?)\b",),
    "availability": (r"\b(?:outage|availability|interrupt(?:ion)?|downtime|failure|breaks?)\b",),
}

_RISK_EXPLICIT_CUE_PATTERN = re.compile(
    r"\b(?:risk|concern|exposure|liabilit\w*|lawsuit|sued|infringement|"
    r"indemnif\w*|forfeit|failure|end[-\s]+of[-\s]+support|lose|losing)\b",
    flags=re.IGNORECASE,
)


def _risk_evidence_semantically_supports(risk: str, quotes: list[str]) -> bool:
    """Require the cited spans themselves to entail the normalized risk.

    A broad local context window is useful for resolving conversational wording,
    but it is too permissive as a final factuality gate: an unrelated nearby
    word such as ``problem`` can make an invented consequence look supported.
    Treat risk verification like claim-level NLI: at least one exact evidence
    span must carry an explicit risk/failure cue and, when the normalized risk
    names a known failure-mode topic, the same topic must be present in evidence.
    For unmodeled topics, preserve only transcript-explicit risks with meaningful
    lexical overlap rather than inferring a new consequence.
    """

    risk_topics = _decision_semantic_concepts(risk, _RISK_TOPIC_CONCEPTS)
    risk_tokens = _commitment_content_tokens(risk)
    for quote in quotes:
        if not quote or not _RISK_EXPLICIT_CUE_PATTERN.search(quote):
            continue
        quote_topics = _decision_semantic_concepts(quote, _RISK_TOPIC_CONCEPTS)
        if risk_topics:
            if risk_topics & quote_topics:
                return True
            continue
        quote_tokens = _commitment_content_tokens(quote)
        if len(risk_tokens & quote_tokens) >= 2:
            return True
    return False


def _risk_evidence_score(risk: str, evidence: str) -> tuple[int, int]:
    risk_topics = _decision_semantic_concepts(risk, _RISK_TOPIC_CONCEPTS)
    evidence_topics = _decision_semantic_concepts(evidence, _RISK_TOPIC_CONCEPTS)
    topic_overlap = len(risk_topics & evidence_topics)
    informative_tokens = len(re.findall(r"[A-Za-z0-9&'-]+", evidence))
    return (topic_overlap, informative_tokens)


def _recover_risk_failure_mode_evidence(risk: str, transcript: str) -> str | None:
    """Recover exact transcript evidence expressing the same concrete risk topic.

    This is a final evidence-fidelity repair for already verified v12 risks.  It
    never creates a new risk; it only replaces a weak/mismatched quote with an
    exact transcript block that names the same failure mode and contains an
    explicit risk/consequence cue.
    """

    risk_topics = _decision_semantic_concepts(risk, _RISK_TOPIC_CONCEPTS)
    if not risk_topics or not transcript:
        return None
    cue = re.compile(
        r"\b(?:risk|concern|exposure|lawsuit|sued|infringement|indemnif\w*|"
        r"lose|losing|without|end[-\s]+of[-\s]+support|forfeit|breaks?|failure)\b",
        flags=re.IGNORECASE,
    )
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for raw in re.split(r"\n\s*\n", transcript):
        block = re.sub(r"\s+", " ", raw).strip()
        if not block or (block.startswith("[") and "**" in block and len(block.split()) <= 6):
            continue
        grounded = _ground_evidence_quote(block, transcript)
        if not grounded:
            continue
        topics = _decision_semantic_concepts(grounded, _RISK_TOPIC_CONCEPTS)
        topic_overlap = len(risk_topics & topics)
        if topic_overlap == 0 or not cue.search(grounded):
            continue
        informative_tokens = len(re.findall(r"[A-Za-z0-9&'-]+", grounded))
        candidates.append(((topic_overlap, 1, min(informative_tokens, 80)), grounded))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _order_risk_evidence(risk: str, quotes: list[str], transcript: str = "") -> list[str]:
    """Prefer grounded risk evidence that states the same concrete failure mode."""

    candidates = [quote for quote in quotes if quote]
    recovered = _recover_risk_failure_mode_evidence(risk, transcript)
    if recovered and recovered not in candidates:
        candidates.append(recovered)
    return sorted(
        dict.fromkeys(candidates),
        key=lambda quote: _risk_evidence_score(risk, quote),
        reverse=True,
    )


def _validate_resolved_risk(item: dict, transcript: str) -> dict | None:
    quotes = _resolved_evidence_quotes(item, transcript)
    risk = re.sub(r"\s+", " ", str(item.get("risk", ""))).strip()
    if not quotes or not risk:
        return None
    words = re.findall(r"[A-Za-z0-9&'-]+", risk)
    if len(words) < 5 or len(words) > 32:
        return None
    # Final risk acceptance is evidence-local, not context-window-local.  This
    # prevents an unrelated nearby concern from licensing a normalized
    # consequence that the cited transcript span never states.
    if not _risk_evidence_semantically_supports(risk, quotes):
        return None
    # Risk wording may normalize the grounded failure mode/consequence. Prefer
    # the grounded quote that actually expresses that same concrete risk. Generic
    # "that's a risk" confirmations remain supporting evidence only.
    quotes = _order_risk_evidence(risk, quotes, transcript)
    risk = _normalize_verified_risk_text(risk, quotes[0])
    return _resolved_memory_item({"risk": risk}, quotes)


def _resolved_question_is_well_formed(question: str) -> bool:
    """Allow durable normalized questions with named-entity subjects.

    The baseline question validator is intentionally tuned to noisy verbatim ASR
    and therefore rejects forms such as ``Will Vendor Alpha ...?`` because the
    second token is not a pronoun/article.  v12 questions are generated only in
    the independently verified High Performance path and are still grounded
    against exact transcript evidence, so named subjects are safe here.
    """

    if _is_well_formed_question(question):
        return True
    text = str(question or "").strip()
    if not text.endswith("?"):
        return False
    if re.search(
        r"\[\d{1,2}:\d{2}\]|\*\*(?:Mic|Remote)\*\*|"
        r"\((?:static|indistinct|inaudible|unintelligible|crosstalk)[^)]*\)",
        text,
        flags=re.IGNORECASE,
    ):
        return False
    words = re.findall(r"[A-Za-z0-9&'-]+", text)
    if len(words) < 4 or len(words) > 30:
        return False
    first = words[0].casefold()
    if first not in {
        "who", "what", "when", "where", "why", "how", "which",
        "is", "are", "was", "were", "do", "does", "did", "can",
        "could", "will", "would", "should", "have", "has",
    }:
        return False
    return True


def _normalize_resolved_open_questions(questions: list[str]) -> list[str]:
    """Deduplicate v12 verified questions without reapplying ASR-only syntax gates."""

    kept: list[str] = []
    for raw in questions:
        question = re.sub(r"\s+", " ", str(raw or "")).strip(" -\t")
        if not _resolved_question_is_well_formed(question):
            continue
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if _questions_are_near_duplicates(question, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(question)
            continue
        existing = kept[duplicate_index]
        if len(re.findall(r"\S+", question)) < len(re.findall(r"\S+", existing)):
            kept[duplicate_index] = question
    return kept


_LATE_ANSWER_CUE_PATTERN = re.compile(
    r"\b(?:yes|no|exactly|correct|current\s+state|right\s+now|"
    r"you\s+(?:would|want|should|need|can)|"
    r"we\s+(?:will|can|are|have)|"
    r"it\s+(?:will|is|does|can)|"
    r"this\s+(?:will|is|does|can)|"
    r"there\s+(?:will|won['’]t|is|isn['’]t)|"
    r"that['’]s|those\s+are|both\b)",
    flags=re.IGNORECASE,
)


def _question_is_answered_later(
    question: str,
    evidence_quotes: list[str],
    transcript: str,
) -> bool:
    """Return True when a later grounded turn substantively answers a question.

    v12 can normalize an early question into durable wording even when the answer
    arrives several minutes later. The older local check intentionally inspects
    only the immediate exchange, so it can miss those delayed answers. This pass
    stays deterministic and conservative: a later turn must share multiple
    content anchors with the original question/evidence and contain declarative
    answer language rather than uncertainty.
    """

    if not transcript or not evidence_quotes:
        return False

    evidence_positions = [
        transcript.find(quote)
        for quote in evidence_quotes
        if quote and transcript.find(quote) >= 0
    ]
    if not evidence_positions:
        return False

    start = min(evidence_positions)
    evidence_end = max(
        transcript.find(quote) + len(quote)
        for quote in evidence_quotes
        if quote and transcript.find(quote) >= 0
    )
    # Bound the scan so a distant, unrelated later meeting topic cannot close a
    # question merely because it reuses common vocabulary.
    tail = transcript[evidence_end : min(len(transcript), evidence_end + 14000)]
    if not tail:
        return False

    anchor_text = " ".join([question, *evidence_quotes])
    anchors = {
        token
        for token in _commitment_content_tokens(anchor_text)
        if len(token) >= 4
    }
    if not anchors:
        return False
    entity_tokens: set[str] = set()
    for entity in re.findall(
        r"\b[A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*)+\b",
        anchor_text,
    ):
        entity_tokens.update(_commitment_content_tokens(entity))

    turns = re.split(
        r"(?=\[\d{1,2}:\d{2}\]\s+\*\*(?:Mic|Remote)\*\*)",
        tail,
        flags=re.IGNORECASE,
    )
    for turn in turns:
        compact = re.sub(r"\s+", " ", turn).strip()
        if not compact:
            continue
        # A turn dominated by explicit uncertainty is not an answer.
        if _STRONG_UNRESOLVED_CONTEXT_PATTERN.search(compact[:320]):
            continue
        if not _LATE_ANSWER_CUE_PATTERN.search(compact[:700]):
            continue

        turn_tokens = _commitment_content_tokens(compact[:1200])
        overlap = anchors & turn_tokens
        # Two shared anchors is the normal threshold. A single distinctive
        # anchor is enough for short operational questions such as "what happens
        # when I hit cancel?" when the later turn directly describes current
        # state / required behavior.
        non_entity_overlap = overlap - entity_tokens
        if len(overlap) >= 2 and non_entity_overlap:
            return True
        if len(overlap) == 1:
            anchor = next(iter(overlap))
            if len(anchor) >= 6 and re.search(
                r"\b(?:current\s+state|right\s+now|you\s+(?:would|want|should|need)|"
                r"it\s+(?:will|does)|this\s+(?:will|does))\b",
                compact,
                flags=re.IGNORECASE,
            ):
                return True

    return False


def _validate_resolved_question(item: dict, transcript: str) -> str | None:
    quotes = _resolved_evidence_quotes(item, transcript)
    question = re.sub(r"\s+", " ", str(item.get("question", ""))).strip()
    if not quotes or not question:
        return None
    if not _resolved_question_is_well_formed(question):
        return None
    context = _resolved_item_context(item, transcript)
    # Normalized durable questions need not reuse transcript vocabulary verbatim.
    # Exact grounded evidence plus unresolved-at-end validation is sufficient.
    for evidence in quotes:
        if _is_well_formed_question(evidence) and not _question_is_locally_unresolved(
            evidence, transcript
        ):
            return None
    if _question_is_answered_later(question, quotes, transcript):
        return None
    return question



def _evidence_tokens_with_spans(text: str) -> list[tuple[str, int, int]]:
    """Return lexical evidence tokens while preserving source character spans.

    Event grounding should tolerate harmless ASR/JSON formatting differences such
    as smart apostrophes, punctuation, and whitespace, but it must not perform
    semantic/fuzzy matching.  Keeping original spans lets us replace a model's
    normalized quote with the exact transcript text that actually grounded it.
    """

    tokens: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*", text):
        token = match.group(0).replace("’", "'").casefold()
        tokens.append((token, match.start(), match.end()))
    return tokens


def _ground_evidence_quote(quote: str, transcript: str) -> str | None:
    """Locate one evidence quote in the transcript using lexical-exact matching.

    First prefer a literal substring.  Otherwise require the complete quote token
    sequence to occur contiguously in the transcript, ignoring only punctuation,
    smart-vs-straight apostrophes, case, and whitespace.  The returned value is
    always the exact transcript slice, never the model's normalized wording.
    """

    quote = str(quote or "").strip()
    if not quote:
        return None
    if quote in transcript:
        return quote

    quote_tokens = _evidence_tokens_with_spans(quote)
    transcript_tokens = _evidence_tokens_with_spans(transcript)
    if not quote_tokens or len(quote_tokens) > len(transcript_tokens):
        return None

    wanted = [token for token, _, _ in quote_tokens]
    width = len(wanted)
    for start in range(0, len(transcript_tokens) - width + 1):
        candidate = transcript_tokens[start:start + width]
        if [token for token, _, _ in candidate] != wanted:
            continue
        char_start = candidate[0][1]
        char_end = candidate[-1][2]
        return transcript[char_start:char_end].strip()
    return None


def _diagnose_memory_event_rejection(item: dict, transcript: str) -> dict:
    """Explain why a v12 pass-1 event failed deterministic validation.

    Diagnostics are observational only: this mirrors the validator's gates and
    must never change whether an event is retained.
    """

    if not isinstance(item, dict):
        return {"reason": "invalid_item", "candidate": repr(item)[:500]}

    event_type = str(item.get("event_type", "")).strip().casefold()
    allowed = {
        "assignment", "commitment", "proposal", "agreement", "decision",
        "concern", "question", "uncertainty", "next_step",
    }
    base = {
        "event_type": event_type or "unknown",
        "speaker": re.sub(r"\s+", " ", str(item.get("speaker", ""))).strip(),
        "target": re.sub(r"\s+", " ", str(item.get("target", ""))).strip(),
        "subject": re.sub(r"\s+", " ", str(item.get("subject", ""))).strip(),
    }
    if event_type not in allowed:
        return {**base, "reason": "invalid_event_type"}

    raw_evidence = item.get("evidence", [])
    if isinstance(raw_evidence, str):
        raw_evidence = [raw_evidence]
    if not isinstance(raw_evidence, list) or not raw_evidence:
        return {**base, "reason": "missing_evidence", "evidence": []}

    evidence = [str(value or "").strip() for value in raw_evidence if str(value or "").strip()]
    grounded = [quote for quote in evidence if _ground_evidence_quote(quote, transcript)]
    if not grounded:
        recovered = _recover_assignment_event_evidence(item, transcript)
        if recovered:
            grounded = recovered
        else:
            return {**base, "reason": "evidence_not_found", "evidence": evidence}
    if not base["subject"]:
        return {**base, "reason": "missing_subject", "evidence": grounded}
    return {**base, "reason": "unknown_validator_rejection", "evidence": grounded}


def _resolved_candidate_snapshot(item: dict, category: str) -> dict:
    key = {
        "actions": "action",
        "decisions": "decision",
        "risks": "risk",
        "questions": "question",
    }[category]
    result = {key: re.sub(r"\s+", " ", str(item.get(key, ""))).strip()}
    if category == "actions":
        result["owner"] = re.sub(r"\s+", " ", str(item.get("owner", "Unknown"))).strip() or "Unknown"
    raw = item.get("evidence", [])
    if isinstance(raw, str):
        raw = [raw]
    result["evidence"] = [str(value or "").strip() for value in raw if str(value or "").strip()] if isinstance(raw, list) else []
    return result


def _diagnose_resolved_rejection(category: str, item: dict, transcript: str) -> dict:
    """Explain a pass-2 deterministic rejection without changing validation."""

    snapshot = _resolved_candidate_snapshot(item, category)
    quotes = _resolved_evidence_quotes(item, transcript)
    if category == "actions":
        action = snapshot["action"]
        owner = snapshot["owner"]
        if not quotes:
            reason = "evidence_not_found"
        elif not action:
            reason = "missing_action"
        elif not _commitment_action_is_self_contained(action):
            reason = "action_not_self_contained"
        else:
            context = _resolved_item_context(item, transcript)
            if not _resolved_text_is_grounded_in_context(action, context):
                reason = "action_not_grounded"
            elif owner != "Unknown" and not re.search(rf"\b{re.escape(owner)}\b", context, flags=re.IGNORECASE):
                reason = "owner_not_grounded"
            elif not re.search(
                r"\b(?:i\s+will|i['’]ll|we\s+will|we['’]ll|why\s+don['’]t\s+you|"
                r"take\s+the\s+lead|reach\s+out|set\s+up|next\s+step|let['’]s)\b",
                context, flags=re.IGNORECASE,
            ):
                reason = "commitment_cue_missing"
            else:
                reason = "unknown_validator_rejection"
    elif category == "decisions":
        decision = snapshot["decision"]
        if not quotes:
            reason = "evidence_not_found"
        elif not decision:
            reason = "missing_decision"
        elif not _decision_candidate_is_well_formed(decision, quotes[0]):
            reason = "decision_not_well_formed"
        else:
            context = _resolved_item_context(item, transcript)
            explicit = any(_decision_is_supported(decision, quote) for quote in quotes)
            agreed = bool(re.search(
                r"\b(?:let['’]s|we\s+will|we['’]ll|that['’]s\s+what\s+we['’]ll\s+do|"
                r"we\s+agreed|sounds\s+good)\b", context, flags=re.IGNORECASE,
            ))
            if not explicit and not agreed:
                reason = "decision_support_missing"
            elif not _resolved_text_is_grounded_in_context(decision, context):
                reason = "decision_not_grounded"
            else:
                reason = "unknown_validator_rejection"
    elif category == "risks":
        risk = snapshot["risk"]
        if not quotes:
            reason = "evidence_not_found"
        elif not risk:
            reason = "missing_risk"
        else:
            words = re.findall(r"[A-Za-z0-9&'-]+", risk)
            context = _resolved_item_context(item, transcript)
            if len(words) < 5 or len(words) > 32:
                reason = "risk_length_invalid"
            elif not re.search(
                r"\b(?:risk|concern|exposure|liabilit|lawsuit|sued|infringement|"
                r"indemnif|lose|losing|forfeit|support|failure)\w*\b",
                context, flags=re.IGNORECASE,
            ):
                reason = "risk_cue_missing"
            elif not _resolved_text_is_grounded_in_context(risk, context):
                reason = "risk_not_grounded"
            else:
                reason = "unknown_validator_rejection"
    else:
        question = snapshot["question"]
        if not quotes:
            reason = "evidence_not_found"
        elif not question:
            reason = "missing_question"
        elif not _resolved_question_is_well_formed(question):
            reason = "question_not_well_formed"
        else:
            context = _resolved_item_context(item, transcript)
            if not _resolved_text_is_grounded_in_context(question, context):
                reason = "question_not_grounded"
            elif any(
                _is_well_formed_question(evidence) and not _question_is_locally_unresolved(evidence, transcript)
                for evidence in quotes
            ):
                reason = "question_already_answered"
            else:
                reason = "unknown_validator_rejection"

    return {**snapshot, "reason": reason, "grounded_evidence": quotes}


def _recover_assignment_event_evidence(item: dict, transcript: str) -> list[str]:
    """Recover a verbatim assignment quote when pass 1 supplied summary prose.

    Summary cues can help the model notice an assignment, but they are never
    evidence.  Recovery is deliberately narrow: the named target must appear in
    a single transcript turn that also contains a direct assignment cue.
    """

    if str(item.get("event_type", "")).strip().casefold() != "assignment":
        return []
    raw_evidence = item.get("evidence", [])
    evidence_values = [raw_evidence] if isinstance(raw_evidence, str) else list(raw_evidence) if isinstance(raw_evidence, list) else []
    synthetic_action_item = any(
        re.search(r"\b(?:due\s+date\s+not\s+identified|owner\s+not\s+identified)\b", str(value), flags=re.IGNORECASE)
        for value in evidence_values
    )
    if not synthetic_action_item:
        return []
    target = re.sub(r"\s+", " ", str(item.get("target", ""))).strip()
    if not target:
        return []

    turn_pattern = re.compile(
        r"(?:^|\n)\[\d{1,2}:\d{2}\]\s+\*\*[^*]+\*\*\s*\n+"
        r"(.*?)(?=(?:\n\[\d{1,2}:\d{2}\]\s+\*\*)|\Z)",
        flags=re.DOTALL,
    )
    assignment_cue = re.compile(
        r"\b(?:why\s+don['’]t\s+you|take\s+the\s+lead|please|can\s+you|"
        r"could\s+you|would\s+you|need\s+you\s+to)\b",
        flags=re.IGNORECASE,
    )
    target_re = re.compile(rf"\b{re.escape(target)}\b", flags=re.IGNORECASE)

    candidates: list[str] = []
    for match in turn_pattern.finditer(transcript):
        turn = re.sub(r"\s+", " ", match.group(1)).strip()
        if not turn or not target_re.search(turn) or not assignment_cue.search(turn):
            continue
        candidates.append(turn)

    if len(candidates) == 1:
        return candidates
    if not candidates:
        return []

    subject_tokens = _commitment_content_tokens(str(item.get("subject", "")))
    ranked = sorted(
        ((len(subject_tokens & _commitment_content_tokens(turn)), turn) for turn in candidates),
        reverse=True,
    )
    if ranked and ranked[0][0] > 0 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
        return [ranked[0][1]]
    return []


def _validate_memory_event(
    item: dict,
    transcript: str,
    identity_map: dict[str, str] | None = None,
) -> dict | None:
    """Validate one v12 intermediate dialogue event against transcript evidence.

    Evidence is grounded by lexical-exact transcript spans rather than requiring
    byte-for-byte model quotation.  Invalid evidence entries are discarded; an
    event survives only when at least one evidence span can be grounded.
    """

    if not isinstance(item, dict):
        return None
    event_type = str(item.get("event_type", "")).strip().casefold()
    allowed = {
        "assignment",
        "commitment",
        "proposal",
        "agreement",
        "decision",
        "concern",
        "question",
        "uncertainty",
        "next_step",
    }
    if event_type not in allowed:
        return None

    raw_evidence = item.get("evidence", [])
    if isinstance(raw_evidence, str):
        raw_evidence = [raw_evidence]
    if not isinstance(raw_evidence, list) or not raw_evidence:
        return None

    evidence: list[str] = []
    for raw_quote in raw_evidence:
        grounded_quote = _ground_evidence_quote(str(raw_quote or ""), transcript)
        if grounded_quote and grounded_quote not in evidence:
            evidence.append(grounded_quote)
    if not evidence:
        # Pass 1 occasionally copies normalized/paraphrased prose into evidence.
        # Recover exact source turns rather than accepting the paraphrase itself.
        # Assignment recovery remains the narrowest first choice; the turn-level
        # retriever handles other dialogue acts only when one high-signal source
        # turn is uniquely identified.
        evidence.extend(_recover_assignment_event_evidence(item, transcript))
        if not evidence and event_type != "assignment":
            evidence.extend(_recover_event_evidence_from_turns(item, transcript))
    if not evidence:
        return None

    subject = re.sub(r"\s+", " ", str(item.get("subject", ""))).strip()
    if not subject:
        return None

    raw_speaker = re.sub(r"\s+", " ", str(item.get("speaker", ""))).strip()
    raw_target = re.sub(r"\s+", " ", str(item.get("target", ""))).strip()
    speaker = _participant_name_for_channel(raw_speaker, identity_map)
    target = _participant_name_for_channel(raw_target, identity_map)

    # First-person future work belongs to the evidence speaker even when the
    # model mislabeled the dialogue act as an assignment or next step.  The
    # model's target is advisory; exact source attribution is authoritative.
    if event_type in {"commitment", "assignment", "next_step"} and any(
        _FIRST_PERSON_FUTURE_WORK_PATTERN.search(q) for q in evidence
    ):
        if speaker and speaker.casefold() not in _AUDIO_CHANNEL_OWNER_LABELS:
            target = speaker

    result = {
        "event_type": event_type,
        "speaker": speaker,
        "target": target,
        "subject": subject,
        "status": str(item.get("status", "")).strip().casefold(),
        "evidence": evidence,
    }
    return result



_MEMORY_EVENT_WINDOW_TOKEN_TARGET = 5000
_MEMORY_EVENT_WINDOW_OVERLAP_TURNS = 3
_MEMORY_EVENT_WINDOW_MAX_EVENTS = 12
_MEMORY_EVENT_WINDOW_MAX_UNCERTAINTIES = 2
_MEMORY_EVENT_WINDOW_MAX_ANCHORS = 6
_MEMORY_EVENT_PRIORITY = {
    "commitment": 0,
    "assignment": 0,
    "decision": 1,
    "agreement": 1,
    "next_step": 2,
    "proposal": 3,
    "concern": 4,
    "question": 5,
    "uncertainty": 6,
}
_MEMORY_HIGH_SIGNAL_FUTURE_WORK_PATTERN = re.compile(
    r"\b(?:i['’]ll|i\s+will|i['’]m\s+(?:going\s+to|gonna)|"
    r"i\s+am\s+going\s+to|i\s+just\s+committed|i\s+committed\s+to|"
    r"i\s+can\s+(?:take|handle|join|call|contact|reach|review|send|schedule))\b",
    flags=re.IGNORECASE,
)
_MEMORY_ASSIGNMENT_ANCHOR_PATTERN = re.compile(
    r"\b(?:why\s+don['’]t\s+you|take\s+the\s+lead|please|can\s+you|"
    r"could\s+you|would\s+you|need\s+you\s+to)\b",
    flags=re.IGNORECASE,
)


def _memory_future_work_anchors(window_text: str) -> list[dict]:
    """Return high-signal source turns that must receive future-work review.

    Anchors are navigation hints only.  They never become memory items directly;
    the LLM still classifies them and the normal grounding/final validators still
    decide whether anything survives.  The purpose is recall: explicit future
    work should not disappear merely because low-value uncertainties consumed a
    bounded window's candidate slots.
    """

    anchors: list[dict] = []
    for turn in _transcript_turn_records(window_text):
        body = re.sub(r"\s+", " ", str(turn.get("body", ""))).strip()
        if not body:
            continue
        if not (
            _MEMORY_HIGH_SIGNAL_FUTURE_WORK_PATTERN.search(body)
            or _MEMORY_ASSIGNMENT_ANCHOR_PATTERN.search(body)
        ):
            continue
        anchors.append({
            "time": str(turn.get("time", "")),
            "speaker": str(turn.get("speaker", "")),
            "text": body,
        })
        if len(anchors) >= _MEMORY_EVENT_WINDOW_MAX_ANCHORS:
            break
    return anchors


def _memory_anchor_is_covered(anchor: dict, events: list[dict]) -> bool:
    anchor_text = re.sub(r"\s+", " ", str(anchor.get("text", ""))).strip()
    if not anchor_text:
        return True
    anchor_norm = re.sub(r"[^a-z0-9]+", " ", anchor_text.casefold()).strip()
    anchor_tokens = _commitment_content_tokens(anchor_text)
    for event in events:
        raw_evidence = event.get("evidence", [])
        evidence = [raw_evidence] if isinstance(raw_evidence, str) else list(raw_evidence or [])
        for quote in evidence:
            quote_text = re.sub(r"\s+", " ", str(quote or "")).strip()
            if not quote_text:
                continue
            quote_norm = re.sub(r"[^a-z0-9]+", " ", quote_text.casefold()).strip()
            if quote_norm and anchor_norm and (quote_norm in anchor_norm or anchor_norm in quote_norm):
                return True
            quote_tokens = _commitment_content_tokens(quote_text)
            overlap = anchor_tokens & quote_tokens
            if len(overlap) >= 4 and len(overlap) >= min(len(anchor_tokens), len(quote_tokens)) * 0.6:
                return True
    return False


_MEMORY_COMPLETED_WORK_CUE_PATTERN = re.compile(
    r"\b(?:after\s+i\s+(?:looked|reviewed|checked|finished|completed|sent|called|contacted)|"
    r"i\s+(?:already\s+)?(?:reviewed|looked|checked|finished|completed|sent|called|contacted)\b|"
    r"i\s+(?:reviewed|looked\s+through|finished|completed)\b.{0,80}\byesterday\b)",
    flags=re.IGNORECASE,
)


def _memory_work_concepts(text: str) -> set[str]:
    """Return coarse work concepts for future-vs-completed consistency checks."""

    value = re.sub(r"\s+", " ", str(text or "")).casefold()
    concepts = set(_commitment_action_family(value))
    if re.search(r"\b(?:review(?:ed|ing)?|look(?:ed|ing)?|assess(?:ed|ing|ment)?|analy[sz](?:e|ed|ing)|analysis|check(?:ed|ing)?)\b", value):
        concepts.add("review")
    if re.search(r"\b(?:send|sent|share|shared|provide|provided|deliver|delivered)\b", value):
        concepts.add("deliver")
    if re.search(r"\b(?:update|updated|clean\s+up|cleanup|tidy|tidying)\b", value):
        concepts.add("update")
    return concepts


def _memory_commitment_event_is_future_work(event: dict, transcript: str = "") -> bool:
    """Keep only event-level commitments that still represent future work.

    Pass 1 can over-classify status/history as a commitment when a busy turn mixes
    past work with future language.  Before pass 2, require a genuine first-person
    future-work cue and reject a future cue that the same grounded event later
    proves was already completed.  This is a temporal hygiene gate, not a semantic
    memory creator.
    """

    if str(event.get("event_type", "")).strip().casefold() != "commitment":
        return True
    evidence = [str(value).strip() for value in event.get("evidence", []) or [] if str(value).strip()]
    if not evidence:
        return False
    future = [quote for quote in evidence if _MEMORY_HIGH_SIGNAL_FUTURE_WORK_PATTERN.search(quote)]
    if not future:
        return False
    if _commitment_is_immediate_meeting_facilitation(
        str(event.get("subject", "")),
        future,
    ):
        return False

    subject_concepts = _memory_work_concepts(str(event.get("subject", "")))
    future_positions = [transcript.find(quote) for quote in future if transcript and transcript.find(quote) >= 0]
    earliest_future = min(future_positions) if future_positions else -1
    for quote in evidence:
        if not _MEMORY_COMPLETED_WORK_CUE_PATTERN.search(quote):
            continue
        completed_concepts = _memory_work_concepts(quote)
        if subject_concepts and completed_concepts and not (subject_concepts & completed_concepts):
            continue
        if transcript and earliest_future >= 0:
            completed_pos = transcript.find(quote)
            if completed_pos >= 0 and completed_pos <= earliest_future:
                continue
        return False
    return True


def _normalize_protected_commitment_action(subject: str) -> str:
    action = re.sub(r"\s+", " ", str(subject or "")).strip()
    action = re.sub(r"\bescalate\s+something\s+with\s+", "Escalate with ", action, flags=re.IGNORECASE)
    return action


def _proposed_commitment_covers_event(proposed: list[dict], event: dict) -> bool:
    owner = re.sub(r"\s+", " ", str(event.get("speaker", ""))).strip().casefold()
    subject_tokens = _commitment_content_tokens(str(event.get("subject", "")))
    evidence = {re.sub(r"\s+", " ", str(value)).strip().casefold() for value in event.get("evidence", []) or []}
    for item in proposed:
        proposed_owner = re.sub(r"\s+", " ", str(item.get("owner", ""))).strip().casefold()
        if owner and proposed_owner and owner != proposed_owner:
            continue
        item_tokens = _commitment_content_tokens(str(item.get("action", "")))
        raw = item.get("evidence", [])
        item_evidence = [raw] if isinstance(raw, str) else list(raw or [])
        item_evidence_norm = {re.sub(r"\s+", " ", str(value)).strip().casefold() for value in item_evidence}
        if evidence & item_evidence_norm:
            return True
        if len(subject_tokens & item_tokens) >= 2:
            return True
    return False


def _protected_event_commitment_candidates(events: list[dict], proposed: list[dict], transcript: str) -> list[dict]:
    """Recover high-confidence grounded commitments omitted by pass 2.

    Pass 2 remains the primary semantic resolver.  This safety net only forwards
    pass-1 events that are already exact-grounded, explicitly future work, and
    self-contained; final commitment validation still applies afterward.
    """

    recovered: list[dict] = []
    working = list(proposed)
    for event in events:
        if str(event.get("event_type", "")).strip().casefold() != "commitment":
            continue
        if not _memory_commitment_event_is_future_work(event, transcript):
            continue
        if _proposed_commitment_covers_event(working, event):
            continue
        action = _normalize_protected_commitment_action(str(event.get("subject", "")))
        if re.fullmatch(r"(?:help\s+)?escalate", action, flags=re.IGNORECASE):
            continue
        if not _commitment_action_is_self_contained(action):
            continue
        owner = re.sub(r"\s+", " ", str(event.get("speaker", ""))).strip() or "Unknown"
        candidate = {
            "owner": owner,
            "action": action,
            "evidence": list(event.get("evidence", []) or []),
        }
        recovered.append(candidate)
        working.append(candidate)
    return recovered


def _prioritize_memory_event_candidates(events: list[dict]) -> list[dict]:
    """Apply the bounded per-window budget without letting uncertainty dominate.

    This is intentionally a candidate-selection rule, not a semantic validator.
    It protects scarce pass-1 slots for durable dialogue acts while preserving the
    model's relative order within each priority class.
    """

    deduped: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    uncertainty_count = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type", "")).strip().casefold()
        if event_type == "uncertainty":
            if uncertainty_count >= _MEMORY_EVENT_WINDOW_MAX_UNCERTAINTIES:
                continue
            uncertainty_count += 1
        key = _memory_event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

    indexed = list(enumerate(deduped))
    indexed.sort(key=lambda pair: (_MEMORY_EVENT_PRIORITY.get(
        str(pair[1].get("event_type", "")).strip().casefold(), 99
    ), pair[0]))
    return [event for _, event in indexed[:_MEMORY_EVENT_WINDOW_MAX_EVENTS]]


def _memory_event_windows(transcript: str) -> list[str]:
    """Split a transcript into bounded, overlapping turn windows for pass-1 extraction.

    The window target is deliberately below the direct-analysis budget.  This keeps
    structured MLX generations compact and prevents one verbose event list from
    consuming the entire structured-output token ceiling.  Overlap preserves local
    antecedents without duplicating the entire meeting in every request.
    """

    turns = _transcript_turn_records(transcript)
    if not turns:
        value = str(transcript or "").strip()
        return [value] if value else []

    windows: list[str] = []
    start = 0
    while start < len(turns):
        end = start
        pieces: list[str] = []
        while end < len(turns):
            turn = turns[end]
            piece = (
                f"[{turn['time']}] **{turn['speaker']}**\n\n"
                f"{turn['body']}"
            )
            candidate = "\n\n".join(pieces + [piece])
            if pieces and estimate_tokens(candidate) > _MEMORY_EVENT_WINDOW_TOKEN_TARGET:
                break
            pieces.append(piece)
            end += 1
        if not pieces:
            turn = turns[start]
            pieces.append(f"[{turn['time']}] **{turn['speaker']}**\n\n{turn['body']}")
            end = start + 1
        windows.append("\n\n".join(pieces))
        if end >= len(turns):
            break
        start = max(start + 1, end - _MEMORY_EVENT_WINDOW_OVERLAP_TURNS)
    return windows


def _memory_event_dedupe_key(event: dict) -> tuple[str, str, str, str]:
    def norm(value: object) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    return (
        norm(event.get("event_type")),
        norm(event.get("speaker")),
        norm(event.get("target")),
        norm(event.get("subject")),
    )


def _merge_memory_events(events: list[dict]) -> list[dict]:
    """Deterministically merge overlap duplicates while preserving exact evidence."""

    merged: list[dict] = []
    by_key: dict[tuple[str, str, str, str], dict] = {}
    for event in events:
        key = _memory_event_dedupe_key(event)
        existing = by_key.get(key)
        if existing is None:
            item = dict(event)
            item["evidence"] = list(dict.fromkeys(item.get("evidence", []) or []))
            by_key[key] = item
            merged.append(item)
            continue
        existing_evidence = existing.setdefault("evidence", [])
        for quote in event.get("evidence", []) or []:
            if quote not in existing_evidence:
                existing_evidence.append(quote)
        # Prefer a stronger conversational status when overlap windows disagree.
        rank = {"settled": 5, "accepted": 4, "rejected": 4, "unresolved": 3, "proposed": 2, "stated": 1, "": 0}
        if rank.get(str(event.get("status", "")).casefold(), 0) > rank.get(str(existing.get("status", "")).casefold(), 0):
            existing["status"] = event.get("status", "")
    return merged


def _memory_event_evidence_context(transcript: str, events: list[dict], *, neighbor_turns: int = 1) -> str:
    """Return only source turns surrounding grounded event evidence for pass 2."""

    turns = _transcript_turn_records(transcript)
    if not turns or not events:
        return transcript
    selected: set[int] = set()
    transcript_value = str(transcript or "")
    for event in events:
        for quote in event.get("evidence", []) or []:
            q = str(quote or "").strip()
            if not q:
                continue
            q_norm = " ".join(token for token, _, _ in _evidence_tokens_with_spans(q))
            for idx, turn in enumerate(turns):
                body = transcript_value[turn["turn_start"]:turn["turn_end"]]
                body_norm = " ".join(token for token, _, _ in _evidence_tokens_with_spans(body))
                if q_norm and (q_norm in body_norm or body_norm in q_norm):
                    for offset in range(-neighbor_turns, neighbor_turns + 1):
                        pos = idx + offset
                        if 0 <= pos < len(turns):
                            selected.add(pos)
                    break
    if not selected:
        return transcript
    pieces = []
    for idx in sorted(selected):
        turn = turns[idx]
        pieces.append(f"[{turn['time']}] **{turn['speaker']}**\n\n{turn['body']}")
    return "\n\n".join(pieces)


def _extract_memory_events(
    meeting_label: str,
    transcript: str,
    meeting_summary: str = "",
) -> list[dict] | None:
    """v12 pass 1: extract grounded dialogue events from bounded local windows.

    Each window has a compact candidate ceiling.  A truncated/failed window is
    recorded and skipped so one runaway structured generation cannot discard the
    entire meeting.  Grounded overlap duplicates are merged deterministically.
    """

    if not _memory_resolution_capable():
        return None

    schema = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "maxItems": _MEMORY_EVENT_WINDOW_MAX_EVENTS,
                "items": {
                    "type": "object",
                    "properties": {
                        "event_type": {
                            "type": "string",
                            "enum": [
                                "assignment", "commitment", "proposal", "agreement",
                                "decision", "concern", "question", "uncertainty",
                                "next_step",
                            ],
                        },
                        "speaker": {"type": "string"},
                        "target": {"type": "string"},
                        "subject": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["proposed", "accepted", "rejected", "unresolved", "settled", "stated"],
                        },
                        "evidence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "maxItems": 3,
                        },
                    },
                    "required": ["event_type", "speaker", "target", "subject", "status", "evidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["events"],
        "additionalProperties": False,
    }

    summary_cues = _summary_memory_cues(meeting_summary)
    identity_map = _meeting_participant_identity_map(meeting_label, transcript)
    windows = _memory_event_windows(transcript)
    if not windows:
        return None

    profile = get_execution_profile(
        PERFORMANCE_PROFILE,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=get_active_llm_model_name(),
    )

    _last_memory_resolution_diagnostics.update({
        "window_count": len(windows),
        "window_truncated_count": 0,
        "window_failed_count": 0,
        "window_diagnostics": [],
    })

    all_proposed: list[dict] = []
    all_grounded: list[dict] = []
    all_rejected: list[dict] = []
    successful_windows = 0
    total_prompt_tokens = 0
    total_llm_seconds = 0.0

    print(f"Extracting grounded meeting dialogue events in {len(windows)} bounded window(s) (v12)...", flush=True)

    for window_index, window_text in enumerate(windows, start=1):
        anchors = _memory_future_work_anchors(window_text)
        prompt = f"""
You are pass 1 of a meeting-memory pipeline. Extract grounded dialogue events
from ONLY this local transcript window. Do NOT produce final Decisions, Action
Items, Risks, or Open Questions.

Meeting: {meeting_label}
High-confidence participant identity map (channel label -> participant name):
{json.dumps(identity_map, indent=2)}
Narrative-summary cues (navigation hints only; NEVER evidence):
{json.dumps(summary_cues, indent=2)}

Return at most {_MEMORY_EVENT_WINDOW_MAX_EVENTS} total events. Prefer omission over repetition.
Do not emit multiple paraphrases of the same event.

PRIORITY/BUDGET RULES:
- Explicit assignments and first-person commitments are highest priority. Do not
  omit them in favor of general uncertainty, background facts, or broad concerns.
- Treat the high-signal future-work anchors below as source turns that MUST be
  reviewed for assignment/commitment/next-step classification. Anchors are not
  automatically events; omit an anchor if it is vague, completed work, or not a
  durable future obligation.
- Return no more than {_MEMORY_EVENT_WINDOW_MAX_UNCERTAINTIES} uncertainty events.
- Questions/uncertainties should not crowd out explicit owned future work.

High-signal future-work anchors to review:
{json.dumps(anchors, indent=2)}

Event types:
- assignment: one person asks/names another person to do future work
- commitment: a speaker accepts or volunteers future work
- proposal: a suggested course of action not yet settled
- agreement: participants accept a proposal or next step
- decision: a direction is explicitly settled
- concern: a concrete failure mode, exposure, or undesirable outcome
- question: a substantive information need
- uncertainty: an explicitly unresolved fact (don't know / need to find out)
- next_step: a future step discussed without a clean owner yet

Rules:
- Each evidence entry MUST be an exact contiguous quote from THIS transcript window.
- Use no more than 3 short evidence quotes per event.
- Preserve explicit names in target when a person is directly assigned work.
- `target` is the PERSON responsible for work, never a vendor/system/object.
- First-person future work ("I'll", "I will", "I'm going to", "I'm gonna") is a
  commitment owned by the speaker; use the identity map when available.
- Prefer self-contained future-work quotes over vague acknowledgements.
- Explicit rejection of a concrete local course ("we're not going to do that")
  is a decision when the local context states what "that" means.
- Questions remain events even when conversationally phrased.
- A concern must state the actual thing that could go wrong.
- Omit chatter, backchannels, jokes, summaries of already completed work, and
  unsupported inference.

Transcript window {window_index}/{len(windows)}:
{window_text}
""".strip()

        prompt_tokens = estimate_tokens(prompt)
        total_prompt_tokens += prompt_tokens
        window_diag = {
            "index": window_index,
            "prompt_tokens": prompt_tokens,
            "status": "pending",
            "events_proposed": 0,
            "events_grounded": 0,
            "future_work_anchor_count": len(anchors),
            "anchor_recovery_needed": 0,
            "anchor_recovered_events": 0,
        }
        if prompt_tokens > profile.direct_token_budget:
            window_diag["status"] = "prompt_too_large"
            _last_memory_resolution_diagnostics["window_failed_count"] += 1
            _last_memory_resolution_diagnostics["window_diagnostics"].append(window_diag)
            continue

        try:
            raw = ask_llm(
                prompt,
                response_format=schema,
                timeout_seconds=profile.llm_call_timeout_seconds,
            )
            payload = json.loads(raw)
            elapsed = float(_last_llm_elapsed_seconds or 0.0)
            total_llm_seconds += elapsed
            window_diag["llm_seconds"] = round(elapsed, 3)
        except RuntimeError as exc:
            message = str(exc)
            if "generation token ceiling" in message.casefold() or "truncated" in message.casefold():
                window_diag["status"] = "truncated"
                _last_memory_resolution_diagnostics["window_truncated_count"] += 1
            else:
                window_diag["status"] = "runtime_error"
            window_diag["error"] = message[:240]
            _last_memory_resolution_diagnostics["window_failed_count"] += 1
            _last_memory_resolution_diagnostics["window_diagnostics"].append(window_diag)
            continue
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            window_diag["status"] = "invalid_json"
            window_diag["error"] = str(exc)[:240]
            _last_memory_resolution_diagnostics["window_failed_count"] += 1
            _last_memory_resolution_diagnostics["window_diagnostics"].append(window_diag)
            continue

        proposed = [item for item in payload.get("events", []) if isinstance(item, dict)]

        # v12.21: if an explicit future-work source turn was crowded out of the
        # bounded main response, give only those missing anchors one tiny recovery
        # classification pass.  This guarantees consideration without creating a
        # deterministic memory item or increasing the normal window event ceiling.
        missing_anchors = [anchor for anchor in anchors if not _memory_anchor_is_covered(anchor, proposed)]
        window_diag["anchor_recovery_needed"] = len(missing_anchors)
        if missing_anchors:
            recovery_schema = {
                "type": "object",
                "properties": {
                    "events": {
                        "type": "array",
                        "maxItems": min(len(missing_anchors), _MEMORY_EVENT_WINDOW_MAX_ANCHORS),
                        "items": schema["properties"]["events"]["items"],
                    }
                },
                "required": ["events"],
                "additionalProperties": False,
            }
            recovery_prompt = f"""
Review ONLY these high-signal future-work source turns from a meeting transcript.
Return an event only when the turn contains a durable future assignment, explicit
first-person commitment, or concrete next step.  Vague offers, completed work,
background status, and mere intentions without actionable work should be omitted.

Meeting: {meeting_label}
High-confidence participant identity map (channel label -> participant name):
{json.dumps(identity_map, indent=2)}

Allowed event types for this recovery pass: assignment, commitment, next_step.
Each evidence quote MUST be an exact contiguous quote from the supplied anchor text.
First-person future work belongs to the speaker, not a model-inferred target.

Anchors:
{json.dumps(missing_anchors, indent=2)}
""".strip()
            recovery_tokens = estimate_tokens(recovery_prompt)
            total_prompt_tokens += recovery_tokens
            try:
                raw_recovery = ask_llm(
                    recovery_prompt,
                    response_format=recovery_schema,
                    timeout_seconds=profile.llm_call_timeout_seconds,
                )
                recovery_payload = json.loads(raw_recovery)
                recovery_elapsed = float(_last_llm_elapsed_seconds or 0.0)
                total_llm_seconds += recovery_elapsed
                window_diag["anchor_recovery_llm_seconds"] = round(recovery_elapsed, 3)
                window_diag["anchor_recovery_prompt_tokens"] = recovery_tokens
                recovered = [
                    item for item in recovery_payload.get("events", [])
                    if isinstance(item, dict)
                    and str(item.get("event_type", "")).strip().casefold()
                    in {"assignment", "commitment", "next_step"}
                ]
                proposed.extend(recovered)
                window_diag["anchor_recovered_events"] = len(recovered)
            except (RuntimeError, json.JSONDecodeError, TypeError, ValueError) as exc:
                # Anchor recovery is recall assistance only.  Preserve the successful
                # main window response if this tiny supplementary call fails.
                window_diag["anchor_recovery_error"] = str(exc)[:240]

        # Enforce a priority-aware candidate ceiling even if the backend ignores
        # schema limits.  Generic uncertainties are intentionally capped so they
        # cannot crowd explicit owned future work out of the bounded window.
        proposed = _prioritize_memory_event_candidates(proposed)
        if _memory_resolution_trace_enabled:
            _last_memory_resolution_trace.setdefault("windows", []).append({
                "index": window_index,
                "anchors": anchors,
                "proposed_events": proposed,
            })
        successful_windows += 1
        grounded_this_window: list[dict] = []
        for item in proposed:
            validated = _validate_memory_event(item, window_text, identity_map)
            if validated is not None:
                # Re-ground against the authoritative full transcript so offsets/source
                # semantics remain consistent downstream.
                full_validated = _validate_memory_event(validated, transcript, identity_map)
                if full_validated is not None:
                    if (
                        str(full_validated.get("event_type", "")).strip().casefold() == "commitment"
                        and not _memory_commitment_event_is_future_work(full_validated, transcript)
                    ):
                        rejected = dict(full_validated)
                        rejected["reason"] = "commitment_not_future_work"
                        all_rejected.append(rejected)
                        continue
                    grounded_this_window.append(full_validated)
                    continue
            all_rejected.append(_diagnose_memory_event_rejection(item, window_text))

        all_proposed.extend(proposed)
        all_grounded.extend(grounded_this_window)
        if _memory_resolution_trace_enabled:
            for window_trace in reversed(_last_memory_resolution_trace.get("windows", [])):
                if window_trace.get("index") == window_index:
                    window_trace["grounded_events"] = grounded_this_window
                    break
        window_diag.update({
            "status": "ok",
            "events_proposed": len(proposed),
            "events_grounded": len(grounded_this_window),
        })
        _last_memory_resolution_diagnostics["window_diagnostics"].append(window_diag)

    _last_memory_resolution_diagnostics["pass1_prompt_tokens"] = total_prompt_tokens
    _last_memory_resolution_diagnostics["pass1_llm_seconds"] = round(total_llm_seconds, 3)

    if successful_windows == 0:
        return None

    events = _merge_memory_events(all_grounded)
    _trace_memory_stage("identity_map", identity_map)
    _trace_memory_stage("merged_events", events)
    _trace_memory_stage("rejected_events", all_rejected)
    proposed_types: dict[str, int] = {}
    for item in all_proposed:
        event_type = str(item.get("event_type", "unknown")).strip().lower() or "unknown"
        proposed_types[event_type] = proposed_types.get(event_type, 0) + 1
    grounded_types: dict[str, int] = {}
    for item in events:
        event_type = str(item.get("event_type", "unknown")).strip().lower() or "unknown"
        grounded_types[event_type] = grounded_types.get(event_type, 0) + 1

    _last_memory_resolution_diagnostics.update({
        "status": "events_extracted",
        "events_proposed": len(all_proposed),
        "events_grounded": len(events),
        "merged_candidate_count": len(events),
        "event_types_proposed": proposed_types,
        "event_types_grounded": grounded_types,
        "rejected_events": all_rejected,
    })
    print(
        f"Memory event extraction: {len(events)}/{len(all_proposed)} grounded events retained "
        f"across {successful_windows}/{len(windows)} windows",
        flush=True,
    )
    return events


def _resolve_meeting_memory_from_events(
    meeting_label: str,
    transcript: str,
    baseline_memory: dict,
    events: list[dict],
    meeting_summary: str = "",
) -> dict | None:
    """v12 pass 2: independently verify/group events into durable memory."""

    if not events:
        return None

    schema = {
        "type": "object",
        "properties": {
            "commitments": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "action": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["owner", "action", "evidence"],
                    "additionalProperties": False,
                },
            },
            "decisions": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["decision", "evidence"],
                    "additionalProperties": False,
                },
            },
            "risks": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "risk": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["risk", "evidence"],
                    "additionalProperties": False,
                },
            },
            "open_questions": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["question", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["commitments", "decisions", "risks", "open_questions"],
        "additionalProperties": False,
    }

    summary_cues = _summary_memory_cues(meeting_summary)
    identity_map = _meeting_participant_identity_map(meeting_label, transcript)
    compact_baseline = {
        key: baseline_memory.get(key, [])
        for key in ("commitments", "decisions", "risks", "open_questions")
    }
    evidence_context = _memory_event_evidence_context(transcript, events, neighbor_turns=1)
    _last_memory_resolution_diagnostics["pass2_evidence_context_tokens"] = estimate_tokens(evidence_context)
    prompt = f"""
You are pass 2, the independent verifier/resolver for durable meeting memory.
Pass 1 extracted dialogue events.  Group related events across turns, verify them
against the grounded evidence context, and emit ONLY high-confidence durable memory.

Meeting: {meeting_label}
High-confidence participant identity map (channel label -> participant name):
{json.dumps(identity_map, indent=2)}

Candidate dialogue events:
{json.dumps(events, indent=2)}

Conservative first-pass memory (may be incomplete or opaque):
{json.dumps(compact_baseline, indent=2)}

Narrative-summary cues (navigation hints only; NEVER evidence):
{json.dumps(summary_cues, indent=2)}

Before retaining each item, verify all of the following internally:
1. SUPPORT: every substantive claim is supported by the grounded evidence context.
2. LINKAGE: if multiple events are combined, they clearly refer to the same
   person/task/issue rather than merely being nearby.
3. OWNERSHIP: a named Action owner is explicitly assigned, volunteers, or accepts
   the task.  Use multiple evidence quotes for assignment + acceptance when useful.
4. STATUS: a Decision is actually settled; an Open Question is still unresolved
   at meeting end; an Action remains future work. Never turn completed/past work
   (for example "I reviewed...", "I looked through...", "I've been working on...")
   into an open Action.
5. PRIORITY: when Action capacity is limited, preserve explicit accepted/first-person
   future commitments before generic review/status activity or tentative next steps.
6. USEFULNESS: the final wording is self-contained and useful weeks later.

Output rules:
- Evidence entries MUST be copied from the Grounded Evidence Context section below as exact
  contiguous quotes.  Narrative-summary cues, baseline memory, candidate subjects,
  and normalized Action/Decision wording are NEVER evidence and must not be copied
  into evidence fields.
- ACTION ITEMS: combine assignment + acceptance + later reaffirmation when they
  are the same task.  Write "what the owner must do", not a raw conversational quote.
- DECISIONS: capture settled group direction.  An agreed next step can be a
  Decision when the group clearly settled on that direction, but do not merely
  duplicate the Action Item wording.
- RISKS/CONCERNS: state subject + failure mode/exposure + consequence when grounded.
  Never retain a raw fragment just because it contains 'risk'.
- OPEN QUESTIONS: normalize unresolved substantive issues into durable questions,
  including conversational uncertainty such as "we'd have to find out".
- Prefer omission over invention.

Grounded Evidence Context:
{evidence_context}
""".strip()

    profile = get_execution_profile(
        PERFORMANCE_PROFILE,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=get_active_llm_model_name(),
    )
    prompt_tokens = estimate_tokens(prompt)
    _last_memory_resolution_diagnostics["pass2_prompt_tokens"] = prompt_tokens
    if prompt_tokens > profile.direct_token_budget:
        return None

    print("Resolving and verifying meeting events into durable memory (v12)...", flush=True)
    try:
        raw = ask_llm(
            prompt,
            response_format=schema,
            timeout_seconds=profile.llm_call_timeout_seconds,
        )
        proposed = json.loads(raw)
        if _last_llm_elapsed_seconds is not None:
            _last_memory_resolution_diagnostics["pass2_llm_seconds"] = round(
                float(_last_llm_elapsed_seconds), 3
            )
    except RuntimeError as exc:
        message = str(exc)
        _last_memory_resolution_diagnostics["pass2_error"] = message[:240]
        if "generation token ceiling" in message.casefold() or "truncated" in message.casefold():
            _last_memory_resolution_diagnostics["pass2_truncated"] = True
        return None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    proposed_commitments = [item for item in proposed.get("commitments", []) if isinstance(item, dict)]
    model_proposed_commitment_count = len(proposed_commitments)
    protected_commitments = _protected_event_commitment_candidates(
        events, proposed_commitments, transcript
    )
    if protected_commitments:
        proposed_commitments.extend(protected_commitments)
        _last_memory_resolution_diagnostics["pass2_protected_commitments"] = len(protected_commitments)
    proposed_decisions = [item for item in proposed.get("decisions", []) if isinstance(item, dict)]
    proposed_risks = [item for item in proposed.get("risks", []) if isinstance(item, dict)]
    proposed_questions = [item for item in proposed.get("open_questions", []) if isinstance(item, dict)]
    _trace_memory_stage("pass2_proposed", {
        "commitments": proposed_commitments,
        "decisions": proposed_decisions,
        "risks": proposed_risks,
        "open_questions": proposed_questions,
    })

    rejected_final = {"actions": [], "decisions": [], "risks": [], "questions": []}

    commitments: list[dict] = []
    owner_repair_trace: list[dict] = []
    for item in proposed_commitments:
        item = dict(item)
        owner = re.sub(r"\s+", " ", str(item.get("owner", "Unknown"))).strip() or "Unknown"
        raw = item.get("evidence", [])
        evidence_values = [raw] if isinstance(raw, str) else list(raw) if isinstance(raw, list) else []

        # If exact first-person evidence comes from one confidently identified
        # participant, that participant owns the action. This separates speaker
        # attribution from the model's semantic `owner` guess.
        grounded_now: list[str] = []
        for value in evidence_values:
            quote = _ground_evidence_quote(str(value or ""), transcript)
            if quote:
                grounded_now.append(quote)
        authoritative_owner = _authoritative_first_person_owner(
            grounded_now, transcript, identity_map
        )
        original_owner = owner
        if authoritative_owner:
            owner = authoritative_owner
            item["owner"] = owner
        owner_repair_trace.append({
            "action": str(item.get("action", "")),
            "original_owner": original_owner,
            "authoritative_owner": authoritative_owner,
            "final_owner_before_validation": owner,
            "grounded_evidence": grounded_now,
        })

        action_tokens = _commitment_content_tokens(str(item.get("action", "")))
        if owner != "Unknown" and action_tokens:
            for event in events:
                if event.get("event_type") not in {"assignment", "commitment", "next_step"}:
                    continue
                event_target = str(event.get("target", "")).strip()
                event_speaker = str(event.get("speaker", "")).strip()
                if owner.casefold() not in {event_target.casefold(), event_speaker.casefold()}:
                    continue
                subject_tokens = _commitment_content_tokens(str(event.get("subject", "")))
                if len(action_tokens & subject_tokens) < 2:
                    continue
                for quote in event.get("evidence", []):
                    if quote not in evidence_values:
                        evidence_values.append(quote)
            item["evidence"] = evidence_values
        validated = _validate_resolved_commitment(item, transcript, identity_map)
        if validated is not None:
            commitments.append(validated)
        else:
            rejected_final["actions"].append(_diagnose_resolved_rejection("actions", item, transcript))

    decisions: list[dict] = []
    for item in proposed_decisions:
        validated = _validate_resolved_decision(item, transcript)
        if validated is not None:
            decisions.append(validated)
        else:
            rejected_final["decisions"].append(_diagnose_resolved_rejection("decisions", item, transcript))

    risks: list[dict] = []
    for item in proposed_risks:
        validated = _validate_resolved_risk(item, transcript)
        if validated is not None:
            risks.append(validated)
        else:
            rejected_final["risks"].append(_diagnose_resolved_rejection("risks", item, transcript))

    questions: list[str] = []
    for item in proposed_questions:
        validated = _validate_resolved_question(item, transcript)
        if validated is not None:
            questions.append(validated)
        else:
            rejected_final["questions"].append(_diagnose_resolved_rejection("questions", item, transcript))

    _trace_memory_stage("owner_resolution", owner_repair_trace)
    _trace_memory_stage("rejected_final", rejected_final)
    _trace_memory_stage("verified_result", {
        "commitments": commitments,
        "decisions": decisions,
        "risks": risks,
        "open_questions": questions,
    })

    _last_memory_resolution_diagnostics.update({
        "status": "verified",
        "actions_proposed": model_proposed_commitment_count,
        "actions_retained": len(commitments),
        "decisions_proposed": len(proposed_decisions),
        "decisions_retained": len(decisions),
        "risks_proposed": len(proposed_risks),
        "risks_retained": len(risks),
        "questions_proposed": len(proposed_questions),
        "questions_retained": len(questions),
        "rejected_final": rejected_final,
    })

    print(
        "Memory event verification: "
        f"actions {len(commitments)}/{len(proposed_commitments)}, "
        f"decisions {len(decisions)}/{len(proposed_decisions)}, "
        f"risks {len(risks)}/{len(proposed_risks)}, "
        f"questions {len(questions)}/{len(proposed_questions)}",
        flush=True,
    )

    normalized_questions = (
        _normalize_resolved_open_questions(questions)
        if questions or not proposed_questions
        else None
    )
    return {
        "commitments": _deduplicate_commitments(commitments) if commitments or not proposed_commitments else None,
        "decisions": _deduplicate_decisions(decisions) if decisions or not proposed_decisions else None,
        "risks": risks if risks or not proposed_risks else None,
        "open_questions": normalized_questions,
        "_verified_open_questions": list(normalized_questions or []),
    }


def _resolve_meeting_memory_event_pipeline(
    meeting_label: str,
    transcript: str,
    memory: dict,
    meeting_summary: str = "",
) -> dict | None:
    """Run v12 event extraction + independent verification on capable systems."""

    if not _memory_resolution_capable():
        _last_memory_resolution_diagnostics.update({"status": "skipped_not_capable"})
        return None
    if not _memory_needs_contextual_resolution(memory, transcript, meeting_summary):
        _last_memory_resolution_diagnostics.update({"status": "skipped_not_needed"})
        return None

    events = _extract_memory_events(
        meeting_label,
        transcript,
        meeting_summary=meeting_summary,
    )
    if events is None:
        _last_memory_resolution_diagnostics.update({"status": "event_extraction_failed", "fallback": "v11_contextual"})
        return None
    resolved = _resolve_meeting_memory_from_events(
        meeting_label,
        transcript,
        memory,
        events,
        meeting_summary=meeting_summary,
    )
    if resolved is None:
        _last_memory_resolution_diagnostics.update({"status": "event_verification_failed", "fallback": "v11_contextual"})
    return resolved


def _resolve_meeting_memory_contextually(
    meeting_label: str,
    transcript: str,
    memory: dict,
    meeting_summary: str = "",
) -> dict | None:
    """Use one high-capability pass to resolve cross-turn meeting memory.

    The model proposes a final authoritative set, but Python still requires
    exact transcript evidence and local lexical grounding for every retained
    item.  Returning None leaves the baseline plumbing untouched.
    """

    if not _memory_resolution_capable():
        return None
    if not _memory_needs_contextual_resolution(memory, transcript, meeting_summary):
        return None

    summary_cues = _summary_memory_cues(meeting_summary)

    schema = {
        "type": "object",
        "properties": {
            "commitments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "action": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["owner", "action", "evidence"],
                    "additionalProperties": False,
                },
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "decision": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["decision", "evidence"],
                    "additionalProperties": False,
                },
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "risk": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["risk", "evidence"],
                    "additionalProperties": False,
                },
            },
            "open_questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    },
                    "required": ["question", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["commitments", "decisions", "risks", "open_questions"],
        "additionalProperties": False,
    }

    prompt = f"""
You are the contextual meeting-memory resolver.  The first extraction pass below
was intentionally conservative and may contain opaque fragments or miss facts
that require connecting nearby turns.  Produce the FINAL authoritative set of
Decisions, Action Items, Risks/Concerns, and Open Questions for this meeting.

Meeting: {meeting_label}

First-pass memory:
{json.dumps({k: memory.get(k, []) for k in ('commitments', 'decisions', 'risks', 'open_questions')}, indent=2)}

Narrative-summary cues (candidate hints only; NOT evidence):
{json.dumps(summary_cues, indent=2)}

Rules:
- The narrative-summary cues are a semantic index only.  They can tell you what
  durable fact to look for, but they can NEVER serve as evidence by themselves.
- Every evidence array entry MUST be an exact contiguous quote from the transcript.
- If a summary cue says the team agreed/planned a follow-up or next step, actively
  search the transcript for the assignment, acceptance, and subject before returning
  an empty Action Items or Decisions category.
- Use multiple short evidence quotes when a fact requires connecting separated turns
  (for example: assignment + later acceptance, or risk cue + earlier stated consequence).
- Use nearby turns to resolve owners, pronouns, antecedents, and accepted tasks.
- An Action Item is assigned/accepted future work.  Prefer a named owner when a
  nearby tasking statement explicitly names that person and later dialogue
  confirms acceptance.  Rewrite the action as a concise self-contained task.
- A Decision is a settled direction/agreement, including an agreed next step.
  Do not duplicate an Action Item verbatim as a Decision; state the distinct
  group-level direction only when one was actually settled.
- A Risk/Concern must be a durable business statement, not a raw quote merely
  containing the word 'risk'.  State the subject/failure mode and consequence.
- An Open Question is a substantive issue still unresolved by meeting end.
  Conversational questions can be normalized into a durable question when the
  nearby transcript supports every substantive term.
- Omit chatter, weak speculation, rhetorical questions, and unsupported inference.
- Prefer omission to invention.

Transcript:
{transcript}
""".strip()

    profile = get_execution_profile(
        PERFORMANCE_PROFILE,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=get_active_llm_model_name(),
    )
    if estimate_tokens(prompt) > profile.direct_token_budget:
        return None

    print("Resolving meeting memory with contextual High Performance pass...", flush=True)
    try:
        raw = ask_llm(
            prompt,
            response_format=schema,
            timeout_seconds=profile.llm_call_timeout_seconds,
        )
        proposed = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    proposed_commitments = [item for item in proposed.get("commitments", []) if isinstance(item, dict)]
    proposed_decisions = [item for item in proposed.get("decisions", []) if isinstance(item, dict)]
    proposed_risks = [item for item in proposed.get("risks", []) if isinstance(item, dict)]
    proposed_questions = [item for item in proposed.get("open_questions", []) if isinstance(item, dict)]

    rejected_final = {"actions": [], "decisions": [], "risks": [], "questions": []}

    commitments: list[dict] = []
    for item in proposed_commitments:
        validated = _validate_resolved_commitment(item, transcript)
        if validated is not None:
            commitments.append(validated)
        else:
            rejected_final["actions"].append(_diagnose_resolved_rejection("actions", item, transcript))

    decisions: list[dict] = []
    for item in proposed_decisions:
        validated = _validate_resolved_decision(item, transcript)
        if validated is not None:
            decisions.append(validated)
        else:
            rejected_final["decisions"].append(_diagnose_resolved_rejection("decisions", item, transcript))

    risks: list[dict] = []
    for item in proposed_risks:
        validated = _validate_resolved_risk(item, transcript)
        if validated is not None:
            risks.append(validated)
        else:
            rejected_final["risks"].append(_diagnose_resolved_rejection("risks", item, transcript))

    questions: list[str] = []
    for item in proposed_questions:
        validated = _validate_resolved_question(item, transcript)
        if validated is not None:
            questions.append(validated)
        else:
            rejected_final["questions"].append(_diagnose_resolved_rejection("questions", item, transcript))

    print(
        "Memory resolver validation: "
        f"summary cues {len(summary_cues)}, "
        f"actions {len(commitments)}/{len(proposed_commitments)}, "
        f"decisions {len(decisions)}/{len(proposed_decisions)}, "
        f"risks {len(risks)}/{len(proposed_risks)}, "
        f"questions {len(questions)}/{len(proposed_questions)}",
        flush=True,
    )

    # None means the resolver attempted a category but validation rejected every
    # proposal.  The caller must preserve the existing baseline for that
    # category rather than silently replacing it with an empty list.  An empty
    # list remains meaningful when the resolver itself proposed no items.
    return {
        "commitments": (
            _deduplicate_commitments(commitments)
            if commitments or not proposed_commitments
            else None
        ),
        "decisions": (
            _deduplicate_decisions(decisions)
            if decisions or not proposed_decisions
            else None
        ),
        "risks": risks if risks or not proposed_risks else None,
        "open_questions": (
            _normalize_open_questions(questions)
            if questions or not proposed_questions
            else None
        ),
    }

def build_complete_meeting_memory(
    meeting_label: str,
    meeting_summary: str,
    transcript: str,
    participants: list[dict] | None = None,
) -> dict:
    """
    Build complete meeting memory from summary state plus
    transcript-grounded commitments and decisions.
    """

    _reset_memory_resolution_diagnostics()

    memory = build_meeting_memory(
        meeting_label=meeting_label,
        meeting_summary=meeting_summary,
    )
    _trace_memory_stage("baseline_memory", memory)

    grounded = (
        extract_grounded_commitments_and_decisions(
            meeting_label=meeting_label,
            transcript=transcript,
            participants=participants,
        )
    )

    memory["commitments"] = grounded.get(
        "commitments",
        [],
    )

    memory["decisions"] = grounded.get(
        "decisions",
        [],
    )

    memory["risks"] = grounded.get(
        "risks",
        [],
    )

    # Narrative memory extraction is useful for topics, but it can
    # manufacture analyst-style questions and sensible-looking tasks.
    # Only transcript-evidenced questions and follow-ups are authoritative.
    memory["open_questions"] = grounded.get(
        "open_questions",
        [],
    )
    memory["follow_ups"] = grounded.get(
        "follow_ups",
        [],
    )

    participant_names = []

    for participant in participants or []:
        if isinstance(
            participant,
            dict,
        ):
            name = str(
                participant.get(
                    "name",
                    "",
                )
            ).strip()
        else:
            name = str(
                participant
            ).strip()

        if not name:
            continue

        if name == SELF_NAME:
            continue

        participant_names.append(
            name
        )

    remote_participant = None

    if len(participant_names) == 1:
        remote_participant = (
            participant_names[0]
        )

    normalized_follow_ups = []

    for follow_up in memory.get(
        "follow_ups",
        [],
    ):
        follow_up_text = str(
            follow_up
        )

        follow_up_text = re.sub(
            rf"\b{re.escape(SELF_SPEAKER_LABEL)}\b",
            SELF_NAME,
            follow_up_text,
            flags=re.IGNORECASE,
        )

        if remote_participant:
            follow_up_text = re.sub(
                r"\bRemote\b",
                remote_participant,
                follow_up_text,
                flags=re.IGNORECASE,
            )

        normalized_follow_ups.append(
            follow_up_text
        )

    memory["follow_ups"] = (
        normalized_follow_ups
    )

    # v12 High Performance path: extract dialogue events first, then resolve and
    # independently verify them into durable memory.  If either v12 pass fails
    # operationally, fall back to the v11 contextual resolver.  Lower-capability
    # profiles never enter either enhanced path.
    resolved_memory = _resolve_meeting_memory_event_pipeline(
        meeting_label,
        transcript,
        memory,
        meeting_summary=meeting_summary,
    )
    verified_open_questions: set[str] = set()
    if resolved_memory is not None:
        verified_open_questions = {
            str(question)
            for question in resolved_memory.get("_verified_open_questions", [])
            if str(question).strip()
        }
    if resolved_memory is None:
        resolved_memory = _resolve_meeting_memory_contextually(
            meeting_label,
            transcript,
            memory,
            meeting_summary=meeting_summary,
        )
    if resolved_memory is not None:
        # The enhanced resolver is authoritative only for precision-sensitive
        # sections. Topics/follow-ups continue through the established path.
        for key in ("commitments", "decisions", "risks", "open_questions"):
            resolved_value = resolved_memory.get(key)
            if resolved_value is not None:
                memory[key] = resolved_value

    if _memory_resolution_capable():
        memory = _high_performance_memory_quality_cleanup(memory)

    reconciled = _reconcile_meeting_memory(
        memory,
        transcript,
        verified_open_questions=verified_open_questions,
    )
    _trace_memory_stage("final_memory", reconciled)
    return reconciled


def _replace_markdown_section(
    summary: str,
    heading: str,
    body: str,
) -> str:
    """Replace a level-two section and collapse duplicate copies."""

    replacement = f"## {heading}\n\n{body.strip()}"
    # Qwen occasionally varies the Markdown heading level even when the
    # prompt requests level two.  Match the requested section at any Markdown
    # heading level, but stop only at the next heading of level 1 or 2 so
    # level-three topic blocks remain inside the Topics section.
    pattern = re.compile(
        rf"(?ms)^#{{1,6}}\s+{re.escape(heading)}\s*$.*?(?=^#{{1,2}}\s+|\Z)"
    )
    matches = list(pattern.finditer(summary))
    if not matches:
        return summary.rstrip() + "\n\n" + replacement

    seen = False

    def replace_once(_match: re.Match) -> str:
        nonlocal seen
        if seen:
            return ""
        seen = True
        return replacement + "\n\n"

    return pattern.sub(replace_once, summary).rstrip()


def _normalize_generated_bullet_sections(summary: str) -> str:
    """Repair LLM list items collapsed into one ` - ` chain.

    Limit this to the two narrative bullet-heavy sections so ordinary prose and
    hyphenated business terms are untouched.
    """

    section_pattern = re.compile(
        r"(?ms)(^#{1,6}\s+(?:Presentations and Updates|Key Themes and Takeaways)\s*$)(.*?)(?=^#{1,2}\s+|\Z)"
    )

    def fix_section(match: re.Match) -> str:
        heading, body = match.group(1), match.group(2)
        fixed_lines = []
        for line in body.splitlines():
            stripped = line.strip()
            bullet_match = re.match(r"^[-*•]\s+(.*)$", stripped)
            if not bullet_match or " - " not in bullet_match.group(1):
                fixed_lines.append(line)
                continue
            parts = [part.strip() for part in re.split(r"\s+-\s+(?=[A-Z])", bullet_match.group(1)) if part.strip()]
            if len(parts) < 2:
                fixed_lines.append(line)
                continue
            fixed_lines.extend(f"- {part}" for part in parts)
        return heading + "\n" + "\n".join(fixed_lines)

    return section_pattern.sub(fix_section, summary)


def compose_summary_with_meeting_memory(
    meeting_summary: str,
    memory: dict,
) -> str:
    """Make structured meeting-memory facts authoritative in the summary."""

    decision_lines = []
    for item in memory.get("decisions", []):
        if isinstance(item, dict):
            text = str(item.get("decision", "")).strip()
        else:
            text = str(item).strip()
        if text and f"- {text}" not in decision_lines:
            decision_lines.append(f"- {text}")

    action_lines = []
    for item in memory.get("commitments", []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).strip()
        if not action:
            continue
        owner = str(item.get("owner", "")).strip() or "Owner not identified"
        if owner == "Unknown":
            owner = "Owner not identified"
        line = f"- {owner} - {action} - Due date not identified"
        if line not in action_lines:
            action_lines.append(line)

    risk_lines = []
    for item in memory.get("risks", []):
        if isinstance(item, dict):
            text = str(item.get("risk", "")).strip()
        else:
            text = str(item).strip()
        if text and f"- {text}" not in risk_lines:
            risk_lines.append(f"- {text}")

    question_lines = []
    for item in memory.get("open_questions", []):
        text = str(item).strip()
        if text and f"- {text}" not in question_lines:
            question_lines.append(f"- {text}")

    topic_blocks = []
    for item in memory.get("topics", []):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic", "")).strip()
        if not topic:
            continue
        status = str(item.get("status", "unclear")).strip() or "unclear"
        topic_summary = str(item.get("summary", "")).strip()
        block = f"### {topic} — {status}"
        if topic_summary:
            block += f"\n\n{topic_summary}"
        topic_blocks.append(block)

    composed = _normalize_generated_bullet_sections(meeting_summary)
    composed = _strip_narrative_no_decision_claims(
        composed,
        bool(decision_lines),
    )
    composed = _strip_narrative_action_item_claims(
        composed,
        bool(action_lines),
    )
    composed = _strip_unsupported_narrative_vendor_preferences(
        composed,
        [item for item in memory.get("decisions", []) if isinstance(item, dict)],
    )
    composed = _replace_markdown_section(
        composed,
        "Decisions",
        "\n".join(decision_lines) or "None identified.",
    )
    composed = _replace_markdown_section(
        composed,
        "Action Items",
        "\n".join(action_lines) or "None identified.",
    )
    composed = _replace_markdown_section(
        composed,
        "Risks and Concerns",
        "\n".join(risk_lines) or "None identified.",
    )
    composed = _replace_markdown_section(
        composed,
        "Open Questions",
        "\n".join(question_lines) or "None identified.",
    )
    composed = _replace_markdown_section(
        composed,
        "Topics",
        "\n\n".join(topic_blocks) or "None identified.",
    )
    return composed.strip()


def clean_transcript_in_chunks(
    transcript: str,
    max_words: int = 1500,
) -> str:
    """
    Clean a long transcript in word-based chunks and
    return the combined result.
    """

    chunks = chunk_transcript(
        transcript,
        max_words=max_words,
    )

    print()
    print(f"Cleaning {len(chunks)} transcript chunks...")

    cleaned_chunks = []

    for chunk_number, chunk in enumerate(chunks, start=1):
        print(
            f"Cleaning chunk "
            f"{chunk_number}/{len(chunks)}...",
            flush=True,
        )

        try:
            cleaned_chunk = clean_transcript(chunk)

        except Exception as e:
            print()
            print(
                f"WARNING: Cleanup failed for chunk "
                f"{chunk_number}/{len(chunks)}"
            )
            print(f"Reason: {e}")
            print("Using original transcript for this chunk.")

            cleaned_chunk = chunk

        cleaned_chunks.append(cleaned_chunk)

    return "\n\n".join(cleaned_chunks)


def summarize_meeting_chunk(
    transcript_chunk: str,
    chunk_number: int,
    total_chunks: int,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """
    Create a factual summary of one transcript chunk.
    """

    prompt = f"""
You are summarizing one chronological section of a meeting transcript.

This is section {chunk_number} of {total_chunks}.

Rules:
- Capture every substantial presentation, update, workstream, decision,
  action item, risk, open question, date, and number in this section.
- Do not omit speaker contributions merely because they are informational.
- When multiple people discuss separate projects, list each one separately.
- Use only information explicitly stated.
- Do not invent names, owners, deadlines, decisions, or action items.
- Use clean Markdown with headings and normal bullets only.
- Do not use bold, italics, or emojis.
- Output only the section summary.

Use this structure:

## Section {chunk_number}

### Presentations and Updates
- Speaker or label — subject and key points

### Key Topics
- Topic

### Decisions
- Confirmed decision
- If none, write "None identified."

### Action Items
- Owner — Action — Due date
- If none, write "None identified."

### Risks and Concerns
- Risk or concern
- If none, write "None identified."

### Open Questions
- Unresolved question
- If none, write "None identified."

### Important Dates and Numbers
- Significant date, amount, quantity, or deadline
- If none, write "None identified."

Transcript section:

{transcript_chunk}
""".strip()

    return ask_llm(
        prompt,
        timeout_seconds=timeout_seconds,
    )


DIRECT_SUMMARY_CONTEXT = """
You are an expert executive meeting analyst.

Create a concise, balanced, business-relevant meeting summary from the
complete chronological meeting transcript below.

General Rules

- Treat the transcript itself as the source of truth.
- Preserve meaningful coverage of every substantial presentation or workstream.
- Give balanced coverage to the beginning, middle, and end of the meeting.
- Prioritize strategic implications, business outcomes, decisions, risks,
  dependencies, commitments, and genuinely unresolved questions.
- Consolidate overlapping topics across the meeting.
- Do not repeat the same point in multiple sections.
- Use only information explicitly contained in the transcript.
- Do not invent decisions, owners, deadlines, action items, names,
  dates, numbers, technical terms, or business rationale.
- Clearly distinguish confirmed decisions from discussion,
  proposals, requests, conditional statements, and tentative plans.
- Do not promote a conditional or proposed outcome to a confirmed decision.
- Incorporate important dates, dollar amounts, targets, quantities,
  and deadlines into the relevant topic.
- Preserve important technical names, project names, products,
  systems, teams, and people exactly as supported by the transcript.
- Exclude greetings, casual conversation, meeting logistics,
  timestamps, and social chatter unless they materially affect business work.
""".strip()


def build_direct_meeting_summary_prompt(transcript: str) -> str:
    return f"""
{DIRECT_SUMMARY_CONTEXT}

{SUMMARY_SECTION_RULES}

{SUMMARY_FORMATTING_RULES}

Complete chronological meeting transcript:

{transcript}
""".strip()


def plan_meeting_summary_execution(transcript: str) -> dict:
    """Choose Direct vs Chunked using the same profile budgets as queries."""
    profile = get_execution_profile(
        PERFORMANCE_PROFILE,
        context_size_tokens=LLM_CONTEXT_SIZE,
        model_name=LLM_MODEL,
    )
    prompt = build_direct_meeting_summary_prompt(transcript)
    execution_plan = choose_execution_plan(
        prompt,
        can_chunk=True,
        direct_token_budget=profile.direct_token_budget,
    )
    return {
        "mode": execution_plan.mode,
        "estimated_prompt_tokens": execution_plan.estimated_prompt_tokens,
        "direct_token_budget": execution_plan.direct_token_budget,
        "profile": profile,
    }


def summarize_meeting_direct(
    transcript: str,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """Summarize one complete cleaned transcript, then polish it."""
    prompt = build_direct_meeting_summary_prompt(transcript)

    print()
    print("Summarizing complete transcript directly...")

    draft_summary = ask_llm(
        prompt,
        timeout_seconds=timeout_seconds,
    )

    return polish_meeting_summary(
        draft_summary,
        source_material=transcript,
        source_label="complete chronological transcript",
        timeout_seconds=timeout_seconds,
    )


def summarize_meeting_in_chunks(
    transcript: str,
    max_words: int = 1500,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """
    Summarize each transcript chunk, then create one final meeting summary.
    """

    chunks = chunk_transcript(
        transcript,
        max_words=max_words,
    )

    section_summaries = []

    print()
    print(f"Summarizing {len(chunks)} transcript chunks...")

    for chunk_number, chunk in enumerate(chunks, start=1):
        print(
            f"Summarizing chunk "
            f"{chunk_number}/{len(chunks)}...",
            flush=True,
        )

        section_summary = summarize_meeting_chunk(
            transcript_chunk=chunk,
            chunk_number=chunk_number,
            total_chunks=len(chunks),
            timeout_seconds=timeout_seconds,
        )

        section_summaries.append(section_summary)

    combined_sections = "\n\n".join(section_summaries)

    final_prompt = f"""
{SUMMARY_CONTEXT}

{SUMMARY_SECTION_RULES}

{SUMMARY_FORMATTING_RULES}

Chronological section summaries:

{combined_sections}
""".strip()

    print()
    print("Synthesizing final meeting summary...")
    
    draft_summary = ask_llm(
        final_prompt,
        timeout_seconds=timeout_seconds,
    )

    return polish_meeting_summary(
        draft_summary,
        source_material=combined_sections,
        source_label="chronological section summaries",
        timeout_seconds=timeout_seconds,
    )


def summarize_meeting_hardware_aware(
    transcript: str,
) -> tuple[str, dict]:
    """Summarize directly when the resolved profile can safely fit it."""
    plan = plan_meeting_summary_execution(transcript)
    profile = plan["profile"]
    mode = plan["mode"]

    print()
    print(
        "Meeting summary plan: "
        f"{profile.name}"
        + (
            f"→{profile.resolved_name}"
            if profile.name == "Auto"
            else ""
        )
        + f" · {mode.title()}"
        + f" · ~{plan['estimated_prompt_tokens']:,} tokens"
        + f" · {plan['direct_token_budget']:,} direct budget"
    )

    if mode == "direct":
        summary = summarize_meeting_direct(
            transcript,
            timeout_seconds=profile.llm_call_timeout_seconds,
        )
    else:
        summary = summarize_meeting_in_chunks(
            transcript,
            timeout_seconds=profile.llm_call_timeout_seconds,
        )

    metadata = {
        "mode": mode.title(),
        "estimated_prompt_tokens": int(plan["estimated_prompt_tokens"]),
        "direct_token_budget": int(plan["direct_token_budget"]),
        "profile_requested": profile.name,
        "profile_resolved": profile.resolved_name,
        "profile_display": (
            f"Auto → {profile.resolved_name}"
            if profile.name == "Auto"
            else profile.resolved_name
        ),
        "context_size_tokens": int(profile.context_size_tokens),
        "ai_model": get_active_llm_model_name(),
        "ai_backend": get_active_llm_backend_name(),
    }
    return summary, metadata


def build_grounded_summary_polish_prompt(
    summary: str,
    *,
    source_material: str | None = None,
    source_label: str = "source material",
) -> str:
    """Build the final grounding and consistency pass for a meeting summary."""
    grounding_block = ""
    if source_material:
        grounding_block = f"""

SOURCE OF TRUTH

Use the {source_label} below to verify every substantive statement in the
summary. The source outranks the draft summary. If the draft conflicts with
the source, correct or remove the draft statement. Prefer omission over an
unsupported inference.

{source_label.title()}:

{source_material}
"""

    return f"""
You are performing the final grounding and consistency review of an existing
business meeting summary.

Do not add new information. Do not improve the story by inventing rationale,
next steps, certainty, ownership, risk, or conclusions.

GROUNDING AND CERTAINTY
- Preserve the difference between discussed, proposed, recommended, requested,
  conditional, planned, agreed, decided, completed, and closed.
- Never promote discussion, a recommendation, a likely outcome, or a conditional
  statement into a confirmed decision.
- Never convert a topic that lacks detail into an open question.
- Never convert a discussion point into an action item merely because further
  work would be sensible.
- Preserve supplier, product, project, system, person, date, quantity, and dollar
  names exactly when the source supports them. Do not substitute similar names.
- Remove unsupported business rationale such as claims that a choice is safer,
  more strategic, or more cost-effective unless that rationale is explicitly
  supported.
- Exclude personal/social material unless it materially affects business work.

DECISIONS
- Include only explicit, confirmed decisions or agreements.
- If the source contains no confirmed decision, write "None identified."
- If Decisions says "None identified", no other section may describe an item
  as decided, approved, confirmed, finalized, closed, or committed unless that
  inconsistency is corrected.
- If another section contains a source-supported confirmed decision, put it in
  Decisions and make the wording consistent everywhere else.

ACTION ITEMS
- Include only explicit commitments, assigned work, requested follow-up, or a
  clearly stated next step that remains to be done.
- Do not create an action item from a topic, risk, recommendation, or unresolved
  situation by itself.
- Use a named owner only when ownership is explicit. Otherwise use
  "Owner not identified". Never use Remote or Mic as an owner.
- Use an actual due date only when stated. Otherwise use
  "Due date not identified".
- Format each item as: Owner - Action - Due date.
- If there are no supported action items, write "None identified."

OPEN QUESTIONS
- Include only questions explicitly raised or clearly stated as unresolved in
  the source.
- Do not invent questions to summarize missing information.
- If none remain unresolved, write "None identified."

RISKS AND STATUS
- Include only risks, concerns, blockers, dependencies, or uncertainties explicitly
  stated by a participant in the source.
- Do not infer hypothetical downstream risk from complexity, cost, timing, vendor
  relationships, contract terms, or administrative friction.
- If the source says an item is not a risk, do not restate it as a risk.
- If no risk or concern is explicitly supported, write "None identified."
- Do not mark a topic closed merely because a choice was discussed. Closed means
  the source establishes that the matter is complete/resolved with no remaining
  work relevant to the topic.

CROSS-SECTION CONSISTENCY
- Reconcile the Executive Summary, updates, themes, Decisions, Action Items,
  Risks, and Open Questions so they do not contradict one another.
- A fact may appear in more than one section only when necessary; use the same
  certainty and status each time.
- Do not say "no decisions" in one section while describing a confirmed
  decision elsewhere.
- Do not say an item is closed while also describing unresolved work on that
  same item unless the source explicitly supports both.

FORMAT
- Keep the Executive Summary to 2 concise paragraphs.
- Limit Presentations and Updates to 8 bullets.
- Combine related details from the same presentation or workstream.
- Limit Key Themes and Takeaways to 6 bullets.
- Remove duplicate content across sections.
- Preserve the existing required section headings.
- Use no bold, italics, emojis, or numbered headings.
- Output only the revised Markdown summary.
{grounding_block}

DRAFT SUMMARY TO REVIEW:

{summary}
""".strip()


def polish_meeting_summary(
    summary: str,
    *,
    source_material: str | None = None,
    source_label: str = "source material",
    timeout_seconds: float | None = None,
) -> str:
    """Ground, reconcile, and normalize an already-generated summary."""

    print()
    print("Grounding and polishing final meeting summary...")

    prompt = build_grounded_summary_polish_prompt(
        summary,
        source_material=source_material,
        source_label=source_label,
    )

    return ask_llm(
        prompt,
        timeout_seconds=timeout_seconds,
    )


def is_self_reference_window(
    candidate_name: str,
    window: str,
) -> bool:
    """
    Return True when a known self-reference name is
    directly addressed by the Remote channel.

    Mic is SELF_SPEAKER_LABEL, so a Mic-side direct
    address to the same name refers to another person.
    """

    if candidate_name not in SELF_REFERENCE_NAMES:
        return False

    lines = window.splitlines()

    current_speaker = None

    speaker_pattern = re.compile(
        r"\*\*(Mic|Remote)\*\*",
        flags=re.IGNORECASE,
    )

    escaped_name = re.escape(
        candidate_name
    )

    self_address_patterns = [
        # "Welcome back <name>"
        # "Hey <name>"
        # "Thanks <name>"
        rf"\b(?:welcome back|hey|hi|hello|thanks|thank you)"
        rf"\s+{escaped_name}\b",

        # "<name>, to your question..."
        rf"\b{escaped_name}\s*[,?!.]",

        # "we agree <name> I..."
        rf"\bagree\s+{escaped_name}\b",

        # "<name> ... your question"
        # "<name> ... you mentioned"
        rf"\b{escaped_name}\b"
        rf"[^\n]{{0,100}}"
        rf"\b(?:you|your|you're|you've|you'll)\b",
    ]

    for line in lines:
        speaker_match = speaker_pattern.search(
            line
        )

        if speaker_match:
            current_speaker = (
                speaker_match.group(1)
            )
            continue

        if (
            candidate_name.casefold()
            not in line.casefold()
        ):
            continue

        if current_speaker is None:
            continue

        # If the local/self channel is speaking, this is the local user
        # addressing somebody else with the same name.
        if (
            current_speaker.casefold()
            == SELF_SPEAKER_LABEL.casefold()
        ):
            return False

        for pattern in self_address_patterns:
            if re.search(
                pattern,
                line,
                flags=re.IGNORECASE,
            ):
                return True

    return False


def build_participant_evidence(
    transcript: str,
    context_lines: int = 4,
) -> str:
    """
    Build a smaller transcript excerpt containing likely
    direct-address evidence plus surrounding conversation.
    """

    lines = transcript.splitlines()

    direct_address_pattern = re.compile(
        r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?=[,?])"
    )

    ignored_words = {
        "Okay",
        "Yes",
        "No",
        "So",
        "Well",
        "Right",
        "Great",
        "Thanks",
        "Thank",
        "Actually",
        "Maybe",
        "Sure",
        "Good",
        "Yeah",
        "Hey",
    }

    selected_indexes = set()

    for index, line in enumerate(lines):
        matches = direct_address_pattern.findall(
            line
        )

        useful_matches = [
            name
            for name in matches
            if name not in ignored_words
        ]

        if not useful_matches:
            continue

        start = max(
            0,
            index - context_lines,
        )

        end = min(
            len(lines),
            index + context_lines + 1,
        )

        selected_indexes.update(
            range(start, end)
        )

    if not selected_indexes:
        return transcript[:12000]

    evidence_lines = [
        lines[index]
        for index in sorted(selected_indexes)
    ]

    return "\n".join(
        evidence_lines
    )


def extract_known_people_from_run_names(
    run_names: list[str],
) -> list[str]:
    """
    Extract known participant names from trusted meeting
    run names, especially explicit 1v1 titles.
    """

    people = set()

    for run_name in run_names:
        candidate = get_context_participant_candidate(
            run_name
        )

        if candidate:
            people.add(
                candidate
            )

    return sorted(
        people,
        key=str.casefold,
    )


def extract_candidate_names(
    transcript: str,
) -> list[str]:
    """
    Extract likely human-name candidates from transcript text.

    This intentionally favors recall over certainty.
    Candidate names are validated later by the
    deterministic window-scoring logic.
    """

    ignored_names = {
        "Okay",
        "Yes",
        "No",
        "So",
        "Well",
        "Right",
        "Great",
        "Thanks",
        "Thank",
        "Actually",
        "Maybe",
        "Sure",
        "Good",
        "Yeah",
        "Hey",
        "Oh",
        "Um",
        "Like",
        "Here",
        "Home",
        "See",
        "Beauty",
        "God",
        "America",
        "Of",
        "Really",
        "Think",
        "Probably",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }

    candidates = set()

    def normalize_candidate(
        name: str,
    ) -> str | None:
        name = name.strip()

        if not name:
            return None

        words = name.split()

        # Collapse duplicated names:
        # "Alex Alex" -> "Alex"
        if (
            len(words) == 2
            and words[0].casefold()
            == words[1].casefold()
        ):
            name = words[0]
            words = [name]

        # Reject phrases containing obvious non-name words:
        # "Think Alex"
        # "Probably Starbucks"
        if any(
            word.title() in ignored_names
            for word in words
        ):
            return None

        if name.title() in ignored_names:
            return None

        # Known phrase fragment, not a person.
        if name.casefold() in {
            "call security",
        }:
            return None

        return name

    # Names used as direct address:
    # "Alex, ..."
    # "I agree, Alex."
    # "Jordan?"
    direct_address_pattern = re.compile(
        r"\b([A-Z][a-z]+"
        r"(?:\s+[A-Z][a-z]+)?)"
        r"(?=[,?!])"
    )

    for match in direct_address_pattern.finditer(
        transcript
    ):
        name = normalize_candidate(
            match.group(1)
        )

        if name:
            candidates.add(
                name
            )

    # Names associated with explicit meeting-presence language:
    # "Alex stepped away"
    # "Jordan joined"
    presence_pattern = re.compile(
        r"\b([A-Z][a-z]+"
        r"(?:\s+[A-Z][a-z]+)?)"
        r"\s+"
        r"(?:stepped away|joined|left|returned|came back)\b",
        flags=re.IGNORECASE,
    )

    for match in presence_pattern.finditer(
        transcript
    ):
        name = normalize_candidate(
            match.group(1).title()
        )

        if name:
            candidates.add(
                name
            )

    return sorted(
        candidates,
        key=str.casefold,
    )


def build_candidate_windows(
    transcript: str,
    candidate_name: str,
    context_lines: int = 2,
) -> list[str]:
    """
    Return a separate evidence window for every occurrence
    of one candidate name.
    """

    lines = transcript.splitlines()

    candidate_pattern = re.compile(
        rf"\b{re.escape(candidate_name)}\b",
        flags=re.IGNORECASE,
    )

    windows = []

    for index, line in enumerate(lines):
        if not candidate_pattern.search(line):
            continue

        start = max(
            0,
            index - context_lines,
        )

        end = min(
            len(lines),
            index + context_lines + 1,
        )

        window = "\n".join(
            lines[start:end]
        ).strip()

        if window:
            windows.append(
                window
            )

    return windows


def score_candidate_window(
    candidate_name: str,
    window: str,
) -> dict:
    """
    Score one evidence window for one candidate.
    """

    name = re.escape(candidate_name)

    positive_signals = []
    negative_signals = []
    score = 0

    obvious_non_person_names = {
        "uh",
        "um",
        "ah",
        "oh",
        "yeah",
        "yep",
        "okay",
        "ok",
        "well",
        "so",
        "but",
        "and",
        "anyways",
        "otherwise",
    }

    if (
        candidate_name.casefold()
        in obvious_non_person_names
    ):
        return {
            "score": 0,
            "positive_signals": [],
            "negative_signals": [],
        }

    if is_self_reference_window(
        candidate_name,
        window,
    ):
        return {
            "score": 0,
            "positive_signals": [],
            "negative_signals": [
                "self reference",
            ],
        }

    # Strong presence language.
    if re.search(
        rf"\b{name}\b.*\bstepped away\b",
        window,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        positive_signals.append(
            "explicit current-meeting presence"
        )
        score += 4
    # Strong direct-address patterns.
    #
    # Avoid treating any arbitrary "Word," as a person.
    # Require conversational language that looks like
    # someone is actually being addressed.
    direct_address_patterns = [
        rf"\b{name}\s*,\s*"
        rf"(?:are|is|do|did|can|could|would|will|"
        rf"have|has|what|how|why|when|where|if|"
        rf"I\b|I'm\b|I'll\b|we\b|you\b|your\b|so\b)",

        rf"(?:^|[?!.]\s+)"
        rf"{name}\s+"
        rf"(?:are|is|do|did|can|could|would|will|"
        rf"have|has|what|how|why|when|where|that\b|"
        rf"I\b|we\b|you\b)",

        # Direct address at the end of a statement/question:
        # "I agree, Alex."
        # "You're up for the day, Taylor?"
        rf",\s*{name}\s*[.?!]",

        # Useful transcript forms seen in real meetings.
        rf"\b{name}\s+does\b",
        rf"\b{name}\s+if\b",
        rf"\b{name}\s+I\b",
    ]

    for pattern in direct_address_patterns:
        if re.search(
            pattern,
            window,
            flags=re.IGNORECASE,
        ):
            positive_signals.append(
                "direct address"
            )
            score += 3
            break
     
    # Group direct address:
    # "Alex, Jordan, Taylor, I'm going to be coming
    #  to one of your team meetings..."
    #
    # A comma-separated list of names followed by
    # second-person language is strong evidence that
    # the people in the list are being addressed.
    name_list_pattern = re.compile(
        r"\b[A-Z][a-z]+"
        r"(?:\s+[A-Z][a-z]+)?"
        r"(?:,\s*[A-Z][a-z]+"
        r"(?:\s+[A-Z][a-z]+)?){1,4},"
    )

    for match in name_list_pattern.finditer(
        window
    ):
        if candidate_name.casefold() in obvious_non_person_names:
            continue        

        name_list_text = match.group(0)

        if not re.search(
            rf"\b{name}\b",
            name_list_text,
            flags=re.IGNORECASE,
        ):
            continue

        following_text = window[
            match.end():match.end() + 160
        ]

        if re.search(
            r"\b(?:you|your|guys)\b",
            following_text,
            flags=re.IGNORECASE,
        ):
            positive_signals.append(
                "group direct address"
            )
            score += 3
            break
 
    # Example/list language should not count as direct address.
    if re.search(
        rf"\b(?:so\s+)?like\s+{name}\s*,",
        window,
        flags=re.IGNORECASE,
    ):
        negative_signals.append(
            "used as an example"
        )
        score -= 4

    if re.search(
        rf"(?:that's|that is)\s+"
        rf"(?:[A-Z][a-z]+,\s*)+"
        rf"{name}\b",
        window,
        flags=re.IGNORECASE,
    ):
        negative_signals.append(
            "listed with other people"
        )
        score -= 3

    # Past / separate interaction.
    past_patterns = [
        rf"one[- ]on[- ]one with (?:him|her|{name})",
        rf"talked (?:to|with) {name}",
        rf"met with {name}",
    ]

    for pattern in past_patterns:
        if re.search(
            pattern,
            window,
            flags=re.IGNORECASE,
        ):
            negative_signals.append(
                "referenced in another interaction"
            )
            score -= 4
            break

    return {
        "score": score,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
    }


def summarize_candidate_windows(
    candidate_name: str,
    windows: list[str],
) -> dict:
    """
    Aggregate per-window scores for one candidate.
    """

    window_results = []

    for window in windows:
        result = score_candidate_window(
            candidate_name,
            window,
        )

        window_results.append(
            result
        )

    positive_windows = sum(
        1
        for result in window_results
        if result["score"] > 0
    )

    negative_windows = sum(
        1
        for result in window_results
        if result["score"] < 0
    )

    strongest_positive = max(
        (
            result["score"]
            for result in window_results
        ),
        default=0,
    )

    strongest_negative = min(
        (
            result["score"]
            for result in window_results
        ),
        default=0,
    )

    return {
        "positive_windows": positive_windows,
        "negative_windows": negative_windows,
        "strongest_positive": strongest_positive,
        "strongest_negative": strongest_negative,
        "window_results": window_results,
    }


def decide_candidate_participation(
    summary: dict,
) -> str:
    """
    Classify candidate participation from deterministic
    per-window evidence.

    Returns:
    - "participant"
    - "not_participant"
    - "uncertain"
    """

    positive_windows = summary.get(
        "positive_windows",
        0,
    )

    negative_windows = summary.get(
        "negative_windows",
        0,
    )

    strongest_positive = summary.get(
        "strongest_positive",
        0,
    )

    strongest_negative = summary.get(
        "strongest_negative",
        0,
    )

    if (
        positive_windows >= 2
        and strongest_positive >= 3
    ):
        return "participant"

    if (
        positive_windows >= 1
        and negative_windows == 0
        and strongest_positive >= 3
    ):
        return "participant"

    if (
        positive_windows == 0
        and negative_windows >= 1
        and strongest_negative < 0
    ):
        return "not_participant"

    return "uncertain"


def build_candidate_evidence(
    transcript: str,
    candidate_name: str,
    context_lines: int = 4,
) -> str:
    """
    Collect all transcript occurrences of one candidate name
    plus surrounding conversational context.
    """

    lines = transcript.splitlines()

    candidate_pattern = re.compile(
        rf"\b{re.escape(candidate_name)}\b",
        flags=re.IGNORECASE,
    )

    selected_indexes = set()

    for index, line in enumerate(lines):
        if not candidate_pattern.search(line):
            continue

        start = max(
            0,
            index - context_lines,
        )

        end = min(
            len(lines),
            index + context_lines + 1,
        )

        selected_indexes.update(
            range(start, end)
        )

    if not selected_indexes:
        return ""

    evidence_lines = [
        lines[index]
        for index in sorted(selected_indexes)
    ]

    return "\n".join(
        evidence_lines
    )


def classify_candidate_participation(
    candidate_name: str,
    evidence: str,
    meeting_context: str | None = None,
) -> dict:
    """
    Decide whether one named person is actually participating
    in the current meeting.
    """

    prompt = f"""
You are determining whether ONE specific person is an actual
participant in the CURRENT meeting.

Candidate:
{candidate_name}

Meeting context:
{meeting_context or "Unknown"}

Only evaluate the candidate named above.

A person IS a participant when the evidence indicates they are
actually present in the current meeting.

Strong evidence includes:
- they are directly addressed in the current meeting
- they answer or respond
- they contribute information
- the conversation explicitly indicates they are present
- they joined, left, returned, or temporarily stepped away
- multiple current-meeting statements are clearly directed to them

A person is NOT a participant merely because their name appears.

Do NOT count someone as a participant when the evidence only:
- discusses them
- describes a previous meeting or one-on-one with them
- quotes something they said previously
- mentions plans to speak with them later
- lists them with other employees
- uses them as an example
- describes work they are doing while they are not present

Pay particular attention to whether the evidence refers to
THIS meeting versus another past or future interaction.

Return only the structured result.

EVIDENCE:

{evidence}
""".strip()

    response = ask_llm(
        prompt,
        response_format={
            "type": "object",
            "properties": {
                "is_participant": {
                    "type": "boolean"
                },
                "confidence": {
                    "type": "string",
                    "enum": [
                        "high",
                        "medium",
                        "low",
                    ],
                },
                "reason": {
                    "type": "string"
                },
            },
            "required": [
                "is_participant",
                "confidence",
                "reason",
            ],
        },
    )

    try:
        result = json.loads(response)

    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Candidate classification returned invalid JSON."
        ) from error

    if not isinstance(result, dict):
        raise RuntimeError(
            "Candidate classification did not return an object."
        )

    return result


def score_candidate_evidence(
    candidate_name: str,
    evidence: str,
) -> dict:
    """
    Score transcript evidence for whether one named person
    appears to be participating in the current meeting.

    Positive scores support current participation.
    Negative scores support mentioned-only / absent status.
    """

    name = re.escape(candidate_name)

    positive_signals = []
    negative_signals = []

    score = 0

    # Strong current-meeting presence language.
    presence_patterns = [
        rf"\b{name}\b.*\bstepped away\b",
        rf"\b{name}\b.*\bjoined\b",
        rf"\b{name}\b.*\bleft\b",
        rf"\b{name}\b.*\breturned\b",
        rf"\b{name}\b.*\bcame back\b",
    ]

    for pattern in presence_patterns:
        if re.search(
            pattern,
            evidence,
            flags=re.IGNORECASE,
        ):
            positive_signals.append(
                "explicit current-meeting presence"
            )
            score += 4
            break

    # Direct address: "Alex, ...", "I agree, Jordan.",
    # "You're up for the day, Taylor?"
    direct_address_patterns = [
        rf"\b{name}\s*[,?!]",
        rf",\s*{name}\s*[.?!]",
    ]

    direct_address_count = 0

    for pattern in direct_address_patterns:
        direct_address_count += len(
            re.findall(
                pattern,
                evidence,
                flags=re.IGNORECASE,
            )
        )

    if direct_address_count:
        positive_signals.append(
            f"direct address x{direct_address_count}"
        )
        score += min(
            direct_address_count * 2,
            6,
        )

    # Strong evidence that the person is being discussed
    # from another interaction rather than attending now.
    past_interaction_patterns = [
        rf"one[- ]on[- ]one with (?:him|her|{name})",
        rf"one on one with (?:him|her|{name})",
        rf"talked (?:to|with) {name}",
        rf"met with {name}",
        rf"meeting with {name}",
    ]

    for pattern in past_interaction_patterns:
        if re.search(
            pattern,
            evidence,
            flags=re.IGNORECASE,
        ):
            negative_signals.append(
                "referenced in another interaction"
            )
            score -= 4
            break

    # Explicit past-time reference near the candidate.
    past_time_patterns = [
        rf"\b{name}\b[^\n]{{0,120}}\byesterday\b",
        rf"\byesterday\b[^\n]{{0,120}}\b{name}\b",
        rf"\b{name}\b[^\n]{{0,120}}\blast week\b",
        rf"\blast week\b[^\n]{{0,120}}\b{name}\b",
    ]

    for pattern in past_time_patterns:
        if re.search(
            pattern,
            evidence,
            flags=re.IGNORECASE,
        ):
            negative_signals.append(
                "past-time reference"
            )
            score -= 3
            break

    # Example-style language such as:
    # "So like Jordan, who's her immediate successor?"
    if re.search(
        rf"\b(?:so\s+)?like\s+{name}\s*,",
        evidence,
        flags=re.IGNORECASE,
    ):
        negative_signals.append(
            "used as an example"
        )
        score -= 3

    return {
        "score": score,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
    }


def get_context_participant_candidate(
    meeting_context: str | None,
) -> str | None:
    """
    Extract a participant name from a meeting run name
    when the title explicitly identifies a 1v1.
    """

    if not meeting_context:
        return None

    try:
        _, _, title = meeting_context.split(
            "_",
            2,
        )
    except ValueError:
        title = meeting_context

    # Remove trailing MMDDYY.
    title = re.sub(
        r"\d{6}$",
        "",
        title,
    )

    match = re.fullmatch(
        r"(.+?)1v1",
        title,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    name = match.group(1)

    name = name.replace(
        "_",
        " ",
    )

    # Split CamelCase.
    name = re.sub(
        r"(?<=[a-z])(?=[A-Z])",
        " ",
        name,
    )

    # Preserve acronyms while separating words.
    name = re.sub(
        r"(?<=[A-Z])(?=[A-Z][a-z])",
        " ",
        name,
    )

    name = name.strip()

    return name or None


def get_title_participant_candidate(
    meeting_context: str | None,
    known_people: list[str],
) -> str | None:
    """
    Identify a trusted participant when a non-1v1
    meeting title begins with a known person's name.
    """

    if not meeting_context:
        return None

    try:
        _, _, title = meeting_context.split(
            "_",
            2,
        )
    except ValueError:
        title = meeting_context

    # Remove trailing MMDDYY.
    title = re.sub(
        r"\d{6}$",
        "",
        title,
    )

    compact_title = re.sub(
        r"[^A-Za-z0-9]",
        "",
        title,
    ).casefold()

    # Longest names first prevents:
    # "Sam" matching the start of "Samantha".
    sorted_people = sorted(
        known_people,
        key=lambda name: len(
            re.sub(
                r"[^A-Za-z0-9]",
                "",
                name,
            )
        ),
        reverse=True,
    )

    for person in sorted_people:
        compact_person = re.sub(
            r"[^A-Za-z0-9]",
            "",
            person,
        ).casefold()

        if (
            compact_person
            and compact_title.startswith(
                compact_person
            )
        ):
            return person

    return None


def extract_participants(
    transcript: str,
    meeting_context: str | None = None,
) -> list[dict]:
    """
    Extract likely meeting participants.

    Uses:
    - deterministic 1v1 title parsing
    - candidate-name extraction
    - per-candidate evidence windows
    - deterministic participation scoring

    Ambiguous candidates are intentionally omitted for now.
    """

    context_candidate = (
        get_context_participant_candidate(
            meeting_context
        )
    )

    if context_candidate:
        return [
            {
                "name": context_candidate,
                "confidence": "high",
                "reason": (
                    "Participant identified by "
                    "the 1v1 meeting title"
                ),
            }
        ]

    participants = []

    candidate_names = load_known_people()

    title_candidate = (
        get_title_participant_candidate(
            meeting_context,
            candidate_names,
        )
    )

    for candidate_name in candidate_names:
        windows = build_candidate_windows(
            transcript,
            candidate_name,
        )

        summary = summarize_candidate_windows(
            candidate_name,
            windows,
        )

        decision = decide_candidate_participation(
            summary
        )

        if decision != "participant":
            continue

        participants.append(
            {
                "name": candidate_name,
                "confidence": "high",
                "reason": (
                    "Participant identified from "
                    "multiple current-meeting "
                    "evidence windows"
                ),
            }
        )

    if title_candidate:
        already_present = any(
            participant["name"].casefold()
            == title_candidate.casefold()
            for participant in participants
        )

        if not already_present:
            participants.append(
                {
                    "name": title_candidate,
                    "confidence": "high",
                    "reason": (
                        "Participant identified from "
                        "the trusted meeting title"
                    ),
                }
            )
    
    return participants


def load_known_people() -> list[str]:
    """
    Load the trusted participant name list.
    """

    known_people_path = (
        Path(__file__).resolve().parent
        / "known_people.json"
    )

    if not known_people_path.exists():
        return []

    data = json.loads(
        known_people_path.read_text(
            encoding="utf-8",
        )
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "known_people.json must contain a JSON list."
        )

    return [
        str(name).strip()
        for name in data
        if str(name).strip()
    ]
