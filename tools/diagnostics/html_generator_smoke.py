"""Legacy manual smoke test. Safe to import during unittest discovery."""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))



def main():
    from pathlib import Path

    import markdown

    from html_generator import (
        build_summary_html,
        build_transcript_html,
    )

    test_dir = Path("output/html_test")
    test_dir.mkdir(parents=True, exist_ok=True)

    summary_markdown = """
    # Meeting Summary

    ## Executive Summary

    This is a test summary.

    ## Action Items

    - Owner – Test the HTML generator.
    """

    summary_html = markdown.markdown(summary_markdown)

    transcript_html = """
    <div class="speaker">[00:00] Remote</div>
    <p class="speech">This is a test transcript entry.</p>

    <div class="speaker">[00:05] Mic</div>
    <p class="speech">The HTML module is working.</p>
    """

    transcript_document = build_transcript_html(
        summary_html=summary_html,
        transcript_html=transcript_html,
    )

    summary_document = build_summary_html(
        summary_html=summary_html,
    )

    (test_dir / "meeting_transcript.html").write_text(
        transcript_document,
        encoding="utf-8",
    )

    (test_dir / "meeting_summary.html").write_text(
        summary_document,
        encoding="utf-8",
    )

    print(f"Created test files in: {test_dir}")


if __name__ == "__main__":
    main()
