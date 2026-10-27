"""Record the local model's answers once, replay them later.

Rewriting how the extraction reads transcripts must not change what it
produces. To prove that without running the model again (slow, and its answers
can vary), the model's replies are recorded once and replayed afterwards:

    record   the real model answers, and every prompt/answer pair is saved
    replay   the saved answer is returned for an identical prompt; a prompt that
             was never recorded stops with a message, because it means the code
             now asks the model something different

Everything goes through ``ai.ask_llm``, the one place prompts leave the program.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path


class MissingRecording(Exception):
    """A prompt was sent that has no recorded answer."""


def prompt_key(prompt: str, response_format=None) -> str:
    material = prompt + "\n--format--\n" + json.dumps(
        response_format, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class Recording:
    """Saved prompt/answer pairs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: dict[str, dict] = {}

    def load(self) -> "Recording":
        if self.path.exists():
            self.items = json.loads(self.path.read_text(encoding="utf-8"))
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)


class Replayer:
    """Stands in for ai.ask_llm."""

    def __init__(self, recording: Recording, mode: str, real=None):
        if mode not in ("record", "replay"):
            raise ValueError("mode must be record or replay")
        if mode == "record" and real is None:
            raise ValueError("record mode needs the real function")
        self.recording = recording
        self.mode = mode
        self.real = real
        self.calls = 0

    def __call__(self, prompt, response_format=None, *, timeout_seconds=None):
        self.calls += 1
        key = prompt_key(prompt, response_format)
        saved = self.recording.items.get(key)
        if saved is not None:
            return saved["response"]
        if self.mode == "replay":
            raise MissingRecording(
                "The code sent the model a prompt that was not recorded "
                f"(starts: {prompt[:160]!r}). Either the prompt changed or the "
                "recording is for a different version.")
        response = self.real(prompt, response_format,
                             timeout_seconds=timeout_seconds)
        self.recording.items[key] = {"response": response, "prompt_chars": len(prompt)}
        self.recording.save()
        return response


@contextmanager
def installed(recording_path: Path, mode: str):
    """Use recorded answers for ai.ask_llm inside the block."""
    import ai
    recording = Recording(recording_path).load()
    if mode == "record":
        recording.items = {}
    replayer = Replayer(recording, mode, real=ai.ask_llm if mode == "record" else None)
    original = ai.ask_llm
    ai.ask_llm = replayer
    try:
        yield replayer
    finally:
        ai.ask_llm = original
