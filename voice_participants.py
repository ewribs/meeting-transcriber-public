"""Compare the participants found from transcript text with who was heard.

Pure logic, no audio. The transcript method lists anyone whose name is said
in the meeting, including people who were only mentioned. Voices list the
people who actually spoke (and whom the app has learned to recognize).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable


def _letters(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalpha())


def same_person(a: str, b: str) -> bool:
    """Names match ignoring case and spaces ("Pat B" = "PatB"); a first name
    matches a longer spelling that starts with it ("Dana" matches "DanaQ")."""
    a, b = _letters(a), _letters(b)
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def text_names(metadata: dict | None) -> list[str]:
    """Names in meeting_metadata.json (the transcript-based list)."""
    names = []
    for item in (metadata or {}).get("participants", []) or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name and name not in names:
            names.append(name)
    return names


def voice_names(document: dict | None) -> list[str]:
    """People recognized by voice in speakers.json, most speech first."""
    if not document or document.get("remote_silent"):
        return []
    named = {}
    for voice in document.get("voices", []):
        name = voice.get("person")
        if voice.get("status") == "named" and name:
            named[name] = named.get(name, 0.0) + float(voice.get("seconds", 0))
    return [n for n, _ in sorted(named.items(), key=lambda kv: -kv[1])]


@dataclass
class Comparison:
    run: str
    both: list[str] = field(default_factory=list)
    text_only: list[str] = field(default_factory=list)    # said, not heard
    voice_only: list[str] = field(default_factory=list)   # heard, not in text list
    unnamed_voices: int = 0
    usable: bool = True    # false when there is no voice data to compare

    @property
    def differs(self) -> bool:
        return bool(self.text_only or self.voice_only)


def compare(run: str, metadata: dict | None, document: dict | None) -> Comparison:
    result = Comparison(run=run)
    if document is None or document.get("remote_silent"):
        result.usable = False
        return result
    old = text_names(metadata)
    new = voice_names(document)
    for name in new:
        match = next((o for o in old if same_person(o, name)), None)
        (result.both if match else result.voice_only).append(name)
    result.text_only = [o for o in old
                        if not any(same_person(o, n) for n in new)]
    result.unnamed_voices = sum(
        1 for v in document.get("voices", [])
        if v.get("status") == "unknown"
    )
    return result


def never_heard(comparisons: Iterable[Comparison]) -> list[tuple[str, int]]:
    """Names that appear in transcript lists but never match a voice,
    with the number of meetings: good candidates to enroll."""
    counts: Counter = Counter()
    for c in comparisons:
        if c.usable:
            counts.update(c.text_only)
    return counts.most_common()


# ------------------------------------------------------ the new list --------

import json
import re
from pathlib import Path

HEARD_REASON = "Recognized by voice in this meeting"
TITLE_REASON = "Named in the meeting title, but not heard"
BACKUP_KEY = "participants_before_voice"


def _title_words(run_name: str) -> list[str]:
    parts = run_name.split("_", 2)
    suffix = parts[2] if len(parts) > 2 else run_name
    return [w.casefold() for w in
            re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+", suffix)]


def title_names(run_name: str, known_names: Iterable[str]) -> list[str]:
    """Known people whose name appears in the meeting title.

    Only people the app already knows count, and a name must match whole
    words ("Bo" is not found in "Boat"). A name written as one word
    plus an initial ("PatB") is matched too.
    """
    words = _title_words(run_name)
    found = []
    for name in known_names:
        target = _letters(name)
        if not target or name in found:
            continue
        for i in range(len(words)):
            joined = ""
            for j in range(i, min(i + 3, len(words))):
                joined += words[j]
                if joined == target:
                    found.append(name)
                    break
            else:
                continue
            break
    return found


def build_participants(
    run_name: str,
    document: dict | None,
    known_names: Iterable[str],
) -> list[dict] | None:
    """Participants from who was heard, plus titled-but-not-heard people.

    Returns None when there is no usable voice data, so the caller leaves
    the existing list alone.
    """
    if document is None or document.get("remote_silent"):
        return None
    heard = voice_names(document)
    result = [{"name": n, "confidence": "high", "reason": HEARD_REASON}
              for n in heard]
    for name in title_names(run_name, known_names):
        if not any(same_person(name, h) for h in heard):
            result.append({"name": name, "confidence": "low",
                           "reason": TITLE_REASON})
    return result


def apply_to_run(run_dir: Path, new_list: list[dict]) -> bool:
    """Write the new list to meeting_metadata.json, keeping the old one once
    under BACKUP_KEY so it can be restored. Returns True when it changed."""
    path = Path(run_dir) / "meeting_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if metadata.get("participants") == new_list:
        return False
    if BACKUP_KEY not in metadata:
        metadata[BACKUP_KEY] = metadata.get("participants", [])
    metadata["participants"] = new_list
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return True


def restore_run(run_dir: Path) -> bool:
    """Put back the list saved by apply_to_run. Returns True when restored."""
    path = Path(run_dir) / "meeting_metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    if BACKUP_KEY not in metadata:
        return False
    metadata["participants"] = metadata.pop(BACKUP_KEY)
    path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return True
