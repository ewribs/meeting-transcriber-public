#!/usr/bin/env python3
"""Build a fresh-history-ready public release archive from the current Git HEAD.

The export contains only files tracked by Git, strips per-user Xcode state,
rewrites bundle identifiers to a public-safe namespace, and runs the release
audit against the exported tree before producing a ZIP.
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
PBXPROJ = Path('swift/Meeting Transcriber/Meeting Transcriber.xcodeproj/project.pbxproj')
BUNDLE_RE = re.compile(r'(PRODUCT_BUNDLE_IDENTIFIER\s*=\s*")([^"]+)(";)')


def run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def public_bundle_id(original: str, prefix: str) -> str:
    if original.endswith('UITests'):
        return f'{prefix}.MeetingTranscriberUITests'
    if original.endswith('Tests'):
        return f'{prefix}.MeetingTranscriberTests'
    return f'{prefix}.MeetingTranscriber'


def rewrite_bundle_ids(tree: Path, prefix: str) -> None:
    path = tree / PBXPROJ
    text = path.read_text()
    text = BUNDLE_RE.sub(lambda m: f'{m.group(1)}{public_bundle_id(m.group(2), prefix)}{m.group(3)}', text)
    path.write_text(text)


def remove_private_release_state(tree: Path) -> None:
    for name in ('identity.local.json', 'business_context.local.json', 'known_people.json',
                 'known_people.local.json', 'release_audit.local.json'):
        candidate = tree / name
        if candidate.exists():
            candidate.unlink()
    for path in list(tree.rglob('xcuserdata')):
        if path.is_dir():
            shutil.rmtree(path)
    for path in list(tree.rglob('*.xcuserstate')):
        path.unlink(missing_ok=True)


def zip_tree(tree: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(tree.rglob('*')):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(tree))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Build sanitized public-release ZIP from Git HEAD.')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'meeting-transcriber-public.zip')
    parser.add_argument('--bundle-prefix', default='org.example.meetingtranscriber')
    args = parser.parse_args(argv)

    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    if status.strip():
        raise SystemExit('Working tree is not clean. Commit or stash changes before exporting.')

    with tempfile.TemporaryDirectory(prefix='meeting-transcriber-public-') as tmp:
        tree = Path(tmp) / 'repo'
        tree.mkdir()
        archive = Path(tmp) / 'head.zip'
        run(['git', 'archive', '--format=zip', f'--output={archive}', 'HEAD'], ROOT)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(tree)

        remove_private_release_state(tree)
        rewrite_bundle_ids(tree, args.bundle_prefix)

        audit = tree / 'tools' / 'release_audit.py'
        audit_config = tree / '.release_audit_export.json'
        audit_config.write_text('\n'.join([
            '{',
            '  \"sensitive_literals\": [],',
            f'  \"allowed_bundle_prefixes\": [\"{args.bundle_prefix}.\", \"com.example.\", \"org.example.\"]',
            '}',
            '',
        ]))
        try:
            run([sys.executable, str(audit), '--config', str(audit_config), '--strict-warnings'], tree)
        finally:
            audit_config.unlink(missing_ok=True)
        zip_tree(tree, args.output.expanduser().resolve())

    print(f'Public release archive created: {args.output.expanduser().resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
