"""Read speaker headers out of transcript text, in one place.

A transcript is text with a header line for every turn:

    [07:37] **Alex**

    What was said.

Several steps of the extraction need to know who spoke at a given place in that
text. They used to search for "**Mic**" or "**Remote**" with their own patterns.
This module is the one reader; it accepts any speaker label, so named speakers
work the same way as the Mic and Remote channels.

It only reads text. Nothing here changes a transcript.
"""

from __future__ import annotations

import re

# One header: "[07:37] **Speaker**". The speaker is whatever sits between the
# bold marks (Mic, Remote, or a person's name).
#
# A speaker name sits on one line and is short. A damaged header (for example
# "[20:43] **" followed by a blank line, left behind when the cleaning step
# dropped the label) is therefore not a header, instead of swallowing the text
# up to the next "**".
SPEAKER = r"[^*\n]{1,60}"
HEADER = re.compile(r"\[(?P<time>\d{1,2}:\d{2})\]\s+\*\*(?P<speaker>" + SPEAKER + r")\*\*")

# The same shapes as strings, for building larger patterns:
#   MARKER        "[07:37] **Speaker**"   a full header
#   BOLD_SPEAKER  "**Speaker**"           the bold name alone
MARKER = r"\[\d{1,2}:\d{2}\]\s+\*\*" + SPEAKER + r"\*\*"
BOLD_SPEAKER = r"\*\*" + SPEAKER + r"\*\*"

# A header inside quoted evidence may lose its opening bracket after
# punctuation-normalised matching, so "[07:37]" and "07:37]" both count.
_EVIDENCE_HEADER = re.compile(
    r"(?:^|\n)\[?\d{1,2}:\d{2}\]\s+\*\*(" + SPEAKER + r")\*\*", flags=re.MULTILINE)

_TURN = re.compile(
    r"(?ms)^\[(?P<time>\d{1,2}:\d{2})\]\s+\*\*(?P<speaker>" + SPEAKER + r")\*\*\s*\n+"
    r"(?P<body>.*?)(?=^\[\d{1,2}:\d{2}\]\s+\*\*|\Z)"
)


def turn_records(transcript: str) -> list[dict]:
    """Parse timestamped transcript turns while preserving exact body text.

    Each record has the header's time and speaker, the exact body, and the
    character positions of the body ("start", "end") and of the whole turn
    ("turn_start", "turn_end").
    """
    turns: list[dict] = []
    for match in _TURN.finditer(str(transcript or "")):
        body = match.group("body").strip()
        if not body:
            continue
        turns.append({
            "time": match.group("time"),
            "speaker": match.group("speaker").strip(),
            "body": body,
            # Both the exact body span and the whole turn span are kept: a
            # quote can begin inside the header after normalised matching, so
            # attribution must resolve either without guessing from nearby text.
            "start": match.start("body"),
            "end": match.end("body"),
            "turn_start": match.start(),
            "turn_end": match.end(),
        })
    return turns


# --------------------------------------------------------------- who is who
#
# Steps that decide who may own a commitment need two answers about a speaker:
# is it the user, or someone else? Until speakers have names, the user is "Mic"
# and everyone else is "Remote". With names, the user's header carries their own
# name. These functions answer from the configured identity, so no step has to
# spell out "Mic" or "Remote" itself.

def self_labels() -> frozenset[str]:
    """Header labels (lower case) that mean the user."""
    import config
    labels = {"mic", str(config.SELF_SPEAKER_LABEL or "").strip().casefold(),
              str(config.SELF_NAME or "").strip().casefold()}
    labels.discard("")
    return frozenset(labels)


def is_self_speaker(speaker: str) -> bool:
    """True when a header label is the user (the Mic channel, or their name)."""
    return str(speaker or "").strip().casefold() in self_labels()


# Labels that name a channel or a gap in knowledge, not a person.
NON_PERSON_LABELS = frozenset({
    "remote", "mic", "microphone", "speaker", "speaker a", "speaker b",
    "unidentified", "unknown"})


def is_person_speaker(speaker: str) -> bool:
    """True when a header label is a named person other than the user."""
    label = str(speaker or "").strip()
    if not label or is_self_speaker(label):
        return False
    return label.casefold() not in NON_PERSON_LABELS


def owner_for_speaker(speaker: str) -> str:
    """Who owns a first-person commitment said under this header label.

    The user's own name for the user; a named person's name for them;
    "" (not known) for Remote, Unidentified or anything else.
    """
    if is_self_speaker(speaker):
        import config
        return str(config.SELF_NAME)
    return str(speaker).strip() if is_person_speaker(speaker) else ""


def speakers_in(text: str) -> list[str]:
    """The distinct header labels in a transcript, in order of first use."""
    seen: list[str] = []
    for match in HEADER.finditer(text or ""):
        label = match.group("speaker").strip()
        if label not in seen:
            seen.append(label)
    return seen


def self_marker_pattern() -> str:
    """A pattern for the user's bold header label, such as ``\\*\\*(?:Mic)\\*\\*``."""
    labels = sorted(self_labels(), key=len, reverse=True)
    return r"\*\*(?:" + "|".join(re.escape(label) for label in labels) + r")\*\*"


def last_marker_before(text: str, end: int) -> int:
    """Where the last bold speaker name ending at or before `end` starts (-1: none)."""
    found = -1
    for match in HEADER.finditer(text, 0, end):
        found = match.start("speaker") - 2        # back over the opening "**"
    return found


def speaker_before(text: str, end: int) -> str | None:
    """The speaker of the last header that begins before position `end`."""
    matches = list(HEADER.finditer(text[:end]))
    if not matches:
        return None
    return matches[-1].group("speaker").strip()


def speaker_in_header(evidence: str) -> str | None:
    """The speaker named by a header at the start of a quoted span, if any."""
    found = _EVIDENCE_HEADER.search(evidence)
    return found.group(1).strip() if found else None


def speaker_at(transcript: str, position: int) -> str:
    """Who spoke at character `position` of the transcript ("" if unknown)."""
    before = speaker_before(transcript, position + 1)
    if before:
        return before
    for turn in turn_records(transcript):
        if turn.get("turn_start", turn["start"]) <= position < turn.get("turn_end", turn["end"]):
            return turn["speaker"]
    return ""


def speaker_blocks(chunk: str) -> list[tuple[str, str]]:
    """The chunk split into (speaker, text) blocks, one per header.

    A chunk with no headers is one block from an "Unknown" speaker.
    """
    matches = list(HEADER.finditer(chunk))
    if not matches:
        return [("Unknown", chunk)]
    blocks = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(chunk)
        blocks.append((match.group("speaker"), chunk[match.end():end]))
    return blocks
