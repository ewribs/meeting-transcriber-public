"""Find voices that keep coming back across meetings but have no name yet.

Pure logic. Each unnamed voice in each meeting has a fingerprint summary
(a "centroid"); voices that sound alike across meetings are grouped so the
user can name a person once and have every meeting recognize them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import voice_profiles as vp
from voice_sources import recording_suffix

# Looser than the matching threshold would be risky; this sits between the
# highest score seen for different people (0.44) and the lowest for the same
# person (0.77) in testing.
GROUP_LINK_SCORE = 0.65
# Voices of one real person stay close to their group's center (0.85 and
# above in testing), so a member far below that suggests a mixed group.
LOOSE_COHESION = 0.7

# Words in meeting titles that are not names.
TITLE_STOPWORDS = {
    "meeting", "huddle", "discussion", "update", "review", "weekly", "monthly",
    "chat", "sync", "call", "intro", "introduction", "with", "internal",
    "external", "kickoff", "checkpoint", "standing", "recap", "session",
    "catchup", "checkin", "team", "staff", "the", "and", "for",
}


@dataclass
class Occurrence:
    run: str
    voice_id: str
    seconds: float
    centroid: list[float]


@dataclass
class Group:
    members: list[Occurrence]
    cohesion: float = 1.0
    hints: list[tuple[str, int]] = field(default_factory=list)

    @property
    def runs(self) -> list[str]:
        return sorted({m.run for m in self.members})

    @property
    def seconds(self) -> float:
        return sum(m.seconds for m in self.members)

    @property
    def loose(self) -> bool:
        return self.cohesion < LOOSE_COHESION


def cluster_occurrences(
    items: list[Occurrence], link: float = GROUP_LINK_SCORE
) -> list[Group]:
    """Group voices whose fingerprints are alike. Biggest groups first."""
    parent = list(range(len(items)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if vp.dot(items[i].centroid, items[j].centroid) >= link:
                parent[root(i)] = root(j)

    buckets: dict[int, list[Occurrence]] = {}
    for i, item in enumerate(items):
        buckets.setdefault(root(i), []).append(item)

    groups = []
    for members in buckets.values():
        center = vp.centroid([m.centroid for m in members])
        cohesion = min(vp.dot(m.centroid, center) for m in members)
        groups.append(Group(members, cohesion))
    groups.sort(key=lambda g: (-len(g.runs), -g.seconds))
    return groups


def title_tokens(run_name: str) -> set[str]:
    """Words in a meeting's title: "2026-10-05_1459_AveryMorgan100526" -> {"avery", "morgan"}."""
    suffix = recording_suffix(run_name)
    words = re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+", suffix)
    return {
        w.lower() for w in words
        if len(w) >= 3 and w.lower() not in TITLE_STOPWORDS
    }


def title_hints(
    group_runs: list[str],
    all_runs: list[str],
    known_names: set[str],
    top: int = 3,
    min_coverage: float = 0.5,
    min_lift: float = 1.5,
    min_meetings: int = 2,
) -> list[tuple[str, int]]:
    """Words that appear in most of a group's meeting titles but not in
    meeting titles generally: likely the person's name.

    Returns (word, number of the group's meetings whose title has it).
    """
    if not group_runs or not all_runs:
        return []
    overall: dict[str, int] = {}
    for run in all_runs:
        for token in title_tokens(run):
            overall[token] = overall.get(token, 0) + 1
    inside: dict[str, int] = {}
    for run in group_runs:
        for token in title_tokens(run):
            inside[token] = inside.get(token, 0) + 1

    scored = []
    for token, count in inside.items():
        if token in known_names:
            continue
        coverage = count / len(group_runs)
        lift = coverage / (overall[token] / len(all_runs))
        if count >= min_meetings and coverage >= min_coverage and lift >= min_lift:
            scored.append((token, count, coverage * lift))
    scored.sort(key=lambda t: (-t[2], -t[1], t[0]))
    return [(token.capitalize(), count) for token, count, _ in scored[:top]]
