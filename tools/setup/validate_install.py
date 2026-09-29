#!/usr/bin/env python3
"""Read-only installation validation for Meeting Transcriber on macOS.

The validator intentionally makes no configuration changes.  It reports PASS,
WARN, or FAIL for the local runtime, configured paths, local AI dependencies,
and optional native-recording prerequisites.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_settings import load_app_settings
from install_config import load_install_config


WHISPER_MODEL = Path.home() / "whisper" / "models" / "ggml-medium.en.bin"


def result(level: str, label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"{level:<4} {label}{suffix}")


def command_version(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)

    text = (completed.stdout or completed.stderr).strip().splitlines()
    detail = text[0] if text else f"exit {completed.returncode}"
    return completed.returncode == 0, detail


def ollama_models() -> tuple[bool, list[str], str]:
    try:
        with urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=5
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return False, [], str(exc)

    models = [
        str(item.get("name") or "")
        for item in payload.get("models", [])
        if isinstance(item, dict)
    ]
    return True, [name for name in models if name], ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Meeting Transcriber setup.")
    parser.add_argument("--run-tests", action="store_true")
    args = parser.parse_args(argv)

    failures = 0
    warnings = 0

    def emit(level: str, label: str, detail: str = "") -> None:
        nonlocal failures, warnings
        result(level, label, detail)
        if level == "FAIL":
            failures += 1
        elif level == "WARN":
            warnings += 1

    print("Meeting Transcriber installation validation\n")

    if platform.system() == "Darwin":
        emit("PASS", "macOS detected", platform.mac_ver()[0] or "unknown version")
    else:
        emit("FAIL", "macOS detected", f"found {platform.system()}")

    if platform.machine() == "arm64":
        emit("PASS", "Apple Silicon architecture", "arm64")
    else:
        emit("WARN", "Apple Silicon architecture", platform.machine())

    install = load_install_config()
    configured_project = Path(install.get("project_dir") or ROOT).expanduser()
    if configured_project.exists():
        emit("PASS", "Configured project directory", str(configured_project))
    else:
        emit("FAIL", "Configured project directory", str(configured_project))

    venv_python = configured_project / ".venv" / "bin" / "python"
    if venv_python.exists():
        ok, detail = command_version([str(venv_python), "--version"])
        emit("PASS" if ok else "FAIL", "Project virtualenv", detail)
    else:
        emit("FAIL", "Project virtualenv", str(venv_python))

    for executable, version_args in (
        ("brew", ["brew", "--version"]),
        ("ffmpeg", ["ffmpeg", "-version"]),
        ("ffprobe", ["ffprobe", "-version"]),
        ("whisper-cli", ["whisper-cli", "--help"]),
        ("ollama", ["ollama", "--version"]),
    ):
        path = shutil.which(executable)
        if not path:
            emit("FAIL", executable, "not found in PATH")
            continue
        ok, detail = command_version(version_args)
        emit("PASS" if ok else "FAIL", executable, detail)

    if WHISPER_MODEL.exists() and WHISPER_MODEL.stat().st_size > 0:
        emit("PASS", "Whisper medium.en model", str(WHISPER_MODEL))
    else:
        emit("FAIL", "Whisper medium.en model", str(WHISPER_MODEL))

    settings = load_app_settings()
    model = str(settings.get("llm_model") or "qwen3:8b")
    ollama_ok, models, error = ollama_models()
    if not ollama_ok:
        emit("FAIL", "Ollama local API", error)
    elif model in models:
        emit("PASS", "Configured Ollama model", model)
    else:
        emit("FAIL", "Configured Ollama model", f"{model} not installed")

    for key, label, required in (
        ("output_dir", "Working directory", True),
        ("recordings_dir", "Meetings / recordings directory", True),
        ("archive_dir", "Archive directory", False),
    ):
        raw = str(settings.get(key) or "").strip()
        path = Path(raw).expanduser() if raw else None
        if path and path.is_dir():
            emit("PASS", label, str(path))
        elif required:
            emit("FAIL", label, raw or "not configured")
        else:
            emit("WARN", label, (raw or "not configured") + " (publishing unavailable until mounted/created)")

    xcode_project = configured_project / "swift" / "Meeting Transcriber" / "Meeting Transcriber.xcodeproj"
    if xcode_project.exists():
        emit("PASS", "Xcode project", str(xcode_project))
    else:
        emit("FAIL", "Xcode project", str(xcode_project))

    if platform.system() == "Darwin":
        try:
            audio = subprocess.run(
                ["/usr/sbin/system_profiler", "SPAudioDataType"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if "Transcribe:" in audio.stdout or "Transcribe" in audio.stdout:
                emit("PASS", "Optional Transcribe audio device", "detected")
            else:
                emit("WARN", "Optional Transcribe audio device", "not detected; existing-file transcription still works")
        except (OSError, subprocess.TimeoutExpired) as exc:
            emit("WARN", "Optional Transcribe audio device", str(exc))

    if venv_python.exists():
        ok, detail = command_version(
            [str(venv_python), "-c", "import backend_bridge; print('backend import OK')"]
        )
        emit("PASS" if ok else "FAIL", "Python backend import", detail)

        if args.run_tests:
            print("\nRunning Python regression suite...")
            completed = subprocess.run(
                [
                    str(venv_python),
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_*.py",
                ],
                cwd=configured_project,
                check=False,
            )
            emit("PASS" if completed.returncode == 0 else "FAIL", "Python regression suite")

    print(f"\nValidation summary: {failures} failure(s), {warnings} warning(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
