"""
Shared processing pipeline for Meeting Transcriber.

Both transcribe.py and recovery.py call these functions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ai import (
    clean_transcript_in_chunks,
    summarize_meeting_hardware_aware,
    extract_participants,
    build_complete_meeting_memory,
    compose_summary_with_meeting_memory,
)

from config import (
    WHISPER_CHUNK_MINUTES,
    WHISPER_MODEL,
)

from html_generator import (
    build_summary_html,
    build_transcript_html,
    build_onenote_html,
)

from metadata import (
    create_meeting_metadata,
    update_meeting_participants,
)

import json
import markdown


def write_html_outputs(
    run_dir: Path,
    summary_html: str,
    transcript_html: str,
) -> tuple[Path, Path]:
    """
    Write the combined transcript HTML and standalone summary HTML.

    Returns:
        A tuple containing:
        - transcript HTML path
        - summary HTML path
    """

    transcript_document = build_transcript_html(
        summary_html=summary_html,
        transcript_html=transcript_html,
    )

    transcript_html_path = run_dir / "meeting_transcript.html"

    transcript_html_path.write_text(
        transcript_document,
        encoding="utf-8",
    )

    summary_document = build_summary_html(
        summary_html=summary_html,
    )

    summary_html_path = run_dir / "meeting_summary.html"

    summary_html_path.write_text(
        summary_document,
        encoding="utf-8",
    )

    return transcript_html_path, summary_html_path


def run_ai_cleanup(
    run_dir: Path,
    transcript: str | None = None,
) -> tuple[str, Path]:
    """
    Clean a meeting transcript with the local LLM and save the result.

    If transcript text is not provided, read meeting_transcript.md
    from the supplied run directory.

    Returns:
        A tuple containing:
        - cleaned transcript text
        - cleaned transcript path
    """

    transcript_path = run_dir / "meeting_transcript.md"

    if transcript is None:
        if not transcript_path.exists():
            raise FileNotFoundError(
                f"Raw transcript not found: {transcript_path}"
            )

        transcript = transcript_path.read_text(
            encoding="utf-8",
        )

    cleaned_transcript = clean_transcript_in_chunks(
        transcript,
    )

    cleaned_path = (
        run_dir / "meeting_transcript_cleaned.md"
    )

    cleaned_path.write_text(
        cleaned_transcript,
        encoding="utf-8",
    )

    return cleaned_transcript, cleaned_path


def run_participant_extraction(
    run_dir: Path,
    cleaned_transcript: str | None = None,
) -> list[dict]:
    """
    Extract explicitly named participants from a cleaned transcript.
    """

    cleaned_path = (
        run_dir / "meeting_transcript_cleaned.md"
    )

    if cleaned_transcript is None:
        if not cleaned_path.exists():
            raise FileNotFoundError(
                f"Cleaned transcript not found: {cleaned_path}"
            )

        cleaned_transcript = cleaned_path.read_text(
            encoding="utf-8",
        )

    try:
        return extract_participants(
            cleaned_transcript,
            meeting_context=run_dir.name,
        )

    except Exception as error:
        print()
        print("WARNING: Participant extraction failed.")
        print(f"Reason: {error}")
        print("Using empty participant list.")

        return []


def run_meeting_memory(
    run_dir: Path,
    meeting_summary: str,
    cleaned_transcript: str,
    participants: list[dict] | None = None,
) -> Path:
    """
    Build and save structured meeting memory.
    """

    memory = build_complete_meeting_memory(
        meeting_label=run_dir.name,
        meeting_summary=meeting_summary,
        transcript=cleaned_transcript,
        participants=participants,
    )

    memory_path = (
        run_dir / "meeting_memory.json"
    )

    import json

    memory_path.write_text(
        json.dumps(
            memory,
            indent=2,
        ),
        encoding="utf-8",
    )

    return memory_path


def apply_structured_summary_composition(
    run_dir: Path,
    meeting_summary: str,
    memory_path: Path,
) -> tuple[str, str]:
    """Replace precision-sensitive summary sections from meeting memory."""

    memory = json.loads(
        memory_path.read_text(encoding="utf-8")
    )
    composed_summary = compose_summary_with_meeting_memory(
        meeting_summary,
        memory,
    )
    (run_dir / "meeting_summary.md").write_text(
        composed_summary,
        encoding="utf-8",
    )
    return composed_summary, markdown.markdown(composed_summary)


def run_meeting_summary(
    run_dir: Path,
    cleaned_transcript: str | None = None,
) -> tuple[str, str, Path, Path]:
    """
    Generate a meeting summary and its HTML representation.

    Returns:
        (
            meeting_summary_markdown,
            meeting_summary_html,
            summary_markdown_path,
            summary_html_path,
        )
    """

    cleaned_path = run_dir / "meeting_transcript_cleaned.md"

    if cleaned_transcript is None:
        if not cleaned_path.exists():
            raise FileNotFoundError(
                f"Cleaned transcript not found: {cleaned_path}"
            )

        cleaned_transcript = cleaned_path.read_text(
            encoding="utf-8",
        )

    meeting_summary, execution_metadata = (
        summarize_meeting_hardware_aware(
            cleaned_transcript,
        )
    )

    whisper_name = WHISPER_MODEL.stem
    if whisper_name.startswith("ggml-"):
        whisper_name = whisper_name[len("ggml-"):]

    processing_metadata = {
        **execution_metadata,
        "whisper_model": whisper_name,
        "whisper_chunk_minutes": WHISPER_CHUNK_MINUTES,
    }

    (run_dir / "processing_runtime.json").write_text(
        json.dumps(
            processing_metadata,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary_path = run_dir / "meeting_summary.md"

    summary_path.write_text(
        meeting_summary,
        encoding="utf-8",
    )

    summary_html = markdown.markdown(
        meeting_summary
    )

    summary_document = build_summary_html(
        summary_html=summary_html,
    )

    summary_html_path = (
        run_dir / "meeting_summary.html"
    )

    summary_html_path.write_text(
        summary_document,
        encoding="utf-8",
    )

    return (
        meeting_summary,
        summary_html,
        summary_path,
        summary_html_path,
    )


def export_onenote_summary(
    run_dir: Path,
) -> Path:
    """
    Create a standalone HTML summary intended for copying
    into OneNote.
    """

    summary_path = run_dir / "meeting_summary.md"

    if not summary_path.exists():
        raise FileNotFoundError(
            f"Meeting summary not found: {summary_path}"
        )

    summary_markdown = summary_path.read_text(
        encoding="utf-8",
    )

    summary_html = markdown.markdown(
        summary_markdown,
    )

    meeting_title = run_dir.name.replace("_", " ")

    onenote_document = build_onenote_html(
        meeting_title=meeting_title,
        summary_html=summary_html,
        source_reference=str(run_dir),
    )

    export_dir = run_dir / "exports"

    export_dir.mkdir(
        exist_ok=True,
    )

    output_filename = f"OneNote_{run_dir.name}.html"

    output_path = export_dir / output_filename

    output_path.write_text(
        onenote_document,
        encoding="utf-8",
    )

    return output_path


def complete_post_summary_artifacts(
    run_dir: Path,
    meeting_summary: str,
    cleaned_transcript: str,
    transcript_html: str,
    source_path: Path | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict:
    """Complete artifacts that depend on an existing transcript and summary.

    Metadata is deliberately initialized before participant extraction and
    structured-memory composition.  A final metadata refresh records the
    completed export while preserving the participants written in between.
    """

    def report(message: str, percent: int) -> None:
        if progress_callback is not None:
            progress_callback(message, percent)

    report("Creating meeting metadata...", 81)
    metadata_path = create_meeting_metadata(
        run_dir=run_dir,
        source_path=source_path,
    )

    report("Identifying meeting participants...", 82)
    participants = run_participant_extraction(
        run_dir=run_dir,
        cleaned_transcript=cleaned_transcript,
    )
    update_meeting_participants(
        run_dir=run_dir,
        participants=participants,
    )

    report("Building meeting memory...", 87)
    memory_path = run_meeting_memory(
        run_dir=run_dir,
        meeting_summary=meeting_summary,
        cleaned_transcript=cleaned_transcript,
        participants=participants,
    )
    meeting_summary, summary_html = (
        apply_structured_summary_composition(
            run_dir=run_dir,
            meeting_summary=meeting_summary,
            memory_path=memory_path,
        )
    )

    report("Generating HTML artifacts...", 91)
    transcript_html_path, summary_html_path = write_html_outputs(
        run_dir=run_dir,
        summary_html=summary_html,
        transcript_html=transcript_html,
    )

    report("Generating OneNote export...", 94)
    onenote_path = export_onenote_summary(
        run_dir=run_dir,
    )

    report("Refreshing meeting metadata...", 97)
    metadata_path = create_meeting_metadata(
        run_dir=run_dir,
        source_path=source_path,
    )

    return {
        "meeting_summary": meeting_summary,
        "summary_html": summary_html,
        "transcript_html_path": transcript_html_path,
        "summary_html_path": summary_html_path,
        "onenote_path": onenote_path,
        "metadata_path": metadata_path,
        "memory_path": memory_path,
        "participants": participants,
    }
