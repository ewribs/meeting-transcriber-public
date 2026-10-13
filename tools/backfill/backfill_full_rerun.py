"""Re-run the AI stages for existing meetings without touching the audio.

For each meeting folder this tool:
  1. copies the files it is about to change into a backup folder;
  2. regenerates the summary from the saved cleaned transcript;
  3. rebuilds participants, meeting memory, summary composition, HTML,
     the OneNote export file and metadata with the current code.

It never changes the raw or cleaned transcripts, never runs Whisper, never
touches the archive/NAS, and never publishes. If a meeting fails part-way, its
original files are restored from the backup and the run continues.

Dry run by default: nothing is written unless --apply is given.
"""

# Allow direct execution from the repository root after tools were reorganized.
import sys
from pathlib import Path as _RepoPath

_REPO_ROOT = _RepoPath(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

MINUTES_PER_MEETING = 3.5  # rough planning estimate shown in the dry run

BACKUP_FILES = (
    "meeting_summary.md",
    "meeting_summary.html",
    "meeting_transcript.html",
    "meeting_memory.json",
    "meeting_metadata.json",
    "processing_runtime.json",
)
BACKUP_DIRS = ("exports",)


def find_runs(output_dir, only=(), newest=None, limit=None, missing_memory_only=False):
    """Meeting folders that have a cleaned transcript, oldest first."""
    runs = []
    for path in sorted(Path(output_dir).iterdir(), key=lambda p: p.name):
        if not path.is_dir() or not (path / "meeting_transcript_cleaned.md").exists():
            continue
        if only and not any(term.casefold() in path.name.casefold() for term in only):
            continue
        if missing_memory_only and (path / "meeting_memory.json").exists():
            continue
        runs.append(path)
    if newest:
        runs = runs[-newest:]
    if limit:
        runs = runs[:limit]
    return runs


def load_state(state_path):
    try:
        return json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state_path, state):
    Path(state_path).write_text(json.dumps(state, indent=2), encoding="utf-8")


def backup_run(run_dir, backup_root):
    destination = Path(backup_root) / run_dir.name
    destination.mkdir(parents=True, exist_ok=True)
    for name in BACKUP_FILES:
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, destination / name)
    for name in BACKUP_DIRS:
        if (run_dir / name).is_dir():
            shutil.copytree(run_dir / name, destination / name, dirs_exist_ok=True)
    return destination


def restore_run(run_dir, backup_dir):
    for name in BACKUP_FILES:
        if (backup_dir / name).exists():
            shutil.copy2(backup_dir / name, run_dir / name)
    for name in BACKUP_DIRS:
        if (backup_dir / name).is_dir():
            shutil.copytree(backup_dir / name, run_dir / name, dirs_exist_ok=True)


def build_transcript_html(run_dir):
    """Same transcript HTML the app builds, from the saved VTT files when present."""
    try:
        from formatter import format_transcript_html
        from utils import (
            merge_adjacent_speakers,
            merge_transcripts,
            parse_vtt_file,
            remove_silence_entries,
        )

        remote_vtt = run_dir / "transcript" / "remote.vtt"
        mic_vtt = run_dir / "transcript" / "mic.vtt"
        if remote_vtt.exists() and mic_vtt.exists():
            entries = merge_adjacent_speakers(
                remove_silence_entries(
                    merge_transcripts(
                        parse_vtt_file(remote_vtt, "Remote"),
                        parse_vtt_file(mic_vtt, "Mic"),
                    )
                )
            )
            return format_transcript_html(entries)
    except Exception as exc:
        print(f"    (transcript HTML fallback: {exc})")
    import markdown

    return markdown.markdown((run_dir / "meeting_transcript.md").read_text(encoding="utf-8"))


def process_run(run_dir, backup_root, summary_fn, complete_fn, html_fn=build_transcript_html):
    """Back up, rebuild one meeting, and restore it if anything fails."""
    backup_dir = backup_run(run_dir, backup_root)
    try:
        cleaned = (run_dir / "meeting_transcript_cleaned.md").read_text(encoding="utf-8")
        summary = summary_fn(run_dir, cleaned)
        complete_fn(run_dir, summary, cleaned, html_fn(run_dir))
    except BaseException:  # includes Ctrl-C: never leave a half-rebuilt meeting behind
        restore_run(run_dir, backup_dir)
        raise


def _real_summary(run_dir, cleaned):
    from pipeline import run_meeting_summary

    return run_meeting_summary(run_dir=run_dir, cleaned_transcript=cleaned)[0]


def _real_complete(run_dir, summary, cleaned, transcript_html):
    from pipeline import complete_post_summary_artifacts

    complete_post_summary_artifacts(
        run_dir=run_dir,
        meeting_summary=summary,
        cleaned_transcript=cleaned,
        transcript_html=transcript_html,
        source_path=None,
    )


def run(output_dir, backup_parent, apply_changes=False, only=(), newest=None, limit=None,
        missing_memory_only=False, redo=False, summary_fn=_real_summary,
        complete_fn=_real_complete, html_fn=build_transcript_html, state_path=None):
    runs = find_runs(output_dir, only, newest, limit, missing_memory_only)
    state_path = Path(state_path or Path(backup_parent) / "backfill_state.json")
    state = {} if redo else load_state(state_path)
    todo = [r for r in runs if r.name not in state]

    print(f"\nMeeting folders selected: {len(runs)}  (already done: {len(runs) - len(todo)})")
    print(f"Mode: {'APPLY' if apply_changes else 'DRY RUN'}")
    print(f"Estimated time: about {len(todo) * MINUTES_PER_MEETING / 60:.1f} hours\n")

    if not apply_changes:
        for r in todo:
            gaps = [n for n in ("meeting_memory.json", "meeting_metadata.json", "processing_runtime.json")
                    if not (r / n).exists()]
            print(f"  WOULD REBUILD: {r.name}" + (f"   (missing: {', '.join(gaps)})" if gaps else ""))
        print("\nDry run only. Add --apply to rebuild.")
        return 0

    backup_root = Path(backup_parent) / datetime.now().strftime("%Y%m%dT%H%M%S")
    print(f"Backups: {backup_root}\n")
    done = failed = 0
    for index, run_dir in enumerate(todo, 1):
        started = time.time()
        print(f"[{index}/{len(todo)}] {run_dir.name}", flush=True)
        try:
            process_run(run_dir, backup_root, summary_fn, complete_fn, html_fn)
        except Exception as exc:
            failed += 1
            print(f"    FAILED (original files restored): {exc}", flush=True)
            continue
        done += 1
        state[run_dir.name] = datetime.now().isoformat(timespec="seconds")
        save_state(state_path, state)
        print(f"    done in {time.time() - started:.0f}s", flush=True)
    print(f"\nFinished: {done} rebuilt, {failed} failed.")
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", help="Local meeting output folder (default: the app's output folder)")
    parser.add_argument("--backup-dir", help="Where backups and progress are kept "
                        "(default: backfill_backups next to the output folder)")
    parser.add_argument("--apply", action="store_true", help="Actually rebuild (default is a dry run)")
    parser.add_argument("--only", action="append", default=[], help="Only folders whose name contains this text (repeatable)")
    parser.add_argument("--newest", type=int, help="Only the newest N folders")
    parser.add_argument("--limit", type=int, help="Stop after N folders")
    parser.add_argument("--missing-memory-only", action="store_true", help="Only folders with no meeting_memory.json")
    parser.add_argument("--redo", action="store_true", help="Ignore saved progress and rebuild again")
    args = parser.parse_args(argv)

    from config import OUTPUT_DIR

    output_dir = Path(args.output_dir) if args.output_dir else Path(OUTPUT_DIR)
    backup_parent = Path(args.backup_dir) if args.backup_dir else output_dir.parent / "backfill_backups"
    backup_parent.mkdir(parents=True, exist_ok=True)
    return run(output_dir, backup_parent, args.apply, tuple(args.only), args.newest, args.limit,
               args.missing_memory_only, args.redo)


if __name__ == "__main__":
    sys.exit(main())
