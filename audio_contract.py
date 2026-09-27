from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import os
from pathlib import Path
from typing import Any


def _find_media_tool(name: str) -> str:
    """Resolve ffmpeg/ffprobe for both Terminal and GUI-launched app processes."""

    discovered = shutil.which(name)
    if discovered:
        return discovered

    for directory in (
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ):
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)

    raise RuntimeError(
        f"{name} was not found. Checked PATH plus /opt/homebrew/bin and /usr/local/bin."
    )


def _ffprobe_audio_stream(path: Path) -> dict[str, Any]:
    ffprobe = _find_media_tool("ffprobe")

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,codec_long_name,sample_rate,channels,channel_layout",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"No audio stream found in {path}")

    return dict(streams[0])


def _extract_contract_channels(
    source: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Run the same c0/c4 ffmpeg pan contract used by transcribe.py."""

    ffmpeg = _find_media_tool("ffmpeg")

    remote_path = output_dir / "remote.wav"
    mic_path = output_dir / "mic.wav"

    for channel, destination in ((0, remote_path), (4, mic_path)):
        subprocess.run(
            [
                ffmpeg,
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-filter_complex",
                f"[0:a]pan=mono|c0=c{channel}[out]",
                "-map",
                "[out]",
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    return remote_path, mic_path


def inspect_audio_contract(path: str | Path) -> dict[str, Any]:
    """Validate a recording against the existing transcription channel contract."""

    source = Path(path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_file():
        raise ValueError(f"Not a file: {source}")

    stream = _ffprobe_audio_stream(source)
    channel_count = int(stream.get("channels") or 0)

    extraction_ok = False
    remote_size = 0
    mic_size = 0
    extraction_error = ""

    if channel_count >= 5:
        try:
            with tempfile.TemporaryDirectory(
                prefix="meeting-transcriber-audio-contract-"
            ) as tmp:
                remote_path, mic_path = _extract_contract_channels(
                    source,
                    Path(tmp),
                )
                remote_size = remote_path.stat().st_size
                mic_size = mic_path.stat().st_size
                extraction_ok = remote_size > 0 and mic_size > 0
        except Exception as exc:  # surfaced directly in the native spike UI
            extraction_error = str(exc)

    compatible = channel_count >= 5 and extraction_ok

    return {
        "schema_version": 1,
        "path": str(source),
        "codec": str(stream.get("codec_name") or ""),
        "codec_long_name": str(stream.get("codec_long_name") or ""),
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": channel_count,
        "channel_layout": str(stream.get("channel_layout") or ""),
        "remote_channel_index": 0,
        "mic_channel_index": 4,
        "remote_extract_bytes": remote_size,
        "mic_extract_bytes": mic_size,
        "extraction_ok": extraction_ok,
        "compatible": compatible,
        "message": (
            "Compatible with the existing Remote=c0 / Mic=c4 transcription contract."
            if compatible
            else (
                extraction_error
                or (
                    f"Expected at least 5 audio channels, found {channel_count}."
                    if channel_count < 5
                    else "Remote/Mic extraction did not produce usable output."
                )
            )
        ),
    }


def finalize_recording_to_m4a(
    source_path: str | Path,
    output_path: str | Path,
    *,
    sample_rate: int,
    channels: int,
) -> dict[str, Any]:
    """Finalize raw interleaved Float32 PCM into a pipeline-compatible M4A.

    Native capture writes the input tap directly as little-endian Float32 PCM
    so the five aggregate-device channels remain in their original ordinal
    order without asking AVAudioFile/ExtAudioFile to accept a nonstandard
    multichannel client format.  Finalization happens only after capture
    stops.  Source c0 remains output c0 (Remote) and source c4 remains output
    c4 (Mic).
    """

    source = Path(source_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()

    if not source.exists():
        raise FileNotFoundError(source)
    if not source.is_file():
        raise ValueError(f"Not a file: {source}")
    if sample_rate <= 0:
        raise ValueError(f"Invalid sample rate: {sample_rate}")
    if channels < 5:
        raise RuntimeError(
            f"Expected at least 5 captured channels, found {channels}."
        )

    ffmpeg = _find_media_tool("ffmpeg")

    output.parent.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "f32le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-i",
            str(source),
            "-filter_complex",
            "[0:a]pan=5.0|FL=c0|FR=c1|FC=c2|BL=c3|BR=c4[out]",
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "384k",
            "-ar",
            str(sample_rate),
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    result = inspect_audio_contract(output)
    result["source_capture_path"] = str(source)
    return result
