"""Clean a transcript turn by turn, so the cleaner can never change who spoke.

The old cleaning step hands the model the whole transcript, headers included,
and trusts it to give the headers back untouched. With names in the transcript
(many short turns, several speakers) the model sometimes folds a short reply
such as "Yeah." into the previous speaker's turn or drops a header, and then a
sentence is credited to the wrong person.

Here the model never sees a speaker. It gets numbered turns and returns the
same numbers with tidied text. The headers are put back by this program. Any
turn the model skips, garbles, or changes too much keeps its original words.
"""

from __future__ import annotations

import re

from transcript_turns import Turn

MAX_WORDS_PER_CALL = 1500
# A cleaned turn may be somewhat shorter (repetitions removed) or longer
# (punctuation) than the original, but not very different.
MIN_RATIO = 0.6
MAX_RATIO = 1.4

_ID_LINE = re.compile(r"^\[(t\d{4})\]\s?(.*)$")

PROMPT = """
You are an expert transcription editor.

Below are numbered pieces of a meeting transcript, each written as [tNNNN]
followed by what was said. Improve readability without changing meaning.

Rules:
- Return every piece, with the same [tNNNN] number at the start of its first line.
- Keep each piece separate. Never merge pieces, split one into two, or reorder them.
- Preserve every spoken fact. Do not summarize, add, or infer anything.
- Correct punctuation and capitalization.
- Remove only obvious accidental repetition.
- You may split a long piece into paragraphs.
- Do not write speaker names or timestamps.
- Output only the pieces.

Pieces:

{pieces}
""".strip()


def _words(text: str) -> int:
    return len(text.split())


def groups(turns: list[Turn], max_words: int = MAX_WORDS_PER_CALL) -> list[list[Turn]]:
    """Consecutive turns, about max_words words per group."""
    result: list[list[Turn]] = []
    current: list[Turn] = []
    count = 0
    for turn in turns:
        size = _words(turn.text_raw)
        if current and count + size > max_words:
            result.append(current)
            current, count = [], 0
        current.append(turn)
        count += size
    if current:
        result.append(current)
    return result


def parse_reply(reply: str) -> dict[str, str]:
    """{turn id: cleaned text} from the model's reply."""
    found: dict[str, list[str]] = {}
    current = None
    for line in str(reply or "").splitlines():
        match = _ID_LINE.match(line.strip())
        if match:
            current = match.group(1)
            if current in found:        # the same number twice: not trustworthy
                found[current] = ["\x00duplicate"]
                current = None
                continue
            found[current] = [match.group(2)]
        elif current is not None:
            found[current].append(line)
    return {key: "\n".join(value).strip() for key, value in found.items()
            if value != ["\x00duplicate"]}


def acceptable(original: str, cleaned: str) -> bool:
    """Is the cleaned text a tidied version of the original, not something else?"""
    before, after = _words(original), _words(cleaned)
    if after == 0:
        return False
    if before <= 3:
        return after <= before + 3
    return MIN_RATIO <= after / before <= MAX_RATIO


def clean_group(group: list[Turn], ask_llm) -> int:
    """Clean one group in place; returns how many turns were changed."""
    pieces = "\n\n".join(f"[{turn.id}] {turn.text_raw}" for turn in group)
    try:
        reply = ask_llm(PROMPT.format(pieces=pieces))
    except Exception as error:      # noqa: BLE001 - keep the original words
        print(f"WARNING: cleanup failed for part of the transcript ({error}). "
              "Using the original words there.")
        return 0
    cleaned = parse_reply(reply)
    changed = 0
    for turn in group:
        text = cleaned.get(turn.id)
        if text and acceptable(turn.text_raw, text):
            turn.text = text
            changed += 1
    return changed


def clean_turns(turns: list[Turn], ask_llm, max_words: int = MAX_WORDS_PER_CALL) -> list[Turn]:
    """Turns with `text` cleaned (text_raw is never touched)."""
    parts = groups(turns, max_words)
    print()
    print(f"Cleaning {len(parts)} transcript chunks (turn by turn)...")
    for number, group in enumerate(parts, start=1):
        print(f"Cleaning chunk {number}/{len(parts)}...", flush=True)
        clean_group(group, ask_llm)
    return turns
