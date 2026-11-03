"""Derive private terms from meeting/file names so the release audit can block them.

Meeting and file names (output folders, recordings, benchmark cases, the archive)
contain people's names, internal acronyms, company and system names. This module
turns those names into a set of terms. The release audit then refuses to publish
any tracked file whose text or path contains one of them as a whole word.

Nothing here contains real names: the names are read from the local machine at
run time. Terms that are harmless in code can be exempted through the
"derived_allow" list in release_audit.local.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Everyday words that meeting titles share with ordinary code and prose. They are
# not sensitive and would only create false alarms, so they are never derived.
GENERIC_WORDS = frozenset(
    """
    and the with for only out not are was via from into onto over under
    meeting meetings notes note session sessions review reviews update updates
    result results summary test tests testing check checks cleanup call chat
    weekly daily monthly standing huddle sync recap intro kickoff lunch friday
    discussion introduction strategy support planning external internal
    txt json md py html csv zip pipeline workspace owner store ops
    """.split()
)

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}_")
_DATE_SUFFIX = re.compile(r"\d{6}$")
_TOKEN = re.compile(r"[A-Z]{2,}(?![a-z])|[A-Z][a-z]+|[a-z]+")
_EXTENSIONS = (".m4a", ".txt", ".md", ".json", ".zip", ".vtt", ".html", ".wav")


def _clean_name(name: str) -> str:
    for ext in _EXTENSIONS:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    name = _DATE_PREFIX.sub("", name)
    return _DATE_SUFFIX.sub("", name)


def derive_terms(names, min_length: int = 3) -> set[str]:
    """Lower-case private terms found in a collection of names."""
    terms: set[str] = set()
    for raw in names:
        if str(raw).startswith("."):
            continue  # hidden files such as .DS_Store are not meeting names
        name = _clean_name(str(raw))
        if len(name) >= 5 and re.search(r"[A-Za-z]", name):
            terms.add(name.lower())  # the whole compact name, e.g. CamelCaseTitle
        for token in _TOKEN.findall(name):
            low = token.lower()
            if len(low) >= min_length and low not in GENERIC_WORDS:
                terms.add(low)
    return terms


def local_names(root: Path, archive_dir: Path | None = None) -> list[str]:
    """Names of meeting folders, recordings and benchmark cases on this machine."""
    names: list[str] = []
    # Meeting folders and recordings, plus benchmark case folders (directories only:
    # the files beside them are tool notes, not meeting names).
    for sub, dirs_only in (("output", False), ("meetings", False), ("private_benchmarks", True)):
        folder = Path(root) / sub
        try:
            names.extend(
                p.name for p in folder.iterdir()
                if not p.name.startswith(".") and (p.is_dir() or not dirs_only)
            )
        except OSError:
            pass
    if archive_dir is not None:
        try:
            names.extend(p.name for p in Path(archive_dir).iterdir() if not p.name.startswith("."))
        except OSError:
            pass
    return names


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _words(values) -> set[str]:
    found: set[str] = set()
    for value in values:
        for token in re.findall(r"[A-Za-z]{3,}", str(value)):
            low = token.lower()
            if low not in GENERIC_WORDS:
                found.add(low)
    return found


def local_people_terms(base: Path) -> set[str]:
    """Names kept in the private local files: known people, name replacements, report terms.

    The owner's own names (identity.local.json) are left out, because they are
    allowed to appear in the public repository.
    """
    base = Path(base)
    terms: set[str] = set()
    people = _read_json(base / "known_people.json")
    if isinstance(people, list):
        terms |= _words(people)
    sanitize = _read_json(base / "sanitize_names.local.json")
    if isinstance(sanitize, dict):
        for key in ("names", "tests_only"):
            if isinstance(sanitize.get(key), dict):
                terms |= _words(sanitize[key])
        if isinstance(sanitize.get("report_terms"), list):
            terms |= _words(sanitize["report_terms"])
    identity = _read_json(base / "identity.local.json")
    if isinstance(identity, dict):
        own = [identity.get("self_name", ""), *identity.get("self_reference_names", [])]
        terms -= _words(own)
    return terms


_CAMEL_GAP = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def build_matcher(terms):
    """Regex that finds any term as a whole word (underscores/hyphens count as breaks)."""
    ordered = sorted({t for t in terms if t}, key=len, reverse=True)
    if not ordered:
        return None
    pattern = "|".join(re.escape(t) for t in ordered)
    return re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])", re.IGNORECASE)


def find_term(matcher, text: str) -> str | None:
    """The first private term in text, also looking inside CamelCase words."""
    if matcher is None:
        return None
    for candidate in (text, _CAMEL_GAP.sub(" ", text)):
        hit = matcher.search(candidate)
        if hit:
            return hit.group(0).lower()
    return None
