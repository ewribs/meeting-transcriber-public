"""Tell speech from static, for voices the splitting step found in a meeting.

Sometimes the voice-splitting step labels a stretch of hiss or near-silence as
a speaker. Such a "voice" has no name and never will, but it shows up in the
Speakers list and in "Who Spoke". This module measures a voice's audio so those
can be recognized:

- level: how loud it is on average;
- dynamics: how much the loudness rises and falls (speech rises and falls with
  every syllable; steady hiss does not);
- flatness: how evenly the energy is spread across frequencies (hiss is flat;
  speech has strong peaks).

Pure Python (no numpy) so it works in the app's own environment. It reads audio
through ffmpeg, never writes it anywhere, and keeps no copy.

The verdict thresholds come from a few real recordings (one static voice
measured -43 dB level, 7 dB dynamics, 0.24 flatness; real speakers measured
-24 to -29 dB, 24 to 38 dB dynamics, 0.01 to 0.06 flatness) and are kept
conservative: a voice must look like static on both measures. A "likely
static" voice is only set aside, never deleted. Tune them with more real
recordings (``voice_cli.py noise-check``).
"""

from __future__ import annotations

import array
import cmath
import math
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

SAMPLE_RATE = 16000
FRAME = 320                 # 20 ms
FFT_SIZE = 512
LOW_BIN, HIGH_BIN = 4, 128  # about 125 Hz to 4 kHz
MAX_FRAMES = 3000
MAX_SPECTRA = 60
DIGITAL_SILENCE_DB = -80.0

# Thresholds (see the module note).
SILENT_LEVEL_DB = -60.0
STATIC_FLATNESS = 0.12
STATIC_DYNAMICS_DB = 15.0


def _fft(values: list[complex]) -> list[complex]:
    """Radix-2 FFT; the length must be a power of two."""
    n = len(values)
    if n == 1:
        return values
    even = _fft(values[0::2])
    odd = _fft(values[1::2])
    out = [0j] * n
    for k in range(n // 2):
        twiddle = cmath.exp(-2j * math.pi * k / n) * odd[k]
        out[k] = even[k] + twiddle
        out[k + n // 2] = even[k] - twiddle
    return out


_WINDOW = [0.5 - 0.5 * math.cos(2 * math.pi * i / (FFT_SIZE - 1))
           for i in range(FFT_SIZE)]


def frame_db(samples: Sequence[float]) -> float:
    if not len(samples):
        return -120.0
    # Decibels relative to full scale (0 dB is the loudest a 16-bit sample gets).
    mean_square = sum(float(x) * float(x) for x in samples) / len(samples)
    mean_square /= 32768.0 * 32768.0
    return 10.0 * math.log10(mean_square) if mean_square > 0 else -120.0


def spectral_flatness(samples: Sequence[float]) -> float:
    """1.0 is perfectly flat (white noise); near 0 is strongly peaked."""
    chunk = list(samples[:FFT_SIZE])
    if len(chunk) < FFT_SIZE:
        chunk += [0.0] * (FFT_SIZE - len(chunk))
    spectrum = _fft([complex(c * w, 0.0) for c, w in zip(chunk, _WINDOW)])
    power = [abs(spectrum[i]) ** 2 + 1e-12 for i in range(LOW_BIN, HIGH_BIN)]
    mean_log = sum(math.log(p) for p in power) / len(power)
    return math.exp(mean_log) / (sum(power) / len(power))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _frames_for(turns: Iterable[Iterable[float]], total: int) -> list[int]:
    """Start sample of each 20 ms frame inside the turns, thinned evenly."""
    starts: list[int] = []
    for turn in turns:
        begin, end = list(turn)[:2]
        first = int(begin * SAMPLE_RATE)
        last = min(int(end * SAMPLE_RATE), total) - FRAME
        starts.extend(range(max(first, 0), last, FRAME))
    if len(starts) > MAX_FRAMES:
        step = len(starts) / MAX_FRAMES
        starts = [starts[int(i * step)] for i in range(MAX_FRAMES)]
    return starts


def measure(samples: Sequence[float], turns: Iterable[Iterable[float]]) -> dict:
    """Level, dynamics and flatness of the audio inside ``turns``."""
    starts = _frames_for(turns, len(samples))
    if not starts:
        return {"level_db": -120.0, "dynamics_db": 0.0, "flatness": None,
                "frames": 0}
    levels = [frame_db(samples[s:s + FRAME]) for s in starts]
    audible = [(lv, s) for lv, s in zip(levels, starts) if lv > DIGITAL_SILENCE_DB]
    if not audible:
        return {"level_db": -120.0, "dynamics_db": 0.0, "flatness": None,
                "frames": len(starts)}
    db_values = [lv for lv, _ in audible]
    mean_square = sum(10 ** (lv / 10) for lv in db_values) / len(db_values)
    level = 10.0 * math.log10(mean_square)
    dynamics = _percentile(db_values, 0.9) - _percentile(db_values, 0.1)

    median = _percentile(db_values, 0.5)
    loud = [s for lv, s in audible if lv >= median]
    step = max(1, len(loud) // MAX_SPECTRA)
    flats = [spectral_flatness(samples[s:s + FFT_SIZE]) for s in loud[::step]]
    flatness = sorted(flats)[len(flats) // 2] if flats else None
    return {"level_db": round(level, 1), "dynamics_db": round(dynamics, 1),
            "flatness": None if flatness is None else round(flatness, 3),
            "frames": len(starts)}


def verdict(metrics: dict) -> str:
    """"silent", "likely static" or "speech-like"."""
    if metrics["level_db"] < SILENT_LEVEL_DB or metrics["flatness"] is None:
        return "silent"
    if (metrics["flatness"] > STATIC_FLATNESS
            and metrics["dynamics_db"] < STATIC_DYNAMICS_DB):
        return "likely static"
    return "speech-like"


def decode_remote(audio: Path, runner=subprocess.run) -> "array.array":
    """The Remote track as 16 kHz mono 16-bit samples (read through ffmpeg)."""
    import voice_sources
    command = ["ffmpeg", "-loglevel", "error", "-i", str(audio)]
    if Path(audio).suffix.lower() == ".wav":
        command += ["-ac", "1"]
    else:
        command += ["-filter_complex", "[0:a]pan=mono|c0=c0[out]", "-map", "[out]"]
    command += ["-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    result = runner(command, check=True, capture_output=True)
    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) // 2 * 2])
    return samples


def check_meeting(audio: Path, document: dict, runner=subprocess.run) -> list[dict]:
    """Measure every voice in a meeting's speakers document."""
    samples = decode_remote(audio, runner)
    rows = []
    for voice in document.get("voices", []):
        metrics = measure(samples, voice.get("turns", []))
        rows.append({"id": voice["id"], "seconds": voice["seconds"],
                     "status": voice["status"], "person": voice.get("person"),
                     **metrics, "verdict": verdict(metrics)})
    return rows


def tag_document(audio: Path, document: dict, runner=subprocess.run) -> int:
    """Mark voices that sound like static or silence, in place.

    Only unnamed voices are measured (a named voice is a person). Adds
    ``"noise": "static"`` or ``"silent"`` to such voices, removes the mark from
    the rest, and records ``"noise_checked": true``. Returns how many were
    marked.
    """
    targets = [v for v in document.get("voices", []) if v.get("status") != "named"]
    marked = 0
    if targets:
        samples = decode_remote(audio, runner)
        for voice in targets:
            result = verdict(measure(samples, voice.get("turns", [])))
            if result == "speech-like":
                voice.pop("noise", None)
            else:
                voice["noise"] = "static" if result == "likely static" else "silent"
                marked += 1
    for voice in document.get("voices", []):
        if voice.get("status") == "named":
            voice.pop("noise", None)
    document["noise_checked"] = True
    return marked
