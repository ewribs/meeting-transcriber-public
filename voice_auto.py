"""Optional voice step that runs after a transcription finishes.

Off unless the user turns it on (setting ``voice_recognition_enabled``).
It can never fail a transcription: every problem is caught and reported
as a short status string.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import voice_participants as vpart
import voice_profiles as vp
import voice_service as vs

AUTO_TIMEOUT_SECONDS = 15 * 60
LOG_PATH = vs.VOICES_DIR / "auto.log"
LOG_KEEP_LINES = 200


def log_status(run_name: str, status: str, log_path: Path = LOG_PATH) -> None:
    """Append one line to the voice log. Never raises. The log holds meeting
    names and counts only, no audio or fingerprints."""
    try:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = []
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
        lines.append(f"{stamp}  {run_name}  {status}")
        log_path.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n",
                            encoding="utf-8")
    except OSError:
        pass


def recent_log(count: int = 5, log_path: Path = LOG_PATH) -> list[str]:
    try:
        lines = Path(log_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return lines[-count:]


def _run_voice_step(
    run_dir: Path,
    audio_path: Path | None,
    settings: dict,
    *,
    store_path: Path = vs.STORE_PATH,
    pending_dir: Path = vs.PENDING_DIR,
    archive_dir: Path | None = None,
    analyzer: Callable | None = None,
) -> str:
    """Identify voices for one finished meeting. Returns a status line.

    Statuses: "off", "no audio", "not set up", "no profiles yet", "done: ...",
    or "skipped: ..." when something went wrong.
    """
    try:
        if not settings.get("voice_recognition_enabled"):
            return "off"
        if audio_path is None or not Path(audio_path).exists():
            return "no audio"
        python_path = settings.get("voice_python")
        if not python_path and analyzer is None:
            return "not set up"
        store = vp.VoiceStore.load(store_path)
        if not store.people():
            return "no profiles yet"

        if analyzer is None:
            def analyzer(audio: Path) -> dict:
                return vs.run_worker(audio, python_path,
                                     timeout=AUTO_TIMEOUT_SECONDS)

        payload = analyzer(Path(audio_path))
        document = vs.keep_confirmations(
            vs.read_speakers(run_dir),
            vs.build_speakers_document(payload, store),
        )
        _mark_static(audio_path, document)
        vs.write_speakers(run_dir, document)
        vs.mirror_speakers(run_dir, archive_dir)
        if not payload.get("remote_silent"):
            vs.save_pending(Path(run_dir).name, payload, pending_dir)
        if payload.get("remote_silent"):
            return _mic_track_step(
                run_dir, analyzer, store, pending_dir, archive_dir)
        voices = document.get("voices", [])
        named = sum(1 for v in voices if v.get("person"))
        status = f"done: {named} of {len(voices)} voices named"
        if settings.get("voice_update_participants", True):
            status += _update_participants(
                run_dir, document, store, archive_dir)
        return status
    except BaseException as error:  # never let this break a transcription
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        return f"skipped: {error}"


def _mic_track_step(run_dir, analyzer, store, pending_dir, archive_dir) -> str:
    """The remote track was silent, so everyone is on the mic track (a
    speakerphone call, say). Analyse that track instead. Voices are only
    named by a direct match: look-alike voices are never grouped, because
    on one microphone different people blend together. Never raises."""
    base = "done: remote audio was not captured"
    try:
        mic = Path(run_dir) / "audio" / "mic.wav"
        if not mic.exists():
            return base
        payload = analyzer(mic)
        document = vs.build_speakers_document(payload, store, group=False)
        document["track"] = "mic"
        document = vs.keep_confirmations(vs.read_speakers(run_dir), document)
        vs.write_speakers(run_dir, document)
        vs.mirror_speakers(run_dir, archive_dir)
        vs.save_pending(Path(run_dir).name, payload, pending_dir)
        voices = document.get("voices", [])
        named = sum(1 for v in voices if v.get("person"))
        return f"{base}; mic track: {named} of {len(voices)} voices named"
    except Exception as error:      # noqa: BLE001 - never fail a transcription
        return f"{base}; mic track not analysed ({error})"


def _mark_static(audio_path, document: dict) -> None:
    """Mark unnamed voices that are really static. Never raises."""
    try:
        import voice_noise
        voice_noise.tag_document(Path(audio_path), document)
    except Exception:
        pass


def _update_participants(run_dir, document, store, archive_dir) -> str:
    """Replace the transcript-based participant list with the voice-based
    one. Never raises; returns a short suffix for the status line."""
    try:
        known = [n for person in store.people() for n in person.names()]
        new = vpart.build_participants(Path(run_dir).name, document, known)
        if new is None:
            return ""
        changed = vpart.apply_to_run(Path(run_dir), new)
        if archive_dir is not None:
            twin = Path(archive_dir) / Path(run_dir).name
            if (twin / "meeting_metadata.json").exists():
                vpart.apply_to_run(twin, new)
        return ", participants updated" if changed else ", participants already match"
    except Exception as error:
        return f", participants not updated ({error})"


def run_voice_step(
    run_dir: Path,
    audio_path: Path | None,
    settings: dict,
    *,
    log_path: Path = LOG_PATH,
    **kwargs,
) -> str:
    """Run the step, record the outcome in the voice log, return the status."""
    status = _run_voice_step(run_dir, audio_path, settings, **kwargs)
    if status != "off":
        log_status(Path(run_dir).name, status, log_path)
        _prune_saved_fingerprints(
            settings, kwargs.get("pending_dir", vs.PENDING_DIR))
    return status


def run_early_voice_step(
    run_dir: Path,
    audio_path: Path | None,
    settings: dict,
    **kwargs,
) -> str:
    """Identify voices before the transcript is cleaned, so the cleaning and
    extraction steps can use people's names.

    The participant list is not touched here: the meeting's metadata does not
    exist yet. finish_participants() does that at the end.
    """
    return run_voice_step(
        run_dir, audio_path,
        {**settings, "voice_update_participants": False},
        **kwargs)


def finish_participants(run_dir: Path, settings: dict, archive_dir: Path | None = None,
                        store_path: Path = vs.STORE_PATH) -> str:
    """After an early voice step: update the participant list from the saved
    voices, without analysing the audio again. Returns a status suffix."""
    try:
        if not settings.get("voice_update_participants", True):
            return ""
        document = vs.read_speakers(run_dir)
        if document is None:
            return ""
        store = vp.VoiceStore.load(store_path)
        return _update_participants(run_dir, document, store, archive_dir)
    except Exception as error:      # noqa: BLE001 - never fail a transcription
        return f", participants not updated ({error})"


def _prune_saved_fingerprints(settings: dict, pending_dir: Path) -> None:
    """Delete saved fingerprints of unnamed voices past the keep limit.
    Never raises."""
    try:
        days = vs.pending_days_setting(settings)
        if days > 0:
            vs.prune_pending(pending_dir, days)
    except Exception:
        pass


def rematch_all(
    runs,
    store: vp.VoiceStore,
    *,
    pending_dir: Path = vs.PENDING_DIR,
    archive_dir: Path | None = None,
    update_participants: bool = True,
    progress: Callable[[str, str], None] | None = None,
) -> dict:
    """Re-match every meeting against the current fingerprints, quickly.

    Counts: updated, same, no_data (needs a full re-analysis), failed.
    Never raises for one bad meeting.
    """
    counts = {"updated": 0, "same": 0, "no_data": 0, "failed": 0}
    for run_dir in runs:
        try:
            outcome, document = vs.rematch_run(
                run_dir, store, pending_dir, archive_dir)
            if outcome == "updated":
                counts["updated"] += 1
                if update_participants and document is not None:
                    _update_participants(run_dir, document, store, archive_dir)
            elif outcome == "same":
                counts["same"] += 1
            elif outcome == "no data":
                counts["no_data"] += 1
        except Exception as error:
            counts["failed"] += 1
            outcome = f"failed ({error})"
        if progress:
            progress(Path(run_dir).name, outcome)
    return counts
