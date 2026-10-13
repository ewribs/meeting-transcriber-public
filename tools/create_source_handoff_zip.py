#!/usr/bin/env python3
"""Create a local, privacy-conscious SOURCE-ONLY zip of the project.

Run from anywhere:  python tools/create_source_handoff_zip.py
Add --show-matches to print, on YOUR screen only, which private values were
found in which files (so you can judge real hits from common words).
The zip is written to the dist/ folder.

What it includes
  * every git-tracked source file (current working-tree contents)
  * UNTRACKED source files (.py/.swift/.sh/.md) in the allowed folders, so new
    work that has not been committed yet is not silently left out. They are
    listed separately in the manifest.

What it never includes
  * meeting data, recordings, transcripts, memory traces, benchmark output
  * private config (*.local.json), logs, backups, archives, virtual envs
  * experiment folders (phase15-*), private_benchmarks*, one-off apply_* scripts

It also scans the included text for any value found in your private
identity/business-context files and warns (file names only) if one appears.
You must still review the zip before sharing it anywhere.
"""
from pathlib import Path
import argparse
import datetime
import fnmatch
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PREFIXES = (
    "meetings/", "output/", "benchmark_runs", "private_benchmarks", "logs/",
    "prompts/", "recordings/", ".venv/", "venv/", "__pycache__/", ".git/",
    "build/", "dist/", "DerivedData/", "private/", "tmp/", "temp/",
    "archive/", "archives/", "OneNote_Import/", "phase15-",
)

# Matched against the file NAME. Transcript patterns are deliberately narrow:
# a broad "*transcript*" also hides real code such as transcription_queue.py.
SENSITIVE_NAMES = (
    "*.local.json", "*.bak", "*.log", "*.m4a", "*.wav", "*.mp3", "*.mp4",
    "*.vtt", "*.sqlite", "*.db", "*.env", "*.key", "*.pem", "*.p12", "*.pfx",
    "*.zip", ".DS_Store",
    "*transcript*.md", "*transcript*.html", "*transcript*.txt", "*transcript*.json",
    "*memory_trace*.json", "*meeting_memory*.json", "*actual_memory*.json",
    "*meeting_summary*.md", "*meeting_summary*.html", "benchmark_result*.json",
    "benchmark_report*.md", "processing_runtime*.json", "meeting_metadata*.json",
)

SAFE_ROOT_FILES = {p.name for p in ROOT.glob("*.py")} | {
    "README.md", "requirements.txt", ".gitignore", "LICENSE",
    "public_release_preserve.txt",
}
SAFE_ROOT_PATTERNS = ("*.example.json",)
SAFE_PREFIXES = ("query/", "swift/", "tests/", "tools/", "docs/", "legacy/qt/")
UNTRACKED_SUFFIXES = (".py", ".swift", ".sh", ".md")
TEXT_SUFFIXES = (".py", ".swift", ".sh", ".md", ".txt", ".json", ".plist",
                 ".pbxproj", ".entitlements", ".zsh", ".yml", ".yaml")


def git_list(*args):
    out = subprocess.check_output(["git", *args, "-z"], cwd=ROOT).decode()
    return [item for item in out.split("\0") if item]


def decide(rel, untracked):
    """Return (include, reason)."""
    name = Path(rel).name
    if any(rel.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False, "excluded folder"
    if any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_NAMES):
        return False, "sensitive file pattern"
    if "/" not in rel:
        allowed = rel in SAFE_ROOT_FILES or any(
            fnmatch.fnmatch(name, pattern) for pattern in SAFE_ROOT_PATTERNS
        )
        if not allowed:
            return False, "root file not allowlisted"
    elif not rel.startswith(SAFE_PREFIXES):
        return False, "folder not allowlisted"
    if untracked:
        if not rel.endswith(UNTRACKED_SUFFIXES):
            return False, "untracked and not a source file type"
        if name.startswith("apply_"):
            return False, "untracked one-off patch script"
    if not (ROOT / rel).is_file():
        return False, "not a file"
    return True, ""


def private_values():
    """Map each private string to the config file it came from."""
    values = {}

    def walk(node, source):
        if isinstance(node, str):
            if len(node.strip()) >= 4:
                values.setdefault(node.strip(), source)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item, source)
        elif isinstance(node, list):
            for item in node:
                walk(item, source)

    for name in ("identity.local.json", "business_context.local.json",
                 "known_people.local.json", "known_people.json"):
        path = ROOT / name
        if path.is_file():
            try:
                walk(json.loads(path.read_text(encoding="utf-8")), name)
            except (OSError, ValueError):
                pass
    return values


def main():
    parser = argparse.ArgumentParser(description="Create a source-only handoff zip in dist/.")
    parser.add_argument("--show-matches", action="store_true",
                        help="print which private values matched in which files (local screen only)")
    args = parser.parse_args()

    tracked = git_list("ls-files")
    untracked = git_list("ls-files", "--others", "--exclude-standard")

    chosen, chosen_untracked, skipped = [], [], []
    for rel in tracked:
        ok, why = decide(rel, untracked=False)
        (chosen if ok else skipped).append(rel if ok else (rel, why))
    for rel in untracked:
        ok, why = decide(rel, untracked=True)
        if ok:
            chosen_untracked.append(rel)
        elif rel.startswith(SAFE_PREFIXES) or "/" not in rel:
            # Only report skipped untracked files that sit in code locations;
            # everything else (logs, backups, experiment folders) is noise.
            skipped.append((rel, f"UNTRACKED: {why}"))

    everything = chosen + chosen_untracked

    # Leak scan. By default only file names are printed.
    secrets = private_values()
    flagged = {}
    if secrets:
        for rel in everything:
            if not rel.endswith(TEXT_SUFFIXES):
                continue
            try:
                body = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hits = sorted(value for value in secrets if value in body)
            if hits:
                flagged[rel] = hits

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"meeting-transcriber-source-handoff-{stamp}.zip"
    manifest = [
        "Source snapshot. Tracked files plus allowed untracked source files.",
        "",
        f"Tracked files included: {len(chosen)}",
        *chosen,
        "",
        f"UNTRACKED source files included: {len(chosen_untracked)}",
        *chosen_untracked,
        "",
        "Skipped:",
        *(f"{rel}: {why}" for rel, why in skipped),
    ]
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in everything:
            archive.write(ROOT / rel, arcname=rel)
        archive.writestr("HANDOFF_SOURCE_MANIFEST.txt", "\n".join(manifest) + "\n")

    print(f"Created: {out}")
    print(f"Tracked: {len(chosen)}   Untracked included: {len(chosen_untracked)}   Skipped: {len(skipped)}")
    if chosen_untracked:
        print("\nUntracked source files included (commit these if they are real code):")
        for rel in chosen_untracked:
            print(f"  {rel}")
    if flagged:
        print(f"\nWARNING: {len(flagged)} included files contain values from your private config files:")
        for rel, hits in flagged.items():
            print(f"  {rel}  ({len(hits)} value{'s' if len(hits) != 1 else ''})")
        if args.show_matches:
            print("\nMatched values (shown on this screen only; do not paste them anywhere):")
            for rel, hits in flagged.items():
                print(f"  {rel}")
                for value in hits:
                    print(f"      {value!r}  <- from {secrets[value]}")
        else:
            print("Run again with --show-matches to see what matched. Short or common")
            print("words can match harmlessly; real names or companies should be removed.")
    elif secrets:
        print("\nPrivate-value scan: no matches in included text files.")
    else:
        print("\nNo private config files found to scan against.")
    print(f"\nReview before sharing:  unzip -Z1 'dist/{out.name}' | less")


if __name__ == "__main__":
    main()
