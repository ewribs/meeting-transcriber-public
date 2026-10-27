"""Dedicated next-steps pass.

The main extraction juggles commitments, decisions, risks and questions in one
prompt and under-extracts next steps on unseen meetings. This pass asks one
narrow question per transcript section: who explicitly said they would do what?

Results are added to follow_ups as 'Possible commitment (unconfirmed)'. The
strict commitments list is never changed. Every item needs an exact transcript
quote, verified in Python. The pass can never fail a meeting: any error is
reported and the memory is returned unchanged. Set MT_NEXT_STEPS_PASS=0 to disable, or
MT_NEXT_STEPS_VERIFY=0 to skip the second-look filter.
"""
from __future__ import annotations

import json
import os
import re

import transcript_view

from chunking import chunk_transcript

_SCHEMA = {
    "type": "object",
    "properties": {
        "next_steps": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "task": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["owner", "task", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["next_steps"],
    "additionalProperties": False,
}


_LEGACY_LABELS = (
    'Speaker labels: "Mic" is the user ({self_name}). "Remote" is one or more other people\n'
    'on the call; their individual names are not given by the label.\n')
_LEGACY_OWNER = (
    "- owner: the person's name only if the transcript names who will do it. If the speaker is\n"
    '  "Mic", use {self_name}. Otherwise write "Unknown". Never guess a name.\n')
_NAMED_LABELS = (
    'Speaker labels: each turn is headed by the speaker\'s name. {self_name} is the user.\n'
    '"Unidentified" means the voice could not be matched to a person.\n')
_NAMED_OWNER = (
    "- owner: the person who will do it. When someone commits to something themselves (\"I'll...\"),\n"
    "  the owner is the name on that turn. When someone is asked to do it and agrees, the owner is\n"
    "  the person who agreed. If the turn is headed \"Unidentified\" and no name is spoken, write\n"
    '  "Unknown". Never guess a name.\n')


def _uses_names(chunk: str) -> bool:
    return any(transcript_view.is_person_speaker(speaker)
               for speaker in transcript_view.speakers_in(chunk))


def _prompt(meeting_label: str, chunk: str, self_name: str) -> str:
    named = _uses_names(chunk)
    labels_note = (_NAMED_LABELS if named else _LEGACY_LABELS).format(self_name=self_name)
    owner_rule = (_NAMED_OWNER if named else _LEGACY_OWNER).format(self_name=self_name)
    return f"""
You are listing the explicit next steps from one section of a business meeting transcript.

Meeting: {meeting_label}

{labels_note}
A next step is something a participant says they WILL do, agrees to do, accepts when
asked, or that the group clearly commits to do in the future. A request that the other
person accepts also counts (for example "send me an email tomorrow" followed by agreement).

Do NOT list:
- work already completed or described in the past tense
- how a process works or how a proposed process would work
- hypotheticals, wishes, or conditions the speakers did not commit to
  ("it would be good to...", "if we decide to...")
- advice or recommendations given to someone else
- ongoing duties or general intentions with no concrete action
- scheduling that is already arranged
- possibilities and open options ("consider...", "maybe we could...", "evaluate whether...")
- opinions about how a process should work
- a speaker only worrying about, or wanting, something, without saying they will do it

For each next step give:
{owner_rule}- task: one concise, self-contained sentence starting with a verb.
- evidence: an exact quote copied from the transcript (the shortest span that shows the
  commitment). Do not paraphrase the quote.

If this section contains no explicit next steps, return an empty list.

Transcript section:

{chunk}
""".strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def _clean_owner(owner: str, self_name: str) -> str:
    owner = str(owner or "").strip()
    folded = owner.casefold()
    if folded == "mic":
        return self_name
    if folded in ("", "remote", "unknown", "unidentified", "unclear", "none", "n/a"):
        return ""
    return owner


_TURN_HEADER = re.compile(r"\[\d+:\d+(?::\d+)?\]\s*\*\*([^*]+)\*\*")


def _speaker_of(chunk: str, evidence: str):
    """Return the speaker label of the turn that contains the quote, or None if unknown."""
    parts = _TURN_HEADER.split(chunk)
    # parts = [text_before, speaker1, text1, speaker2, text2, ...]
    needle = _norm(evidence)
    head = " ".join(needle.split()[:8])
    for i in range(1, len(parts) - 1, 2):
        body = _norm(parts[i + 1])
        if needle in body:
            return parts[i].strip()
    for i in range(1, len(parts) - 1, 2):
        if head and head in _norm(parts[i + 1]):
            return parts[i].strip()
    return None


def extract_next_steps(transcript, meeting_label, ask_llm, self_name,
                       chunk_words=1500, split=None):
    """Return validated next-step dicts: owner, task, evidence."""
    queue = list(chunk_transcript(transcript, max_words=chunk_words))
    found = []
    while queue:
        chunk = queue.pop(0)
        try:
            raw = ask_llm(_prompt(meeting_label, chunk, self_name), response_format=_SCHEMA)
        except RuntimeError as exc:
            if "truncated" not in str(exc):
                raise
            halves = split(chunk) if split else []
            if halves:
                queue[0:0] = halves
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        chunk_norm = _norm(chunk)
        for row in data.get("next_steps", []) if isinstance(data, dict) else []:
            if not isinstance(row, dict):
                continue
            task = re.sub(r"\s+", " ", str(row.get("task", ""))).strip()
            evidence = re.sub(r"\s+", " ", str(row.get("evidence", ""))).strip()
            words = re.findall(r"[A-Za-z0-9&'-]+", task)
            if not task or not evidence or not (3 <= len(words) <= 30):
                continue
            if re.match(r"(?:consider|evaluate|explore|think about|decide whether|determine whether|"
                        r"regroup|discuss whether|look into whether|assess whether)\b", task, re.I):
                continue
            if _norm(evidence) not in chunk_norm:
                continue
            if re.search(r"\b(?:already|just)\s+(?:sent|shared|completed|finished|done)\b", evidence, re.I):
                continue
            owner = _clean_owner(row.get("owner", ""), self_name)
            # An item can only be the user's if the quote came from the user's own turn.
            if owner == self_name:
                speaker = _speaker_of(chunk, evidence)
                if speaker is not None and not transcript_view.is_self_speaker(speaker):
                    owner = ""
            found.append({
                "owner": owner,
                "task": task,
                "evidence": evidence,
            })
    unique, seen = [], set()
    for item in found:
        key = _norm(item["task"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "integer"},
                    "label": {
                        "type": "string",
                        "enum": ["commitment", "plan_description", "suggestion", "already_done"],
                    },
                },
                "required": ["number", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}

_VERIFY_BATCH = 10
_CONTEXT_CHARS = 450


def _context_around(transcript: str, evidence: str) -> str:
    """The quote plus nearby transcript, so the judge sees who was speaking and why."""
    words = evidence.split()
    if words:
        pattern = r"\s+".join(re.escape(w) for w in words)
        match = re.search(pattern, transcript, flags=re.IGNORECASE)
        if match:
            start = max(0, match.start() - _CONTEXT_CHARS)
            end = min(len(transcript), match.end() + _CONTEXT_CHARS)
            return re.sub(r"\s+", " ", transcript[start:end]).strip()
    return evidence


def _verify_prompt(entries: list[tuple[int, dict, str]]) -> str:
    listing = "\n\n".join(
        f"{number}. Proposed next step: {item['task']}\n"
        f"   Quote: {item['evidence']}\n"
        f"   Surrounding transcript: {context}"
        for number, item, context in entries
    )
    return f"""
You are reviewing proposed next steps from a business meeting. For each one, decide which
label fits, using the quote and the surrounding transcript.

Labels:
- commitment: a specific person on the call (or the people on the call together) takes on a
  concrete task, offers to do it, accepts a request to do it, or agrees to do it next.
  Offers and conditions still count when a person is the one acting. Examples: "I'll send you
  the notes tomorrow"; "I can bring that up at this afternoon's committee"; "Can you review
  it?" answered with "Sure"; "I'll send the invite once I'm confident of the date".
- plan_description: the actor is an organization, team, program or process in general, and no
  person on the call takes the task on. Example: "we're going to have finance partners work
  alongside the new leaders".
- suggestion: an idea or possibility that nobody took on. Example: "we could look at removing
  the link".
- already_done: work that is finished, or an arrangement already made.

When a specific person on the call is the one who would do the task, choose commitment over
suggestion. Choose plan_description only when no person on the call is the actor.

Proposed next steps:

{listing}

Return one verdict for every number.
""".strip()


def verify_next_steps(items, transcript, ask_llm):
    """Keep only items the judge labels 'commitment'. Any problem keeps the item."""
    keep = list(items)
    for offset in range(0, len(items), _VERIFY_BATCH):
        batch = items[offset:offset + _VERIFY_BATCH]
        entries = [(offset + i + 1, item, _context_around(transcript, item["evidence"]))
                   for i, item in enumerate(batch)]
        try:
            raw = ask_llm(_verify_prompt(entries), response_format=_VERIFY_SCHEMA)
            data = json.loads(raw)
        except (RuntimeError, json.JSONDecodeError, TypeError):
            continue
        for row in data.get("verdicts", []) if isinstance(data, dict) else []:
            if not isinstance(row, dict):
                continue
            number = row.get("number")
            if (isinstance(number, int) and 1 <= number <= len(items)
                    and row.get("label") in ("plan_description", "suggestion", "already_done")):
                keep[number - 1] = None
    return [item for item in keep if item is not None]


def add_next_step_items(memory, items, limit=6):
    """Append unseen next steps to follow_ups as Possible commitments."""
    from memory_reconciliation import _sentence, _tokens, near_duplicate

    if not isinstance(memory, dict):
        return memory
    followups = memory.get("follow_ups")
    followups = list(followups) if isinstance(followups, list) else []
    shown = []
    for item in memory.get("commitments") or []:
        if isinstance(item, dict):
            shown.append(_tokens(str(item.get("action", ""))))
    for entry in followups:
        shown.append(_tokens(re.sub(r"^[^:]*\):\s*", "", str(entry))))

    def duplicate(words):
        return near_duplicate(words, shown, jaccard=0.5)

    added = []
    for item in items:
        if len(added) >= limit:
            break
        words = _tokens(item["task"])
        if len(words) < 2 or duplicate(words):
            continue
        owner = item.get("owner", "")
        qualifier = "unconfirmed" + (f", owner {owner}" if owner else "")
        line = f"Possible commitment ({qualifier}): {_sentence(item['task'])}"
        if line not in followups and line not in added:
            added.append(line)
            shown.append(words)
    if not added:
        return memory
    result = dict(memory)
    result["follow_ups"] = followups + added
    return result


def run_next_steps_pass(meeting_label, transcript, memory, ask_llm, split, self_name,
                        trace=None):
    """Run the pass; never raise."""
    if os.environ.get("MT_NEXT_STEPS_PASS", "").strip() == "0":
        return memory
    try:
        print("Looking for explicit next steps (dedicated pass)...", flush=True)
        items = extract_next_steps(transcript, meeting_label, ask_llm, self_name, split=split)
        if trace is not None:
            trace("next_steps_pass", items)
        if items and os.environ.get("MT_NEXT_STEPS_VERIFY", "").strip() != "0":
            verified = verify_next_steps(items, transcript, ask_llm)
            if trace is not None:
                dropped = [i for i in items if i not in verified]
                trace("next_steps_verification", {"kept": len(verified), "dropped": dropped})
            items = verified
        return add_next_step_items(memory, items)
    except Exception as exc:  # the safety net must never fail a meeting
        print(f"  Next-steps pass skipped: {exc}", flush=True)
        return memory
