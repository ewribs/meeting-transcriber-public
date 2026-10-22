"""Voice profiles: who is speaking, learned from past meetings.

Pure logic only. This module does not load audio or models. A separate
step turns audio into "fingerprints" (lists of numbers, one per short clip
of speech); everything here works on those numbers, so it is easy to test
and has no heavy dependencies.

Privacy: fingerprints are biometric data about real people. They are kept
in one local file with owner-only permissions, never inside a meeting
folder, and are never published or archived.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

Vector = list[float]

STORE_VERSION = 1

# Starting values from the experiments; expected to be tuned.
NAME_SCORE = 0.65          # best match must be at least this close
NAME_GAP = 0.25            # and this far ahead of the second best
SAME_VOICE_SCORE = 0.60    # two voices this close are the same person
MIN_VOICE_SECONDS = 30.0   # less speech than this is not judged
MIN_FINGERPRINTS_TO_ENROLL = 3
MAX_FINGERPRINTS_PER_PERSON = 200


class VoiceStoreError(Exception):
    """The voice profile file cannot be read or is not valid."""


# ------------------------------------------------------------------ vectors --

def normalize(vector: Sequence[float]) -> Vector:
    values = [float(x) for x in vector]
    if not values:
        raise ValueError("Empty fingerprint.")
    if not all(math.isfinite(x) for x in values):
        raise ValueError("Fingerprint contains a non-finite number.")
    norm = math.sqrt(sum(x * x for x in values))
    if norm == 0:
        raise ValueError("Fingerprint is all zeros.")
    return [x / norm for x in values]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Fingerprints have different lengths.")
    return sum(x * y for x, y in zip(a, b))


def centroid(vectors: Iterable[Sequence[float]]) -> Vector:
    """Average direction of several fingerprints (unit length)."""
    unit = [normalize(v) for v in vectors]
    if not unit:
        raise ValueError("No fingerprints.")
    size = len(unit[0])
    total = [0.0] * size
    for vec in unit:
        if len(vec) != size:
            raise ValueError("Fingerprints have different lengths.")
        for i, x in enumerate(vec):
            total[i] += x
    return normalize(total)


def clean_centroid(vectors: Sequence[Sequence[float]]) -> Vector:
    """Centroid after dropping outliers (a stray voice, noise).

    A fingerprint is an outlier if it is more than two standard deviations
    less similar to the average than typical. If dropping them would leave
    fewer than three, everything is kept.
    """
    unit = [normalize(v) for v in vectors]
    first = centroid(unit)
    sims = [dot(v, first) for v in unit]
    mean = sum(sims) / len(sims)
    var = sum((s - mean) ** 2 for s in sims) / len(sims)
    cut = mean - 2 * math.sqrt(var)
    kept = [v for v, s in zip(unit, sims) if s >= cut]
    return centroid(kept if len(kept) >= 3 else unit)


def _spread(items: list, limit: int) -> list:
    """Keep `limit` items spread evenly across the list."""
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


# -------------------------------------------------------------------- store --

@dataclass
class Person:
    person_id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    fingerprints: list[Vector] = field(default_factory=list)
    enrollments: int = 0
    centroid: Vector | None = None

    def names(self) -> list[str]:
        return [self.name] + list(self.aliases)


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "person"


class VoiceStore:
    """The set of people the app can recognize."""

    def __init__(self, max_fingerprints: int = MAX_FINGERPRINTS_PER_PERSON):
        self.max_fingerprints = max_fingerprints
        self._people: dict[str, Person] = {}

    # --- people

    def people(self) -> list[Person]:
        return sorted(self._people.values(), key=lambda p: p.name.lower())

    def find(self, name_or_id: str) -> Person | None:
        key = (name_or_id or "").strip().lower()
        if not key:
            return None
        if key in self._people:
            return self._people[key]
        for person in self._people.values():
            if key in (n.lower() for n in person.names()):
                return person
        return None

    def add_person(self, name: str) -> Person:
        name = (name or "").strip()
        if not name:
            raise ValueError("A person needs a name.")
        if self.find(name) is not None:
            raise ValueError("Already exists: " + name)
        base = _slug(name)
        person_id, n = base, 2
        while person_id in self._people:
            person_id = f"{base}-{n}"
            n += 1
        person = Person(person_id=person_id, name=name)
        self._people[person_id] = person
        return person

    def ensure_person(self, name: str) -> Person:
        return self.find(name) or self.add_person(name)

    def rename_person(self, person_id: str, new_name: str) -> None:
        person = self._require(person_id)
        new_name = (new_name or "").strip()
        if not new_name:
            raise ValueError("A person needs a name.")
        other = self.find(new_name)
        if other is not None and other.person_id != person.person_id:
            raise ValueError("Already exists: " + new_name)
        if person.name.lower() != new_name.lower() and person.name not in person.aliases:
            person.aliases.append(person.name)
        person.name = new_name

    def remove_person(self, person_id: str) -> None:
        self._require(person_id)
        del self._people[person_id]

    def _require(self, person_id: str) -> Person:
        if person_id not in self._people:
            raise KeyError("Unknown person: " + person_id)
        return self._people[person_id]

    # --- learning

    def enroll(self, person_id: str, fingerprints: Sequence[Sequence[float]]) -> int:
        """Add fingerprints to a person's profile; returns how many were added."""
        person = self._require(person_id)
        if len(fingerprints) < MIN_FINGERPRINTS_TO_ENROLL:
            raise ValueError(
                f"Need at least {MIN_FINGERPRINTS_TO_ENROLL} fingerprints to enroll."
            )
        new = [normalize(f) for f in fingerprints]
        if person.fingerprints and len(new[0]) != len(person.fingerprints[0]):
            raise ValueError("Fingerprints have a different length than this profile.")
        person.fingerprints = _spread(person.fingerprints + new, self.max_fingerprints)
        person.enrollments += 1
        person.centroid = clean_centroid(person.fingerprints)
        return len(new)

    def centroids(self) -> dict[str, Vector]:
        return {
            pid: p.centroid for pid, p in self._people.items() if p.centroid
        }

    # --- saving

    def save(self, path: Path) -> None:
        path = Path(path)
        payload = {
            "version": STORE_VERSION,
            "people": [
                {
                    "id": p.person_id,
                    "name": p.name,
                    "aliases": p.aliases,
                    "enrollments": p.enrollments,
                    "fingerprints": [[round(x, 5) for x in f] for f in p.fingerprints],
                }
                for p in self.people()
            ],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".voices-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: Path) -> "VoiceStore":
        """Read a store; a missing file gives an empty store."""
        path = Path(path)
        store = cls()
        if not path.exists():
            return store
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != STORE_VERSION:
                raise VoiceStoreError("Unsupported voice profile version.")
            for item in data["people"]:
                person = Person(
                    person_id=item["id"],
                    name=item["name"],
                    aliases=list(item.get("aliases", [])),
                    fingerprints=[normalize(f) for f in item.get("fingerprints", [])],
                    enrollments=int(item.get("enrollments", 0)),
                )
                if person.fingerprints:
                    person.centroid = clean_centroid(person.fingerprints)
                store._people[person.person_id] = person
        except VoiceStoreError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise VoiceStoreError("Voice profile file is not valid: " + str(error))
        return store


# ----------------------------------------------------------- identification --

@dataclass(frozen=True)
class Suggestion:
    person_id: str
    score: float


@dataclass
class VoiceInput:
    voice_id: str
    seconds: float
    fingerprints: list[Vector]


@dataclass
class VoiceResult:
    voice_id: str
    seconds: float
    status: str                      # "named", "unknown" or "too_short"
    person_id: str | None = None
    suggestions: list[Suggestion] = field(default_factory=list)
    gap: float = 0.0
    via: str = ""                    # "match" or "grouped" when named
    same_as: list[str] = field(default_factory=list)


def score_against(voice_centroid: Sequence[float], store: VoiceStore) -> list[Suggestion]:
    scores = [
        Suggestion(pid, dot(voice_centroid, c))
        for pid, c in store.centroids().items()
    ]
    scores.sort(key=lambda s: -s.score)
    return scores


def identify_voices(
    voices: Sequence[VoiceInput],
    store: VoiceStore,
    *,
    name_score: float = NAME_SCORE,
    name_gap: float = NAME_GAP,
    same_voice: float = SAME_VOICE_SCORE,
    min_seconds: float = MIN_VOICE_SECONDS,
) -> list[VoiceResult]:
    """Decide which voices in one meeting belong to known people.

    A voice is only named when it is both close to one person and clearly
    closer to them than to anyone else. Voices that sound like each other
    are linked, so a short fragment of a named voice takes the same name.
    """
    results: list[VoiceResult] = []
    cents: dict[str, Vector] = {}

    for voice in voices:
        if voice.seconds < min_seconds or not voice.fingerprints:
            results.append(VoiceResult(voice.voice_id, voice.seconds, "too_short"))
            continue
        c = centroid(voice.fingerprints)
        cents[voice.voice_id] = c
        suggestions = score_against(c, store)[:3]
        gap = 0.0
        status, person_id, via = "unknown", None, ""
        if suggestions:
            second = suggestions[1].score if len(suggestions) > 1 else 0.0
            gap = suggestions[0].score - second
            if suggestions[0].score >= name_score and gap >= name_gap:
                status, person_id, via = "named", suggestions[0].person_id, "match"
        results.append(
            VoiceResult(voice.voice_id, voice.seconds, status, person_id,
                        suggestions, gap, via)
        )

    by_id = {r.voice_id: r for r in results}
    ids = list(cents)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if dot(cents[a], cents[b]) >= same_voice:
                by_id[a].same_as.append(b)
                by_id[b].same_as.append(a)

    # A voice that sounds like a named voice takes the same name, unless it
    # is close to voices named as two different people.
    for result in results:
        if result.status != "unknown" or not result.same_as:
            continue
        owners = {
            by_id[o].person_id for o in result.same_as
            if by_id[o].status == "named" and by_id[o].via == "match"
        }
        if len(owners) == 1:
            result.status, result.via = "named", "grouped"
            result.person_id = owners.pop()
    return results


@dataclass(frozen=True)
class EliminationHint:
    voice_ids: tuple[str, ...]
    name: str


def suggest_by_elimination(
    results: Sequence[VoiceResult],
    expected_names: Iterable[str],
    store: VoiceStore,
) -> EliminationHint | None:
    """If everyone but one expected person is accounted for, suggest them.

    `expected_names` is who should be on the call, other than the user.
    Returns a hint only when exactly one expected name is unaccounted for
    and exactly one unnamed person (a voice, or several voices that sound
    alike) is left. This is a suggestion to confirm, never a fact.
    """
    named_ids = {r.person_id for r in results if r.status == "named"}
    leftover_names: list[str] = []
    seen: set[str] = set()
    for raw in expected_names:
        name = (raw or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        person = store.find(name)
        if person is not None and person.person_id in named_ids:
            continue
        leftover_names.append(name)

    unknown = [r for r in results if r.status == "unknown"]
    # Voices that sound alike are one person.
    parent = {r.voice_id: r.voice_id for r in unknown}

    def root(v: str) -> str:
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for r in unknown:
        for other in r.same_as:
            if other in parent:
                parent[root(r.voice_id)] = root(other)
    groups: dict[str, list[str]] = {}
    for r in unknown:
        groups.setdefault(root(r.voice_id), []).append(r.voice_id)

    if len(groups) == 1 and len(leftover_names) == 1:
        return EliminationHint(tuple(next(iter(groups.values()))), leftover_names[0])
    return None
