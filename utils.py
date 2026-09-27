from dataclasses import dataclass

from pathlib import Path

from config import (
    MAX_MERGE_GAP_SECONDS,
    MAX_PARAGRAPH_CHARS,
)

@dataclass
class TranscriptEntry:
    """One timestamped segment from a transcript."""

    start: float
    end: float
    speaker: str
    text: str


def parse_timestamp(timestamp: str) -> float:
    """
    Convert a VTT timestamp (HH:MM:SS.mmm) into seconds.
    """

    hours, minutes, seconds = timestamp.split(":")

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(seconds)
    )


def parse_vtt_block(block: str, speaker: str) -> TranscriptEntry:
    """
    Parse a single VTT block into a TranscriptEntry.
    """

    lines = block.strip().splitlines()

    timing = lines[0]
    text = " ".join(lines[1:])

    start_str, end_str = timing.split(" --> ")

    return TranscriptEntry(
        start=parse_timestamp(start_str),
        end=parse_timestamp(end_str),
        speaker=speaker,
        text=text,
    )


def read_vtt_file(vtt_path: Path) -> str:
    """
    Read an entire VTT file into a string.
    """

    with open(vtt_path, "r", encoding="utf-8") as file:
        return file.read()


def split_vtt_blocks(contents: str) -> list[str]:
    """
    Split a VTT file into individual caption blocks.
    """

    blocks = contents.split("\n\n")

    return [
        block
        for block in blocks
        if "-->" in block
    ]

def parse_vtt_file(vtt_path: Path, speaker: str) -> list[TranscriptEntry]:
    """
    Parse an entire VTT file into TranscriptEntry objects.
    """

    contents = read_vtt_file(vtt_path)
    blocks = split_vtt_blocks(contents)

    entries = []

    for block in blocks:
        entry = parse_vtt_block(block, speaker)

        # Clean Whisper placeholders
        entry.text = (
            entry.text
                .replace("[BLANK_AUDIO]", "")
                .replace("[Silence]", "")
                .strip()
        )

        # Skip entries that became empty
        if not entry.text:
            continue

        entries.append(entry)

    return entries


def merge_transcripts(
    remote_entries: list[TranscriptEntry],
    mic_entries: list[TranscriptEntry],
) -> list[TranscriptEntry]:
    """
    Merge and sort transcript entries chronologically.
    """

    all_entries = remote_entries + mic_entries

    all_entries.sort(key=lambda entry: entry.start)

    return all_entries


def remove_silence_entries(
    entries: list[TranscriptEntry],
) -> list[TranscriptEntry]:
    """
    Remove transcript entries that contain only a silence marker.
    """

    silence_markers = {
        "[silence]",
        "(silence)",
        "silence",
    }

    return [
        entry
        for entry in entries
        if entry.text.strip().lower() not in silence_markers
    ]


def merge_adjacent_speakers(
    entries: list[TranscriptEntry],
) -> list[TranscriptEntry]:
    """
    Merge consecutive transcript entries from the same speaker
    when the gap between them is below the configured threshold.
    """

    merged = []

    for entry in entries:
        if not merged:
            merged.append(entry)
            continue

        previous = merged[-1]

        gap = entry.start - previous.end
 
        combined_length = (
            len(previous.text)
            + 1
            + len(entry.text)
        )    

        if (
            previous.speaker == entry.speaker
            and gap <= MAX_MERGE_GAP_SECONDS
            and combined_length <= MAX_PARAGRAPH_CHARS
        ):

            previous.end = entry.end
            previous.text = f"{previous.text} {entry.text}"
        else:
            merged.append(entry)

    return merged
