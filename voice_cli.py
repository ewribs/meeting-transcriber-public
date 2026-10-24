#!/usr/bin/env python3
"""Voice profiles: command line.

    python3 voice_cli.py set-python PATH     tell the app where the voice
                                             environment's Python is
    python3 voice_cli.py check               check the voice environment is ready
    python3 voice_cli.py enroll              learn people from one-on-ones
    python3 voice_cli.py people              list who is known
    python3 voice_cli.py identify RUN        work out who spoke in a meeting
    python3 voice_cli.py identify-all        do that for every meeting that
                                             has not been done yet
    python3 voice_cli.py unknowns            list unnamed voices that keep
                                             coming back, and name them
    python3 voice_cli.py rematch             re-check every meeting against the
                                             current fingerprints (fast, no audio)
    python3 voice_cli.py noise-check RUN     measure whether each voice is speech
                                             or static
    python3 voice_cli.py show RUN            show what was worked out
    python3 voice_cli.py confirm RUN ...     say who a voice is

RUN is a meeting's folder name (or path). Nothing here changes the
transcript; names are kept in the meeting's speakers.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

import voice_auto
import voice_groups
import voice_participants
import voice_profiles as vp
import voice_service as vs
import voice_review
import voice_sources


def _default_dirs() -> tuple[Path, Path, Path]:
    import config
    return config.OUTPUT_DIR, config.MEETINGS_DIR, config.ARCHIVE_DIR


def _voice_python(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if os.environ.get("MT_VOICE_PYTHON"):
        return os.environ["MT_VOICE_PYTHON"]
    from app_settings import load_app_settings
    return load_app_settings().get("voice_python") or None


def _make_worker(python_path: str, cache_dir: Path) -> Callable[[Path], dict]:
    def worker(audio: Path) -> dict:
        cache = cache_dir / (Path(audio).stem + ".json")
        if cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        payload = vs.run_worker(audio, python_path)
        vs._write_private_json(cache, payload)
        return payload
    return worker


_list_runs = voice_review.list_runs
_collect_occurrences = voice_review.collect_occurrences


def _resolve_run(run: str, output_dir: Path) -> Path | None:
    direct = Path(run)
    if direct.is_dir():
        return direct
    inside = Path(output_dir) / run
    return inside if inside.is_dir() else None


def _short(voice_id: str) -> str:
    return voice_id.replace("SPEAKER_", "")


def print_document(document: dict, run_name: str) -> None:
    if document.get("remote_silent"):
        print("The other people were not captured in this recording "
              "(the Remote track is silent), so voices cannot be identified.")
        return
    voices = sorted(document["voices"], key=lambda v: -v["seconds"])
    print(f"{len(voices)} voices in {run_name}\n")
    for voice in voices:
        minutes = f"{voice['seconds'] / 60:4.1f} min"
        label = _short(voice["id"])
        if voice["status"] == "named":
            how = {"match": "matched", "grouped": "same voice as a matched one",
                   "user": "confirmed by you"}.get(voice["via"], voice["via"])
            print(f"  {label:>3}  {minutes}  {voice['person']}  ({how})")
        elif voice["status"] == "too_short":
            print(f"  {label:>3}  {minutes}  too little speech to judge")
        else:
            best = voice["suggestions"][0] if voice["suggestions"] else None
            if best and best["score"] >= 0.4:
                note = f"closest known: {best['person']} {best['score']:.2f}, not confident"
            elif best:
                note = "no known voice is close"
            else:
                note = "no profiles yet"
            print(f"  {label:>3}  {minutes}  unknown  ({note})")
    hint = document.get("hint")
    if hint:
        ids = ", ".join(_short(v) for v in hint["voice_ids"])
        print(f"\nSuggestion: voice {ids} may be {hint['name']} "
              "(everyone else expected is accounted for).")
        print(f"To accept: python3 voice_cli.py confirm {run_name} --accept-hint")


def _load_store(path: Path) -> vp.VoiceStore:
    return vp.VoiceStore.load(path)


def main(
    argv: list[str] | None = None,
    *,
    worker: Callable[[Path], dict] | None = None,
    voices_dir: Path | None = None,
    dirs: tuple[Path, Path, Path] | None = None,
    ask: Callable[[str], str] = input,
    clipper: Callable = voice_sources.make_clip,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--python", help="Python of the voice environment")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("set-python")
    p.add_argument("path")

    p = sub.add_parser("people")
    p.add_argument("--delete", metavar="NAME")

    p = sub.add_parser("enroll")
    p.add_argument("--meetings", action="append", type=Path, default=None)
    p.add_argument("--archive", action="append", type=Path, default=None)
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--exclude", action="append", default=[])
    p.add_argument("--min-recordings", type=int, default=1)
    p.add_argument("--yes", action="store_true", help="do not ask first")

    p = sub.add_parser("identify")
    p.add_argument("run")
    p.add_argument("--audio", type=Path)
    p.add_argument("--expect", default="", help="comma-separated names expected")

    p = sub.add_parser("identify-all")
    p.add_argument("--limit", type=int, help="stop after this many meetings")
    p.add_argument("--redo", action="store_true", help="also redo finished meetings")
    p.add_argument("--no-archive", action="store_true")

    p = sub.add_parser("rematch", help="re-check all meetings against current fingerprints (fast)")
    p.add_argument("--no-archive", action="store_true")

    sub.add_parser("check", help="check that the voice environment is ready")

    p = sub.add_parser("noise-scan", help="mark voices in all meetings that are really static")
    p.add_argument("--redo", action="store_true", help="also re-check meetings already checked")
    p.add_argument("--no-archive", action="store_true")

    p = sub.add_parser("noise-check", help="measure whether each voice in a meeting is speech or static")
    p.add_argument("run")
    p.add_argument("--audio", type=Path)

    p = sub.add_parser("participants")
    p.add_argument("--limit", type=int, default=20, help="meetings to show")
    p.add_argument("--all", action="store_true", help="include meetings that agree")
    p.add_argument("--no-archive", action="store_true")

    p = sub.add_parser("participants-new")
    p.add_argument("--limit", type=int, default=20, help="meetings to show")
    p.add_argument("--apply", action="store_true",
                   help="write the new lists (the old ones are kept for undo)")
    p.add_argument("--restore", action="store_true",
                   help="put the old lists back")

    p = sub.add_parser("unknowns")
    p.add_argument("--min-meetings", type=int, default=2)
    p.add_argument("--min-seconds", type=float, default=vp.MIN_VOICE_SECONDS)
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--name", nargs=2, metavar=("GROUP", "NAME"),
                   help="name a group, e.g. --name 1 Jordan")
    p.add_argument("--show", type=int, metavar="GROUP",
                   help="list every meeting a group appears in")
    p.add_argument("--clips", type=int, metavar="GROUP",
                   help="save a few short audio clips to listen to")
    p.add_argument("--count", type=int, default=3, help="clips to save")
    p.add_argument("--out", type=Path, help="folder for clips (default ~/voice-clips)")

    p = sub.add_parser("auto")
    p.add_argument("state", nargs="?", choices=["on", "off", "status"],
                   default="status")

    p = sub.add_parser("show")
    p.add_argument("run")
    p.add_argument("--clips", action="store_true",
                   help="save a short audio clip of each voice to listen to")
    p.add_argument("--count", type=int, default=1,
                   help="clips to save of each voice (default 1)")
    p.add_argument("--out", type=Path, help="folder for clips (default ~/voice-clips)")

    p = sub.add_parser("confirm")
    p.add_argument("run")
    p.add_argument("name", nargs="?")
    p.add_argument("--voice")
    p.add_argument("--accept-hint", action="store_true")

    args = parser.parse_args(argv)

    voices_dir = Path(voices_dir) if voices_dir else vs.VOICES_DIR
    store_path = voices_dir / "profiles.json"
    pending_dir = voices_dir / "pending"
    cache_dir = voices_dir / "cache"
    enrolled_path = voices_dir / "enrolled.json"

    try:
        # ---------------------------------------------------------- set-python
        if args.command == "set-python":
            if not Path(args.path).expanduser().exists():
                print("Not found: " + args.path)
                return 2
            from app_settings import update_app_setting
            update_app_setting("voice_python", str(Path(args.path).expanduser()))
            print("Saved.")
            return 0

        # ----------------------------------------------------------------- auto
        if args.command == "auto":
            import app_settings
            settings = app_settings.load_app_settings()
            if args.state in ("on", "off"):
                if args.state == "on":
                    if not settings.get("voice_python"):
                        print("Voice environment not set. Run: "
                              "python3 voice_cli.py set-python PATH_TO_PYTHON")
                        return 2
                    if not vp.VoiceStore.load(store_path).people():
                        print("No voice profiles yet. Enroll or name some people first.")
                        return 2
                app_settings.update_app_setting(
                    "voice_recognition_enabled", args.state == "on")
                settings = app_settings.load_app_settings()
            on = bool(settings.get("voice_recognition_enabled"))
            print("Automatic voice recognition after each transcription: "
                  + ("ON" if on else "off"))
            if on:
                print("It adds roughly half a minute per meeting and never "
                      "affects the transcript if it fails.")
            recent = voice_auto.recent_log(5, voices_dir / "auto.log")
            if recent:
                print("\nMost recent runs:")
                for line in recent:
                    print("  " + line)
            return 0

        # -------------------------------------------------------------- people
        if args.command == "people":
            store = _load_store(store_path)
            if args.delete:
                person = store.find(args.delete)
                if person is None:
                    print("No such person: " + args.delete)
                    return 1
                store.remove_person(person.person_id)
                store.save(store_path)
                if enrolled_path.exists():
                    done = json.loads(enrolled_path.read_text(encoding="utf-8"))
                    done.pop(person.person_id, None)
                    vs._write_private_json(enrolled_path, done)
                print(f"Deleted the voice profile for {person.name}.")
                return 0
            if not store.people():
                print("No voice profiles yet. Try: python3 voice_cli.py enroll")
                return 0
            print(f"{'Name':20} {'Recordings':>10} {'Fingerprints':>13}")
            for person in store.people():
                print(f"{person.name:20} {person.enrollments:>10} {len(person.fingerprints):>13}")
            return 0

        # --------------------------------------------------------------- enroll
        if args.command == "enroll":
            output_dir, meetings_dir, archive_dir = dirs or _default_dirs()
            folders = args.meetings or [meetings_dir]
            archives = [] if args.no_archive else (args.archive or [archive_dir])
            groups = voice_sources.find_recordings(folders, archives, args.exclude)
            groups = {p: f for p, f in groups.items() if len(f) >= args.min_recordings}
            if not groups:
                print("No one-on-one recordings found.")
                return 0
            done = (json.loads(enrolled_path.read_text(encoding="utf-8"))
                    if enrolled_path.exists() else {})
            store = _load_store(store_path)

            todo: list[tuple[str, Path]] = []
            for person in sorted(groups, key=lambda p: (-len(groups[p]), p)):
                existing = store.find(person)
                already = set(done.get(existing.person_id, [])) if existing else set()
                new = [f for f in groups[person] if f.name not in already]
                shown = voice_sources.display_name(groups[person][0].name)
                print(f"{shown}: {len(groups[person])} recordings, {len(new)} new")
                for f in new:
                    print("    " + f.name)
                todo += [(person, f) for f in new]
            if not todo:
                print("\nNothing new to learn.")
                return 0
            if not args.yes:
                reply = ask(f"\nLearn from {len(todo)} recordings? "
                            "Check the names above first. [y/N] ")
                if reply.strip().lower() not in ("y", "yes"):
                    print("Cancelled.")
                    return 1
            python_path = None
            if worker is None:
                python_path = _voice_python(args.python)
                if not python_path:
                    print("Voice environment not set. Run: "
                          "python3 voice_cli.py set-python PATH_TO_PYTHON")
                    return 2
                worker = _make_worker(python_path, cache_dir)

            learned = skipped = 0
            for person, path in todo:
                try:
                    payload = worker(path)
                    info = vs.enroll_one_on_one(
                        store, voice_sources.display_name(path.name), payload
                    )
                except vs.VoiceServiceError as error:
                    skipped += 1
                    print(f"  skipped {path.name}: {error}")
                    continue
                learned += 1
                done.setdefault(info["person_id"], []).append(path.name)
                store.save(store_path)
                vs._write_private_json(enrolled_path, done)
                print(f"  learned {path.name}: {info['person_id']} "
                      f"(+{info['added']} fingerprints)")
            print(f"\nLearned from {learned} recordings, skipped {skipped}.")
            return 0

        # ------------------------------------------------------------- unknowns
        if args.command == "participants":
            output_dir, _, archive_dir = dirs or _default_dirs()
            runs = _list_runs(output_dir, archive_dir, args.no_archive)
            comparisons = []
            for folder in runs:
                meta_path = folder / "meeting_metadata.json"
                try:
                    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    metadata = None
                comparisons.append(voice_participants.compare(
                    folder.name, metadata, vs.read_speakers(folder)))
            usable = [c for c in comparisons if c.usable]
            if not usable:
                print("No meetings have voice data yet. Run identify-all first.")
                return 0
            shown = [c for c in usable if args.all or c.differs]
            for c in shown[:args.limit]:
                print(c.run)
                print("   agree      : " + (", ".join(c.both) or "-"))
                if c.text_only:
                    print("   text only  : " + ", ".join(c.text_only)
                          + "   (named in the transcript, no matching voice)")
                if c.voice_only:
                    print("   voice only : " + ", ".join(c.voice_only)
                          + "   (heard, missing from the list)")
                if c.unnamed_voices:
                    print(f"   not yet named: {c.unnamed_voices} voice(s)")
            if len(shown) > args.limit:
                print(f"\n... and {len(shown) - args.limit} more "
                      "(use --limit to see more)")
            differing = [c for c in usable if c.differs]
            print(f"\n{len(usable)} meetings compared; "
                  f"{len(differing)} differ.")
            print(f"  voices found people the text list missed in "
                  f"{sum(1 for c in usable if c.voice_only)} meetings")
            print(f"  text list named someone not heard in "
                  f"{sum(1 for c in usable if c.text_only)} meetings")
            missing = voice_participants.never_heard(usable)
            enrolled = [n for person in _load_store(store_path).people()
                        for n in person.names()]
            fresh = [(n, k) for n, k in missing
                     if not any(voice_participants.same_person(n, e) for e in enrolled)]
            known = [(n, k) for n, k in missing
                     if any(voice_participants.same_person(n, e) for e in enrolled)]
            if fresh:
                print("\nNamed in transcripts but not fingerprinted yet "
                      "(people to add, or just people who were mentioned):")
                for name, count in fresh[:15]:
                    print(f"  {name}: {count} meetings")
            if known:
                print("\nAlready fingerprinted, but not heard in these meetings "
                      "(mentioned, or spoke too little to judge):")
                for name, count in known[:10]:
                    print(f"  {name}: {count} meetings")
            return 0

        if args.command == "participants-new":
            output_dir, _, archive_dir = dirs or _default_dirs()
            runs = _list_runs(output_dir, archive_dir, True)
            def archive_twin(folder: Path):
                """The same meeting's published copy, which the app reads."""
                twin = Path(archive_dir) / folder.name
                if twin.is_dir() and (twin / "meeting_metadata.json").exists():
                    return twin
                return None

            if args.restore:
                restored = 0
                for folder in runs:
                    for target in (folder, archive_twin(folder)):
                        if target is None:
                            continue
                        try:
                            restored += voice_participants.restore_run(target)
                        except (OSError, ValueError):
                            pass
                print(f"Restored the old participant list in {restored} meetings.")
                if restored:
                    print("Refresh the app's index: tools/mt rebuild-index")
                return 0
            store = _load_store(store_path)
            known = [n for person in store.people() for n in person.names()]
            changed = unchanged = skipped = 0
            shown = 0
            for folder in runs:
                meta_path = folder / "meeting_metadata.json"
                try:
                    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    skipped += 1
                    continue
                new = voice_participants.build_participants(
                    folder.name, vs.read_speakers(folder), known)
                if new is None:
                    skipped += 1
                    continue
                old_names = voice_participants.text_names(metadata)
                new_names = [p["name"] + ("*" if p["confidence"] == "low" else "")
                             for p in new]
                if [p["name"] for p in new] == old_names and not any(
                        p["confidence"] == "low" for p in new):
                    unchanged += 1
                    continue
                changed += 1
                if args.apply:
                    voice_participants.apply_to_run(folder, new)
                    twin = archive_twin(folder)
                    if twin is not None:
                        try:
                            voice_participants.apply_to_run(twin, new)
                        except (OSError, ValueError):
                            print(f"  could not update the published copy of {folder.name}")
                elif shown < args.limit:
                    shown += 1
                    print(folder.name)
                    print("   now : " + (", ".join(old_names) or "-"))
                    print("   new : " + (", ".join(new_names) or "-"))
            if args.apply:
                print(f"Updated {changed} meetings; {unchanged} already matched; "
                      f"{skipped} left alone (no voice data).")
                print("To see the change in the app, refresh the index: "
                      "tools/mt rebuild-index")
                print("To undo: python3 voice_cli.py participants-new --restore")
            else:
                if changed > shown:
                    print(f"\n... and {changed - shown} more (use --limit to see more)")
                print(f"\nDry run. {changed} meetings would change, "
                      f"{unchanged} already match, {skipped} have no voice data "
                      "and stay as they are.")
                print("* = named in the title, but not heard")
                print("To apply: python3 voice_cli.py participants-new --apply")
            return 0

        if args.command == "unknowns":
            output_dir, _, archive_dir = dirs or _default_dirs()
            store = _load_store(store_path)
            runs = _list_runs(output_dir, archive_dir, args.no_archive)
            items = _collect_occurrences(runs, pending_dir, args.min_seconds)
            if not items:
                print("No unnamed voices to group. Run identify-all first.")
                return 0
            known: set[str] = set()
            for person in store.people():
                for name in person.names():
                    known.add(name.lower())
            all_names = [r.name for r in runs]
            groups = [g for g in voice_groups.cluster_occurrences(items)
                      if len(g.runs) >= args.min_meetings]
            for group in groups:
                group.hints = voice_groups.title_hints(group.runs, all_names, known)
            if not groups:
                print(f"No voice appears in {args.min_meetings} or more meetings yet.")
                return 0

            def describe(number: int, group) -> None:
                minutes = group.seconds / 60
                first, last = group.runs[0][:10], group.runs[-1][:10]
                print(f"Group {number}: {len(group.runs)} meetings, "
                      f"{minutes:.0f} min of speech  ({first} to {last})")
                if group.hints:
                    print("    title hints: " + ", ".join(
                        f"{w} ({n} of {len(group.runs)})" for w, n in group.hints))
                shown = [voice_sources.recording_suffix(r) for r in group.runs[-4:]]
                print("    recent meetings: " + "; ".join(shown))
                if group.loose:
                    print("    note: this group may mix more than one person")

            def pick(number_text: str):
                try:
                    number = int(number_text)
                    if number < 1:
                        raise IndexError
                    return number, groups[number - 1]
                except (ValueError, IndexError):
                    print(f"No group {number_text}. Run unknowns to see the list.")
                    return None

            if args.show is not None:
                chosen = pick(str(args.show))
                if chosen is None:
                    return 2
                number, group = chosen
                describe(number, group)
                print()
                for member in sorted(group.members, key=lambda m: m.run, reverse=True):
                    print(f"  {member.run[:10]}  "
                          f"{voice_sources.recording_suffix(member.run)}  "
                          f"voice {_short(member.voice_id)}  "
                          f"{member.seconds / 60:.1f} min")
                return 0

            if args.clips is not None:
                chosen = pick(str(args.clips))
                if chosen is None:
                    return 2
                number, group = chosen
                out_dir = (args.out or Path.home() / "voice-clips").expanduser()
                by_name = {r.name: r for r in runs}
                options = []
                for member in group.members:
                    folder = by_name[member.run]
                    document = vs.read_speakers(folder) or {"voices": []}
                    turns = next((v["turns"] for v in document["voices"]
                                  if v["id"] == member.voice_id), [])
                    window = voice_sources.pick_clip_window(turns)
                    if window:
                        options.append((window[1], member, folder, window))
                options.sort(key=lambda o: -o[0])
                saved = 0
                used: set[str] = set()
                _, meetings_dir, _ = dirs or _default_dirs()
                for _, member, folder, (start, length) in options:
                    if saved >= args.count or member.run in used:
                        continue
                    audio = voice_sources.resolve_audio(
                        folder, meetings_dir, None, archive_dir)
                    if audio is None:
                        continue
                    name = (f"group{number}_{saved + 1}_"
                            f"{voice_sources.safe_name(voice_sources.recording_suffix(member.run))}.wav")
                    try:
                        clipper(audio, start, length, out_dir / name)
                    except Exception as error:
                        print(f"  could not make a clip from {member.run}: {error}")
                        continue
                    used.add(member.run)
                    saved += 1
                    print(f"  {out_dir / name}   ({voice_sources.recording_suffix(member.run)}, "
                          f"{length:.0f} s)")
                if not saved:
                    print("No clips could be made (the audio may no longer exist).")
                    return 1
                print(f"\nSaved {saved} clips. Listen to them: do they sound like "
                      "one person?")
                print(f"Open the folder with: open {out_dir}")
                return 0

            if args.name:
                try:
                    number = int(args.name[0])
                    if number < 1:
                        raise IndexError
                    group = groups[number - 1]
                except (ValueError, IndexError):
                    print(f"No group {args.name[0]}. Run unknowns to see the list.")
                    return 2
                person_name = args.name[1].strip()
                describe(number, group)
                reply = ask(f"\nName all {len(group.members)} voices in this group "
                            f"as {person_name}? [y/N] ")
                if reply.strip().lower() not in ("y", "yes"):
                    print("Cancelled.")
                    return 1
                try:
                    result = voice_review.name_group(
                        group, runs, person_name, store, pending_dir, archive_dir)
                except voice_review.ReviewError as error:
                    print("Error: " + str(error))
                    return 2
                named, learned = result["named"], result["learned"]
                store.save(store_path)
                print(f"\nNamed {named} voices in {result['meetings']} meetings as "
                      f"{person_name} and learned {learned} fingerprints.")
                counts = voice_review.rematch_everything(
                    output_dir, archive_dir, pending_dir, store,
                    no_archive=args.no_archive)
                print(voice_review.rematch_summary(counts))
                return 0

            shown = groups[:args.limit]
            print(f"{len(groups)} recurring unnamed voices "
                  f"(showing {len(shown)}):\n")
            for number, group in enumerate(shown, start=1):
                describe(number, group)
                print()
            print("To name one: python3 voice_cli.py unknowns --name 1 NAME")
            print("The numbers can change if new meetings are analyzed in between, "
                  "so check the list just before naming.")
            return 0

        # ------------------------------------------------------------- rematch
        if args.command == "rematch":
            output_dir, _meetings, archive_dir = dirs or _default_dirs()
            store = _load_store(store_path)
            counts = voice_review.rematch_everything(
                output_dir, archive_dir, pending_dir, store,
                no_archive=args.no_archive,
                progress=lambda name, outcome: (
                    print(f"{name}: {outcome}") if outcome == "updated" else None))
            print(voice_review.rematch_summary(counts))
            return 0

        # --------------------------------------------------------- identify-all
        if args.command == "identify-all":
            output_dir, meetings_dir, archive_dir = dirs or _default_dirs()
            store = _load_store(store_path)
            if not store.people():
                print("No voice profiles yet. Run: python3 voice_cli.py enroll")
                return 1
            if worker is None:
                python_path = _voice_python(args.python)
                if not python_path:
                    print("Voice environment not set. Run: "
                          "python3 voice_cli.py set-python PATH_TO_PYTHON")
                    return 2
                worker = _make_worker(python_path, cache_dir)

            runs = _list_runs(output_dir, archive_dir, args.no_archive)
            todo = [d for d in runs
                    if args.redo or not (d / vs.SPEAKERS_FILE).exists()]
            if args.limit:
                todo = todo[:args.limit]
            if not todo:
                print("Nothing to do: every meeting already has speaker information.")
                return 0

            print(f"{len(todo)} meetings to look at (newest first). "
                  "Safe to stop with Ctrl-C and run again later.\n")
            done_count = no_audio = failed = 0
            started = time.time()
            for number, folder in enumerate(todo, start=1):
                audio = voice_sources.resolve_audio(
                    folder, meetings_dir, None, archive_dir
                )
                if audio is None:
                    no_audio += 1
                    print(f"[{number}/{len(todo)}] {folder.name}: no audio, skipped")
                    continue
                try:
                    payload = worker(audio)
                    document = vs.keep_confirmations(
                        vs.read_speakers(folder),
                        vs.build_speakers_document(payload, store),
                    )
                    voice_auto._mark_static(audio, document)
                    vs.write_speakers(folder, document)
                    vs.mirror_speakers(folder, archive_dir)
                    if not payload.get("remote_silent"):
                        vs.save_pending(folder.name, payload, pending_dir)
                except (vs.VoiceServiceError, OSError) as error:
                    failed += 1
                    print(f"[{number}/{len(todo)}] {folder.name}: failed ({error})")
                    continue
                done_count += 1
                voices = document["voices"]
                named = sum(1 for v in voices if v["status"] == "named")
                if document["remote_silent"]:
                    detail = "remote not captured"
                else:
                    detail = f"{len(voices)} voices, {named} named"
                per = (time.time() - started) / number
                left = int(per * (len(todo) - number) / 60)
                print(f"[{number}/{len(todo)}] {folder.name}: {detail}  "
                      f"(about {left} min left)")
            print(f"\nDone: {done_count} analyzed, {no_audio} without audio, "
                  f"{failed} failed.")
            return 0

        # ---------------------------------------------------------------- check
        if args.command == "check":
            import voice_check
            python_path = _voice_python(None)
            if not python_path:
                print("Voice environment not set. Run: "
                      "python3 voice_cli.py set-python PATH_TO_PYTHON")
                return 2
            ready, lines = voice_check.describe(voice_check.run_check(python_path))
            print("Voice environment: " + python_path)
            for line in lines:
                print("  " + line)
            print("\n" + ("Ready." if ready else "Not ready yet. Fix the lines above, "
                          "then run this again."))
            return 0 if ready else 1

        # ------------------------------------------------------------ noise-scan
        if args.command == "noise-scan":
            import voice_noise
            output_dir, meetings_dir, archive_dir = dirs or _default_dirs()
            runs = _list_runs(output_dir, archive_dir, args.no_archive)
            todo = []
            for folder in runs:
                try:
                    document = vs.read_speakers(folder)
                except vs.VoiceServiceError:
                    continue
                if (document and not document.get("remote_silent")
                        and (args.redo or not document.get("noise_checked"))):
                    todo.append((folder, document))
            if not todo:
                print("Nothing to do: every meeting has been checked.")
                return 0
            print(f"{len(todo)} meetings to check. Safe to stop with Ctrl-C and run again.\n")
            marked_total = skipped = 0
            for number, (folder, document) in enumerate(todo, start=1):
                audio = voice_sources.resolve_audio(
                    folder, meetings_dir, None, archive_dir)
                if audio is None:
                    skipped += 1
                    print(f"[{number}/{len(todo)}] {folder.name}: no audio, skipped")
                    continue
                try:
                    marked = voice_noise.tag_document(audio, document)
                    vs.write_speakers(folder, document)
                    vs.mirror_speakers(folder, archive_dir)
                except (vs.VoiceServiceError, OSError, Exception) as error:
                    skipped += 1
                    print(f"[{number}/{len(todo)}] {folder.name}: failed ({error})")
                    continue
                marked_total += marked
                note = f"{marked} static" if marked else "clean"
                print(f"[{number}/{len(todo)}] {folder.name}: {note}")
            print(f"\nDone: {marked_total} static voices marked, {skipped} meetings skipped.")
            return 0

        # ----------------------------------------------------------- noise-check
        if args.command == "noise-check":
            import voice_noise
            output_dir, meetings_dir, archive_dir = dirs or _default_dirs()
            run_dir = _resolve_run(args.run, output_dir)
            if run_dir is None:
                print("Meeting folder not found: " + args.run)
                return 2
            document = vs.read_speakers(run_dir)
            if not document:
                print("This meeting has no voice information yet.")
                return 1
            audio = voice_sources.resolve_audio(
                run_dir, meetings_dir, args.audio, archive_dir)
            if audio is None:
                print("No audio found for this meeting. Pass one with --audio PATH.")
                return 2
            rows = voice_noise.check_meeting(audio, document)
            print("voice   minutes  level dB  dynamics dB  flatness  verdict           who")
            for row in rows:
                flat = "-" if row["flatness"] is None else f"{row['flatness']:.2f}"
                print(f"{_short(row['id']):<7} {row['seconds'] / 60:>6.1f}  "
                      f"{row['level_db']:>8.1f}  {row['dynamics_db']:>11.1f}  "
                      f"{flat:>8}  {row['verdict']:<16}  {row['person'] or ''}")
            print("\nSpeech has a lot of dynamics and low flatness; static is steady "
                  "and flat. The verdict is provisional.")
            return 0

        # ----------------------------------------------- identify / show / confirm
        output_dir, meetings_dir, archive_dir = dirs or _default_dirs()
        run_dir = _resolve_run(args.run, output_dir)
        if run_dir is None:
            print("Meeting folder not found: " + args.run)
            return 2
        store = _load_store(store_path)

        if args.command == "identify":
            audio = voice_sources.resolve_audio(
                run_dir, meetings_dir, args.audio, archive_dir
            )
            if audio is None:
                print("No audio found for this meeting. Pass one with --audio PATH.")
                return 2
            if worker is None:
                python_path = _voice_python(args.python)
                if not python_path:
                    print("Voice environment not set. Run: "
                          "python3 voice_cli.py set-python PATH_TO_PYTHON")
                    return 2
                worker = _make_worker(python_path, cache_dir)
            payload = worker(audio)
            expected = [n.strip() for n in args.expect.split(",") if n.strip()]
            document = vs.keep_confirmations(
                vs.read_speakers(run_dir),
                vs.build_speakers_document(payload, store, expected),
            )
            vs.write_speakers(run_dir, document)
            vs.mirror_speakers(run_dir, archive_dir)
            if not payload.get("remote_silent"):
                vs.save_pending(run_dir.name, payload, pending_dir)
            print_document(document, run_dir.name)
            return 0

        document = vs.read_speakers(run_dir)
        if document is None:
            print("No speaker information yet. Run: "
                  f"python3 voice_cli.py identify {args.run}")
            return 1

        if args.command == "show":
            print_document(document, run_dir.name)
            if args.clips:
                out_dir = (args.out or Path.home() / "voice-clips").expanduser()
                _, meetings_dir, _ = dirs or _default_dirs()
                audio = voice_sources.resolve_audio(
                    run_dir, meetings_dir, None, archive_dir)
                if audio is None:
                    print("The audio for this meeting is no longer available.")
                    return 1
                print()
                for voice in document["voices"]:
                    windows = voice_sources.pick_clip_windows(
                        voice.get("turns", []), max(args.count, 1))
                    for index, window in enumerate(windows, 1):
                        tag = f"_{index}" if args.count > 1 else ""
                        name = (f"voice{_short(voice['id'])}{tag}_"
                                f"{voice_sources.safe_name(run_dir.name[-30:])}.wav")
                        try:
                            clipper(audio, window[0], window[1], out_dir / name)
                        except Exception as error:
                            print(f"  could not make a clip of voice {_short(voice['id'])}: {error}")
                            continue
                        print(f"  voice {_short(voice['id'])}: {out_dir / name}")
                print(f"\nOpen the folder with: open {out_dir}")
            return 0

        if args.command == "confirm":
            name, voice = args.name, args.voice
            if args.accept_hint:
                hint = document.get("hint")
                if not hint:
                    print("There is no suggestion to accept for this meeting.")
                    return 1
                name = name or hint["name"]
                voice = voice or hint["voice_ids"][0]
            if not name or not voice:
                print("Say who and which voice: confirm RUN NAME --voice 02")
                return 2
            ids = [v["id"] for v in document["voices"]]
            matches = [i for i in ids if i == voice or i.endswith(voice)]
            if len(matches) != 1:
                print(f"Voice '{voice}' not found. Voices: "
                      + ", ".join(_short(i) for i in ids))
                return 2
            info = vs.confirm_voice(run_dir, matches[0], name, store, pending_dir)
            vs.mirror_speakers(run_dir, archive_dir)
            store.save(store_path)
            if voice_review._participants_setting():
                voice_auto._update_participants(
                    run_dir, vs.read_speakers(run_dir), store, archive_dir)
                voice_review.refresh_index(archive_dir)
            learned = (f" and learned {info['enrolled']} fingerprints"
                       if info["enrolled"] else "")
            print(f"Named voice {_short(matches[0])} as {name}{learned}.")
            return 0
    except (vs.VoiceServiceError, vp.VoiceStoreError) as error:
        print("Error: " + str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
