from __future__ import annotations

import os
import subprocess
import time

from pathlib import Path
from typing import Callable

from preflight import run_preflight

from datetime import datetime

from config import (
    LOGS_DIR,
    MEETINGS_DIR,
    OUTPUT_DIR,
    WHISPER_CLI,
    WHISPER_MODEL,
    WHISPER_OUTPUT_FORMAT,
    REMOTE_AUDIO,
    MIC_AUDIO,
    WHISPER_CHUNK_MINUTES,
)

from utils import (
    parse_vtt_file,
    merge_transcripts,
    remove_silence_entries,
    merge_adjacent_speakers,
)

from formatter import (
    format_transcript,
    format_transcript_html,
)

from pipeline import (
    run_ai_cleanup,
    run_meeting_summary,
    complete_post_summary_artifacts,
)

def extract_audio_channels(
        meeting_path: Path,
        output_dir: Path,
) -> tuple[Path, Path]:
    """Extract remote and microphone channels from the Zoom recording."""

    remote_path = output_dir / REMOTE_AUDIO
    mic_path = output_dir / MIC_AUDIO

#    print("Extracting remote audio...")
    print("Preparing audio...")
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-i",
            str(meeting_path),
            "-filter_complex",
            "[0:a]pan=mono|c0=c0[out]",
            "-map",
            "[out]",
            str(remote_path),
        ],
        check=True,
    )

#    print("Extracting microphone audio...")
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-i",
            str(meeting_path),
            "-filter_complex",
            "[0:a]pan=mono|c0=c4[out]",
            "-map",
            "[out]",
            str(mic_path),
        ],
        check=True,
    )

    return remote_path, mic_path


def get_audio_duration_ms(audio_path: Path) -> int:
    """
    Return the duration of an audio file in milliseconds.
    """

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    duration_seconds = float(result.stdout.strip())

    return int(duration_seconds * 1000)


def calculate_audio_chunks(
    duration_ms: int,
    chunk_minutes: int,
) -> list[tuple[int, int]]:
    """
    Return audio chunks as (offset_ms, duration_ms) pairs.
    """

    chunk_size_ms = chunk_minutes * 60 * 1000
    chunks = []

    offset_ms = 0

    while offset_ms < duration_ms:
        remaining_ms = duration_ms - offset_ms
        current_duration_ms = min(
            chunk_size_ms,
            remaining_ms,
        )

        chunks.append(
            (
                offset_ms,
                current_duration_ms,
            )
        )

        offset_ms += current_duration_ms

    return chunks


def transcribe_audio_chunk(
    audio_path: Path,
    output_dir,
    offset_ms: int,
    duration_ms: int,
    chunk_number: int,
    total_chunks: int,
) -> Path:

    output_base = (
        output_dir
        / f"{audio_path.stem}_chunk_{chunk_number:02d}"
    )
    transcript_path = output_base.with_suffix(f".{WHISPER_OUTPUT_FORMAT}")

    print(
        f"Chunk {chunk_number}/{total_chunks}"
    )

    subprocess.run(
        [
            str(WHISPER_CLI),
            "-m",
            str(WHISPER_MODEL),
            "-ot",
            str(offset_ms),
            "-d",
            str(duration_ms),
            "-f",
            str(audio_path),
            f"-o{WHISPER_OUTPUT_FORMAT}",
            "-of",
            str(output_base),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not transcript_path.exists():
        raise FileNotFoundError(
            f"Transcript not created: {transcript_path}"
        )

#    print(f"Transcript created: {transcript_path}")
    return transcript_path


def merge_chunk_vtts(
    chunk_transcripts: list[Path],
    merged_transcript: Path,
) -> Path:
    """
    Merge multiple VTT files into one VTT.
    """

    with merged_transcript.open("w", encoding="utf-8") as outfile:

        outfile.write("WEBVTT\n\n")

        for chunk in chunk_transcripts:

            with chunk.open("r", encoding="utf-8") as infile:

                for line in infile:

                    if line.startswith("WEBVTT"):
                        continue

                    outfile.write(line)

    return merged_transcript


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    progress_callback: Callable[[str, int], None] | None = None,
    progress_start: int = 0,
    progress_end: int = 100,
) -> Path:
    """
    Transcribe an audio file in configured chunks,
    then merge the chunk VTT files into one transcript.
    """

    duration_ms = get_audio_duration_ms(audio_path)

    chunks = calculate_audio_chunks(
        duration_ms,
        WHISPER_CHUNK_MINUTES,
    )

    chunk_transcripts = []

    print()
    audio_label = (
        "remote"
        if audio_path.stem == "remote"
        else "microphone"
    )
    print(f"Transcribing {audio_label} audio...")

    for chunk_number, (offset_ms, chunk_duration_ms) in enumerate(
        chunks,
        start=1,
    ):
        chunk_transcript = transcribe_audio_chunk(
            audio_path=audio_path,
            output_dir=output_dir,
            offset_ms=offset_ms,
            duration_ms=chunk_duration_ms,
            chunk_number=chunk_number,
            total_chunks=len(chunks),
        )

        chunk_transcripts.append(chunk_transcript)

        if progress_callback is not None:
            progress_fraction = (
                chunk_number / len(chunks)
            )
            progress_value = int(
                progress_start
                + (
                    progress_end
                    - progress_start
                )
                * progress_fraction
            )
            progress_callback(
                f"Transcribing {audio_label} audio "
                f"({chunk_number}/{len(chunks)})",
                progress_value,
            )

    merged_transcript = (
        output_dir
        / f"{audio_path.stem}.{WHISPER_OUTPUT_FORMAT}"
    )

    merge_chunk_vtts(
        chunk_transcripts,
        merged_transcript,
    )

    print(f"Merged transcript created: {merged_transcript}")

    return merged_transcript


def choose_meeting_file() -> Path:
    recordings = sorted(
        MEETINGS_DIR.glob("*.m4a"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not recordings:
        raise FileNotFoundError(
            f"No .m4a files found in {MEETINGS_DIR}"
        )

    print()
    print("Available recordings:")
    print()

    for i, recording in enumerate(recordings, start=1):
        print(f"  {i}. {recording.name}")

    print()

    while True:
        choice = input("Select recording: ")

        try:
            index = int(choice)

            if 1 <= index <= len(recordings):
                return recordings[index - 1]

        except ValueError:
            pass

        print("Invalid selection.")


def _report_progress(
    progress_callback: Callable[[str, int], None] | None,
    message: str,
    percent: int,
) -> None:
    if progress_callback is not None:
        progress_callback(
            message,
            max(0, min(100, percent)),
        )


def transcribe_meeting(
    meeting_path: Path,
    progress_callback: Callable[[str, int], None] | None = None,
) -> Path:
    """
    Run the complete transcription/AI artifact pipeline for one M4A.

    Returns the generated run directory. The optional progress callback
    receives (message, percent) updates suitable for GUI consumers.
    """
    start_time = time.perf_counter()

    meeting_path = Path(meeting_path)

    _report_progress(
        progress_callback,
        "Running preflight checks...",
        2,
    )
    run_preflight()

    if not meeting_path.exists():
        raise FileNotFoundError(
            f"Meeting file not found: {meeting_path}"
        )

    meeting_stem = meeting_path.stem

    run_name = (
        f"{datetime.now():%Y-%m-%d_%H%M}_"
        f"{meeting_stem}"
    )

    run_dir = OUTPUT_DIR / run_name

    run_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    active_run_file = os.environ.get(
        "MEETING_TRANSCRIBER_ACTIVE_RUN_FILE"
    )


    if active_run_file:


        Path(active_run_file).write_text(


            str(run_dir),


            encoding="utf-8",


        )

    audio_dir = run_dir / "audio"
    transcript_dir = run_dir / "transcript"
    logs_dir = run_dir / "logs"

    audio_dir.mkdir(exist_ok=True)
    transcript_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Meeting Transcriber")
    print("=" * 60)

    _report_progress(
        progress_callback,
        "Preparing audio channels...",
        7,
    )

    remote_audio, mic_audio = extract_audio_channels(
        meeting_path,
        audio_dir,
    )

    remote_duration_ms = get_audio_duration_ms(remote_audio)
    mic_duration_ms = get_audio_duration_ms(mic_audio)

    meeting_duration_seconds = max(
        remote_duration_ms,
        mic_duration_ms,
    ) // 1000

    meeting_minutes = meeting_duration_seconds // 60
    meeting_seconds = meeting_duration_seconds % 60

    print()
    print(
        f"Meeting duration: "
        f"{meeting_minutes}m {meeting_seconds:02d}s"
    )

    remote_chunks = calculate_audio_chunks(
        remote_duration_ms,
        WHISPER_CHUNK_MINUTES,
    )

    mic_chunks = calculate_audio_chunks(
        mic_duration_ms,
        WHISPER_CHUNK_MINUTES,
    )

    print()
    print(
        f"Processing {len(mic_chunks)} transcription chunks."
    )

    _report_progress(
        progress_callback,
        "Transcribing remote audio...",
        12,
    )
    remote_transcript = transcribe_audio(
        remote_audio,
        transcript_dir,
        progress_callback=progress_callback,
        progress_start=12,
        progress_end=36,
    )

    _report_progress(
        progress_callback,
        "Transcribing microphone audio...",
        38,
    )
    mic_transcript = transcribe_audio(
        mic_audio,
        transcript_dir,
        progress_callback=progress_callback,
        progress_start=38,
        progress_end=62,
    )

    _report_progress(
        progress_callback,
        "Merging speaker transcripts...",
        65,
    )

    remote_entries = parse_vtt_file(
        remote_transcript,
        "Remote",
    )

    mic_entries = parse_vtt_file(
        mic_transcript,
        "Mic",
    )

    merged_entries = merge_transcripts(
        remote_entries,
        mic_entries,
    )

    cleaned_entries = remove_silence_entries(
        merged_entries
    )

    final_entries = merge_adjacent_speakers(
        cleaned_entries
    )

    formatted_transcript = format_transcript(final_entries)

    markdown_path = run_dir / "meeting_transcript.md"
    markdown_path.write_text(
        formatted_transcript,
        encoding="utf-8",
    )

    print()
    print(f"Transcript saved: {markdown_path}")

    _report_progress(
        progress_callback,
        "Cleaning transcript with Qwen...",
        69,
    )

    cleaned_transcript, cleaned_markdown_path = run_ai_cleanup(
        run_dir=run_dir,
        transcript=formatted_transcript,
    )

    _report_progress(
        progress_callback,
        "Generating meeting summary...",
        77,
    )

    meeting_summary, summary_html, summary_path, _ = (
        run_meeting_summary(
            run_dir=run_dir,
            cleaned_transcript=cleaned_transcript,
        )
    )

    html_transcript = format_transcript_html(
        final_entries
    )

    completed_artifacts = complete_post_summary_artifacts(
        run_dir=run_dir,
        meeting_summary=meeting_summary,
        cleaned_transcript=cleaned_transcript,
        transcript_html=html_transcript,
        source_path=meeting_path,
        progress_callback=progress_callback,
    )
    html_path = completed_artifacts["transcript_html_path"]

    elapsed_seconds = time.perf_counter() - start_time
    elapsed_minutes = int(elapsed_seconds // 60)
    remaining_seconds = elapsed_seconds % 60

    print()
    print("=" * 60)
    print("Finished successfully")
    print("=" * 60)
    print(f"Raw transcript   : {markdown_path}")
    print(f"Clean transcript : {cleaned_markdown_path}")
    print(f"HTML transcript  : {html_path}")
    print(
        f"Total runtime    : "
        f"{elapsed_minutes}m {remaining_seconds:.1f}s"
    )
    print("=" * 60)

    _report_progress(
        progress_callback,
        "Transcription complete.",
        100,
    )

    return run_dir


def main() -> None:
    meeting_path = choose_meeting_file()
    transcribe_meeting(
        meeting_path,
    )


if __name__ == "__main__":
    main()
