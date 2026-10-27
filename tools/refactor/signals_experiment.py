"""Experiment: decisions, risks and open questions from a named transcript.

    python3 tools/refactor/signals_experiment.py TRANSCRIPT.md --memory MEMORY.json --out REPORT.md

Prints and saves what the new pass finds next to what the current pipeline made.
Nothing in the meeting folders is changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import signals_pass  # noqa: E402

TITLES = {"decisions": "DECISIONS", "risks": "RISKS", "open_questions": "OPEN QUESTIONS"}


def render(run_name: str, kept: dict, removed: dict, current: dict, notes: list) -> str:
    lines = [f"# {run_name}"]
    for kind in signals_pass.KINDS:
        lines += ["", f"## {TITLES[kind]} (new: {len(kept[kind])})", ""]
        for item in kept[kind]:
            tag = "" if item.get("firm", True) else " [unconfirmed]"
            lines.append(f"- {item['text']}{tag}")
            lines.append(f"  - quote: \"{item['evidence']}\"")
        if removed[kind]:
            lines += ["", "removed by the second look:"]
            lines += [f"- {item['text']}" for item in removed[kind]]
        lines += ["", f"current pipeline ({len(current.get(kind, []))}):"]
        for row in current.get(kind, []):
            text = row if isinstance(row, str) else (
                row.get("decision") or row.get("risk") or row.get("question") or str(row))
            lines.append(f"- {text}")
    if notes:
        lines += ["", "## dropped before the second look", ""]
        lines += [f"- chunk {n} {kind}: {reason}" + (f" - {text}" if text else "")
                  for n, kind, reason, text in notes]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--memory", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    import config
    from ai import ask_llm
    text = args.transcript.read_text(encoding="utf-8")
    notes: list = []
    kept, removed = signals_pass.run(text, args.transcript.parent.name, ask_llm,
                                     config.SELF_NAME, dropped=notes)
    current = {}
    if args.memory and args.memory.exists():
        current = json.loads(args.memory.read_text(encoding="utf-8"))
    report = render(args.transcript.parent.name, kept, removed, current, notes)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
