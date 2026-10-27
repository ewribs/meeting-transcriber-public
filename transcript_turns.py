"""The turns of a meeting, kept as data.

Until now the transcript existed only as text (meeting_transcript.md) and later
steps found out who said what by searching that text for "**Mic**" and
"**Remote**" headers. This module keeps the same transcript as a list of turns
(transcript_turns.json) so that the speaker of any turn is a lookup.

Phase 1 changes no behaviour: the turns are exactly the paragraphs of today's
transcript, and rendering them gives back today's text, character for
character. The speaker of a turn is not filled in yet (None); who spoke
is added in a later phase from speakers.json.

A turn:
    id         "t0001", "t0002", ... in time order
    start/end  seconds from the start of the recording
    channel    "mic" (the user's microphone) or "remote" (the other side)
    speaker    None for now; later {"kind": "self" | "person" | "unidentified", ...}
    text_raw   the words as transcribed
    text       the words after cleaning (same as text_raw until cleaned)

The file is derived data: it can always be rebuilt from the saved caption files
(transcript/remote.vtt and mic.vtt), so a damaged or missing file is never a
reason to lose a meeting.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import contextlib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import formatter
import utils
from utils import TranscriptEntry

TURNS_FILE = "transcript_turns.json"
TURNS_VERSION = 1

CHANNEL_LABELS = {"mic": "Mic", "remote": "Remote"}
LABEL_CHANNELS = {label.casefold(): channel for channel, label in CHANNEL_LABELS.items()}


class TurnsError(Exception):
    """A readable message for the person using the app."""


@dataclass
class Turn:
    id: str
    start: float
    end: float
    channel: str
    speaker: dict | None
    text_raw: str
    text: str


# --------------------------------------------------------------- building

def turns_from_entries(entries: list[TranscriptEntry]) -> list[Turn]:
    """Turns for transcript entries already merged into paragraphs.

    Each entry's speaker must be "Mic" or "Remote".
    """
    turns = []
    for number, entry in enumerate(entries, 1):
        channel = LABEL_CHANNELS.get(str(entry.speaker).casefold())
        if channel is None:
            raise TurnsError(f"Unexpected speaker label: {entry.speaker!r}")
        turns.append(Turn(
            id=f"t{number:04d}",
            start=float(entry.start),
            end=float(entry.end),
            channel=channel,
            speaker=None,
            text_raw=entry.text,
            text=entry.text,
        ))
    return turns


def build_turns(remote_entries: list[TranscriptEntry],
                mic_entries: list[TranscriptEntry]) -> list[Turn]:
    """The same merging, filtering and joining the transcript has always had."""
    with contextlib.redirect_stdout(io.StringIO()):     # the filter prints a report
        merged = utils.merge_transcripts(remote_entries, mic_entries)
        cleaned = utils.remove_silence_entries(merged)
        final = utils.merge_adjacent_speakers(cleaned)
    return turns_from_entries(final)


def turns_from_run(run_dir: Path) -> list[Turn]:
    """Rebuild the turns of a meeting from its saved caption files."""
    run_dir = Path(run_dir)
    remote_vtt = run_dir / "transcript" / "remote.vtt"
    mic_vtt = run_dir / "transcript" / "mic.vtt"
    if not remote_vtt.exists() and not mic_vtt.exists():
        raise TurnsError("The saved caption files for this meeting were not found.")
    remote = utils.parse_vtt_file(remote_vtt, "Remote") if remote_vtt.exists() else []
    mic = utils.parse_vtt_file(mic_vtt, "Mic") if mic_vtt.exists() else []
    return build_turns(remote, mic)


def speaker_for_label(label: str) -> dict:
    """The speaker record for a label from the naming step."""
    import transcript_names
    import transcript_view
    if label == CHANNEL_LABELS["mic"] or transcript_view.is_self_speaker(label):
        return {"kind": "self"}
    if label == transcript_names.UNIDENTIFIED:
        return {"kind": "unidentified"}
    return {"kind": "person", "name": label}


def build_named_turns(remote_entries: list[TranscriptEntry],
                      mic_entries: list[TranscriptEntry],
                      document: dict) -> list[Turn]:
    """Turns split by voice: every turn has a speaker record.

    Remote lines are named first (from speakers.json) and merged afterwards,
    so one turn never holds two different voices. Mic lines stay "Mic" here;
    they become {"kind": "self"}.
    """
    import transcript_names
    mic_mode = document.get("track") == "mic"
    if mic_mode:
        # Voices were found on the mic track; the Remote track holds only hum.
        remote_entries = []
        for entry in mic_entries:
            entry.speaker = transcript_names.label_for_span(
                entry.start, entry.end, document.get("voices", []))
    else:
        transcript_names.name_remote_entries(remote_entries, document)
        for entry in mic_entries:
            entry.speaker = CHANNEL_LABELS["mic"]
    with contextlib.redirect_stdout(io.StringIO()):
        merged = utils.merge_transcripts(remote_entries, mic_entries)
        cleaned = utils.remove_silence_entries(merged)
        final = utils.merge_adjacent_speakers(cleaned)
    turns = []
    mic_holds_everyone = bool(document.get("remote_silent"))
    for number, entry in enumerate(final, 1):
        is_mic = mic_mode or entry.speaker == CHANNEL_LABELS["mic"]
        turns.append(Turn(
            id=f"t{number:04d}", start=float(entry.start), end=float(entry.end),
            channel="mic" if is_mic else "remote",
            # Remote not captured: the mic holds everyone, so no one is named.
            speaker=({"kind": "unidentified"} if is_mic and mic_holds_everyone
                     else speaker_for_label(entry.speaker)),
            text_raw=entry.text, text=entry.text))
    return turns


def named_turns_from_run(run_dir: Path) -> list[Turn]:
    """Named turns for a meeting, from its caption files and speakers.json."""
    import voice_service as vs
    run_dir = Path(run_dir)
    document = vs.read_speakers(run_dir)
    if document is None:
        raise TurnsError("This meeting has no voice information yet.")
    remote_vtt = run_dir / "transcript" / "remote.vtt"
    mic_vtt = run_dir / "transcript" / "mic.vtt"
    if not remote_vtt.exists() and not mic_vtt.exists():
        raise TurnsError("The saved caption files for this meeting were not found.")
    remote = utils.parse_vtt_file(remote_vtt, "Remote") if remote_vtt.exists() else []
    mic = utils.parse_vtt_file(mic_vtt, "Mic") if mic_vtt.exists() else []
    return build_named_turns(remote, mic, document)


def display_label(turn: Turn, self_name: str) -> str:
    """The name shown for a turn."""
    import transcript_names
    speaker = turn.speaker or {}
    kind = speaker.get("kind")
    if kind == "self":
        return self_name or CHANNEL_LABELS["mic"]
    if kind == "person":
        return speaker.get("name") or transcript_names.UNIDENTIFIED
    if kind == "unidentified":
        return transcript_names.UNIDENTIFIED
    return CHANNEL_LABELS[turn.channel]


def render_named_markdown(turns: list[Turn], self_name: str, field: str = "text_raw") -> str:
    """The transcript with names instead of Mic / Remote."""
    entries = [
        TranscriptEntry(start=t.start, end=t.end,
                        speaker=display_label(t, self_name), text=getattr(t, field))
        for t in turns]
    return formatter.format_transcript(entries)


# -------------------------------------------------------------- rendering

def to_entries(turns: list[Turn], field: str = "text_raw") -> list[TranscriptEntry]:
    """Turns as transcript entries labelled "Mic" / "Remote"."""
    if field not in ("text_raw", "text"):
        raise TurnsError("field must be text_raw or text")
    return [
        TranscriptEntry(start=turn.start, end=turn.end,
                        speaker=CHANNEL_LABELS[turn.channel],
                        text=getattr(turn, field))
        for turn in turns
    ]


def render_markdown(turns: list[Turn], field: str = "text_raw") -> str:
    """The transcript text, identical to what the app has always written."""
    return formatter.format_transcript(to_entries(turns, field))


# ------------------------------------------------------------ saving / loading

def save_turns(run_dir: Path, turns: list[Turn]) -> Path:
    """Write transcript_turns.json (all at once, never half-written)."""
    path = Path(run_dir) / TURNS_FILE
    document = {
        "version": TURNS_VERSION,
        "turns": [asdict(turn) for turn in turns],
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(document, indent=1), encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_turns(run_dir: Path) -> list[Turn] | None:
    """The saved turns, or None when the meeting has none yet."""
    path = Path(run_dir) / TURNS_FILE
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TurnsError(f"{TURNS_FILE} is not readable: {error}")
    if document.get("version") != TURNS_VERSION:
        raise TurnsError(f"{TURNS_FILE} has an unsupported version.")
    try:
        return [Turn(**item) for item in document["turns"]]
    except (KeyError, TypeError) as error:
        raise TurnsError(f"{TURNS_FILE} is not in the expected shape: {error}")


def save_turns_safely(run_dir: Path, entries: list[TranscriptEntry]) -> bool:
    """Save the turns for freshly merged entries; never raise.

    Used inside transcription: a problem here must not cost anyone a meeting,
    because the file can be rebuilt later from the caption files.
    """
    try:
        save_turns(run_dir, turns_from_entries(entries))
        return True
    except Exception as error:      # noqa: BLE001 - deliberately broad
        print(f"Note: the structured transcript was not saved ({error}).")
        return False


# ----------------------------------------------------------------- checking

def compare_with_saved(run_dir: Path) -> str:
    """Does rebuilding give today's meeting_transcript.md?

    "same"       character for character
    "older"      only words missing: the meeting was made before the noise
                 filter that now drops lone punctuation and repetition loops
    "different"  anything else (needs a look)
    "skipped"    no caption files or no saved transcript
    """
    run_dir = Path(run_dir)
    saved_path = run_dir / "meeting_transcript.md"
    if not saved_path.exists():
        return "skipped"
    try:
        rebuilt = render_markdown(turns_from_run(run_dir))
    except TurnsError:
        return "skipped"
    saved = saved_path.read_text(encoding="utf-8")
    if rebuilt == saved:
        return "same"
    return "older" if not (_spoken_words(rebuilt) - _spoken_words(saved)) else "different"


_HEADER_LINE = re.compile(r"^\[\d{1,2}(?::\d{2}){1,2}\]\s+\*\*[^*]+\*\*\s*$")


def _spoken_words(markdown: str) -> Counter:
    """Word counts of what was said, ignoring the timestamp/speaker headers."""
    body = "\n".join(line for line in markdown.splitlines()
                     if not _HEADER_LINE.match(line))
    return Counter(re.findall(r"[a-z0-9']+", body.lower()))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Check that turns rebuilt from the caption files give back "
                    "the saved transcripts.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="compare every meeting's rebuilt transcript with the saved one")
    check.add_argument("runs", nargs="*", help="meeting folder names (default: all)")
    check.add_argument("--output-dir", type=Path)
    build = sub.add_parser("build", help="write transcript_turns.json for a meeting")
    build.add_argument("run")
    build.add_argument("--output-dir", type=Path)
    named = sub.add_parser("named", help="build named turns for a meeting and compare with the named transcript")
    named.add_argument("run")
    named.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)

    if args.output_dir:
        output_dir = args.output_dir
    else:
        import config
        output_dir = config.OUTPUT_DIR

    if args.command == "named":
        import config
        import transcript_names
        run_dir = Path(output_dir) / args.run
        try:
            turns = named_turns_from_run(run_dir)
            text = render_named_markdown(turns, config.SELF_NAME)
            expected, counts = transcript_names.build_named_transcript(run_dir, config.SELF_NAME)
        except (TurnsError, transcript_names.TranscriptNamesError) as error:
            print("Error: " + str(error))
            return 1
        kinds = Counter((t.speaker or {}).get("kind") for t in turns)
        print(f"{len(turns)} turns: {dict(kinds)}")
        print("matches meeting_transcript_named.md rendering:", text == expected)
        return 0 if text == expected else 1

    if args.command == "build":
        run_dir = Path(output_dir) / args.run
        if not run_dir.is_dir():
            print("Meeting folder not found: " + args.run)
            return 2
        try:
            path = save_turns(run_dir, turns_from_run(run_dir))
        except TurnsError as error:
            print("Error: " + str(error))
            return 1
        print(f"Wrote {path}")
        return 0

    folders = [Path(output_dir) / name for name in args.runs] if args.runs else \
        sorted(p for p in Path(output_dir).iterdir() if p.is_dir())
    counts: Counter = Counter()
    for folder in folders:
        result = compare_with_saved(folder)
        counts[result] += 1
        if result == "different":
            print("  needs a look:", folder.name)
    print("same: {same}  older (noise lines removed): {older}  "
          "different: {different}  skipped: {skipped}".format(
              **{k: counts.get(k, 0) for k in ("same", "older", "different", "skipped")}))
    return 1 if counts.get("different") else 0


if __name__ == "__main__":
    sys.exit(main())
