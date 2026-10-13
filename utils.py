import re
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


# ---------------------------------------------------------
# Transcript noise filtering
# ---------------------------------------------------------
# Whisper sometimes invents text on near-silent audio. On the Mic channel
# (silent whenever you are not talking) this shows up as lines containing only
# punctuation (".") and as repetition loops ("And then we're going to give it
# a name. And then we're going to give it a name. ...").
#
# These limits were chosen by measuring three real meetings: every loop scored
# at or below 0.38, while every normal turn scored 0.71 or higher.

NOISE_MIN_WORDS = 20
NOISE_NGRAM_SIZE = 4
NOISE_UNIQUE_RATIO_LIMIT = 0.60

# Counts of what the most recent run removed. Counts only (no text).
LAST_NOISE_REPORT = {"empty_entries": 0, "repetition_loops": 0}


def has_speech_characters(text: str) -> bool:
    """
    True when the text contains at least one letter or digit.
    Entries such as "." or "..." or "-" are Whisper noise, not speech.
    """

    return re.search(r"[A-Za-z0-9]", text) is not None


def repetition_ratio(text: str) -> float:
    """
    Share of distinct 4-word sequences in the text (1.0 = no repetition,
    close to 0.0 = the same phrase over and over).
    Returns 1.0 when the text is too short to judge.
    """

    words = re.findall(r"[a-z0-9']+", text.lower())

    if len(words) < NOISE_MIN_WORDS:
        return 1.0

    grams = [
        tuple(words[index:index + NOISE_NGRAM_SIZE])
        for index in range(len(words) - NOISE_NGRAM_SIZE + 1)
    ]

    return len(set(grams)) / len(grams)


def is_repetition_loop(text: str) -> bool:
    """
    True when the text is long enough to judge and is dominated by repeats.
    """

    return repetition_ratio(text) < NOISE_UNIQUE_RATIO_LIMIT


def remove_repetition_loops(
    entries: list[TranscriptEntry],
) -> list[TranscriptEntry]:
    """
    Remove entries that are Whisper repetition loops.
    """

    kept = []

    for entry in entries:
        if is_repetition_loop(entry.text):
            LAST_NOISE_REPORT["repetition_loops"] += 1
            continue

        kept.append(entry)

    return kept


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
    Remove transcript entries that contain only a silence marker or only
    punctuation (no letters or digits). Starts a fresh noise report.
    """

    LAST_NOISE_REPORT["empty_entries"] = 0
    LAST_NOISE_REPORT["repetition_loops"] = 0

    silence_markers = {
        "[silence]",
        "(silence)",
        "silence",
    }

    kept = []

    for entry in entries:
        if entry.text.strip().lower() in silence_markers:
            continue

        if not has_speech_characters(entry.text):
            LAST_NOISE_REPORT["empty_entries"] += 1
            continue

        kept.append(entry)

    return kept


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

    # Loops are judged after merging so a loop split across several short
    # entries is seen as one block.
    merged = remove_repetition_loops(merged)

    removed_empty = LAST_NOISE_REPORT["empty_entries"]
    removed_loops = LAST_NOISE_REPORT["repetition_loops"]

    if removed_empty or removed_loops:
        print(
            "Noise filter removed "
            f"{removed_empty} empty entries and "
            f"{removed_loops} repetition loops."
        )

    return merged
