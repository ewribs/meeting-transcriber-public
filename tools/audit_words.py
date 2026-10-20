#!/usr/bin/env python3
"""Review words the release audit treats as private, and allow harmless ones.

The release audit derives "private terms" from the names of your meetings and
files. Everyday words that happen to appear in a meeting name (for example
"help" or "business") then fail the release. This tool lists those words, shows
where each one appears, and lets you approve the harmless ones. Approvals are
saved to the Git-ignored release_audit.local.json.

    tools/mt audit-words                 review flagged words one by one
    tools/mt audit-words --list          just list them (changes nothing)
    tools/mt audit-words --allow a b     allow specific words
    tools/mt audit-words --check         only check the config file is valid

Allowing a word means it may appear in public code and docs. Never allow a
person's name, a company, a project, or anything else that identifies them;
change the text instead.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import release_audit
except ImportError:  # pragma: no cover - imported as part of the tools package
    from tools import release_audit

SAMPLE_LINES = 3


class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict:
    """Read the local config, with a plain-English error if it is not valid."""
    path = Path(path)

    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path.name} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}). The usual cause is a missing comma after an item in a list. "
            "Fix that line, then run this again."
        ) from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"{path.name} must contain a JSON object.")

    allow = payload.get("derived_allow", [])

    if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
        raise ConfigError('"derived_allow" must be a list of words in quotes.')

    return payload


def allow_words(path: Path, words) -> list[str]:
    """Add words to derived_allow. Returns the words that were newly added."""
    path = Path(path)
    payload = load_config(path)
    current = {str(x).strip().lower() for x in payload.get("derived_allow", [])}
    added = []

    for word in words:
        cleaned = str(word).strip().lower()
        if cleaned and cleaned not in current:
            current.add(cleaned)
            added.append(cleaned)

    if not added:
        return []

    payload["derived_allow"] = sorted(current)
    text = json.dumps(payload, indent=2) + "\n"
    json.loads(text)  # never write something we could not read back

    if path.exists():
        backup = path.with_name(path.name + ".bak")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".audit-words-", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

    return sorted(added)


def hits_from_findings(findings, root: Path) -> dict[str, list[tuple[str, int, str]]]:
    """Group the audit's own "private-name-derived" errors by flagged word.

    Using the audit's findings (rather than a separate scan) guarantees this
    tool lists exactly the words that make the release fail.
    """
    hits: dict[str, list[tuple[str, int, str]]] = {}

    for finding in findings:
        if finding.code != "private-name-derived":
            continue

        match = re.search(r"\('([^']*)'\)", finding.detail)
        if not match:
            continue

        term = match.group(1).lower()
        number = finding.line or 0
        text = "(file name)"

        if number:
            try:
                lines = (Path(root) / finding.path).read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                text = lines[number - 1].strip()
            except (OSError, IndexError):
                text = ""

        hits.setdefault(term, []).append((finding.path, number, text))

    return {term: hits[term] for term in sorted(hits)}


def flagged(root: Path, config_path: Path) -> dict[str, list[tuple[str, int, str]]]:
    return hits_from_findings(release_audit.audit(root, config_path), root)


def describe(term: str, where: list[tuple[str, int, str]]) -> str:
    files = sorted({rel for rel, _, _ in where})
    lines = [f"{term}  —  {len(where)} place(s) in {len(files)} file(s)"]
    for rel, number, text in where[:SAMPLE_LINES]:
        shown = text if len(text) <= 100 else text[:97] + "..."
        place = rel if number == 0 else f"{rel}:{number}"
        lines.append(f"    {place}: {shown}")
    if len(where) > SAMPLE_LINES:
        lines.append(f"    (+{len(where) - SAMPLE_LINES} more)")
    return "\n".join(lines)


def review(root: Path, config_path: Path, *, input_fn=input, output=print) -> int:
    hits = flagged(root, config_path)

    if not hits:
        output("No flagged words. The release audit has nothing to approve.")
        return 0

    output(f"{len(hits)} word(s) taken from meeting/file names appear in committed files.")
    output("For each: allow it only if it is a harmless everyday word.")
    output("If it identifies a person, company or project, change the text instead.\n")

    approved: list[str] = []

    for term, where in hits.items():
        output(describe(term, where))
        answer = input_fn("  Allow this word? [y = allow, n = skip, q = quit] ").strip().lower()
        output("")

        if answer == "q":
            break
        if answer == "y":
            approved.append(term)

    if approved:
        added = allow_words(config_path, approved)
        output("Allowed: " + ", ".join(added))
        output(f"Saved to {Path(config_path).name} (a backup copy was kept as .bak).")
    else:
        output("Nothing allowed.")

    skipped = [t for t in hits if t not in approved]
    if skipped:
        output("\nStill flagged (the release will fail until these are fixed or allowed): "
               + ", ".join(skipped))

    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Review and allow harmless flagged words.")
    parser.add_argument("--config", type=Path, default=release_audit.LOCAL_CONFIG)
    parser.add_argument("--list", action="store_true", help="list flagged words; change nothing")
    parser.add_argument("--allow", nargs="+", metavar="WORD", help="allow these words")
    parser.add_argument("--check", action="store_true", help="only check the config file")
    args = parser.parse_args(argv)

    try:
        load_config(args.config)

        if args.check:
            print(f"{args.config.name} is valid.")
            return 0

        if args.allow:
            added = allow_words(args.config, args.allow)
            print("Allowed: " + ", ".join(added) if added else "Nothing new to allow.")
            return 0

        if args.list:
            hits = flagged(release_audit.ROOT, args.config)
            if not hits:
                print("No flagged words.")
            for term, where in hits.items():
                print(describe(term, where))
            return 0

        return review(release_audit.ROOT, args.config)

    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Nothing was changed after the last answer.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
