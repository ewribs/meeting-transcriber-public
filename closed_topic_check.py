"""Re-check topics the summary step marked "closed".

The summary step sometimes treats "I'll come back with a confirmation" as a finished
matter. This check asks one narrow question per transcript section: for each closed
topic, does someone still have to do, verify, decide or confirm something about it?
A topic is reopened only when the model gives an exact transcript quote (verified in
Python). The pass can never fail a meeting: any error is reported and the memory is
returned unchanged. Set MT_CLOSED_TOPIC_CHECK=0 to disable.
"""
from __future__ import annotations

import json
import os
import re

from chunking import chunk_transcript

_SCHEMA = {
    "type": "object",
    "properties": {
        "unfinished": {
            "type": "array",
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "topic_number": {"type": "integer"},
                    "remaining_work": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["topic_number", "remaining_work", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["unfinished"],
    "additionalProperties": False,
}

# Wording that claims a matter is settled; removed from a topic summary once it is reopened.
_SETTLED_CLAIM = re.compile(
    r"\b(?:resolved|completed|finished|closed|fully\s+addressed|confirmed|"
    r"no\s+(?:other|further|remaining|additional)\s+(?:issues?|concerns?|problems?)|"
    r"no\s+major\s+disruptions)\b",
    flags=re.IGNORECASE,
)


def _prompt(meeting_label: str, chunk: str, topics: list[dict]) -> str:
    listing = "\n".join(
        f"{i}. {t.get('topic', '')}: {t.get('summary', '')}" for i, t in enumerate(topics, 1)
    )
    return f"""
You are checking whether topics from a business meeting were actually finished.

Meeting: {meeting_label}

These topics were summarized as complete:
{listing}

Read the transcript section below. For each topic, report it ONLY if, in this section,
a speaker says that something about it still has to be done, checked, verified, decided
or confirmed (for example "I'll come back with a confirmation", "I need to figure out if
there are others", "we still need to decide"). Do not report a topic just because it was
discussed, and do not report work that the speakers say is already done.

For each report give:
- topic_number: the number from the list above.
- remaining_work: one short sentence saying what is still pending.
- evidence: an exact quote copied from the transcript section. Do not paraphrase.

If every topic looks finished in this section, return an empty list.

Transcript section:

{chunk}
""".strip()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def find_unfinished_topics(transcript, meeting_label, topics, ask_llm,
                           split=None, chunk_words=1500):
    """Return {index_in_topics: {"remaining_work", "evidence"}} for reopened topics."""
    queue = list(chunk_transcript(transcript, max_words=chunk_words))
    found: dict[int, dict] = {}
    while queue:
        chunk = queue.pop(0)
        try:
            raw = ask_llm(_prompt(meeting_label, chunk, topics), response_format=_SCHEMA)
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
        for row in data.get("unfinished", []) if isinstance(data, dict) else []:
            if not isinstance(row, dict):
                continue
            number = row.get("topic_number")
            if not isinstance(number, int) or not 1 <= number <= len(topics):
                continue
            work = re.sub(r"\s+", " ", str(row.get("remaining_work", ""))).strip().rstrip(".")
            evidence = re.sub(r"\s+", " ", str(row.get("evidence", ""))).strip()
            if not 3 <= len(re.findall(r"[A-Za-z0-9&'-]+", work)) <= 30:
                continue
            if not evidence or _norm(evidence) not in chunk_norm:
                continue
            if re.search(r"\b(?:already|just)\s+(?:sent|shared|completed|finished|done)\b", evidence, re.I):
                continue
            found.setdefault(number - 1, {"remaining_work": work, "evidence": evidence})
    return found


def reopen_topics(memory, closed_indexes, found):
    """Return a copy of memory with the found topics reopened and their summaries corrected."""
    topics = [dict(t) if isinstance(t, dict) else t for t in memory.get("topics", [])]
    for position, info in found.items():
        topic = topics[closed_indexes[position]]
        topic["status"] = "open"
        kept = [
            s for s in re.split(r"(?<=[.!?])\s+", str(topic.get("summary", "")).strip())
            if s and not _SETTLED_CLAIM.search(s)
        ]
        kept.append(f"Still open: {info['remaining_work']}.")
        topic["summary"] = " ".join(kept)
    result = dict(memory)
    result["topics"] = topics
    return result


def run_closed_topic_check(meeting_label, transcript, memory, ask_llm, split, trace=None):
    """Run the check; never raise."""
    if os.environ.get("MT_CLOSED_TOPIC_CHECK", "").strip() == "0":
        return memory
    try:
        topics = memory.get("topics") if isinstance(memory, dict) else None
        closed_indexes = [
            i for i, t in enumerate(topics or [])
            if isinstance(t, dict) and str(t.get("status", "")).strip().casefold() == "closed"
        ]
        if not closed_indexes:
            return memory
        print("Re-checking topics marked closed...", flush=True)
        closed = [topics[i] for i in closed_indexes]
        found = find_unfinished_topics(transcript, meeting_label, closed, ask_llm, split=split)
        if trace is not None:
            trace("closed_topic_check", [
                {"topic": closed[p].get("topic"), **info} for p, info in found.items()])
        if not found:
            return memory
        return reopen_topics(memory, closed_indexes, found)
    except Exception as exc:  # the safety net must never fail a meeting
        print(f"  Closed-topic check skipped: {exc}", flush=True)
        return memory
