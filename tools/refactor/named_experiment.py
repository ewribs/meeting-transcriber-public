"""Phase 4: does putting names in the transcript fix the owners?

For each meeting this builds, in a temporary copy, the meeting memory the
new way (cleaning and extraction read a transcript with real names) and sets
it beside the memory recorded the old way (private_benchmarks/golden). It
needs the real model, so it only runs where the model is: your Mac. Nothing in
the meeting folders is changed.

    python3 tools/refactor/named_experiment.py RUN [RUN ...] --output-dir DIR

Writes, for each meeting, private_benchmarks/named_experiment/<RUN>/:
    report.md                the side-by-side comparison
    cleaned_named.md         the cleaned transcript with names
    memory_named.json        the new memory
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_GOLDEN = REPO / "private_benchmarks" / "golden"
DEFAULT_OUT = REPO / "private_benchmarks" / "named_experiment"
COPY_FILES = ("meeting_transcript.md", "meeting_summary.md",
              "meeting_metadata.json", "speakers.json")
SECTIONS = ("commitments", "decisions", "open_questions", "risks", "follow_ups")


class ExperimentError(Exception):
    """A readable message."""


def is_unowned(owner) -> bool:
    return str(owner or "").strip().casefold() in {"", "unknown", "remote", "unidentified"}


def describe(item) -> tuple[str, str]:
    """(owner, text) for one memory row."""
    if isinstance(item, str):
        return "", item
    owner = str(item.get("owner") or item.get("speaker") or "")
    text = (item.get("action") or item.get("decision") or item.get("question")
            or item.get("risk") or item.get("text") or json.dumps(item)[:120])
    return owner, str(text)


def summarise(memory: dict) -> dict:
    counts = {}
    for section in SECTIONS:
        rows = memory.get(section) or []
        counts[section] = len(rows)
    rows = memory.get("commitments") or []
    counts["commitments_unowned"] = sum(
        1 for row in rows if is_unowned(describe(row)[0]))
    return counts


def report(run: str, old: dict, new: dict) -> str:
    old_counts, new_counts = summarise(old), summarise(new)
    lines = [f"# {run}", "", "| | old | new |", "|---|---|---|"]
    for key in old_counts:
        lines.append(f"| {key} | {old_counts[key]} | {new_counts[key]} |")
    for title, memory in (("OLD (Mic / Remote)", old), ("NEW (names)", new)):
        lines += ["", f"## {title}", ""]
        for section in ("commitments", "decisions", "open_questions", "risks"):
            rows = memory.get(section) or []
            lines.append(f"### {section} ({len(rows)})")
            for row in rows:
                owner, text = describe(row)
                prefix = f"[{owner or '-'}] " if section == "commitments" else ""
                lines.append(f"- {prefix}{text}")
            lines.append("")
    return "\n".join(lines)


def build_named_memory(run_dir: Path, scratch_root: Path,
                       names: bool = True, by_turn_only: bool = False) -> tuple[dict, str]:
    """Clean the (named, or with names=False the ordinary) transcript and build
    the memory from it."""
    import config
    import pipeline
    work = Path(scratch_root) / run_dir.name
    work.mkdir(parents=True, exist_ok=True)
    for name in COPY_FILES:
        if (run_dir / name).exists():
            shutil.copy2(run_dir / name, work / name)
    if (run_dir / "transcript").is_dir():
        shutil.copytree(run_dir / "transcript", work / "transcript", dirs_exist_ok=True)
    summary = work / "meeting_summary.md"
    if not summary.exists():
        raise ExperimentError(f"{run_dir.name}: needs a summary.")
    previous = config.NAMED_TRANSCRIPT
    config.NAMED_TRANSCRIPT = names
    try:
        if names and pipeline.named_transcript_for_run(work) is None:
            raise ExperimentError(f"{run_dir.name}: no voice information, so no names.")
        if by_turn_only:
            # Turn-by-turn cleaning, but with the usual Mic / Remote labels:
            # separates the effect of the cleaning method from the effect of names.
            import structured_cleaning
            import transcript_turns
            from ai import ask_llm
            turns = transcript_turns.turns_from_run(work)
            structured_cleaning.clean_turns(turns, ask_llm)
            cleaned = transcript_turns.render_markdown(turns, field="text")
            (work / "meeting_transcript_cleaned.md").write_text(cleaned, encoding="utf-8")
        else:
            cleaned, _path = pipeline.run_ai_cleanup(work)
    finally:
        config.NAMED_TRANSCRIPT = previous
    metadata = {}
    if (work / "meeting_metadata.json").exists():
        metadata = json.loads((work / "meeting_metadata.json").read_text(encoding="utf-8"))
    memory_path = pipeline.run_meeting_memory(
        run_dir=work,
        meeting_summary=summary.read_text(encoding="utf-8"),
        cleaned_transcript=cleaned,
        participants=metadata.get("participants") or [],
    )
    import ai
    build_named_memory.diagnostics = json.loads(
        json.dumps(getattr(ai, "_last_memory_resolution_diagnostics", {}), default=str))
    return json.loads(Path(memory_path).read_text(encoding="utf-8")), cleaned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--control", action="store_true",
                        help="run the same way WITHOUT names, to measure how much the "
                             "model varies from one run to the next")
    parser.add_argument("--turns-only", action="store_true",
                        help="clean turn by turn but keep the Mic / Remote labels")
    parser.add_argument("--vs-current", action="store_true",
                        help="compare with each meeting's own saved memory instead of a "
                             "recording (for meetings that were never recorded)")
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.output_dir:
        output_dir = args.output_dir
    else:
        import config
        output_dir = config.OUTPUT_DIR
    failed = 0
    for name in args.runs:
        run_dir = Path(output_dir) / name
        old_path = (run_dir / "meeting_memory.json" if args.vs_current
                    else Path(args.golden) / f"{name}.memory.json")
        print(name)
        if not run_dir.is_dir() or not old_path.exists():
            print("  meeting folder or recorded memory not found")
            failed += 1
            continue
        try:
            with tempfile.TemporaryDirectory() as scratch:
                new, cleaned = build_named_memory(run_dir, Path(scratch),
                                                  names=not (args.control or args.turns_only),
                                                  by_turn_only=args.turns_only)
        except ExperimentError as error:
            print("  " + str(error))
            failed += 1
            continue
        old = json.loads(old_path.read_text(encoding="utf-8"))
        target = Path(args.out) / (name + ("_control" if args.control else "_turns" if args.turns_only else ""))
        target.mkdir(parents=True, exist_ok=True)
        (target / "cleaned_named.md").write_text(cleaned, encoding="utf-8")
        (target / "memory_named.json").write_text(
            json.dumps(new, indent=1, sort_keys=True), encoding="utf-8")
        (target / "diagnostics.json").write_text(
            json.dumps(getattr(build_named_memory, "diagnostics", {}), indent=1),
            encoding="utf-8")
        (target / "report.md").write_text(report(name, old, new), encoding="utf-8")
        print(f"  old {summarise(old)}")
        print(f"  new {summarise(new)}")
        print(f"  report: {target / 'report.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
