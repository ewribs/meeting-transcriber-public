#!/usr/bin/env python3
"""Turn a recording's Remote track into voices and fingerprints.

This is the only part of the voice feature that needs PyTorch and the
pyannote models, so it is meant to run in its own Python environment, not
the app's main one. The app calls it as a separate process and reads the
JSON it writes; all decisions are made elsewhere (voice_profiles.py).

    python voice_worker.py AUDIO --out RESULT.json

AUDIO is either a recording (.m4a, the Remote track is channel 0) or an
already-extracted mono Remote track (.wav).

The result contains no audio. Fingerprints are numbers; treat the file as
private and delete it once it has been used.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

RESULT_VERSION = 1
DIARIZE_MODEL = "pyannote/speaker-diarization-3.1"
EMBED_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"
SAMPLE_RATE = 16000
CHUNK_SECONDS = 4.0
MIN_CHUNK_SECONDS = 2.0
MAX_CHUNKS_PER_VOICE = 80

# Measured on real recordings: a normal Remote track averages about -34 dB;
# one where the other person was not captured averaged -68 dB.
SILENT_MEAN_DB = -55.0


# ------------------------------------------------------------ pure helpers --

def level_db(samples) -> float:
    """Average loudness of mono samples in decibels (0 dB is full scale)."""
    values = list(samples)
    if not values:
        return -120.0
    mean_square = sum(float(x) * float(x) for x in values) / len(values)
    if mean_square <= 0:
        return -120.0
    return 10.0 * math.log10(mean_square)


def is_silent(mean_db: float) -> bool:
    return mean_db < SILENT_MEAN_DB


def chunk_turns(
    turns: list[tuple[float, float]],
    chunk_seconds: float = CHUNK_SECONDS,
    min_seconds: float = MIN_CHUNK_SECONDS,
    max_chunks: int = MAX_CHUNKS_PER_VOICE,
) -> list[tuple[float, float]]:
    """Cut speech turns into short windows, spread evenly if there are many."""
    chunks: list[tuple[float, float]] = []
    for start, end in turns:
        t = start
        while end - t >= min_seconds:
            chunks.append((t, min(t + chunk_seconds, end)))
            t += chunk_seconds
    if len(chunks) > max_chunks:
        step = len(chunks) / max_chunks
        chunks = [chunks[int(i * step)] for i in range(max_chunks)]
    return chunks


def build_payload(
    *,
    duration_seconds: float,
    mean_db: float,
    voices: list[dict],
    seconds_taken: float,
) -> dict:
    return {
        "version": RESULT_VERSION,
        "models": {"diarization": DIARIZE_MODEL, "embedding": EMBED_MODEL},
        "duration_seconds": round(duration_seconds, 1),
        "remote_mean_db": round(mean_db, 1),
        "remote_silent": is_silent(mean_db),
        "seconds_taken": round(seconds_taken, 1),
        "voices": voices,
    }


def voice_record(voice_id: str, turns, fingerprints) -> dict:
    return {
        "voice_id": voice_id,
        "seconds": round(sum(e - s for s, e in turns), 1),
        "turns": [[round(s, 2), round(e, 2)] for s, e in turns],
        "fingerprints": [[round(float(x), 5) for x in f] for f in fingerprints],
    }


# ---------------------------------------------------------- heavy (PyTorch) --

def extract_remote(recording: Path, out_wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(recording),
         "-filter_complex", "[0:a]pan=mono|c0=c0[out]", "-map", "[out]",
         "-ar", str(SAMPLE_RATE), str(out_wav)],
        check=True,
    )


def to_mono_16k(source: Path, out_wav: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(source),
         "-ac", "1", "-ar", str(SAMPLE_RATE), str(out_wav)],
        check=True,
    )


def analyze(audio_path: Path, *, use_gpu: bool = True,
            max_speakers: int | None = None) -> dict:
    import numpy as np
    import soundfile as sf
    import torch
    from pyannote.audio import Inference, Model, Pipeline
    from pyannote.core import Segment

    started = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "remote.wav"
        if audio_path.suffix.lower() == ".wav":
            to_mono_16k(audio_path, wav)
        else:
            extract_remote(audio_path, wav)
        data, rate = sf.read(str(wav), dtype="float32")

    duration = len(data) / rate
    mean_db = level_db(data[:: max(1, rate // 100)])
    if is_silent(mean_db):
        return build_payload(duration_seconds=duration, mean_db=mean_db,
                             voices=[], seconds_taken=time.time() - started)

    audio = {"waveform": torch.from_numpy(data).unsqueeze(0),
             "sample_rate": rate}

    pipeline = Pipeline.from_pretrained(DIARIZE_MODEL)
    if pipeline is None:
        raise SystemExit("The diarization model did not load. Accept its "
                         "terms on Hugging Face and log in with `hf auth login`.")
    model = Model.from_pretrained(EMBED_MODEL)
    inference = Inference(model, window="whole")
    if use_gpu and torch.backends.mps.is_available():
        device = torch.device("mps")
        pipeline.to(device)
        try:
            inference.to(device)
        except Exception:
            pass

    kwargs = {"max_speakers": max_speakers} if max_speakers else {}
    result = pipeline(audio, **kwargs)
    annotation = getattr(result, "speaker_diarization", result)

    by_voice: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for segment, _, who in annotation.itertracks(yield_label=True):
        by_voice[who].append((segment.start, segment.end))

    voices = []
    for who in sorted(by_voice):
        turns = sorted(by_voice[who])
        prints = []
        for start, end in chunk_turns(turns):
            vec = np.asarray(inference.crop(audio, Segment(start, end))).reshape(-1)
            norm = float(np.linalg.norm(vec))
            if norm > 0 and math.isfinite(norm):
                prints.append(vec / norm)
        voices.append(voice_record(who, turns, prints))

    return build_payload(duration_seconds=duration, mean_db=mean_db,
                         voices=voices, seconds_taken=time.time() - started)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cpu", action="store_true", help="do not use the Apple GPU")
    parser.add_argument("--max-speakers", type=int)
    args = parser.parse_args()

    if not args.audio.exists():
        print("Audio file not found: " + str(args.audio), file=sys.stderr)
        return 2
    payload = analyze(args.audio, use_gpu=not args.cpu,
                      max_speakers=args.max_speakers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"{len(payload['voices'])} voices, "
          f"{'remote silent' if payload['remote_silent'] else 'ok'}, "
          f"{payload['seconds_taken']}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
