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


def is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name in {"README", "LICENSE", "Makefile"}


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def audit_paths(files: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        rel = relative(path)
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

    for lineno, line in enumerate(text.splitlines(), 1):
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
    findings = audit_paths(files)
    for path in files:
        if path.exists() and is_text_candidate(path):
            findings.extend(audit_text(path, config))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit tracked files for public-release privacy risks.")
    parser.add_argument("--config", type=Path, default=LOCAL_CONFIG, help="private local denylist/config JSON")
    parser.add_argument("--strict-warnings", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)

    findings = audit(ROOT, args.config)
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARN"]

    if findings:
        for finding in findings:
            print(finding.render())
    else:
        print("Release audit: no findings.")

    print(f"Release audit summary: {len(errors)} error(s), {len(warnings)} warning(s).")
    if errors or (args.strict_warnings and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
