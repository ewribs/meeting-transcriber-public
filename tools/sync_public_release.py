#!/usr/bin/env python3
"""Safely synchronize a sanitized private release into the public repository.

The private repository remains the development source of truth. This tool:

1. Requires clean private and public working trees.
2. Builds a sanitized release from committed private HEAD.
3. Validates the candidate with the release audit and full Python test suite.
4. Preserves explicitly public-only files/directories.
5. Excludes transient Python/macOS artifacts.
6. Performs a dry run by default.
7. Modifies the public repository only when --apply is supplied.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRESERVE_FILE = ROOT / "public_release_preserve.txt"

ALWAYS_PRESERVE = (
    ".git/",
)

TRANSIENT_EXCLUDES = (
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
)


def run(
    cmd: list[str],
    cwd: Path,
    *,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def require_clean_repo(path: Path, label: str) -> None:
    result = run(
        ["git", "status", "--porcelain"],
        path,
        capture=True,
    )

    if result.stdout.strip():
        raise SystemExit(
            f"{label} repository is not clean:\n"
            f"{result.stdout}\n"
            "Commit, stash, or discard those changes before continuing."
        )


def load_preserve_rules() -> list[str]:
    if not PRESERVE_FILE.exists():
        raise SystemExit(
            f"Missing preservation file: {PRESERVE_FILE}"
        )

    rules: list[str] = []

    for raw_line in PRESERVE_FILE.read_text().splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        rules.append(line)

    return rules


def clean_transient_artifacts(tree: Path) -> None:
    for path in list(tree.rglob("__pycache__")):
        if path.is_dir():
            shutil.rmtree(path)

    for pattern in ("*.pyc", "*.pyo", ".DS_Store"):
        for path in list(tree.rglob(pattern)):
            if path.is_file():
                path.unlink()


def validate_candidate(tree: Path) -> None:
    print("\nValidating sanitized candidate...")

    run(
        [sys.executable, "tools/release_audit.py"],
        tree,
    )

    run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
        ],
        tree,
    )

    clean_transient_artifacts(tree)


def rsync_candidate(
    candidate: Path,
    public_repo: Path,
    preserve_rules: list[str],
    *,
    apply: bool,
) -> None:
    if shutil.which("rsync") is None:
        raise SystemExit("rsync is required but was not found.")

    cmd = [
        "rsync",
        "-rlpc",
        "--checksum",
        "--delete",
        "--itemize-changes",
    ]

    if not apply:
        cmd.append("--dry-run")

    for rule in ALWAYS_PRESERVE:
        cmd.append(f"--exclude={rule}")

    for rule in preserve_rules:
        cmd.append(f"--exclude={rule}")

    for rule in TRANSIENT_EXCLUDES:
        cmd.append(f"--exclude={rule}")

    cmd.extend(
        [
            f"{candidate}/",
            f"{public_repo}/",
        ]
    )

    mode = "APPLY" if apply else "DRY RUN"
    print(f"\nPublic synchronization: {mode}")
    print(f"Private source: {ROOT}")
    print(f"Public target:  {public_repo}")
    print()

    result = run(cmd, ROOT, capture=True)

    for line in result.stdout.splitlines():
        # Suppress rsync metadata-only timestamp noise such as:
        # .f..T.... path/to/file
        if line.startswith(".f..T.... "):
            continue

        print(line)


def validate_public_repo(public_repo: Path) -> None:
    print("\nValidating synchronized public repository...")

    run(
        [sys.executable, "tools/release_audit.py"],
        public_repo,
    )

    run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_*.py",
        ],
        public_repo,
    )

    clean_transient_artifacts(public_repo)

    print("\nPublic repository status:")
    run(["git", "status", "--short"], public_repo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely sync sanitized private HEAD to the public repository."
    )

    parser.add_argument(
        "--public-repo",
        type=Path,
        default=Path.home() / "Projects" / "meeting-transcriber-public",
        help="Path to the public Git repository.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually modify the public repository. Default is dry run.",
    )

    args = parser.parse_args(argv)

    public_repo = args.public_repo.expanduser().resolve()

    if not (public_repo / ".git").exists():
        raise SystemExit(
            f"Public repository does not appear to be a Git checkout: "
            f"{public_repo}"
        )

    require_clean_repo(ROOT, "Private")
    require_clean_repo(public_repo, "Public")

    preserve_rules = load_preserve_rules()

    with tempfile.TemporaryDirectory(
        prefix="meeting-transcriber-public-sync-"
    ) as tmp:
        temp_root = Path(tmp)
        archive = temp_root / "public-release.zip"
        candidate = temp_root / "candidate"

        print("Building sanitized public release...")

        run(
            [
                sys.executable,
                "tools/build_public_release.py",
                "--output",
                str(archive),
                "--bundle-prefix",
                "org.example.meetingtranscriber",
            ],
            ROOT,
        )

        candidate.mkdir()

        with zipfile.ZipFile(archive) as zf:
            zf.extractall(candidate)

        validate_candidate(candidate)

        rsync_candidate(
            candidate,
            public_repo,
            preserve_rules,
            apply=args.apply,
        )

    if args.apply:
        validate_public_repo(public_repo)

        print(
            "\nSynchronization complete. Review the public Git diff "
            "before committing."
        )
    else:
        print(
            "\nDry run complete. No public files were changed.\n"
            "Review the rsync output above. If it is correct, rerun with --apply."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
