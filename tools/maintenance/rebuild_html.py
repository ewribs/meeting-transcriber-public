
# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pathlib import Path

import markdown

from html_generator import (
    build_summary_html,
    build_transcript_html,
)


run_dir = Path(
    "output/2026-08-05_1419_BrianK1v1080426"
)

summary_markdown = (
    run_dir / "meeting_summary.md"
).read_text(encoding="utf-8")

transcript_markdown = (
    run_dir / "meeting_transcript.md"
).read_text(encoding="utf-8")

summary_html = markdown.markdown(summary_markdown)
transcript_html = markdown.markdown(transcript_markdown)

transcript_document = build_transcript_html(
    summary_html=summary_html,
    transcript_html=transcript_html,
)

summary_document = build_summary_html(
    summary_html=summary_html,
)

transcript_html_path = (
    run_dir / "meeting_transcript.html"
)

summary_html_path = (
    run_dir / "meeting_summary.html"
)

transcript_html_path.write_text(
    transcript_document,
    encoding="utf-8",
)

summary_html_path.write_text(
    summary_document,
    encoding="utf-8",
)

print(f"HTML transcript rebuilt: {transcript_html_path}")
print(f"HTML summary rebuilt: {summary_html_path}")
