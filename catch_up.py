"""Catch-up: give an older meeting names and owners from its saved material.

An older meeting was processed before speaker names existed. Its saved voice
information (speakers.json) and per-track transcripts are still there, so the
steps after transcription can be repeated with names. This is done in two
safe stages:

    python3 catch_up.py rebuild RUN [RUN ...]
        Rebuild in a separate staging folder. The meeting itself is not touched.
    python3 catch_up.py apply RUN [RUN ...]
        Replace only the files that change, after saving the originals.
    python3 catch_up.py undo RUN [RUN ...]
        Put the originals back.
    python3 catch_up.py status [RUN ...]

For many meetings at once (newest first, safe to stop and start again):

    python3 catch_up.py list
        Every meeting, and whether it can be caught up or why not.
    python3 catch_up.py rebuild-all [--limit N] [--redo]
        Rebuild each meeting that has not been rebuilt yet. Stop any time with
        Ctrl-C; running it again carries on where it stopped.
    python3 catch_up.py tidy-all
        Plain-code cleanup of rebuilt and applied meetings (no model needed):
        repeats removed, task-like or secondhand decisions made unconfirmed.
        Only meetings that change are marked to be applied again.
    python3 catch_up.py apply-all
        Apply every rebuilt meeting that has not been applied yet.

What is replaced: the cleaned transcript, the summary (.md and .html), the
meeting memory, the OneNote export, and the participants list inside the
metadata. Everything else (title, folder, published state, audio, the original
transcript) is left exactly as it is. Meetings that also have an archived copy
get the same files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

REPLACED = (
    "meeting_transcript_cleaned.md",
    "meeting_summary.md",
    "meeting_summary.html",
    "meeting_memory.json",
)
INPUTS = (
    "meeting_transcript.md",
    "meeting_transcript.html",
    "meeting_metadata.json",
    "processing_runtime.json",
    "speakers.json",
)
UNOWNED = {"", "unknown", "remote", "unidentified"}


class CatchUpError(Exception):
    """A readable message."""


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    shutil.copy2(source, temporary)
    temporary.replace(target)


def memory_counts(memory: dict) -> dict:
    commitments = memory.get("commitments") or []
    unowned = sum(
        1 for row in commitments
        if isinstance(row, dict) and str(row.get("owner") or "").strip().casefold() in UNOWNED
    )
    return {
        "commitments": len(commitments),
        "unowned": unowned,
        "decisions": len(memory.get("decisions") or []),
        "open_questions": len(memory.get("open_questions") or []),
        "risks": len(memory.get("risks") or []),
    }


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def problem_with(run_dir: Path) -> str | None:
    """Why a meeting cannot be caught up (None when it can)."""
    run_dir = Path(run_dir)
    if not (run_dir / "speakers.json").exists():
        return "no voice information (speakers.json)"
    if not (run_dir / "meeting_transcript.md").exists():
        return "no saved transcript"
    if not list((run_dir / "transcript").glob("*.vtt")):
        return "no saved per-track transcripts"
    if not (run_dir / "meeting_memory.json").exists():
        return "no saved meeting memory to compare with"
    return None


def default_runner(work: Path) -> None:
    """Repeat the steps after transcription, with names, inside `work`."""
    import config
    import pipeline
    import voice_auto
    from app_settings import load_app_settings

    previous = config.NAMED_TRANSCRIPT
    config.NAMED_TRANSCRIPT = True
    try:
        if pipeline.named_transcript_for_run(work) is None:
            raise CatchUpError("no usable voice information, so no names")
        cleaned, _path = pipeline.run_ai_cleanup(work)
        summary, _html, _md, _html_path = pipeline.run_meeting_summary(work, cleaned)
        transcript_html = (work / "meeting_transcript.html").read_text(encoding="utf-8")
        pipeline.complete_post_summary_artifacts(
            run_dir=work,
            meeting_summary=summary,
            cleaned_transcript=cleaned,
            transcript_html=transcript_html,
            source_path=None,
        )
        voice_auto.finish_participants(work, load_app_settings(), archive_dir=None)
    finally:
        config.NAMED_TRANSCRIPT = previous


def rebuild(
    run_dir: Path,
    staging_root: Path,
    runner: Callable[[Path], None] = default_runner,
    now: datetime | None = None,
) -> dict:
    """Rebuild one meeting in the staging folder. Never touches the meeting."""
    run_dir = Path(run_dir)
    target = Path(staging_root) / run_dir.name
    reason = problem_with(run_dir)
    if reason:
        return {"state": "skipped", "reason": reason}
    if target.exists():
        shutil.rmtree(target)
    work = target / "work"
    work.mkdir(parents=True)
    for name in INPUTS:
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, work / name)
    shutil.copytree(run_dir / "transcript", work / "transcript")
    try:
        runner(work)
        missing = [name for name in REPLACED if not (work / name).exists()]
        if missing:
            raise CatchUpError("the rebuild did not produce " + ", ".join(missing))
    except Exception as error:      # noqa: BLE001 - one bad meeting must not stop a batch
        shutil.rmtree(target, ignore_errors=True)
        return {"state": "failed", "reason": str(error)}
    status = {
        "state": "built",
        "built": (now or datetime.now()).isoformat(timespec="seconds"),
        "old": memory_counts(_read_json(run_dir / "meeting_memory.json")),
        "new": memory_counts(_read_json(work / "meeting_memory.json")),
    }
    _write_json(target / "status.json", status)
    return status


def _default_export(run_dir: Path) -> None:
    import pipeline
    pipeline.export_onenote_summary(run_dir)


def apply(
    run_dir: Path,
    staging_root: Path,
    backup_root: Path,
    archive_dir: Path | None = None,
    now: datetime | None = None,
    export: Callable[[Path], None] = _default_export,
) -> dict:
    """Replace the changed files, after saving the originals."""
    run_dir = Path(run_dir)
    staged = Path(staging_root) / run_dir.name
    status = _read_json(staged / "status.json")
    if status.get("state") != "built":
        raise CatchUpError(f"{run_dir.name}: nothing rebuilt to apply (run rebuild first)")
    work = staged / "work"
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    backup = Path(backup_root) / run_dir.name / stamp
    bases = [("output", run_dir)]
    twin = Path(archive_dir) / run_dir.name if archive_dir else None
    if twin is not None and twin.is_dir():
        bases.append(("archive", twin))
    entries: list[dict] = []

    def save_original(where: str, base: Path, rel: str) -> None:
        path = base / rel
        if path.exists():
            _copy(path, backup / where / rel)
            entries.append({"where": where, "rel": rel, "backup": True})
        else:
            entries.append({"where": where, "rel": rel, "backup": False})

    def write_record(state: str) -> None:
        _write_json(backup / "record.json", {
            "run": run_dir.name, "stamp": stamp, "state": state, "entries": entries})

    participants = _read_json(work / "meeting_metadata.json").get("participants")
    try:
        for where, base in bases:
            for rel in REPLACED:
                save_original(where, base, rel)
                _copy(work / rel, base / rel)
            if participants is not None and (base / "meeting_metadata.json").exists():
                save_original(where, base, "meeting_metadata.json")
                metadata = _read_json(base / "meeting_metadata.json")
                metadata["participants"] = participants
                _write_json(base / "meeting_metadata.json", metadata)
        export_name = f"OneNote_{run_dir.name}.html"
        save_original("output", run_dir, f"exports/{export_name}")
        export(run_dir)
        save_after = run_dir / "exports" / export_name
        if twin is not None and ("archive", twin) in bases and save_after.exists():
            save_original("archive", twin, f"exports/{export_name}")
            _copy(save_after, twin / "exports" / export_name)
    except BaseException:
        write_record("failed part-way")
        raise
    write_record("applied")
    status["state"] = "applied"
    status["applied"] = stamp
    _write_json(staged / "status.json", status)
    return {"stamp": stamp, "files": len(entries), "archive": len(bases) > 1}


def undo(
    run_dir: Path,
    backup_root: Path,
    archive_dir: Path | None = None,
) -> str:
    """Put back the originals saved by the latest apply."""
    run_dir = Path(run_dir)
    folder = Path(backup_root) / run_dir.name
    candidates = sorted((p for p in folder.glob("*") if (p / "record.json").exists()), reverse=True)
    for candidate in candidates:
        record = _read_json(candidate / "record.json")
        if record.get("state") not in ("applied", "failed part-way"):
            continue
        twin = Path(archive_dir) / run_dir.name if archive_dir else None
        roots = {"output": run_dir, "archive": twin}
        for entry in record["entries"]:
            base = roots.get(entry["where"])
            if base is None:
                continue
            destination = base / entry["rel"]
            if entry["backup"]:
                _copy(candidate / entry["where"] / entry["rel"], destination)
            elif destination.exists():
                destination.unlink()
        record["state"] = "undone"
        _write_json(candidate / "record.json", record)
        return candidate.name
    raise CatchUpError(f"{run_dir.name}: nothing to undo")


def all_runs(output_root: Path) -> list[str]:
    """Meeting folders, newest first."""
    names = [p.name for p in Path(output_root).glob("20*") if p.is_dir()]
    return sorted(names, reverse=True)


def staged_state(staging_root: Path, name: str) -> str:
    return _read_json(Path(staging_root) / name / "status.json").get("state", "not rebuilt")


def rebuild_all(
    output_root: Path,
    staging_root: Path,
    runner: Callable[[Path], None] = default_runner,
    limit: int | None = None,
    redo: bool = False,
    log: Callable[[str], None] = print,
) -> dict:
    """Rebuild every meeting that needs it. One bad meeting never stops the rest."""
    counts = {"built": 0, "failed": 0, "skipped": 0, "already": 0}
    for name in all_runs(output_root):
        if not redo and staged_state(staging_root, name) in ("built", "applied"):
            counts["already"] += 1
            continue
        if limit is not None and counts["built"] + counts["failed"] >= limit:
            break
        result = rebuild(Path(output_root) / name, staging_root, runner)
        if result["state"] == "built":
            counts["built"] += 1
            log(f"{name}: built  old {result['old']}  new {result['new']}")
        elif result["state"] == "failed":
            counts["failed"] += 1
            log(f"{name}: failed: {result['reason']}")
        else:
            counts["skipped"] += 1
            log(f"{name}: skipped: {result['reason']}")
    return counts


def retidy(work: Path) -> bool:
    """Clean the memory in a rebuilt folder and rewrite its summary. True if it changed."""
    import markdown
    import ai
    import pipeline
    import signals_pass

    memory_path = Path(work) / "meeting_memory.json"
    memory = _read_json(memory_path)
    tidied = signals_pass.tidy_memory(memory)
    if tidied == memory:
        return False
    _write_json(memory_path, tidied)
    summary_path = Path(work) / "meeting_summary.md"
    # Replace only the two sections the cleanup can change. (Composing the whole
    # summary a second time is not safe: a narrative step can eat a line break.)
    composed = summary_path.read_text(encoding="utf-8")
    for heading, key, other_key, label in (
        ("Decisions", "decision", "other_decisions", "Possible decisions (unconfirmed)"),
        ("Risks and Concerns", "risk", "other_risks", "Possible risks (unconfirmed)"),
    ):
        lines = []
        for item in tidied.get(heading.split(" ")[0].lower(), []):
            text = str(item.get(key, "") if isinstance(item, dict) else item).strip()
            if text and f"- {text}" not in lines:
                lines.append(f"- {text}")
        body = ai._with_unconfirmed("\n".join(lines) or "None identified.",
                                    tidied.get(other_key), label)
        composed = ai._replace_markdown_section(composed, heading, body)
    summary_path.write_text(composed, encoding="utf-8")
    (Path(work) / "meeting_summary.html").write_text(
        pipeline.build_summary_html(summary_html=markdown.markdown(composed)),
        encoding="utf-8")
    return True


def tidy_all(
    output_root: Path,
    staging_root: Path,
    tidy: Callable[[Path], bool] = retidy,
    log: Callable[[str], None] = print,
) -> dict:
    counts = {"changed": 0, "unchanged": 0, "failed": 0}
    for name in all_runs(output_root):
        if staged_state(staging_root, name) not in ("built", "applied"):
            continue
        staged = Path(staging_root) / name
        try:
            if tidy(staged / "work"):
                status = _read_json(staged / "status.json")
                status["state"] = "built"
                status.pop("applied", None)
                status["new"] = memory_counts(_read_json(staged / "work" / "meeting_memory.json"))
                _write_json(staged / "status.json", status)
                counts["changed"] += 1
                log(f"{name}: tidied")
            else:
                counts["unchanged"] += 1
        except Exception as error:      # noqa: BLE001 - carry on with the others
            counts["failed"] += 1
            log(f"{name}: failed: {error}")
    return counts


def apply_all(
    output_root: Path,
    staging_root: Path,
    backup_root: Path,
    archive_dir: Path | None = None,
    export: Callable[[Path], None] = _default_export,
    log: Callable[[str], None] = print,
) -> dict:
    counts = {"applied": 0, "failed": 0}
    for name in all_runs(output_root):
        if staged_state(staging_root, name) != "built":
            continue
        try:
            result = apply(Path(output_root) / name, staging_root, backup_root, archive_dir,
                           export=export)
            counts["applied"] += 1
            log(f"{name}: applied {result['files']} files"
                + (" (and the archived copy)" if result["archive"] else ""))
        except Exception as error:      # noqa: BLE001 - carry on with the others
            counts["failed"] += 1
            log(f"{name}: failed: {error}")
    return counts


def _roots(args):
    import config
    from app_settings import APP_SUPPORT_DIR
    output = Path(args.output_dir) if args.output_dir else config.OUTPUT_DIR
    archive = Path(args.archive_dir) if args.archive_dir else config.ARCHIVE_DIR
    staging = Path(args.staging_dir) if args.staging_dir else Path(APP_SUPPORT_DIR) / "catch_up"
    backups = Path(args.backup_dir) if args.backup_dir else Path(APP_SUPPORT_DIR) / "catch_up_backups"
    return output, archive, staging, backups


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=[
        "rebuild", "apply", "undo", "status", "list", "rebuild-all", "apply-all", "tidy-all"])
    parser.add_argument("runs", nargs="*", help="meeting folder names")
    parser.add_argument("--limit", type=int, help="rebuild-all: stop after this many")
    parser.add_argument("--redo", action="store_true", help="rebuild-all: rebuild again")
    parser.add_argument("--output-dir")
    parser.add_argument("--archive-dir")
    parser.add_argument("--staging-dir")
    parser.add_argument("--backup-dir")
    args = parser.parse_args(argv)
    output, archive, staging, backups = _roots(args)
    failed = 0
    if args.action == "list":
        for name in all_runs(output):
            reason = problem_with(output / name)
            print(f"{name}: " + (f"cannot: {reason}" if reason else staged_state(staging, name)))
        return 0
    if args.action == "rebuild-all":
        try:
            counts = rebuild_all(output, staging, limit=args.limit, redo=args.redo)
        except KeyboardInterrupt:
            print("\nStopped. Run the same command again to carry on.")
            return 1
        print(f"done: {counts}")
        return 1 if counts["failed"] else 0
    if args.action == "tidy-all":
        counts = tidy_all(output, staging)
        print(f"done: {counts}")
        return 1 if counts["failed"] else 0
    if args.action == "apply-all":
        counts = apply_all(output, staging, backups, archive)
        print(f"done: {counts}")
        return 1 if counts["failed"] else 0
    runs = args.runs or ([p.name for p in sorted(staging.glob("20*"))] if args.action == "status" else [])
    if not runs:
        parser.error("name at least one meeting")
    for name in runs:
        run_dir = output / name
        try:
            if args.action == "rebuild":
                result = rebuild(run_dir, staging)
                if result["state"] == "built":
                    print(f"{name}: built  old {result['old']}  new {result['new']}")
                else:
                    print(f"{name}: {result['state']}: {result['reason']}")
                    failed += result["state"] == "failed"
            elif args.action == "apply":
                result = apply(run_dir, staging, backups, archive)
                print(f"{name}: applied {result['files']} files"
                      + (" (and the archived copy)" if result["archive"] else ""))
            elif args.action == "undo":
                print(f"{name}: restored the originals saved at {undo(run_dir, backups, archive)}")
            else:
                status = _read_json(staging / name / "status.json")
                print(f"{name}: {status.get('state', 'not rebuilt')}")
        except CatchUpError as error:
            print(str(error))
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
