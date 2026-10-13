#!/usr/bin/env python3
"""Replace real people/vendor names in public-bound files with invented ones.

Safe by default: it only PREVIEWS. Nothing changes until you add --apply.

    python tools/sanitize_names.py            # preview
    python tools/sanitize_names.py --apply    # make the changes (backs up first)

The names live in a PRIVATE, git-ignored file, sanitize_names.local.json, in
the repo root, so this script itself contains no real names:

    {"names":       {"Real Name": "Invented Name", ...},
     "tests_only":  {"phrase used only in tests": "replacement", ...},
     "report_terms": ["Term", "To", "Report", ...]}

What it changes
  * docs, text files, scripts, tests and tools: names replaced everywhere
  * root-level .py files (like memory_reconciliation.py): names replaced ONLY
    inside comments and docstrings, never in working code
  * one working-code fix: memory_reconciliation.py compared a commitment
    owner to a hard-coded name. It now compares to your configured self name
    (config.SELF_NAME), so behavior is unchanged for you and no name is
    written in the code.

What it never changes
  * Any other name inside working code. Those rules change behavior, so they
    are only REPORTED, with line numbers, for a proper refactor.
  * Your private config files, meetings/, output/, benchmark data, backups.

Backups of every changed file go to .sanitize_backup/<timestamp>/ (keep it out
of git: echo ".sanitize_backup/" >> .git/info/exclude).
"""
from __future__ import annotations

import argparse
import ast
import datetime
import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONFIG = ROOT / "sanitize_names.local.json"
SELF_PATH = "tools/sanitize_names.py"


def load_config():
    if not CONFIG.is_file():
        raise SystemExit(
            "Missing sanitize_names.local.json (private, git-ignored). "
            "See the top of this file for its format."
        )
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    names = dict(data.get("names", {}))
    # Longest first so "First L" is replaced before "First".
    ordered = sorted(names.items(), key=lambda kv: -len(kv[0]))
    return ordered, sorted(dict(data.get("tests_only", {})).items()), list(data.get("report_terms", []))


# Matching is case-sensitive and whole-word, so a GitHub name like "ewname" or
# ordinary words like "Graceful" are left alone.
NAME_MAP, TEST_ONLY_MAP, REPORT_TERMS = load_config()

TEXT_SUFFIXES = {".py", ".md", ".txt", ".sh", ".zsh", ".json", ".swift",
                 ".plist", ".yml", ".yaml"}
SKIP_PREFIXES = ("meetings/", "output/", "benchmark_runs", "private_benchmarks",
                 "logs/", "prompts/", ".venv", "venv/", "dist/", "build/",
                 ".build/", "phase15-", ".sanitize_backup/", "legacy/")
SKIP_NAMES = {"release_audit.local.json", "known_people.json",
              "identity.local.json", "business_context.local.json",
              "benchmark_meetings.local.json", "sanitize_names.local.json"}


def git_files() -> list[str]:
    def run(*args):
        out = subprocess.check_output(["git", *args, "-z"], cwd=ROOT).decode()
        return [x for x in out.split("\0") if x]

    return sorted(set(run("ls-files") + run("ls-files", "--others", "--exclude-standard")))


def pattern_for(old: str) -> re.Pattern:
    # Whole word, but also match right after a typed "\\n" inside a string.
    return re.compile(rf"(?:(?<![A-Za-z])|(?<=\\n)){re.escape(old)}(?![a-z])")


def replace_text(text: str, rel: str) -> tuple[str, int]:
    count = 0
    pairs = list(NAME_MAP)
    if rel.startswith("tests/"):
        pairs += TEST_ONLY_MAP
    for old, new in pairs:
        text, n = pattern_for(old).subn(new, text)
        count += n
    return text, count


def comment_and_docstring_lines(source: str) -> set[int]:
    """1-based line numbers that are comments or docstring text."""
    lines: set[int] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return lines
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                first = body[0]
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    return lines


def replace_in_comments_only(source: str) -> tuple[str, int]:
    allowed = comment_and_docstring_lines(source)
    out, total = [], 0
    for number, line in enumerate(source.splitlines(keepends=True), start=1):
        if number in allowed:
            line, n = replace_text(line, "root.py")
            total += n
        out.append(line)
    return "".join(out), total


OWNER_CHECK_RE = re.compile(r"norm\(item\.get\('owner', ''\)\) != '[^']+'")
NEW_OWNER_CHECK = "norm(item.get('owner', '')) != _self_owner_key()"
HELPER = '''

def _self_owner_key() -> str:
    """Normalized configured self name (private; set in identity.local.json)."""
    try:
        from config import SELF_NAME
    except Exception:  # config unavailable in some tooling contexts
        return ""
    return norm(SELF_NAME)
'''


def fix_owner_logic(text: str) -> tuple[str, bool]:
    if len(OWNER_CHECK_RE.findall(text)) != 1 or "_self_owner_key" in text:
        return text, False
    text = OWNER_CHECK_RE.sub(NEW_OWNER_CHECK, text, count=1)
    anchor = "\n\ndef narrow_commitment_evidence("
    if text.count(anchor) == 1:
        text = text.replace(anchor, HELPER + anchor, 1)
        return text, True
    return text, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()

    changes: dict[str, str] = {}
    counts: dict[str, int] = {}
    remaining: list[tuple[str, int, str]] = []

    for rel in git_files():
        path = ROOT / rel
        if (rel == SELF_PATH or any(rel.startswith(p) for p in SKIP_PREFIXES) or path.name in SKIP_NAMES
                or path.suffix not in TEXT_SUFFIXES or not path.is_file()):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        is_root_py = path.suffix == ".py" and "/" not in rel
        if is_root_py:
            updated, n = replace_in_comments_only(original)
            if rel == "memory_reconciliation.py":
                updated, fixed = fix_owner_logic(updated)
                if fixed:
                    n += 1
        else:
            updated, n = replace_text(original, rel)

        if n and updated != original:
            changes[rel] = updated
            counts[rel] = n

        for number, line in enumerate(updated.splitlines(), start=1):
            if any(pattern_for(term).search(line) for term in REPORT_TERMS):
                remaining.append((rel, number, line.strip()[:110]))

    print(f"Files to change: {len(changes)}   Replacements: {sum(counts.values())}")
    for rel, n in sorted(counts.items()):
        print(f"  {n:3}  {rel}")

    print(f"\nStill present after this cleanup (needs a refactor or a decision): {len(remaining)}")
    for rel, number, line in remaining[:80]:
        print(f"  {rel}:{number}  {line}")

    if not args.apply:
        print("\nPreview only. Nothing was changed. Add --apply to make the changes.")
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / ".sanitize_backup" / stamp
    for rel, updated in changes.items():
        target = backup / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
        (ROOT / rel).write_text(updated, encoding="utf-8")
    print(f"\nApplied. Originals saved in {backup}")
    print("Next: python -m unittest discover -s tests   then   python tools/release_audit.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
