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
)
from config import (
    LLM_CONTEXT_SIZE,
    LLM_MODEL,
    PERFORMANCE_PROFILE,
    OLLAMA_URL,
    SELF_NAME,
    SELF_REFERENCE_NAMES,
    SELF_SPEAKER_LABEL,
    TOPIC_NORMALIZATION_RULES,
)

_last_llm_elapsed_seconds: float | None = None


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


def ask_llm(
    prompt: str,
    response_format=None,
    *,
    timeout_seconds: float | None = None,
) -> str:
    """
    Send a prompt to the configured local language model
    and return its response.
    """

    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "think": False,
    }

    if LLM_CONTEXT_SIZE > 0:
        payload["options"] = {
            "num_ctx": LLM_CONTEXT_SIZE,
        }

    if response_format is not None:
        payload["format"] = response_format

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()

    effective_timeout = (
        float(timeout_seconds)
        if timeout_seconds is not None
        else 120.0
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=effective_timeout,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Could not connect to Ollama at {OLLAMA_URL}: {error}"
        ) from error

    global _last_llm_elapsed_seconds
    _last_llm_elapsed_seconds = (
        time.perf_counter() - start
    )

    response_text = result.get("response", "").strip()

    if not response_text:
        raise RuntimeError("Ollama returned an empty response.")

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
    r"|\b[A-Z][A-Za-z0-9&.-]*\s+is\s+out\b",
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
    """Reject raw ASR spill that was promoted directly into a decision."""

    decision_words = re.findall(r"[A-Za-z0-9&'-]+", decision)
    evidence_words = re.findall(r"[A-Za-z0-9&'-]+", evidence)
    if len(decision_words) > 45:
        return False
    if (
        decision.casefold() == evidence.casefold()
        and len(evidence_words) > 36
    ):
        return False
    if re.search(
        r"\b(?:and|but|if|or|so|then|to|with|see\s+if)\s*$",
        decision.strip(),
        flags=re.IGNORECASE,
    ):
        return False
    return True


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


def _risk_is_supported(risk: str, evidence: str) -> bool:
    """Require an explicit, non-negated risk/concern statement and lexical support."""

    if not risk or not evidence:
        return False
    if not _RISK_EVIDENCE_PATTERN.search(evidence):
        return False
    if _RISK_NEGATION_PATTERN.search(evidence):
        return False

    risk_tokens = _meaningful_tokens(risk)
    evidence_tokens = _meaningful_tokens(evidence)
    if not risk_tokens:
        return False
    required_overlap = min(2, len(risk_tokens))
    return len(risk_tokens & evidence_tokens) >= required_overlap


def _is_well_formed_question(question: str) -> bool:
    """Reject ASR fragments and rhetorical confirmation questions."""

    words = re.findall(r"[A-Za-z0-9&'-]+", question)
    if len(words) < 4:
        return False
    if re.search(
        r"^\s*(?:who|what|when|where|why|how)\s+"
        r"(?:did|does|do|is|are|was|were|can|could|will|would|should)\s*,",
        question,
        flags=re.IGNORECASE,
    ):
        return False
    # Tag/confirmation questions are conversational checks, not unresolved
    # meeting questions.  They should not become durable meeting memory.
    if re.search(r"(?:,\s*)?(?:right|correct|okay|ok)\?\s*$", question, flags=re.IGNORECASE):
        return False
    return True


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
    for match in removal.finditer(transcript):
        context_start = max(0, match.start() - 240)
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


def _reconcile_meeting_memory(memory: dict, transcript: str) -> dict:
    """Apply deterministic evidence and cross-section consistency rules."""

    decisions = []
    for item in memory.get("decisions", []):
        if not isinstance(item, dict):
            continue
        evidence = str(item.get("evidence", "")).strip()
        decision = str(item.get("decision", "")).strip()
        if not decision or not evidence or evidence not in transcript:
            continue
        if not _decision_is_supported(decision, evidence):
            continue
        if not _decision_candidate_is_well_formed(decision, evidence):
            continue
        decisions.append({"decision": decision, "evidence": evidence})

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

    normalized_decisions = []
    for item in decisions:
        decision = str(item.get("decision", "")).strip()
        evidence = str(item.get("evidence", "")).strip()
        if decision.casefold().rstrip(".") == evidence.casefold().rstrip("."):
            decision = _canonical_fallback_decision_text(evidence)
        normalized_decisions.append({"decision": decision, "evidence": evidence})

    memory["decisions"] = _deduplicate_decisions_in_context(
        normalized_decisions,
        transcript,
    )

    memory["open_questions"] = [
        question
        for question in memory.get("open_questions", [])
        if _is_well_formed_question(str(question))
    ]

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

    return memory


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
- The evidence field MUST contain exact words copied from the
  transcript.
- Keep the evidence quote as short as possible while still
  proving the commitment.
- Do not treat a suggestion, request, discussion, intention,
  status update, or completed action as a commitment.
- Do not infer an owner.
- If the speaker's name is not explicit enough to identify
  confidently, use "Unknown".
- The action field may be a concise paraphrase of the committed
  action, but must not add information not supported by the
  evidence.

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
- Do not treat opinions, proposals, questions, concerns, or
  unresolved discussion as decisions.
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
  and that remained unanswered in this section.
- Do not turn missing detail, uncertainty, or an analyst's desire
  for more information into a question.
- The evidence field MUST contain the exact question copied from
  the transcript.

FOLLOW-UPS:
- Include only an explicitly requested or assigned task, or a
  clearly declared next step that remains to be done.
- Do not create sensible next steps from discussion, topic status,
  risk, or missing information.
- Do not duplicate a first-person commitment in follow_ups; put
  that in commitments only.
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

            if (
                raw_owner.lower()
                == SELF_SPEAKER_LABEL.lower()
            ):
                resolved_owner = SELF_NAME

            elif (
                raw_owner.lower()
                == "remote"
                and remote_participant
            ):
                resolved_owner = (
                    remote_participant
                )

            else:
                resolved_owner = (
                    raw_owner
                    or "Unknown"
                )

            action_text = str(
                item.get(
                    "action",
                    "",
                )
            ).strip()

            # A generated paraphrase is convenient only when it is literally
            # supported by the quote. Otherwise retain the quote itself as the
            # action so unsupported detail cannot become authoritative.
            if action_text.casefold() not in evidence_text.casefold():
                action_text = evidence_text

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

            grounded_question = evidence_text
            if grounded_question not in validated_open_questions:
                validated_open_questions.append(grounded_question)

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

            grounded_follow_up = evidence_text
            if grounded_follow_up not in validated_follow_ups:
                validated_follow_ups.append(grounded_follow_up)

    return {
        "commitments": validated_commitments,
        "decisions": _deduplicate_decisions(validated_decisions),
        "risks": validated_risks,
        "open_questions": validated_open_questions,
        "follow_ups": validated_follow_ups,
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

    memory = build_meeting_memory(
        meeting_label=meeting_label,
        meeting_summary=meeting_summary,
    )

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

    return _reconcile_meeting_memory(
        memory,
        transcript,
    )


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
        "ai_model": LLM_MODEL,
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
