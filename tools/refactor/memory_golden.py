"""Prove that a code change does not change what the extraction produces.

For a few meetings this builds the structured meeting memory (action items,
decisions, open questions, risks) from the saved cleaned transcript and summary,
using recorded model answers (see llm_replay.py), and compares it with the
result saved earlier.

    python3 tools/refactor/memory_golden.py record RUN [RUN ...]
        Runs the real model once (about 3 to 4 minutes per meeting) and saves
        the model's answers and the resulting memory.
    python3 tools/refactor/memory_golden.py compare [RUN ...]
        Rebuilds from the saved answers (seconds) and says whether anything
        changed. Run it after each step of a refactor.
    python3 tools/refactor/memory_golden.py stamp [RUN ...]
        Marks existing recordings as made in this environment. Only run it on
        the machine that made them.

The extraction takes a different path on a different machine (chip, memory and
model settings choose the profile), so a comparison is only meaningful where
the recording was made. Each recording remembers its environment and `compare`
refuses to run anywhere else.

Saved data contains real meeting text, so it goes in private_benchmarks/golden/
(never published). Meeting folders are only read; the work happens in a
temporary copy.
"""

from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.refactor import llm_replay

COPY_FILES = (
    "meeting_transcript_cleaned.md",
    "meeting_summary.md",
    "meeting_metadata.json",
    "speakers.json",
)
DEFAULT_STORE = REPO / "private_benchmarks" / "golden"


class GoldenError(Exception):
    """A readable message."""


def environment() -> dict:
    """What decides which extraction path runs on this machine."""
    import config
    profile = getattr(config, "_RESOLVED_PERFORMANCE_PROFILE", None)
    return {
        "backend": str(config.LLM_BACKEND),
        "mlx_model": str(config.MLX_MODEL),
        "llm_model": str(config.LLM_MODEL),
        "context": int(config.LLM_CONTEXT_SIZE),
        "profile": getattr(profile, "resolved_name", None),
        "profile_context": getattr(profile, "context_size_tokens", None),
        "hardware": getattr(profile, "hardware_label", None),
    }


def environment_problem(run_name: str, store: Path) -> str | None:
    """Why a comparison would not be meaningful here, or None."""
    path = Path(store) / f"{run_name}.env.json"
    if not path.exists():
        return ("this recording does not say where it was made. On the machine "
                "that made it, run: stamp " + run_name)
    recorded = json.loads(path.read_text(encoding="utf-8"))
    here = environment()
    differing = [f"{key}: recorded {recorded.get(key)!r}, here {here.get(key)!r}"
                 for key in sorted(set(recorded) | set(here))
                 if recorded.get(key) != here.get(key)]
    if differing:
        return ("this machine's settings differ from where it was recorded, so the "
                "result would not be comparable: " + "; ".join(differing))
    return None


def stamp(run_name: str, store: Path) -> None:
    Path(store).mkdir(parents=True, exist_ok=True)
    (Path(store) / f"{run_name}.env.json").write_text(
        json.dumps(environment(), indent=1, sort_keys=True), encoding="utf-8")


def diff_text(old: dict, new: dict, limit: int = 60) -> list[str]:
    """Readable differences between two memory results (empty when equal)."""
    a = json.dumps(old, indent=1, sort_keys=True).splitlines()
    b = json.dumps(new, indent=1, sort_keys=True).splitlines()
    lines = list(difflib.unified_diff(a, b, "saved", "now", lineterm="", n=1))
    return lines[:limit] + ([f"... {len(lines) - limit} more lines"] if len(lines) > limit else [])


def build_memory(run_dir: Path, scratch_root: Path) -> dict:
    """The meeting memory for one meeting, built in a temporary copy."""
    run_dir = Path(run_dir)
    cleaned = run_dir / "meeting_transcript_cleaned.md"
    summary = run_dir / "meeting_summary.md"
    if not cleaned.exists() or not summary.exists():
        raise GoldenError(f"{run_dir.name}: needs a cleaned transcript and a summary.")
    work = Path(scratch_root) / run_dir.name
    work.mkdir(parents=True, exist_ok=True)
    for name in COPY_FILES:
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, work / name)
    metadata = {}
    if (work / "meeting_metadata.json").exists():
        metadata = json.loads((work / "meeting_metadata.json").read_text(encoding="utf-8"))
    import pipeline
    memory_path = pipeline.run_meeting_memory(
        run_dir=work,
        meeting_summary=summary.read_text(encoding="utf-8"),
        cleaned_transcript=cleaned.read_text(encoding="utf-8"),
        participants=metadata.get("participants") or [],
    )
    return json.loads(Path(memory_path).read_text(encoding="utf-8"))


def record(run_dir: Path, store: Path) -> dict:
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        with llm_replay.installed(store / f"{run_dir.name}.replay.json", "record") as replayer:
            memory = build_memory(run_dir, Path(scratch))
    (store / f"{run_dir.name}.memory.json").write_text(
        json.dumps(memory, indent=1, sort_keys=True), encoding="utf-8")
    stamp(run_dir.name, store)
    print(f"  recorded {replayer.calls} model calls")
    return memory


def diagnose(run_dir: Path, store: Path) -> list[str]:
    """Why the checker threw out each candidate (replays the recorded model answers)."""
    store = Path(store)
    replay_path = store / f"{run_dir.name}.replay.json"
    if not replay_path.exists():
        raise GoldenError(f"{run_dir.name}: nothing recorded yet. Run: record {run_dir.name}")
    problem = environment_problem(run_dir.name, store)
    if problem:
        raise GoldenError(f"{run_dir.name}: {problem}")
    with tempfile.TemporaryDirectory() as scratch:
        with llm_replay.installed(replay_path, "replay"):
            build_memory(run_dir, Path(scratch))
    import ai
    rejected = (getattr(ai, "_last_memory_resolution_diagnostics", {}) or {}).get("rejected_final", {})
    lines = []
    for category, rows in rejected.items():
        for row in rows:
            text = (row.get("question") or row.get("risk") or row.get("decision")
                    or row.get("action") or "")
            lines.append(f"{category}: {row.get('reason')}: {' '.join(str(text).split())[:110]}")
    return lines


def accept(run_dir: Path, store: Path) -> None:
    """Make today's result the saved one, after you have reviewed the differences.

    Uses the recorded model answers (no model needed), so it only suits a change
    that does not alter what the model is asked.
    """
    store = Path(store)
    replay_path = store / f"{run_dir.name}.replay.json"
    if not replay_path.exists():
        raise GoldenError(f"{run_dir.name}: nothing recorded yet. Run: record {run_dir.name}")
    problem = environment_problem(run_dir.name, store)
    if problem:
        raise GoldenError(f"{run_dir.name}: {problem}")
    with tempfile.TemporaryDirectory() as scratch:
        with llm_replay.installed(replay_path, "replay"):
            now = build_memory(run_dir, Path(scratch))
    (store / f"{run_dir.name}.memory.json").write_text(
        json.dumps(now, indent=1, sort_keys=True), encoding="utf-8")


def compare(run_dir: Path, store: Path) -> list[str]:
    """Differences from the saved result (empty list = identical)."""
    store = Path(store)
    golden_path = store / f"{run_dir.name}.memory.json"
    replay_path = store / f"{run_dir.name}.replay.json"
    if not golden_path.exists() or not replay_path.exists():
        raise GoldenError(f"{run_dir.name}: nothing recorded yet. Run: record {run_dir.name}")
    problem = environment_problem(run_dir.name, store)
    if problem:
        raise GoldenError(f"{run_dir.name}: {problem}")
    saved = json.loads(golden_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as scratch:
        try:
            with llm_replay.installed(replay_path, "replay"):
                now = build_memory(run_dir, Path(scratch))
        except llm_replay.MissingRecording as error:
            return ["The model was asked something that was not recorded:", str(error)]
    return diff_text(saved, now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["record", "compare", "stamp", "diagnose", "accept"])
    parser.add_argument("runs", nargs="*", help="meeting folder names")
    parser.add_argument("--output-dir", type=Path, help="where the meeting folders are")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args(argv)

    if args.output_dir:
        output_dir = args.output_dir
    else:
        import config
        output_dir = config.OUTPUT_DIR
    runs = args.runs
    if not runs:
        if args.action == "record":
            print("Name the meetings to record.")
            return 2
        runs = sorted(p.name.removesuffix(".memory.json")
                      for p in Path(args.store).glob("*.memory.json"))
    failed = 0
    for name in runs:
        run_dir = Path(output_dir) / name
        if not run_dir.is_dir():
            print(f"{name}: meeting folder not found")
            failed += 1
            continue
        print(name)
        try:
            if args.action == "record":
                record(run_dir, args.store)
            elif args.action == "stamp":
                stamp(run_dir.name, args.store)
                print("  stamped")
            elif args.action == "accept":
                accept(run_dir, args.store)
                print("  accepted: today's result is now the saved one")
            elif args.action == "diagnose":
                for line in diagnose(run_dir, args.store):
                    print("  " + line)
            else:
                differences = compare(run_dir, args.store)
                if differences:
                    failed += 1
                    print("  CHANGED")
                    for line in differences:
                        print("   " + line)
                else:
                    print("  identical")
        except GoldenError as error:
            print("  " + str(error))
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
