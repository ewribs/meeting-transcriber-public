"""Put people's names on transcript lines.

A transcript line says only "Remote" or "Mic". The voice step knows when each
voice spoke (speakers.json) and, for people you have named, who they are.
This module matches each Remote line to the voice that spoke during it and
writes a second copy of the transcript with names. It never changes the
original transcript.

Pure logic: it reads the saved caption files (transcript/remote.vtt and
mic.vtt) and speakers.json. No audio is read and nothing is guessed:

- a line is given a name only when one named voice clearly covers it;
- otherwise it is labelled "Unidentified" (an unnamed voice, background
  noise, two people talking over each other, or no voice found at that time).
"""

from __future__ import annotations

from pathlib import Path

import formatter
import utils
import voice_service as vs

UNIDENTIFIED = "Unidentified"
NAMED_FILE = "meeting_transcript_named.md"

# Voices must be heard for at least this long during a line to count at all.
# Whisper's line times include pauses, so a share of the line would be too
# strict (a long line can hold only a few seconds of speech).
MIN_VOICED_SECONDS = 0.5
# One voice must account for at least this share of the voiced time in a line.
MIN_DOMINANCE = 0.7


class TranscriptNamesError(Exception):
    """A readable message for the person using the app."""


def _overlap(start: float, end: float, turns: list) -> float:
    total = 0.0
    for turn in turns:
        low = max(start, float(turn[0]))
        high = min(end, float(turn[1]))
        if high > low:
            total += high - low
    return total


def voice_label(voice: dict) -> str:
    """The name to show for one voice."""
    if (voice.get("status") == "named" and voice.get("person")
            and not voice.get("noise")):
        return str(voice["person"])
    return UNIDENTIFIED


def label_for_span(start: float, end: float, voices: list) -> str:
    """Who spoke between `start` and `end` (seconds), or "Unidentified"."""
    duration = end - start
    if duration <= 0:
        return UNIDENTIFIED
    overlaps = []
    for voice in voices:
        seconds = _overlap(start, end, voice.get("turns", []))
        if seconds > 0:
            overlaps.append((seconds, voice))
    if not overlaps:
        return UNIDENTIFIED
    voiced = sum(seconds for seconds, _ in overlaps)
    if voiced < MIN_VOICED_SECONDS:
        return UNIDENTIFIED
    overlaps.sort(key=lambda item: -item[0])
    best_seconds, best_voice = overlaps[0]
    if best_seconds / voiced < MIN_DOMINANCE:
        return UNIDENTIFIED
    return voice_label(best_voice)


def name_remote_entries(entries: list, document: dict) -> list:
    """Give each Remote line the name of the voice that spoke it."""
    voices = document.get("voices", [])
    for entry in entries:
        entry.speaker = label_for_span(entry.start, entry.end, voices)
    return entries


def build_named_entries(remote_entries: list, mic_entries: list,
                        document: dict, self_name: str) -> list:
    """Both tracks merged in time order, every line labelled with a person."""
    if document.get("track") == "mic":
        # The voices were found on the mic track (a speakerphone or an in-person
        # meeting, where the other side has no track of its own). Name the mic
        # lines by voice. The Remote track holds only hum, whose invented text
        # ("static crackling") is not speech.
        for entry in mic_entries:
            entry.speaker = label_for_span(entry.start, entry.end, document.get("voices", []))
        merged = utils.merge_transcripts([], mic_entries)
        cleaned = utils.remove_silence_entries(merged)
        return utils.merge_adjacent_speakers(cleaned)
    name_remote_entries(remote_entries, document)
    # When the other side was never captured on its own track (a speakerphone,
    # or an in-person meeting), the mic holds everyone. Crediting all of it to
    # the user would give them other people's commitments, so say nothing.
    mic_label = UNIDENTIFIED if document.get("remote_silent") else (self_name or "Mic")
    for entry in mic_entries:
        entry.speaker = mic_label
    merged = utils.merge_transcripts(remote_entries, mic_entries)
    cleaned = utils.remove_silence_entries(merged)
    return utils.merge_adjacent_speakers(cleaned)


def build_named_transcript(run_dir: Path, self_name: str) -> tuple[str, dict]:
    """The named transcript text for one meeting, and how many lines each
    label got."""
    run_dir = Path(run_dir)
    document = vs.read_speakers(run_dir)
    if document is None:
        raise TranscriptNamesError(
            "This meeting has no voice information yet. Run: "
            f"python3 voice_cli.py identify {run_dir.name}")
    remote_vtt = run_dir / "transcript" / "remote.vtt"
    mic_vtt = run_dir / "transcript" / "mic.vtt"
    if not remote_vtt.exists() and not mic_vtt.exists():
        raise TranscriptNamesError(
            "The saved caption files for this meeting were not found, so the "
            "names cannot be added.")
    remote = utils.parse_vtt_file(remote_vtt, "Remote") if remote_vtt.exists() else []
    mic = utils.parse_vtt_file(mic_vtt, "Mic") if mic_vtt.exists() else []
    entries = build_named_entries(remote, mic, document, self_name)
    counts: dict = {}
    for entry in entries:
        counts[entry.speaker] = counts.get(entry.speaker, 0) + 1
    return formatter.format_transcript(entries), counts


def write_named_transcript(run_dir: Path, self_name: str) -> tuple[Path, dict]:
    """Save meeting_transcript_named.md beside the original transcript."""
    text, counts = build_named_transcript(run_dir, self_name)
    path = Path(run_dir) / NAMED_FILE
    path.write_text(text, encoding="utf-8")
    return path, counts
