"""Review recurring unnamed voices: list them, listen to clips, name them.

The command line (``voice_cli.py unknowns``) and the app share this logic.
Groups are identified by a stable key made from their members, so a group
keeps its identity when the list is re-sorted or new meetings are added
elsewhere (a plain position number would shift).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Callable

import voice_auto
import voice_groups
import voice_profiles as vp
import voice_service as vs
import voice_sources

CLIPS_DIR = vs.VOICES_DIR / "clips"
STATE_PATH = vs.VOICES_DIR / "review_state.json"
MAX_NAME_LENGTH = 60


class ReviewError(ValueError):
    """A problem worth showing to the user as it is."""


def list_runs(output_dir: Path, archive_dir: Path, no_archive: bool) -> list[Path]:
    """Every meeting folder, newest first. A meeting in both places is listed
    once, from the output folder."""
    roots = [output_dir] + ([] if no_archive else [archive_dir])
    seen: set[str] = set()
    runs: list[Path] = []
    for root in roots:
        if not Path(root).is_dir():
            continue
        for folder in Path(root).iterdir():
            if (folder.is_dir() and folder.name not in seen
                    and re.match(r"\d{4}-\d{2}-\d{2}_", folder.name)):
                seen.add(folder.name)
                runs.append(folder)
    runs.sort(key=lambda d: d.name, reverse=True)
    return runs


def collect_occurrences(runs, pending_dir: Path, min_seconds: float):
    items = []
    for folder in runs:
        try:
            document = vs.read_speakers(folder)
        except vs.VoiceServiceError:
            continue
        if not document:
            continue
        pending = vs.load_pending(folder.name, pending_dir)
        for voice in document.get("voices", []):
            prints = pending.get(voice["id"]) or []
            if (voice["status"] == "unknown" and voice["seconds"] >= min_seconds
                    and len(prints) >= 2 and not vs.is_noise(voice)):
                items.append(voice_groups.Occurrence(
                    folder.name, voice["id"], voice["seconds"], vp.centroid(prints)))
    return items


def build_groups(
    output_dir: Path,
    archive_dir: Path,
    pending_dir: Path,
    store: vp.VoiceStore,
    *,
    min_meetings: int = 2,
    min_seconds: float = vp.MIN_VOICE_SECONDS,
    no_archive: bool = False,
):
    """(runs, groups) for the recurring unnamed voices, biggest first."""
    runs = list_runs(output_dir, archive_dir, no_archive)
    items = collect_occurrences(runs, pending_dir, min_seconds)
    known: set[str] = set()
    for person in store.people():
        for name in person.names():
            known.add(name.lower())
    all_names = [r.name for r in runs]
    groups = [g for g in voice_groups.cluster_occurrences(items)
              if len(g.runs) >= min_meetings]
    for group in groups:
        group.hints = voice_groups.title_hints(group.runs, all_names, known)
    return runs, groups


def group_id(group) -> str:
    """A key that stays the same while the group's members stay the same."""
    members = sorted(f"{m.run}|{m.voice_id}" for m in group.members)
    return hashlib.sha1("\n".join(members).encode("utf-8")).hexdigest()[:12]


def find_group(groups, key: str):
    for group in groups:
        if group_id(group) == key:
            return group
    raise ReviewError(
        "That group has changed since the list was loaded. Refresh and try again."
    )


# ----------------------------------------------------------- hide / ignore --
#
# Two ways to set a group aside without naming it:
#   hidden  - "not now": it moves to a Hidden section and can come back.
#   ignored - "don't track": the person does not matter; it moves to an
#             Ignored section and is never counted as a missing name.
# Both are remembered per voice (meeting folder + voice number), never by
# fingerprint, so nothing about the person's voice is saved. A group counts as
# hidden or ignored only while every one of its voices is. When a later
# meeting adds a voice to the group, that voice is new, so the group shows
# again and can be set aside again.

STATE_ACTIONS = ("hide", "ignore", "restore")


def member_keys(group) -> set[str]:
    return {f"{m.run}|{m.voice_id}" for m in group.members}


def load_state(path: Path | None = None) -> dict[str, set[str]]:
    path = Path(path or STATE_PATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    def keys(name: str) -> set[str]:
        value = data.get(name)
        return {k for k in value if isinstance(k, str)} if isinstance(value, list) else set()

    return {"hidden": keys("hidden"), "ignored": keys("ignored")}


def save_state(state: dict[str, set[str]], path: Path | None = None) -> None:
    vs._write_private_json(
        Path(path or STATE_PATH),
        {"version": 1,
         "hidden": sorted(state["hidden"]),
         "ignored": sorted(state["ignored"])},
    )


def group_status(group, state: dict[str, set[str]]) -> str:
    """"active", "hidden" or "ignored"."""
    keys = member_keys(group)
    if keys and keys <= state["ignored"]:
        return "ignored"
    if keys and keys <= (state["hidden"] | state["ignored"]):
        return "hidden"
    return "active"


def set_group_status(group, action: str, state: dict[str, set[str]]) -> None:
    """Apply "hide", "ignore" or "restore" to the state (caller saves it)."""
    if action not in STATE_ACTIONS:
        raise ReviewError("Unknown action: " + str(action))
    keys = member_keys(group)
    state["hidden"] -= keys
    state["ignored"] -= keys
    if action == "hide":
        state["hidden"] |= keys
    elif action == "ignore":
        state["ignored"] |= keys


def clear_clips(clips_dir: Path | None = None) -> int:
    """Delete saved listening clips; returns how many were removed."""
    clips_dir = Path(clips_dir or CLIPS_DIR)
    removed = 0
    if clips_dir.is_dir():
        for path in clips_dir.glob("*.wav"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def describe_group(group) -> dict:
    """The facts about a group, ready to show (and to send as JSON)."""
    runs = group.runs
    return {
        "id": group_id(group),
        "meetings": len(runs),
        "voices": len(group.members),
        "minutes": round(group.seconds / 60, 1),
        "first": runs[0][:10],
        "last": runs[-1][:10],
        "hints": [word for word, _ in group.hints],
        "loose": bool(group.loose),
        "recent": [voice_sources.recording_suffix(r) for r in reversed(runs[-4:])],
    }


def make_group_clips(
    group,
    runs,
    meetings_dir: Path,
    archive_dir: Path,
    clips_dir: Path,
    *,
    count: int = 3,
    clipper: Callable = voice_sources.make_clip,
) -> list[dict]:
    """Short audio clips of a group, each from a different meeting.

    Returns [{"path", "meeting", "seconds"}]. Old clips in ``clips_dir`` are
    removed first: they are other people's voices and should not pile up.
    """
    clips_dir = Path(clips_dir)
    if clips_dir.is_dir():
        for old in clips_dir.glob("*.wav"):
            try:
                old.unlink()
            except OSError:
                pass

    by_name = {r.name: r for r in runs}
    key = group_id(group)
    options = []
    for member in group.members:
        folder = by_name.get(member.run)
        if folder is None:
            continue
        document = vs.read_speakers(folder) or {"voices": []}
        turns = next((v["turns"] for v in document["voices"]
                      if v["id"] == member.voice_id), [])
        window = voice_sources.pick_clip_window(turns)
        if window:
            options.append((window[1], member, folder, window))
    options.sort(key=lambda o: -o[0])

    clips: list[dict] = []
    used: set[str] = set()
    for _, member, folder, (start, length) in options:
        if len(clips) >= count or member.run in used:
            continue
        audio = voice_sources.resolve_audio(folder, meetings_dir, None, archive_dir)
        if audio is None:
            continue
        out = clips_dir / f"{key}_{len(clips) + 1}.wav"
        try:
            clipper(audio, start, length, out)
        except Exception:
            continue
        used.add(member.run)
        clips.append({
            "path": str(out),
            "meeting": voice_sources.recording_suffix(member.run),
            "seconds": round(length),
        })
    return clips


# ------------------------------------------------------- one meeting's voices --

def find_run(run_name: str, output_dir: Path, archive_dir: Path) -> Path:
    """The folder for a meeting, from its name (never a path)."""
    if not run_name or "/" in run_name or run_name in (".", ".."):
        raise ReviewError("That meeting was not found.")
    for root in (output_dir, archive_dir):
        folder = Path(root) / run_name
        if folder.is_dir():
            return folder
    raise ReviewError("That meeting was not found.")


def _seconds_label(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def meeting_voices(run_dir: Path, pending_dir: Path) -> dict:
    """Everything the app needs to list one meeting's voices."""
    document = vs.read_speakers(run_dir)
    if document is None:
        raise ReviewError(
            "This meeting has no voice information yet. It is added after a "
            "transcription when voice recognition is on.")
    saved = vs.load_pending(Path(run_dir).name, pending_dir)
    voices = []
    for voice in sorted(document.get("voices", []), key=lambda v: -v["seconds"]):
        best = (voice.get("suggestions") or [None])[0]
        voices.append({
            "id": voice["id"],
            "label": voice["id"].replace("SPEAKER_", ""),
            "seconds": round(voice["seconds"]),
            "status": voice["status"],
            "person": voice.get("person"),
            "via": voice.get("via"),
            "suggestion": (
                {"person": best["person"], "score": best["score"]}
                if best and voice["status"] != "named" else None),
            "short": voice["seconds"] < vp.MIN_VOICE_SECONDS,
            "noise": voice.get("noise") if vs.is_noise(voice) else None,
            "can_learn": len(saved.get(voice["id"], []))
            >= vp.MIN_FINGERPRINTS_TO_ENROLL,
        })
    return {
        "run": Path(run_dir).name,
        "remote_silent": bool(document.get("remote_silent")),
        "voices": voices,
    }


def make_voice_clips(
    run_dir: Path,
    voice_id: str,
    meetings_dir: Path,
    archive_dir: Path,
    clips_dir: Path,
    *,
    count: int = 3,
    clipper: Callable = voice_sources.make_clip,
) -> list[dict]:
    """Short clips of one voice in one meeting, spread over its longest turns.
    Old clips are removed first."""
    clear_clips(clips_dir)
    document = vs.read_speakers(run_dir) or {"voices": []}
    turns = next((v["turns"] for v in document["voices"] if v["id"] == voice_id), None)
    if turns is None:
        raise ReviewError("That voice was not found in this meeting.")
    audio = voice_sources.resolve_audio(run_dir, meetings_dir, None, archive_dir)
    if audio is None:
        return []
    key = hashlib.sha1(f"{Path(run_dir).name}|{voice_id}".encode()).hexdigest()[:8]
    clips = []
    for start, length in voice_sources.pick_clip_windows(turns, count):
        out = Path(clips_dir) / f"{key}_{len(clips) + 1}.wav"
        try:
            clipper(audio, start, length, out)
        except Exception:
            continue
        clips.append({"path": str(out), "meeting": "at " + _seconds_label(start),
                      "seconds": round(length)})
    return clips


def name_meeting_voice(
    run_dir: Path,
    voice_id: str,
    name: str,
    store: vp.VoiceStore,
    pending_dir: Path,
    archive_dir: Path,
    *,
    only_this: bool = True,
    update_participants: bool | None = None,
) -> dict:
    """Name one voice in one meeting. The caller saves the store."""
    name = clean_name(name)
    try:
        info = vs.confirm_voice(run_dir, voice_id, name, store, pending_dir,
                                only_this=only_this)
    except vs.VoiceServiceError as error:
        raise ReviewError(str(error))
    vs.mirror_speakers(run_dir, archive_dir)
    if update_participants is None:
        update_participants = _participants_setting()
    if update_participants:
        document = vs.read_speakers(run_dir)
        if document:
            voice_auto._update_participants(run_dir, document, store, archive_dir)
    return {"named": len(info["voices"]), "learned": info["enrolled"]}


def correct_meeting_voice(
    run_dir: Path,
    voice_id: str,
    name: str,
    store: vp.VoiceStore,
    pending_dir: Path,
    archive_dir: Path,
    *,
    update_participants: bool | None = None,
) -> dict:
    """Change the name given to one voice, and take back what was learned.

    If the voice was named by hand, the fingerprints it taught the old person
    are removed (when the saved copies still exist), and a profile that was
    created only by this mistake is deleted. The voice is then named as the
    new person. The caller saves the store.
    """
    name = clean_name(name)
    document = vs.read_speakers(run_dir)
    voice = next((v for v in (document or {}).get("voices", [])
                  if v["id"] == voice_id), None)
    if voice is None:
        raise ReviewError("That voice was not found in this meeting.")
    if voice["status"] != "named":
        raise ReviewError("That voice has no name to change. Name it instead.")
    old = store.find(voice.get("person_id") or "")
    if old is not None and old.name.lower() == name.lower():
        raise ReviewError("That voice is already named " + old.name + ".")

    removed, removed_person, could_unlearn = 0, False, True
    if old is not None and voice.get("via") == "user":
        saved = vs.load_pending(Path(run_dir).name, pending_dir).get(voice_id)
        if saved:
            removed = store.remove_matching(old.person_id, saved)
            if not old.fingerprints:
                store.remove_person(old.person_id)
                removed_person = True
        else:
            could_unlearn = False

    info = name_meeting_voice(
        run_dir, voice_id, name, store, pending_dir, archive_dir,
        only_this=True, update_participants=update_participants)
    return {**info, "removed": removed, "removed_person": removed_person,
            "could_unlearn": could_unlearn,
            "was": old.name if old else None}


def recent_meetings(output_dir: Path, archive_dir: Path, limit: int = 20) -> list[dict]:
    """Newest meetings that have voice information, for choosing one."""
    found = []
    for folder in list_runs(output_dir, archive_dir, False):
        try:
            document = vs.read_speakers(folder)
        except vs.VoiceServiceError:
            continue
        if not document or document.get("remote_silent"):
            continue
        voices = document.get("voices", [])
        found.append({
            "run": folder.name,
            "title": voice_sources.recording_suffix(folder.name),
            "date": folder.name[:10],
            "voices": len(voices),
            "unnamed": sum(1 for v in voices
                           if v["status"] != "named" and not vs.is_noise(v)),
        })
        if len(found) >= limit:
            break
    return found


def _participants_setting() -> bool:
    try:
        import app_settings
        return bool(app_settings.load_app_settings().get(
            "voice_update_participants", True))
    except Exception:
        return True


def rematch_everything(
    output_dir: Path,
    archive_dir: Path,
    pending_dir: Path,
    store: vp.VoiceStore,
    *,
    no_archive: bool = False,
    update_participants: bool | None = None,
    progress=None,
    refresh_index_anyway: bool = False,
) -> dict:
    """Re-match every meeting against the current fingerprints (fast).

    Participant lists shown in the app come from the published index, so when
    any participants may have changed the index is rebuilt at the end."""
    if update_participants is None:
        update_participants = _participants_setting()
    runs = list_runs(output_dir, archive_dir, no_archive)
    counts = voice_auto.rematch_all(
        runs, store, pending_dir=pending_dir, archive_dir=archive_dir,
        update_participants=update_participants, progress=progress)
    if update_participants and (counts["updated"] or refresh_index_anyway):
        counts["index_refreshed"] = refresh_index(archive_dir)
    return counts


def refresh_index(archive_dir: Path) -> bool:
    """Rebuild the published-meeting index so the app shows current
    participant lists. Never raises; False if it could not be done."""
    try:
        archive_dir = Path(archive_dir)
        if not any(archive_dir.glob("*/meeting_metadata.json")):
            return False
        from dashboard_generator import build_meeting_dashboard
        from indexer import build_meeting_index
        index_path = build_meeting_index(archive_dir)
        build_meeting_dashboard(index_path)
        return True
    except Exception:
        return False


def rematch_summary(counts: dict) -> str:
    text = f"Updated {counts['updated']} meetings"
    if counts["no_data"]:
        text += (f"; {counts['no_data']} older meetings would need a full "
                 "re-analysis to be checked")
    return text + "."


def clean_name(name: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ReviewError("Type a name first.")
    if len(text) > MAX_NAME_LENGTH:
        raise ReviewError(f"Names are limited to {MAX_NAME_LENGTH} characters.")
    return text


def name_group(
    group,
    runs,
    name: str,
    store: vp.VoiceStore,
    pending_dir: Path,
    archive_dir: Path | None,
) -> dict:
    """Name every voice in a group. The caller saves the store.

    Returns {"named": voices named, "meetings": meetings touched,
    "learned": fingerprints learned}.
    """
    name = clean_name(name)
    by_name = {r.name: r for r in runs}
    named = learned = 0
    touched: set[str] = set()
    for member in group.members:
        folder = by_name.get(member.run)
        if folder is None:
            continue
        document = vs.read_speakers(folder)
        current = {v["id"]: v for v in document["voices"]}
        if current[member.voice_id]["status"] == "named":
            continue
        info = vs.confirm_voice(folder, member.voice_id, name, store, pending_dir)
        vs.mirror_speakers(folder, archive_dir)
        named += len(info["voices"])
        learned += info["enrolled"]
        touched.add(member.run)
    return {"named": named, "meetings": len(touched), "learned": learned}
