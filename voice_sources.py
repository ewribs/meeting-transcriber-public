"""Find the recordings that voice profiles can learn from.

Pure file-name and folder logic; no audio is read here.
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

NAME_RE = re.compile(r"^(?P<before>.*?)\s*1v1\s*(?P<after>[A-Za-z ]*)", re.IGNORECASE)

# Words after "1v1" that describe the meeting rather than the person.
NOT_NAMES = {"catchup", "sync", "checkin", "weekly", "monthly"}


def _name_token(name: str) -> str | None:
    """The person's name as written in the file name, or None."""
    stem = name[:-4] if name.lower().endswith(".m4a") else name
    match = NAME_RE.match(stem)
    if not match:
        return None
    before = re.sub(r"[^A-Za-z]", "", match.group("before"))
    after = re.sub(r"[^A-Za-z]", "", match.group("after"))
    if after.lower() in NOT_NAMES:
        after = ""
    return before or after or None


def person_from_filename(name: str) -> str | None:
    """"Alex1v1092126.m4a" or "1v1Alex092826.m4a" -> "alex" (a grouping key)."""
    token = _name_token(name)
    return token.lower() if token else None


def display_name(file_name: str) -> str:
    """The name as it should be shown: "Alex", "AlexK"."""
    token = _name_token(file_name) or ""
    if token.islower() or token.isupper():
        return token.capitalize()
    return token


def find_recordings(
    folders: Iterable[Path] = (),
    archives: Iterable[Path] = (),
    exclude: Iterable[str] = (),
) -> dict[str, list[Path]]:
    """One-on-one recordings grouped by person.

    `folders` hold recordings directly (*.m4a). `archives` hold meetings as
    <archive>/<meeting>/source/<file>.m4a. A file name seen twice is used
    once, preferring the plain folders. Names containing any `exclude` text
    are skipped.
    """
    skip = [x.lower() for x in exclude if x]
    seen: set[str] = set()
    found: dict[str, list[Path]] = defaultdict(list)

    candidates: list[Path] = []
    for folder in folders:
        if Path(folder).is_dir():
            candidates += sorted(Path(folder).glob("*.m4a"))
    for archive in archives:
        if Path(archive).is_dir():
            candidates += sorted(Path(archive).glob("*/source/*.m4a"))

    for path in candidates:
        if path.name in seen or any(x in path.name.lower() for x in skip):
            continue
        person = person_from_filename(path.name)
        if person:
            seen.add(path.name)
            found[person].append(path)
    return dict(found)


def recording_suffix(run_name: str) -> str:
    """"2026-10-20_1353_SomeMeeting102026" -> "SomeMeeting102026"."""
    parts = run_name.split("_", 2)
    return parts[2] if len(parts) == 3 else run_name


def resolve_audio(
    run_dir: Path,
    meetings_dir: Path | None = None,
    override: Path | None = None,
    archive_dir: Path | None = None,
) -> Path | None:
    """Best audio to analyze for a meeting, or None if none can be found.

    Order: an explicit file, the meeting's own extracted Remote track, a
    source recording inside the meeting folder, the local recordings folder
    (fast), and last the archive's copy of the meeting (often on a network
    drive, so slower).
    """
    if override:
        return Path(override) if Path(override).exists() else None
    run_dir = Path(run_dir)
    remote = run_dir / "audio" / "remote.wav"
    if remote.exists():
        return remote
    inside = sorted((run_dir / "source").glob("*.m4a")) if (run_dir / "source").is_dir() else []
    if inside:
        return inside[0]
    if meetings_dir:
        candidate = Path(meetings_dir) / (recording_suffix(run_dir.name) + ".m4a")
        if candidate.exists():
            return candidate
    if archive_dir:
        twin = Path(archive_dir) / run_dir.name / "source"
        found = sorted(twin.glob("*.m4a")) if twin.is_dir() else []
        if found:
            return found[0]
    return None


# ------------------------------------------------------------------- clips --

CLIP_SECONDS = 10.0
MIN_CLIP_SECONDS = 4.0


def pick_clip_window(
    turns: Iterable[Iterable[float]], seconds: float = CLIP_SECONDS
) -> tuple[float, float] | None:
    """(start, length) of a short clip from the voice's longest turn."""
    best = None
    for start, end in turns:
        length = end - start
        if best is None or length > best[1] - best[0]:
            best = (start, end)
    if best is None or best[1] - best[0] < MIN_CLIP_SECONDS:
        return None
    start, end = best
    length = min(seconds, end - start)
    return (start + (end - start - length) / 2, length)


def pick_clip_windows(
    turns: Iterable[Iterable[float]], count: int, seconds: float = CLIP_SECONDS
) -> list[tuple[float, float]]:
    """Up to `count` clips, each from a different one of the longest turns."""
    usable = [(s, e) for s, e in turns if e - s >= MIN_CLIP_SECONDS]
    usable.sort(key=lambda t: -(t[1] - t[0]))
    windows = []
    for start, end in usable[:max(count, 0)]:
        length = min(seconds, end - start)
        windows.append((start + (end - start - length) / 2, length))
    return sorted(windows)


def clip_command(audio: Path, start: float, length: float, out_path: Path) -> list[str]:
    """ffmpeg command for a mono clip of the Remote track.

    Uses the same channel extraction as the voice worker, and cuts after
    decoding so the position is exact.
    """
    command = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(audio)]
    if Path(audio).suffix.lower() == ".wav":
        command += ["-ac", "1"]                       # already the Remote track
    else:
        command += ["-filter_complex", "[0:a]pan=mono|c0=c0[out]",
                    "-map", "[out]"]                  # channel 0 is Remote
    return command + ["-ss", f"{start:.2f}", "-t", f"{length:.2f}",
                      "-ar", "16000", str(out_path)]


def make_clip(
    audio: Path,
    start: float,
    length: float,
    out_path: Path,
    runner: Callable = subprocess.run,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    runner(clip_command(audio, start, length, out_path),
           check=True, capture_output=True)
    return out_path


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "clip"
