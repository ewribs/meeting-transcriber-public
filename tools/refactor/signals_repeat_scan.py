#!/usr/bin/env python3
"""Read-only scan: saved decisions, risks and open questions that say nearly the same thing.

    .venv/bin/python tools/refactor/signals_repeat_scan.py [--min 0.5]

Compares items of the same kind inside each meeting (firm and unconfirmed together).
Prints each close pair with its overlap score. Changes nothing.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import action_items_pass  # noqa: E402
import config  # noqa: E402

KINDS = {"decisions": ("decision", "other_decisions"),
         "risks": ("risk", "other_risks"),
         "open_questions": ("question", "other_questions")}


def text_of(item, key) -> str:
    return str(item.get(key, "")) if isinstance(item, dict) else str(item)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min", type=float, default=0.5, help="overlap needed to report a pair")
    args = parser.parse_args()
    totals = {k: [0, 0] for k in KINDS}
    for path in sorted(Path(config.OUTPUT_DIR).glob("20*/meeting_memory.json")):
        try:
            memory = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        printed = False
        for kind, (key, other) in KINDS.items():
            items = [("firm", text_of(i, key)) for i in memory.get(kind) or []]
            items += [("maybe", text_of(i, key)) for i in memory.get(other) or []]
            words = [action_items_pass._content(t) for _, t in items]
            totals[kind][0] += len(items)
            for a in range(len(items)):
                for b in range(a + 1, len(items)):
                    small = min(len(words[a]), len(words[b]))
                    if not small:
                        continue
                    score = len(words[a] & words[b]) / small
                    if score >= args.min:
                        totals[kind][1] += 1
                        if not printed:
                            print(path.parent.name)
                            printed = True
                        print(f"  {kind} {score:.2f}\n    [{items[a][0]}] {items[a][1][:100]}"
                              f"\n    [{items[b][0]}] {items[b][1][:100]}")
    for kind, (count, pairs) in totals.items():
        print(f"{kind}: {count} items, {pairs} close pairs")


main()
