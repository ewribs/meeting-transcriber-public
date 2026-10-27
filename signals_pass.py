"""Decisions, risks and open questions for a meeting with speaker names.

Like the action-items pass: a specific prompt (what, who, which deal, amounts),
the quote checked against the real transcript, plain-code filters, and a second
look that sees the text around each quote (so a question answered later in the
meeting is dropped). Used only when speaker names are switched on.
"""

from __future__ import annotations

import json
import re

from action_items_pass import locate, norm

KINDS = ("decisions", "risks", "open_questions")
KEY = {"decisions": "decision", "risks": "risk", "open_questions": "question"}
PER_KIND_LIMIT = 8
FIRM_DECISION_LIMIT = 5
UNCONFIRMED_LIMIT = 4
SECOND_READ_WORDS = 1000

SCHEMA = {
    "type": "object",
    "properties": {
        kind: {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {KEY[kind]: {"type": "string"}, "evidence": {"type": "string"}},
                "required": [KEY[kind], "evidence"],
                "additionalProperties": False,
            },
        }
        for kind in KINDS
    },
    "required": list(KINDS),
    "additionalProperties": False,
}


def build_prompt(meeting_label: str, chunk: str, self_name: str) -> str:
    return f"""
You are writing the decisions, risks and open questions that a busy executive will read after
this meeting.

Meeting: {meeting_label}

Each turn is headed by the speaker's name. {self_name} is the user. "Unidentified" means the
voice could not be matched to a person.

DECISIONS: a choice made or agreed in this meeting. Someone says what will be done or chosen
and the other person agrees or does not object. This includes how something will be handled
or approved ("anything under $5 million goes to Beth, not Todd"). Not decisions: ideas, options
being weighed, plans nobody agreed to, status updates, guesses ("probably", "I think it
will"), and anything that is a task for a person to do (create, send, schedule, reach out,
follow up - those are action items, never decisions). If the speaker was not sure, say
"likely" in the item.

RISKS: a concern or possible problem that a speaker raises or describes, which could hurt a
deal, cost, schedule or outcome (a price that could go up, an approval that could delay a deal,
a commitment that conflicts with plans to look at alternatives, a budget that has to line up).
Only include a risk when a speaker actually voiced the worry or the consequence (words like
worried, nervous, concern, could, might, if X then Y, delay, wild card), and say what could go
wrong and why, naming the specific deal, vendor, amount, date or project it affects. Not risks: routine status ("waiting on quotes", "has not sent it yet") with no
stated concern, small talk, general uncertainty, or a problem you inferred yourself.

OPEN QUESTIONS: something the speakers still need to find out or decide after this meeting, or
a question asked and left unanswered. Write it as a complete question and include what depends
on the answer when that was said. Only include a question when the transcript shows what depends on the answer (a deal, a price
or number, an approval, a date, a decision). Not open questions: anything answered later in
this section, whether someone has had time to look at something, small talk, or questions
about the call itself.

Write every item as one complete sentence that makes sense on its own, with the concrete detail
that was spoken (deal, vendor, amount, person, date). Use names, never "I", "you", "we" or "it".
For each item give an exact quote copied from the transcript (the shortest span that shows it).
If a category has nothing in this section, return an empty list for it.

Transcript section:

{chunk}
""".strip()


_IDEA_START = re.compile(
    r"^(?:consider|evaluate|explore|discuss|think\s+about|look\s+into)\b", re.I)
_QUESTION_START = re.compile(
    r"^(?:whether|if|how|what|when|where|who|whom|which|why|is|are|do|does|did|can|could|"
    r"will|would|should|has|have)\b", re.I)


_TASK_START = re.compile(
    r"^[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?\s+(?:will|is going to|plans to)\s+"
    r"(?:create|send|schedule|reach out|follow up|put|ask|set up|draft|share|email|call|check|"
    r"write|prepare|review|update|talk to|contact|work with|organi[sz]e|handle|meet|"
    r"bring|coordinate|transition|reach)\b")
_STATEMENT_LIKE = re.compile(
    r"\bconfirmed that\b|\bwill need to\b|\bshould\b|\bmust\b|\bhas not yet\b|"
    r"\bhave not yet\b|\bunclear\b|\bfair level\b", re.I)
_SECONDHAND = re.compile(
    r"^[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?\s+(?:asked|requested|told|sent|said|emailed|wrote|"
    r"mentioned|reported)\b")
_NO_STAKE = re.compile(
    r"\b(?:have|had)\s+a\s+chance\s+to\b|\bhad\s+time\s+to\b|\bgotten\s+to\b", re.I)
_RISK_CUE = re.compile(
    r"\b(?:worr\w*|nervous|concern\w*|afraid|risk\w*|could|might|may\s+not|if|delay\w*|"
    r"problem|issue|wild\s+card|bomb|trouble|conflict|danger|uncertain\w*|estimate)\b", re.I)


_UNKNOWN_CUE = re.compile(
    r"\?|\bnot sure\b|\bdon'?t know\b|\bneed to (?:find out|figure out|decide)\b|"
    r"\bwaiting (?:on|for)\b|\bwhether\b|\bTBD\b|\bstill (?:working|figuring|deciding)\b|"
    r"\bwe'?ll (?:find out|see)\b|\bunknown\b|\bhow (?:much|many|long)\b|"
    r"\bwhat (?:we|i|they) need\b|\bfinalizing\b|\bhave to (?:find|check|confirm)\b|"
    r"\bhopefully\b|\bpending\b|\bto be determined\b|\bonce (?:we|they) (?:hear|know)\b", re.I)


def _plain_filter(kind: str, text: str) -> str | None:
    words = re.findall(r"[A-Za-z0-9&'-]+", text)
    if kind == "decisions":
        if "?" in text or _IDEA_START.match(text.strip()):
            return "an idea or a question, not a decision"
        if _TASK_START.match(text.strip()):
            return "a task for a person, not a decision"
        if not 4 <= len(words) <= 45:
            return "wrong length"
    elif kind == "risks":
        if not 5 <= len(words) <= 45:
            return "wrong length"
    else:
        if not _QUESTION_START.match(text.strip()):
            return "not worded as a question"
        if _NO_STAKE.search(text):
            return "nothing depends on the answer"
        if not 4 <= len(words) <= 45:
            return "wrong length"
    return None


def extract(transcript: str, meeting_label: str, ask_llm, self_name: str,
            chunk_words: int = 1500, dropped: list | None = None) -> dict[str, list[dict]]:
    from chunking import chunk_transcript
    found: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    for number, chunk in enumerate(chunk_transcript(transcript, max_words=chunk_words), 1):
        try:
            data = json.loads(ask_llm(build_prompt(meeting_label, chunk, self_name),
                                      response_format=SCHEMA))
        except (RuntimeError, ValueError, TypeError) as error:
            if dropped is not None:
                dropped.append((number, "all", f"model call failed: {error}", ""))
            continue
        chunk_norm = norm(chunk)
        for kind in KINDS:
            rows = data.get(kind, []) if isinstance(data, dict) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                text = re.sub(r"\s+", " ", str(row.get(KEY[kind], ""))).strip()
                evidence = re.sub(r"\s+", " ", str(row.get("evidence", ""))).strip()
                if not text or not evidence:
                    continue
                if norm(evidence) not in chunk_norm:
                    real = locate(evidence, chunk, minimum=0.7)
                    if real is None:
                        if dropped is not None:
                            dropped.append((number, kind, "quote not found in the transcript", text))
                        continue
                    evidence = real
                reason = _plain_filter(kind, text)
                if reason:
                    if dropped is not None:
                        dropped.append((number, kind, reason, text))
                    continue
                if kind == "open_questions" and not _UNKNOWN_CUE.search(evidence):
                    if dropped is not None:
                        dropped.append((number, kind, "no real question or stated unknown in the quote", text))
                    continue
                item = {"text": text, "evidence": evidence}
                if kind == "risks":
                    item["firm"] = bool(_RISK_CUE.search(evidence))
                found[kind].append(item)
    for kind in KINDS:
        found[kind] = _one_per_quote(_unique(found[kind]))
    return found


def _one_per_quote(items: list[dict]) -> list[dict]:
    seen, kept = set(), []
    for item in items:
        key = norm(item["evidence"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _unique(items: list[dict]) -> list[dict]:
    from memory_reconciliation import _tokens, near_duplicate
    kept, shown = [], []
    for item in items:
        words = _tokens(item["text"])
        if words and near_duplicate(words, shown, jaccard=0.5):
            continue
        shown.append(words)
        kept.append(item)
    return kept


# ---- the second look ------------------------------------------------------

LABELS = {
    "decisions": ("decision", ["decision", "idea_or_option", "status_or_fact", "action_item", "guess", "unsupported"]),
    "risks": ("risk", ["risk", "routine_status", "idea_or_option", "already_resolved", "unsupported", "vague"]),
    "open_questions": ("open", ["open", "answered_later", "small_talk", "unclear", "low_stake", "unsupported"]),
}

_JUDGE_RULES = {
    "decisions": (
        "decision: a choice made or agreed in the meeting, including how something will be "
        "handled or approved.\n"
        "idea_or_option: something suggested or being weighed that nobody settled.\n"
        "status_or_fact: a description of where things stand or how something works.\n"
        "action_item: a task for a person to do.\n"
        "guess: a prediction or a maybe (\"probably\", \"I think\") that nobody settled.\n"
        "unsupported: the quote and surrounding transcript do NOT say what the item claims "
        "(wrong person, wrong topic, or it goes beyond what was said)."),
    "risks": (
        "risk: someone raises or describes a concern or possible problem that could hurt a deal, "
        "cost, schedule or outcome.\n"
        "routine_status: ordinary status or waiting, with no stated concern.\n"
        "idea_or_option: a suggestion or hypothetical.\n"
        "already_resolved: the problem was solved in the meeting.\n"
        "vague: does not name any specific deal, vendor, amount, date or project, so a reader "
        "could not tell what is at risk.\n"
        "unsupported: the quote and surrounding transcript do NOT say what the item claims "
        "(wrong person, wrong topic, or it goes beyond what was said)."),
    "open_questions": (
        "open: still unresolved after the quoted passage and the text that follows it.\n"
        "answered_later: the text that follows answers it.\n"
        "small_talk: social chatter or a question about the call itself.\n"
        "unclear: the question is too vague to be useful.\n"
        "low_stake: nothing important depends on the answer (no deal, number, approval or "
        "decision is tied to it).\n"
        "unsupported: the quote and surrounding transcript do NOT say what the item claims "
        "(wrong person, wrong topic, or it goes beyond what was said)."),
}

_AFTER = 900
_BEFORE = 300


def context_around(transcript: str, evidence: str) -> str:
    words = evidence.split()
    if words:
        pattern = r"\s+".join(re.escape(w) for w in words)
        match = re.search(pattern, transcript, flags=re.IGNORECASE)
        if match:
            start = max(0, match.start() - _BEFORE)
            end = min(len(transcript), match.end() + _AFTER)
            return re.sub(r"\s+", " ", transcript[start:end]).strip()
    return evidence


def _judge_schema(labels: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {"verdicts": {"type": "array", "items": {
            "type": "object",
            "properties": {"number": {"type": "integer"},
                           "label": {"type": "string", "enum": labels}},
            "required": ["number", "label"], "additionalProperties": False}}},
        "required": ["verdicts"], "additionalProperties": False,
    }


def judge(kind: str, items: list[dict], transcript: str, ask_llm, batch: int = 8) -> list[dict]:
    """Keep the items the second look labels with the wanted label. A problem keeps the item."""
    wanted, labels = LABELS[kind]
    keep = list(items)
    for offset in range(0, len(items), batch):
        group = items[offset:offset + batch]
        listing = "\n\n".join(
            f"{offset + i + 1}. {item['text']}\n   Quote: {item['evidence']}\n"
            f"   Surrounding transcript: {context_around(transcript, item['evidence'])}"
            for i, item in enumerate(group))
        prompt = (
            f"You are reviewing proposed {kind.replace('_', ' ')} from a business meeting. "
            "For each one, choose the label that fits, using the quote and the surrounding "
            f"transcript (which includes what was said after).\n\nLabels:\n{_JUDGE_RULES[kind]}\n\n"
            f"Proposed items:\n\n{listing}\n\nReturn one verdict for every number.")
        try:
            data = json.loads(ask_llm(prompt, response_format=_judge_schema(labels)))
        except (RuntimeError, ValueError, TypeError):
            continue
        for row in data.get("verdicts", []) if isinstance(data, dict) else []:
            number = row.get("number") if isinstance(row, dict) else None
            if (isinstance(number, int) and 1 <= number <= len(items)
                    and row.get("label") in labels and row["label"] not in (wanted, "unsupported")):
                keep[number - 1] = None
    return [item for item in keep if item is not None]


_SUPPORT_SCHEMA = {
    "type": "object",
    "properties": {"says_it": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["says_it", "reason"], "additionalProperties": False,
}
_CLAIM_WORDS = {"decisions": "a decision that was made", "risks": "a risk or worry that was voiced",
                "open_questions": "an open question"}


def supported(kind: str, item: dict, transcript: str, ask_llm) -> bool:
    """One item at a time: does the passage really say it? A problem keeps the item."""
    passage = context_around(transcript, item["evidence"])
    if kind == "open_questions":
        ask = (
            "Does the passage show that someone asked this question, or said this is still "
            "unknown or undecided, about the same topic? Answer false if the passage is about "
            "something else, or if the question was answered right there. Answer true if a "
            "careful listener would agree it is a real open question. Keep the reason to one "
            "short sentence.")
    else:
        ask = (
            "Does the passage itself clearly say this, about the same people, vendor and topic? "
            "Answer false if it is about a different vendor, deal or person, if it goes further "
            "than what was said, or if it only hints at it. Answer true only if a careful "
            "listener would agree it was said. Keep the reason to one short sentence.")
    prompt = (
        f"Read this passage from a business meeting.\n\nPassage: {passage}\n\n"
        f"Someone wrote this as {_CLAIM_WORDS[kind]}:\n\"{item['text']}\"\n\n" + ask)
    try:
        data = json.loads(ask_llm(prompt, response_format=_SUPPORT_SCHEMA))
    except (RuntimeError, ValueError, TypeError):
        return True
    return not (isinstance(data, dict) and data.get("says_it") is False)


def run(transcript: str, meeting_label: str, ask_llm, self_name: str,
        dropped: list | None = None) -> tuple[dict, dict]:
    """(kept, removed) lists per kind."""
    first = extract(transcript, meeting_label, ask_llm, self_name, dropped=dropped)
    # A second read with different chunk boundaries: the model finds a different
    # subset each time, so the union recovers items one read misses. Every item
    # still has to pass the same quote check and second look.
    second = extract(transcript, meeting_label, ask_llm, self_name,
                     chunk_words=SECOND_READ_WORDS, dropped=dropped)
    found = {kind: _one_per_quote(_unique(first[kind] + second[kind])) for kind in KINDS}
    kept, removed = {}, {}
    for kind in KINDS:
        looked = judge(kind, found[kind], transcript, ask_llm)
        for item in looked:
            if not supported(kind, item, transcript, ask_llm):
                item["firm"] = False
        if kind == "decisions":
            for item in looked:
                if _STATEMENT_LIKE.search(item["text"]):
                    item["firm"] = False
        firm = [item for item in looked if item.get("firm", True)]
        loose = [item for item in looked if not item.get("firm", True)]
        limit = FIRM_DECISION_LIMIT if kind == "decisions" else PER_KIND_LIMIT
        kept[kind] = firm[:limit] + loose[:UNCONFIRMED_LIMIT]
        removed[kind] = [item for item in found[kind] if item not in kept[kind]]
    return kept, removed


def _action_matcher(commitments, tokens):
    """A function: does this text mostly repeat one of the action items?"""
    sets = [set(tokens(str(c.get("action", "")))) for c in commitments if isinstance(c, dict)]
    sets = [s for s in sets if s]

    def matches(text: str) -> bool:
        words = set(tokens(text))
        if not words:
            return False
        for other in sets:
            if len(words & other) / min(len(words), len(other)) >= 0.5:
                return True
        return False
    return matches


def run_signals_pass(meeting_label, transcript, memory, ask_llm, self_name, trace=None):
    """Return (memory, ok). Never raises; ok is False when the pass did not run.

    Firm items become the meeting's decisions, risks and open questions (older
    decisions and risks that are not repeats are kept). Unconfirmed items go to
    `other_decisions`, `other_risks` and `other_questions`. The older open
    questions are replaced.
    """
    import os
    if os.environ.get("MT_SIGNALS_PASS", "").strip() == "0":
        return memory, False
    try:
        from memory_reconciliation import _tokens, near_duplicate
        print("Looking for decisions, risks and open questions (names pass)...", flush=True)
        kept, _removed = run(transcript, meeting_label, ask_llm, self_name)
        if trace is not None:
            trace("signals_pass", kept)
        result = dict(memory)
        duplicates_an_action = _action_matcher(memory.get("commitments") or [], _tokens)
        kept = dict(kept)
        kept["decisions"] = [i for i in kept["decisions"]
                             if not duplicates_an_action(i["text"])]

        def similar(words, shown, threshold):
            mine = set(words)
            return any(len(mine & set(prev)) / min(len(mine), len(set(prev))) >= threshold
                       for prev in shown if prev and mine)

        def old_item_tier(kind, text):
            """Older strict items: keep, demote to unconfirmed, or drop."""
            if kind != "decisions":
                return "keep"
            if _plain_filter("decisions", text) or duplicates_an_action(text):
                return "drop"           # a task or an idea: the action items already cover it
            if _STATEMENT_LIKE.search(text) or _SECONDHAND.match(text.strip()):
                return "demote"
            return "keep"

        def build(kind, old_items, old_text, make):
            firm = [i for i in kept[kind] if i.get("firm", True)]
            loose = [i for i in kept[kind] if not i.get("firm", True)]
            shown, items, others = [], [], []
            for item in firm:
                words = _tokens(item["text"])
                if not words or near_duplicate(words, shown, jaccard=0.5) \
                        or similar(words, shown, 0.65):
                    continue
                shown.append(words)
                items.append(make(item))
            demoted = []
            for old in old_items:
                text = old_text(old)
                words = _tokens(text)
                if not words or near_duplicate(words, shown, jaccard=0.5) \
                        or similar(words, shown, 0.65):
                    continue
                tier = old_item_tier(kind, text)
                if tier == "drop":
                    continue
                if tier == "demote":
                    demoted.append(text)
                else:
                    shown.append(words)
                    items.append(old)
            for text in demoted + [i["text"] for i in loose]:
                words = _tokens(text)
                if len(words) < 2 or near_duplicate(words, shown, jaccard=0.5) \
                        or similar(words, shown, 0.6):
                    continue
                shown.append(words)
                others.append(text)
            return items, others

        result["decisions"], result["other_decisions"] = build(
            "decisions", memory.get("decisions") or [],
            lambda o: str(o.get("decision", "")) if isinstance(o, dict) else str(o),
            lambda i: {"decision": i["text"], "evidence": i["evidence"]})
        result["risks"], result["other_risks"] = build(
            "risks", memory.get("risks") or [],
            lambda o: str(o.get("risk", "")) if isinstance(o, dict) else str(o),
            lambda i: {"risk": i["text"], "evidence": i["evidence"]})
        questions, result["other_questions"] = build(
            "open_questions", [], str, lambda i: i["text"])
        result["open_questions"] = questions
        return result, True
    except Exception as error:  # the older results stand
        print(f"decisions/risks pass skipped: {error}", flush=True)
        return memory, False


def tidy_memory(memory: dict) -> dict:
    """Apply the plain-code cleanup to an already built memory (no model calls).

    Older strict decisions that are really tasks are dropped, ones that report
    what someone else did or are statements move to the unconfirmed list, and
    near-repeats among decisions and risks are removed.
    """
    from memory_reconciliation import _tokens, near_duplicate
    result = dict(memory)
    duplicates_an_action = _action_matcher(memory.get("commitments") or [], _tokens)

    def similar(words, shown, threshold):
        mine = set(words)
        return any(len(mine & set(prev)) / min(len(mine), len(set(prev))) >= threshold
                   for prev in shown if prev and mine)

    def text_of(kind, item):
        key = {"decisions": "decision", "risks": "risk"}[kind]
        return str(item.get(key, "")) if isinstance(item, dict) else str(item)

    for kind in ("decisions", "risks"):
        other_key = "other_" + kind
        shown, firm, demoted = [], [], []
        for item in memory.get(kind) or []:
            text = text_of(kind, item)
            words = _tokens(text)
            if not words or near_duplicate(words, shown, jaccard=0.5) \
                    or similar(words, shown, 0.65):
                continue
            if kind == "decisions":
                if _plain_filter("decisions", text) or duplicates_an_action(text):
                    continue
                if _STATEMENT_LIKE.search(text) or _SECONDHAND.match(text.strip()):
                    demoted.append(text)
                    continue
            shown.append(words)
            firm.append(item)
        others = []
        for text in demoted + [str(t) for t in memory.get(other_key) or []]:
            words = _tokens(text)
            if len(words) < 2 or near_duplicate(words, shown, jaccard=0.5) \
                    or similar(words, shown, 0.6):
                continue
            shown.append(words)
            others.append(text)
        result[kind] = firm
        if others or other_key in memory:
            result[other_key] = others
    return result
