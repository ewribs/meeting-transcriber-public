#!/usr/bin/env python3
"""Build a fresh-history-ready public release archive from the current Git HEAD.

The export contains only files tracked by Git, strips private/per-user state,
rewrites bundle identifiers to a public-safe namespace, and runs release audits
before and after export.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBXPROJ = Path("swift/Meeting Transcriber/Meeting Transcriber.xcodeproj/project.pbxproj")
PRIVATE_AUDIT_DOC = Path("docs/PUBLIC_RELEASE_AUDIT.md")
BUNDLE_RE = re.compile(r'(PRODUCT_BUNDLE_IDENTIFIER\s*=\s*")([^"]+)(";)')
DEVELOPMENT_TEAM_RE = re.compile(r'(DEVELOPMENT_TEAM\s*=\s*)([^;]*)(;)')
PROVISIONING_PROFILE_RE = re.compile(r'(PROVISIONING_PROFILE_SPECIFIER\s*=\s*)([^;]*)(;)')

PRIVATE_STATE_FILES = (
    "identity.local.json",
    "business_context.local.json",
    "known_people.json",
    "known_people.local.json",
    "release_audit.local.json",
)


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def extract_zip_preserving_permissions(
    archive: Path,
    destination: Path,
) -> None:
    """Extract a ZIP while restoring Unix permission bits.

    Python's ZipFile.extractall() does not reliably restore executable bits.
    Git archives preserve those bits in ZipInfo.external_attr, so restore them
    explicitly after extraction. This keeps executable setup/tools executable
    in the sanitized public release instead of silently flattening them to 0644.
    """
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            extracted = Path(zf.extract(info, destination))

            if not extracted.exists() or extracted.is_symlink():
                continue

            mode = (info.external_attr >> 16) & 0o7777
            if mode:
                extracted.chmod(mode)


def public_bundle_id(original: str, prefix: str) -> str:
    if original.endswith("UITests"):
        return f"{prefix}.MeetingTranscriberUITests"
    if original.endswith("Tests"):
        return f"{prefix}.MeetingTranscriberTests"
    return f"{prefix}.MeetingTranscriber"


def rewrite_bundle_ids(tree: Path, prefix: str) -> None:
    path = tree / PBXPROJ
    text = path.read_text()
    text = BUNDLE_RE.sub(
        lambda m: f"{m.group(1)}{public_bundle_id(m.group(2), prefix)}{m.group(3)}",
        text,
    )
    path.write_text(text)


def scrub_xcode_signing_metadata(tree: Path) -> None:
    """Remove developer-account identifiers from the exported Xcode project."""

    path = tree / PBXPROJ
    if not path.exists():
        return
    text = path.read_text()
    text = DEVELOPMENT_TEAM_RE.sub(lambda m: f'{m.group(1)}""{m.group(3)}', text)
    text = PROVISIONING_PROFILE_RE.sub(lambda m: f'{m.group(1)}""{m.group(3)}', text)
    path.write_text(text)


def remove_private_release_state(tree: Path) -> None:
    for name in PRIVATE_STATE_FILES:
        candidate = tree / name
        if candidate.exists():
            candidate.unlink()

    private_audit = tree / PRIVATE_AUDIT_DOC
    private_audit.unlink(missing_ok=True)

    internal_docs = tree / "docs" / "internal"
    if internal_docs.exists():
        shutil.rmtree(internal_docs)

    for path in list(tree.rglob("xcuserdata")):
        if path.is_dir():
            shutil.rmtree(path)

    for path in list(tree.rglob("*.xcuserstate")):
        path.unlink(missing_ok=True)


def zip_tree(tree: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(tree.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(tree))


def run_private_release_audit() -> None:
    audit = ROOT / "tools" / "release_audit.py"

    print("Running private release audit...")
    run([sys.executable, str(audit)], ROOT)


def run_export_release_audit(tree: Path, bundle_prefix: str) -> None:
    audit = tree / "tools" / "release_audit.py"
    audit_config = tree / ".release_audit_export.json"

    audit_config.write_text(
        "\n".join(
            [
                "{",
                '  "sensitive_literals": [],',
                (
                    '  "allowed_bundle_prefixes": '
                    f'["{bundle_prefix}.", "com.example.", "org.example."]'
                ),
                "}",
                "",
            ]
        )
    )

    try:
        print("Running exported-tree release audit...")
        run(
            [
                sys.executable,
                str(audit),
                "--config",
                str(audit_config),
                "--strict-warnings",
            ],
            tree,
        )
    finally:
        audit_config.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build sanitized public-release ZIP from Git HEAD."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "meeting-transcriber-public.zip",
    )
    parser.add_argument(
        "--bundle-prefix",
        default="org.example.meetingtranscriber",
    )
    args = parser.parse_args(argv)

    status = subprocess.check_output(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
    )

    if status.strip():
        raise SystemExit(
            "Working tree is not clean. Commit or stash changes before exporting."
        )

    run_private_release_audit()

    with tempfile.TemporaryDirectory(
        prefix="meeting-transcriber-public-"
    ) as tmp:
        tree = Path(tmp) / "repo"
        tree.mkdir()

        archive = Path(tmp) / "head.zip"

        run(
            [
                "git",
                "archive",
                "--format=zip",
                f"--output={archive}",
                "HEAD",
            ],
            ROOT,
        )

        extract_zip_preserving_permissions(
            archive,
            tree,
        )

        remove_private_release_state(tree)
        rewrite_bundle_ids(tree, args.bundle_prefix)
        scrub_xcode_signing_metadata(tree)
        run_export_release_audit(tree, args.bundle_prefix)

        output = args.output.expanduser().resolve()
        zip_tree(tree, output)

    print(f"Public release archive created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
