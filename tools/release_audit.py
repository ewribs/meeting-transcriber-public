#!/usr/bin/env python3
"""Audit the committed repository surface for public-release privacy risks.

By default the scanner inspects files tracked by Git so ignored local runtime data
can remain on a developer machine without causing false failures. Optional private
sensitive literals can be supplied in release_audit.local.json; that file is
Git-ignored and must never be committed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / "release_audit.local.json"
EXAMPLE_CONFIG = ROOT / "release_audit.example.json"

TEXT_SUFFIXES = {
    ".py", ".swift", ".md", ".txt", ".json", ".plist", ".pbxproj", ".xcconfig",
    ".zsh", ".sh", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html", ".css",
}
MEDIA_SUFFIXES = {".m4a", ".wav", ".mp3", ".mp4", ".mov", ".aiff", ".caf"}
PRIVATE_FILENAMES = {
    "identity.local.json",
    "business_context.local.json",
    "known_people.json",
    "known_people.local.json",
    "release_audit.local.json",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
USER_PATH_RE = re.compile(r"/Users/[A-Za-z0-9._-]+(?:/[^\s'\"`<>]*)?")
CREATED_BY_RE = re.compile(r"Created by\s+[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+)+\s+on\s+", re.I)
BUNDLE_ID_RE = re.compile(r'PRODUCT_BUNDLE_IDENTIFIER\s*=\s*"?([A-Za-z0-9._-]+)"?;')
DEVELOPMENT_TEAM_RE = re.compile(r'DEVELOPMENT_TEAM\s*=\s*"?([A-Za-z0-9._-]+)"?;')
PROVISIONING_PROFILE_RE = re.compile(r'PROVISIONING_PROFILE_SPECIFIER\s*=\s*"?([^";]+)"?;')


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    line: int | None
    detail: str

    def render(self) -> str:
        where = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{self.severity:<5} {self.code:<24} {where} — {self.detail}"


try:
    from private_terms import build_matcher as _build_matcher, find_term as _find_term
except ImportError:  # pragma: no cover - run as a package
    from tools.private_terms import build_matcher as _build_matcher, find_term as _find_term


def tracked_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL
        )
    except (OSError, subprocess.CalledProcessError):
        return [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts]

    paths = [root / raw.decode("utf-8") for raw in output.split(b"\0") if raw]
    return [path for path in paths if path.exists()]


def load_private_config(path: Path) -> dict:
    if not path.exists():
        return {"sensitive_literals": [], "allowed_bundle_prefixes": ["com.example.", "org.example."]}
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"Unable to read {path.name}: {exc}") from exc

    literals = payload.get("sensitive_literals", [])
    prefixes = payload.get("allowed_bundle_prefixes", ["com.example.", "org.example."])
    if not isinstance(literals, list) or not all(isinstance(x, str) for x in literals):
        raise SystemExit("sensitive_literals must be a JSON list of strings")
    if not isinstance(prefixes, list) or not all(isinstance(x, str) for x in prefixes):
        raise SystemExit("allowed_bundle_prefixes must be a JSON list of strings")
    return {"sensitive_literals": [x for x in literals if x.strip()], "allowed_bundle_prefixes": prefixes}


def load_derived_terms(config_path: Path, root: Path = None) -> set[str]:
    """Private terms taken from local meeting/file names, minus the user's allow list."""
    try:
        from private_terms import derive_terms, local_names
    except ImportError:  # pragma: no cover - run as a package
        from tools.private_terms import derive_terms, local_names
    allow: set[str] = set()
    archive = None
    try:
        payload = json.loads(Path(config_path).read_text())
        allow = {str(x).lower() for x in payload.get("derived_allow", [])}
        if payload.get("derive_from_archive"):
            archive = Path(str(payload["derive_from_archive"]))
    except Exception:
        pass
    terms = derive_terms(local_names(root or ROOT, archive))
    return {t for t in terms if t not in allow}


def is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name in {"README", "LICENSE", "Makefile"}


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def audit_paths(files: Iterable[Path], config: dict | None = None) -> list[Finding]:
    findings: list[Finding] = []
    matcher = (config or {}).get("derived_matcher")
    for path in files:
        rel = relative(path)
        if matcher is not None and rel not in (config or {}).get("derived_allow_paths", ()):
            from_name = _find_term(matcher, rel)
            if from_name:
                findings.append(Finding("ERROR", "private-name-derived", rel, None, f"file path contains a term taken from a meeting/file name ({from_name!r})"))
        lower_parts = [part.lower() for part in path.parts]
        if path.name in PRIVATE_FILENAMES:
            findings.append(Finding("ERROR", "private-file-tracked", rel, None, "private local configuration must not be tracked"))
        if "xcuserdata" in lower_parts or path.suffix == ".xcuserstate":
            findings.append(Finding("ERROR", "xcode-user-state", rel, None, "Xcode per-user state must not be tracked"))
        if path.suffix.lower() in MEDIA_SUFFIXES:
            findings.append(Finding("ERROR", "media-artifact", rel, None, "audio/video artifact is tracked"))
    return findings


def audit_text(path: Path, config: dict) -> list[Finding]:
    rel = relative(path)
    try:
        text = path.read_text(errors="strict")
    except (UnicodeDecodeError, OSError):
        return []

    findings: list[Finding] = []
    literals = config["sensitive_literals"]
    prefixes = tuple(config["allowed_bundle_prefixes"])
    matcher = config.get("derived_matcher")
    if rel in config.get("derived_allow_paths", ()):
        matcher = None  # this one file is allowed to contain derived names (e.g. LICENSE)

    for lineno, line in enumerate(text.splitlines(), 1):
        if matcher is not None:
            from_name = _find_term(matcher, line)
            if from_name:
                findings.append(Finding("ERROR", "private-name-derived", rel, lineno, f"contains a term taken from a meeting/file name ({from_name!r})"))
        if EMAIL_RE.search(line):
            findings.append(Finding("ERROR", "email-address", rel, lineno, "email address found in tracked text"))
        if USER_PATH_RE.search(line):
            findings.append(Finding("ERROR", "absolute-user-path", rel, lineno, "absolute /Users/<name> path found"))
        if CREATED_BY_RE.search(line):
            findings.append(Finding("WARN", "personal-file-header", rel, lineno, "personal 'Created by' header found"))

        for literal in literals:
            if literal.casefold() in line.casefold():
                findings.append(Finding("ERROR", "private-denylist", rel, lineno, f"matches a private sensitive literal ({literal!r})"))

        for match in BUNDLE_ID_RE.finditer(line):
            bundle_id = match.group(1)
            if prefixes and not bundle_id.startswith(prefixes):
                findings.append(Finding("WARN", "bundle-identifier-review", rel, lineno, f"review bundle identifier {bundle_id!r} before public release"))

        for match in DEVELOPMENT_TEAM_RE.finditer(line):
            team_id = match.group(1).strip()
            if team_id:
                findings.append(Finding("WARN", "xcode-development-team", rel, lineno, "non-empty Xcode DEVELOPMENT_TEAM identifier should be stripped from public release"))

        for match in PROVISIONING_PROFILE_RE.finditer(line):
            profile = match.group(1).strip()
            if profile:
                findings.append(Finding("WARN", "xcode-provisioning-profile", rel, lineno, "Xcode provisioning profile metadata should be stripped from public release"))

    return findings


def audit(root: Path = ROOT, config_path: Path = LOCAL_CONFIG) -> list[Finding]:
    files = tracked_files(root)
    config = load_private_config(config_path)
    derived = load_derived_terms(config_path, root)
    config["derived_matcher"] = _build_matcher(derived)
    try:
        config["derived_allow_paths"] = set(json.loads(Path(config_path).read_text()).get("derived_allow_paths", []))
    except Exception:
        config["derived_allow_paths"] = set()
    findings = audit_paths(files, config)
    for path in files:
        if path.exists() and is_text_candidate(path):
            findings.extend(audit_text(path, config))
    return findings


def scan_history(repo: Path, config_path: Path) -> int:
    """Scan every file version and commit message in a repo's whole history for private terms."""
    config = load_private_config(config_path)
    matcher = _build_matcher(load_derived_terms(config_path, ROOT))
    literals = [x.casefold() for x in config["sensitive_literals"]]
    try:
        allowed_paths = set(json.loads(Path(config_path).read_text()).get("derived_allow_paths", []))
    except Exception:
        allowed_paths = set()

    def hit_in(text: str):
        if matcher is not None:
            found = _find_term(matcher, text)
            if found:
                return found
        folded = text.casefold()
        return next((lit for lit in literals if lit in folded), None)

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)

    commits = git("rev-list", "--all").decode().split()
    problems = 0
    for sha in commits:
        message = git("show", "-s", "--format=%B", sha).decode(errors="ignore")
        found = hit_in(message)
        if found:
            problems += 1
            print(f"commit {sha[:8]} message: contains {found!r}")
    seen: set[str] = set()
    for line in git("rev-list", "--all", "--objects").decode(errors="ignore").splitlines():
        blob, _, name = line.partition(" ")
        if not name or blob in seen:
            continue
        seen.add(blob)
        if git("cat-file", "-t", blob).strip() != b"blob":
            continue
        size = int(git("cat-file", "-s", blob))
        if name in allowed_paths:
            continue  # e.g. LICENSE, which is allowed to carry the owner's name
        found = hit_in(name)
        if not found and size <= 2_000_000:
            data = git("cat-file", "-p", blob)
            if b"\0" not in data[:4096]:
                found = hit_in(data.decode("utf-8", errors="ignore"))
        if found:
            problems += 1
            print(f"{name}: a past version contains {found!r}")
    print(f"History scan: {len(commits)} commit(s), {len(seen)} distinct file version(s), {problems} problem(s).")
    return 1 if problems else 0


def derived_report(root: Path, config_path: Path) -> int:
    """Show every derived term with the tracked files it appears in, for triage."""
    terms = sorted(load_derived_terms(config_path, root))
    files = [p for p in tracked_files(root) if p.exists()]
    texts = {}
    for path in files:
        if is_text_candidate(path):
            try:
                texts[relative(path)] = path.read_text(errors="strict")
            except (UnicodeDecodeError, OSError):
                pass
    clean, hits = [], []
    for term in terms:
        matcher = _build_matcher([term])
        where = [rel for rel, text in texts.items() if _find_term(matcher, text) or _find_term(matcher, rel)]
        (hits if where else clean).append((term, where))
    print(f"{len(terms)} terms derived from meeting/file names.")
    print(f"\n{len(clean)} appear nowhere in tracked files (good, nothing to do).")
    print(f"\n{len(hits)} appear in tracked files (each one is an ERROR in the audit until fixed or allowed):")
    for term, where in hits:
        shown = ", ".join(where[:3]) + (f" (+{len(where) - 3} more)" if len(where) > 3 else "")
        print(f"  {term}: {len(where)} file(s): {shown}")
    print('\nIf a term is a harmless everyday word, add it to "derived_allow" in release_audit.local.json.')
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit tracked files for public-release privacy risks.")
    parser.add_argument("--config", type=Path, default=LOCAL_CONFIG, help="private local denylist/config JSON")
    parser.add_argument("--strict-warnings", action="store_true", help="treat warnings as failures")
    parser.add_argument("--scan-history", type=Path, metavar="REPO",
                        help="scan a git repo's entire history for private terms (use on the public repo)")
    parser.add_argument("--derived-report", action="store_true",
                        help="list terms taken from meeting/file names and where each one appears (no failure)")
    args = parser.parse_args(argv)

    if args.scan_history:
        return scan_history(args.scan_history.expanduser(), args.config)
    if args.derived_report:
        return derived_report(ROOT, args.config)

    findings = audit(ROOT, args.config)
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARN"]

    if findings:
        for finding in findings:
            print(finding.render())
    else:
        print("Release audit: no findings.")

    print(f"Release audit summary: {len(errors)} error(s), {len(warnings)} warning(s).")
    if any(f.code == "private-name-derived" for f in errors):
        print("Some errors are words taken from meeting names. Review them with: tools/mt audit-words")
    if errors or (args.strict_warnings and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
