"""Action items for a meeting with speaker names.

Asks the model for specific, stand-alone action items (what, for whom, which
deal, by when), then checks each one in plain code and with a second look:

  * the quote must really be in the transcript (a near-exact quote is matched
    to the real text),
  * waiting, things done during the meeting and things that already happened
    are not action items,
  * a "firm" item is one the owner said about themselves in the first person
    ("I'll ...", "I'm working on ..."); everything else that survives goes to
    a short second list of other next steps mentioned.

Used only when speaker names are switched on. Any problem leaves the meeting
memory unchanged. Set MT_ACTION_ITEMS_PASS=0 to turn it off.
"""

from __future__ import annotations

import json
import os
import re

OTHER_LIMIT = 6

SCHEMA = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "maxItems": 15,
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "task": {"type": "string"},
                    "due": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["owner", "task", "due", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["actions"],
    "additionalProperties": False,
}


def build_prompt(meeting_label: str, chunk: str, self_name: str) -> str:
    return f"""
You are writing the action-item list that a busy executive will read after this meeting.

Meeting: {meeting_label}

Each turn is headed by the speaker's name. {self_name} is the user. "Unidentified" means the
voice could not be matched to a person.

An action item is something a person on the call says they will do, agrees to do, or is asked
to do and accepts, that is still to be done after the meeting ends. Also include work a person
says they are pushing forward ("I'm working on X, it goes to Y next"), follow-ups ("I'll circle
back once..."), and next steps that depend on something else.

Write each item as one complete sentence that makes sense on its own, with the concrete detail
that was spoken: what is to be done, for or with whom, which deal, vendor or document, amounts,
who has to approve it, what it is waiting on. Never write "it", "that", "her note" or "the
issue" when the transcript says what it is.

- owner: the person who will do it (the name on the turn when they say "I will...", or the person
  who agreed when asked). If the owner cannot be known, write "Unknown". Never guess a name.
- task: the sentence described above, starting with a verb, written about the person by name.
  Never use "I", "me", "my", "you", "your" or "we": use the names instead.
  Example: the quote "I'll circle back with you and let you know what Jordan says" from Sam to
  Dana becomes "Circle back with Dana to report what Jordan says".
- due: the deadline or timing if it was said ("today", "early this week", "by Friday"), otherwise "".
- evidence: an exact quote copied from the transcript (the shortest span that shows it).

Do NOT list:
- work already completed or described in the past tense
- anything a person does during this conversation itself ("I'll put that in the chat now")
- hypotheticals, wishes, ideas nobody took on, or advice given to someone else
- how a process works in general
- vague stances ("stay on top of it", "keep an eye on it")
- an item where the owner would be doing it with themselves

If there are no action items in this section, return an empty list.

Transcript section:

{chunk}
""".strip()


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


_HEADER = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|\*\*[^*\n]{1,60}\*\*")


def locate(evidence: str, chunk: str, minimum: float = 0.85) -> str | None:
    """The transcript text a not-quite-exact quote refers to, or None.

    The model sometimes drops a filler word or fixes a stutter when it copies a
    quote. If most of its words line up with one stretch of the transcript, that
    stretch is the evidence (shown as it really was said).
    """
    import difflib
    plain = _HEADER.sub(" ", chunk)
    tokens = plain.split()
    key = [re.sub(r"[^a-z0-9]", "", t.casefold()) for t in tokens]
    wanted = [re.sub(r"[^a-z0-9]", "", w.casefold()) for w in str(evidence).split()]
    wanted = [w for w in wanted if w]
    if len(wanted) < 4:
        return None
    anchors = set(wanted[:3])
    best, best_span = 0.0, None
    length = len(wanted)
    for start in range(len(key)):
        if key[start] not in anchors:
            continue
        for size in (length, length + 2, length - 2):
            if size < 3:
                continue
            window = key[start:start + size]
            matcher = difflib.SequenceMatcher(None, wanted, window)
            covered = sum(block.size for block in matcher.get_matching_blocks()) / length
            score = min(matcher.ratio(), covered)
            if score > best:
                best, best_span = score, (start, start + size)
    if best_span and best >= minimum:
        return " ".join(tokens[best_span[0]:best_span[1]])
    return None


_FIRST_PERSON_COMMITMENT = re.compile(
    r"\b(?:i\s+will|i['\u2019]ll|i['\u2019]m\s+(?:going\s+to|gonna|working\s+on|"
    r"planning\s+to)|i\s+am\s+(?:going\s+to|working\s+on)|i\s+can|let\s+me|"
    r"i['\u2019]ve\s+got\s+to|i\s+need\s+to|i\s+have\s+to)\b",
    re.I,
)


def is_firm(owner: str, speaker: str | None, evidence: str) -> bool:
    """A firm action item: the person who said it is the one who will do it, in
    the first person ("I'll ...", "I'm working on ..."). Group plans said by a
    presenter ("we will ...") and things said about someone else are not firm."""
    if not speaker or not owner or owner.casefold() == "unknown":
        return False
    return (owner.strip().casefold() == speaker.strip().casefold()
            and bool(_FIRST_PERSON_COMMITMENT.search(evidence)))


_SAID_IT_ALREADY_HAPPENED = re.compile(
    r"\b(?:i|we)\s+(?:just\s+)?(?:pinged|sent|met|called|emailed|talked|spoke|"
    r"reached\s+out|followed\s+up|checked|asked|wrapped)\b", re.I)
_LOOKS_AHEAD = re.compile(
    r"\b(?:will|['\u2019]ll|going\s+to|gonna|need\s+to|have\s+to|plan\s+to|"
    r"let['\u2019]s|next\s+week|tomorrow|later)\b", re.I)
_LEADING_SPEECH = re.compile(
    r"^(?:i(?:['\u2019]ll|\s+will|['\u2019]m\s+going\s+to|\s+am\s+going\s+to)|let\s+me)\s+", re.I)


def tidy_task(task: str) -> str:
    """"I'll circle back ..." -> "Circle back ..." (a leftover from speech)."""
    stripped = _LEADING_SPEECH.sub("", task.strip())
    return stripped[:1].upper() + stripped[1:] if stripped != task.strip() else task.strip()


def not_an_action(task: str, evidence: str) -> str | None:
    """Why an item is not something to do later (None: it may be)."""
    if re.match(r"\s*(?:wait|waiting)\b", task, re.I):
        return "waiting is not an action"
    if re.search(r"\bright\s+now\b", f"{task} {evidence}", re.I):
        return "done during the meeting"
    if re.search(r"\b(?:last\s+(?:week|month|year|night)|yesterday)\b", task, re.I):
        return "already happened"
    if _SAID_IT_ALREADY_HAPPENED.search(evidence) and not _LOOKS_AHEAD.search(evidence):
        return "already happened"
    return None


def extract(transcript: str, meeting_label: str, ask_llm, self_name: str,
            chunk_words: int = 1000, dropped: list | None = None) -> list[dict]:
    """`dropped`, when given, collects (chunk number, reason, task) for each rejection."""
    from chunking import chunk_transcript
    found: list[dict] = []
    for number, chunk in enumerate(chunk_transcript(transcript, max_words=chunk_words), 1):
        try:
            data = json.loads(ask_llm(build_prompt(meeting_label, chunk, self_name),
                                      response_format=SCHEMA))
        except (RuntimeError, ValueError, TypeError) as error:
            if dropped is not None:
                dropped.append((number, f"model call failed: {error}", ""))
            continue
        chunk_norm = norm(chunk)
        rows = data.get("actions", []) if isinstance(data, dict) else []
        if dropped is not None:
            dropped.append((number, f"chunk gave {len(rows)} candidates", ""))
        for row in rows:
            if not isinstance(row, dict):
                continue
            task = re.sub(r"\s+", " ", str(row.get("task", ""))).strip()
            evidence = re.sub(r"\s+", " ", str(row.get("evidence", ""))).strip()
            if not task or not evidence:
                continue
            if norm(evidence) not in chunk_norm:
                found_text = locate(evidence, chunk)
                if found_text is None:
                    if dropped is not None:
                        dropped.append((number, "quote not found in the transcript", task))
                    continue
                evidence = found_text
            task = tidy_task(task)
            reason = not_an_action(task, evidence)
            if reason:
                if dropped is not None:
                    dropped.append((number, reason, task))
                continue
            owner = str(row.get("owner", "")).strip()
            if owner.casefold() in {"", "mic", "remote", "unclear", "none", "n/a"}:
                owner = "Unknown"
            import next_steps_pass
            speaker = next_steps_pass._speaker_of(chunk, evidence)
            found.append({"owner": owner, "task": task,
                          "due": str(row.get("due", "")).strip(), "evidence": evidence,
                          "speaker": speaker or "",
                          "firm": is_firm(owner, speaker, evidence)})
    unique, seen = [], set()
    for item in found:
        key = norm(item["task"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def judge(items: list[dict], transcript: str, ask_llm) -> list[dict]:
    """Second look: drop plans, suggestions and work already done (the existing judge)."""
    import next_steps_pass
    return next_steps_pass.verify_next_steps(items, transcript, ask_llm)


_NO_DUE = {"", "not specified", "not stated", "none", "n/a", "unknown", "unspecified"}


def clean_due(value) -> str:
    text = str(value or "").strip()
    return "" if text.casefold().strip(".") in _NO_DUE else text


def other_line(item: dict) -> str:
    owner = item.get("owner", "")
    who = owner if owner and owner.casefold() != "unknown" else "Owner not identified"
    due = clean_due(item.get("due"))
    return f"{who} - {item['task']}" + (f" ({due})" if due else "")


def run_action_items_pass(meeting_label, transcript, memory, ask_llm, split, self_name,
                          trace=None):
    """Return (memory, ok). ok is False when the pass did not run, so the caller
    can fall back to the older next-steps pass. Never raises.

    Firm items become the commitments (plus any older strict commitment that
    is not a repeat of them); the rest go to `other_next_steps`.
    """
    if os.environ.get("MT_ACTION_ITEMS_PASS", "").strip() == "0":
        return memory, False
    try:
        from memory_reconciliation import _tokens, near_duplicate
        print("Looking for action items (names pass)...", flush=True)
        items = extract(transcript, meeting_label, ask_llm, self_name)
        kept = judge(items, transcript, ask_llm)
        if trace is not None:
            trace("action_items_pass", [
                {k: v for k, v in item.items()} for item in kept])
        firm = [item for item in kept if item.get("firm")]
        rest = [item for item in kept if not item.get("firm")]

        commitments, shown = [], []
        for item in firm:
            words = _tokens(item["task"])
            if near_duplicate(words, shown, jaccard=0.5):
                continue
            shown.append(words)
            commitments.append({
                "owner": item["owner"], "action": item["task"],
                "due": clean_due(item.get("due")),
                "evidence": item["evidence"], "status": "open",
            })
        for old in memory.get("commitments") or []:
            if not isinstance(old, dict):
                continue
            words = _tokens(str(old.get("action", "")))
            if words and not near_duplicate(words, shown, jaccard=0.5):
                shown.append(words)
                commitments.append(old)

        others = []
        for item in rest:
            if len(others) >= OTHER_LIMIT:
                break
            words = _tokens(item["task"])
            if len(words) < 2 or near_duplicate(words, shown, jaccard=0.5):
                continue
            shown.append(words)
            others.append(other_line(item))

        result = dict(memory)
        result["commitments"] = commitments
        result["other_next_steps"] = others
        result["follow_ups"] = [
            line for line in memory.get("follow_ups") or []
            if not str(line).startswith("Possible commitment")
        ]
        return result, True
    except Exception as error:      # noqa: BLE001 - never fail a meeting
        print(f"Action items pass skipped: {error}", flush=True)
        return memory, False
