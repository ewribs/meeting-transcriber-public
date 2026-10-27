"""Experiment: can a different action-item prompt give a list people can use?

Reads a cleaned transcript that already has names (for example the one a
catch-up or named experiment produced) and asks the model for action items in
the new style: specific, stand-alone sentences with the detail that was
spoken. Prints and saves the list next to the one the current pipeline made.
Nothing in the meeting folders is changed.

    python3 tools/refactor/actions_experiment.py TRANSCRIPT.md --out REPORT.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from action_items_pass import (  # noqa: E402,F401  (re-exported for the tests)
    OTHER_LIMIT, SCHEMA, build_prompt, extract, is_firm, judge, locate, norm,
    not_an_action, tidy_task,
)

def render(run: str, items: list[dict], current: list[str],
           removed: list[dict] | None = None, notes: list | None = None) -> str:
    firm = [item for item in items if item.get("firm")]
    other = [item for item in items if not item.get("firm")][:OTHER_LIMIT]
    lines = [f"# {run}", "", f"## ACTION ITEMS ({len(firm)})", ""]
    for item in firm:
        due = f" (due: {item['due']})" if item["due"] else ""
        lines.append(f"- **{item['owner']}**: {item['task']}{due}")
        lines.append(f"  - quote: \"{item['evidence']}\"")
    lines += ["", f"## OTHER NEXT STEPS MENTIONED ({len(other)} of {len(items) - len(firm)})", ""]
    for item in other:
        due = f" (due: {item['due']})" if item["due"] else ""
        lines.append(f"- {item['owner']}: {item['task']}{due}  [said by {item['speaker'] or '?'}]")
    if removed:
        lines += ["", "## Removed by the second look", ""]
        lines += [f"- {item['owner']}: {item['task']}" for item in removed]
    if notes:
        lines += ["", "## Dropped before the second look", ""]
        lines += [f"- chunk {n}: {reason}" + (f" - {task}" if task else "") for n, reason, task in notes]
    lines += ["", "## CURRENT action items", ""]
    lines += [f"- {text}" for text in current] or ["- (none)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcript", type=Path)
    parser.add_argument("--memory", type=Path, help="the memory JSON to compare with")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    import config
    from ai import ask_llm
    text = args.transcript.read_text(encoding="utf-8")
    notes: list = []
    items = extract(text, args.transcript.parent.name, ask_llm, config.SELF_NAME, dropped=notes)
    kept = judge(items, text, ask_llm)
    removed = [item for item in items if item not in kept]
    items = kept
    current: list[str] = []
    if args.memory and args.memory.exists():
        memory = json.loads(args.memory.read_text(encoding="utf-8"))
        current = [f"{row.get('owner')}: {row.get('action')}"
                   for row in memory.get("commitments") or [] if isinstance(row, dict)]
        current += [str(row) for row in memory.get("follow_ups") or []
                    if str(row).startswith("Possible commitment")]
    report = render(args.transcript.parent.name, items, current, removed, notes)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
