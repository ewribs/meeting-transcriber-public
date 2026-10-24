"""Voice service: work out who spoke in a meeting and learn from it.

Glue between the audio worker (voice_worker.py, which runs in its own
Python environment) and the decision logic in voice_profiles.py.

What is written where:
  <meeting folder>/speakers.json   timings, voice ids and names. No audio
                                   and no fingerprints, so it is safe to
                                   archive and publish like the transcript.
  <app support>/voices/profiles.json   the people the app can recognize.
  <app support>/voices/pending/        fingerprints kept briefly so a voice
                                   can be confirmed later. Private.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

import voice_profiles as vp
from app_settings import APP_SUPPORT_DIR

VOICES_DIR = APP_SUPPORT_DIR / "voices"
STORE_PATH = VOICES_DIR / "profiles.json"
PENDING_DIR = VOICES_DIR / "pending"
WORKER_PATH = Path(__file__).resolve().parent / "voice_worker.py"

SPEAKERS_FILE = "speakers.json"
SPEAKERS_VERSION = 1
WORKER_RESULT_VERSION = 1
MIN_ONE_ON_ONE_SHARE = 0.85
PENDING_MAX_AGE_DAYS = 180


def pending_days_setting(settings: dict) -> int:
    """How many days saved fingerprints of unnamed voices are kept.
    0 means never delete. Anything unreadable falls back to the default."""
    try:
        days = int(settings.get("voice_pending_days", PENDING_MAX_AGE_DAYS))
    except (TypeError, ValueError):
        return PENDING_MAX_AGE_DAYS
    return days if days >= 0 else PENDING_MAX_AGE_DAYS


class VoiceServiceError(Exception):
    """Something went wrong that the user should be told about plainly."""


# ------------------------------------------------------------------- files --

def _write_private_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_speakers(run_dir: Path) -> dict | None:
    path = Path(run_dir) / SPEAKERS_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VoiceServiceError("speakers.json is not readable: " + str(error))
    if data.get("version") != SPEAKERS_VERSION:
        raise VoiceServiceError("speakers.json has an unsupported version.")
    return data


def write_speakers(run_dir: Path, document: dict) -> Path:
    path = Path(run_dir) / SPEAKERS_FILE
    _write_private_json(path, document)
    return path


def mirror_speakers(run_dir: Path, archive_dir: Path | None) -> bool:
    """Copy a meeting's speakers.json to its published copy.

    The app reads published meetings from the archive, so a change made to
    the working copy (naming a voice, re-analyzing) must reach it too.
    Does nothing if the meeting is not published or the two are the same
    folder. Returns True if a copy was written. Never raises.
    """
    if archive_dir is None:
        return False
    try:
        run_dir = Path(run_dir)
        twin = Path(archive_dir) / run_dir.name
        if (
            not twin.is_dir()
            or not (twin / "meeting_metadata.json").exists()
            or twin.resolve() == run_dir.resolve()
        ):
            return False
        document = read_speakers(run_dir)
        if document is None:
            return False
        write_speakers(twin, document)
        return True
    except (OSError, ValueError, VoiceServiceError):
        return False


# ------------------------------------------------------------------ worker --

def run_worker(
    audio_path: Path,
    python_path: str | Path,
    *,
    worker_path: Path = WORKER_PATH,
    runner: Callable = subprocess.run,
    timeout: int = 3600,
) -> dict:
    """Run the audio worker and return its result."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        command = [str(python_path), str(worker_path), str(audio_path),
                   "--out", str(out)]
        try:
            done = runner(command, capture_output=True, text=True,
                          timeout=timeout)
        except subprocess.TimeoutExpired:
            raise VoiceServiceError("Voice analysis took too long and was stopped.")
        except OSError as error:
            raise VoiceServiceError("Could not start voice analysis: " + str(error))
        if done.returncode != 0:
            tail = (done.stderr or "").strip().splitlines()[-3:]
            raise VoiceServiceError(
                "Voice analysis failed. " + " ".join(tail)
            )
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise VoiceServiceError("Voice analysis gave no usable result: " + str(error))
    if payload.get("version") != WORKER_RESULT_VERSION:
        raise VoiceServiceError("Voice analysis returned an unsupported version.")
    return payload


def payload_voices(payload: dict) -> list[vp.VoiceInput]:
    return [
        vp.VoiceInput(v["voice_id"], float(v["seconds"]), v["fingerprints"])
        for v in payload.get("voices", [])
    ]


# --------------------------------------------------------------- documents --

def build_speakers_document(
    payload: dict,
    store: vp.VoiceStore,
    expected_names: Iterable[str] = (),
    now: datetime | None = None,
) -> dict:
    expected = [n.strip() for n in expected_names if n and n.strip()]
    results = vp.identify_voices(payload_voices(payload), store)
    hint = vp.suggest_by_elimination(results, expected, store) if expected else None
    names = {p.person_id: p.name for p in store.people()}
    raw = {v["voice_id"]: v for v in payload.get("voices", [])}

    voices = []
    for r in results:
        voices.append({
            "id": r.voice_id,
            "seconds": r.seconds,
            "status": r.status,
            "person_id": r.person_id,
            "person": names.get(r.person_id) if r.person_id else None,
            "via": r.via,
            "gap": round(r.gap, 2),
            "suggestions": [
                {"person_id": s.person_id,
                 "person": names.get(s.person_id, s.person_id),
                 "score": round(s.score, 2)}
                for s in r.suggestions
            ],
            "same_as": r.same_as,
            "turns": raw[r.voice_id]["turns"],
        })

    return {
        "version": SPEAKERS_VERSION,
        "created": (now or datetime.now()).isoformat(timespec="seconds"),
        "remote_silent": bool(payload.get("remote_silent")),
        "duration_seconds": payload.get("duration_seconds"),
        "models": payload.get("models", {}),
        "thresholds": {
            "name_score": vp.NAME_SCORE,
            "name_gap": vp.NAME_GAP,
            "same_voice": vp.SAME_VOICE_SCORE,
            "min_seconds": vp.MIN_VOICE_SECONDS,
        },
        "expected_names": expected,
        "voices": voices,
        "hint": (
            {"voice_ids": list(hint.voice_ids), "name": hint.name}
            if hint else None
        ),
    }


def is_noise(voice: dict) -> bool:
    """True for an unnamed voice marked as static or silence."""
    return bool(voice.get("noise")) and voice.get("status") != "named"


def carry_noise(old: dict, new: dict) -> None:
    """Keep the static marks when a meeting is re-matched without audio."""
    marks = {v["id"]: v["noise"] for v in old.get("voices", []) if v.get("noise")}
    for voice in new.get("voices", []):
        if voice["id"] in marks and voice["status"] != "named":
            voice["noise"] = marks[voice["id"]]
    if old.get("noise_checked"):
        new["noise_checked"] = True


def keep_confirmations(old: dict | None, new: dict) -> dict:
    """Carry names the user confirmed by hand into a freshly built document.

    Re-analyzing a meeting must never throw away what the user said.
    """
    if not old:
        return new
    confirmed = {
        v["id"]: v for v in old.get("voices", [])
        if v.get("via") == "user" and v.get("status") == "named"
    }
    for voice in new.get("voices", []):
        before = confirmed.get(voice["id"])
        if before:
            voice.update({
                "status": "named", "via": "user",
                "person_id": before["person_id"], "person": before["person"],
            })
    hint = new.get("hint")
    if hint and all(
        any(v["id"] == vid and v["status"] == "named" for v in new["voices"])
        for vid in hint["voice_ids"]
    ):
        new["hint"] = None
    return new


def display_labels(document: dict) -> dict[str, str]:
    """A readable label for every voice: the person's name, or "Speaker N"."""
    labels: dict[str, str] = {}
    unknown = sorted(
        (v for v in document.get("voices", []) if v["status"] != "named"),
        key=lambda v: -v["seconds"],
    )
    counter = 0
    for voice in unknown:
        if voice["status"] == "too_short":
            labels[voice["id"]] = "Unidentified"
        else:
            counter += 1
            labels[voice["id"]] = f"Speaker {counter}"
    for voice in document.get("voices", []):
        if voice["status"] == "named":
            labels[voice["id"]] = voice["person"] or voice["person_id"]
    return labels


# ----------------------------------------------------------------- pending --

def save_pending(run_name: str, payload: dict, pending_dir: Path = PENDING_DIR) -> None:
    data = {v["voice_id"]: v["fingerprints"] for v in payload.get("voices", [])}
    if data:
        _write_private_json(Path(pending_dir) / (run_name + ".json"), data)


def load_pending(run_name: str, pending_dir: Path = PENDING_DIR) -> dict:
    path = Path(pending_dir) / (run_name + ".json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def delete_pending(run_name: str, pending_dir: Path = PENDING_DIR) -> None:
    try:
        (Path(pending_dir) / (run_name + ".json")).unlink()
    except OSError:
        pass


def prune_pending(
    pending_dir: Path = PENDING_DIR,
    max_age_days: int = PENDING_MAX_AGE_DAYS,
    now: float | None = None,
) -> int:
    """Delete saved fingerprints older than the limit; returns how many."""
    pending_dir = Path(pending_dir)
    if not pending_dir.exists():
        return 0
    cutoff = (now if now is not None else time.time()) - max_age_days * 86400
    removed = 0
    for path in pending_dir.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


# ----------------------------------------------------------------- rematch --

def _voice_summary(document: dict) -> list[tuple]:
    return sorted(
        (v["id"], v["status"], v.get("person_id"), v.get("via"))
        for v in document.get("voices", [])
    )


def rematch_run(
    run_dir: Path,
    store: vp.VoiceStore,
    pending_dir: Path = PENDING_DIR,
    archive_dir: Path | None = None,
) -> tuple[str, dict | None]:
    """Re-check one meeting's voices against the current fingerprints, using
    the fingerprints saved when it was analyzed. No audio, no voice tools.

    Returns (outcome, document). Outcomes: "updated", "same", "no data" (the
    meeting has no speakers file or its saved fingerprints are gone, so only a
    full re-analysis can help) and "silent" (remote audio was not captured).
    """
    old = read_speakers(run_dir)
    if not old:
        return "no data", None
    if old.get("remote_silent"):
        return "silent", old
    saved = load_pending(Path(run_dir).name, pending_dir)
    voices = old.get("voices", [])
    if not voices or any(v["id"] not in saved for v in voices):
        return "no data", None

    rebuilt = {
        "remote_silent": False,
        "duration_seconds": old.get("duration_seconds"),
        "models": old.get("models", {}),
        "voices": [
            {"voice_id": v["id"], "seconds": v["seconds"],
             "turns": v["turns"], "fingerprints": saved[v["id"]]}
            for v in voices
        ],
    }
    new = keep_confirmations(
        old,
        build_speakers_document(rebuilt, store, old.get("expected_names", [])),
    )
    carry_noise(old, new)
    if _voice_summary(new) == _voice_summary(old):
        return "same", old
    write_speakers(run_dir, new)
    mirror_speakers(run_dir, archive_dir)
    return "updated", new


# ---------------------------------------------------------------- learning --

def dominant_voice(payload: dict) -> tuple[dict, float] | None:
    voices = payload.get("voices", [])
    if not voices:
        return None
    total = sum(v["seconds"] for v in voices) or 1.0
    best = max(voices, key=lambda v: v["seconds"])
    return best, best["seconds"] / total


def enroll_one_on_one(
    store: vp.VoiceStore, name: str, payload: dict
) -> dict:
    """Learn a person from a one-on-one: the Remote track is only them."""
    if payload.get("remote_silent"):
        raise VoiceServiceError("The other person was not captured in this recording.")
    found = dominant_voice(payload)
    if found is None:
        raise VoiceServiceError("No speech was found on the Remote track.")
    voice, share = found
    if share < MIN_ONE_ON_ONE_SHARE:
        raise VoiceServiceError(
            f"Only {share:.0%} of the speech is one voice; this does not look "
            "like a one-on-one."
        )
    person = store.ensure_person(name)
    added = store.enroll(person.person_id, voice["fingerprints"])
    return {"person_id": person.person_id, "added": added, "share": round(share, 2)}


def confirm_voice(
    run_dir: Path,
    voice_id: str,
    name: str,
    store: vp.VoiceStore,
    pending_dir: Path = PENDING_DIR,
    only_this: bool = False,
) -> dict:
    """The user says who a voice is. Names it, and learns from it if possible.

    Normally this also names the voices that sound like it in the same meeting
    (they are the same person split in two). ``only_this`` names just the one
    chosen."""
    run_dir = Path(run_dir)
    document = read_speakers(run_dir)
    if document is None:
        raise VoiceServiceError("This meeting has no speaker information yet.")
    by_id = {v["id"]: v for v in document["voices"]}
    if voice_id not in by_id:
        raise VoiceServiceError("Unknown voice: " + voice_id)

    person = store.ensure_person(name)
    targets = [voice_id] + ([] if only_this else [
        other for other in by_id[voice_id]["same_as"]
        if by_id[other]["status"] != "named"
    ])
    pending = load_pending(run_dir.name, pending_dir)
    prints = []
    for target in targets:
        prints.extend(pending.get(target, []))
        voice = by_id[target]
        voice.update({
            "status": "named", "person_id": person.person_id,
            "person": person.name, "via": "user",
        })

    enrolled = 0
    if len(prints) >= vp.MIN_FINGERPRINTS_TO_ENROLL:
        enrolled = store.enroll(person.person_id, prints)

    hint = document.get("hint")
    if hint and set(hint["voice_ids"]) & set(targets):
        document["hint"] = None
    write_speakers(run_dir, document)
    return {"person_id": person.person_id, "voices": targets, "enrolled": enrolled}


def identify_recording(
    run_dir: Path,
    audio_path: Path,
    python_path: str | Path,
    store: vp.VoiceStore,
    expected_names: Sequence[str] = (),
    *,
    pending_dir: Path = PENDING_DIR,
    runner: Callable = subprocess.run,
    worker_path: Path = WORKER_PATH,
) -> dict:
    """Analyze a meeting's Remote track and write its speakers.json."""
    payload = run_worker(audio_path, python_path, worker_path=worker_path,
                         runner=runner)
    document = build_speakers_document(payload, store, expected_names)
    write_speakers(run_dir, document)
    if not payload.get("remote_silent"):
        save_pending(Path(run_dir).name, payload, pending_dir)
    return document
