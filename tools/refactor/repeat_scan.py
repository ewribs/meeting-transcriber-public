#!/usr/bin/env python3
"""Read-only scan: which saved action items would the repeat check merge?

    .venv/bin/python tools/refactor/repeat_scan.py [--show]

Looks at every meeting's meeting_memory.json. Changes nothing.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import action_items_pass  # noqa: E402
import config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", action="store_true", help="print each merged pair")
    args = parser.parse_args()
    meetings = hit_meetings = total = merged = 0
    for path in sorted(Path(config.OUTPUT_DIR).glob("20*/meeting_memory.json")):
        try:
            items = [x for x in json.loads(path.read_text()).get("commitments", [])
                     if isinstance(x, dict)]
        except (OSError, ValueError):
            continue
        meetings += 1
        total += len(items)
        seen, dropped = [], []
        for item in items:
            triple = (item.get("owner", ""), item.get("action", ""), item.get("evidence", ""))
            match = next((s for s in seen if action_items_pass.repeats(*triple, [s])), None)
            if match:
                dropped.append((match[1], triple[1]))
            else:
                seen.append(triple)
        if dropped:
            hit_meetings += 1
            merged += len(dropped)
            if args.show:
                print(path.parent.name)
                for kept, gone in dropped:
                    print(f"  keep: {kept[:90]}\n  drop: {gone[:90]}")
    print(f"{meetings} meetings, {total} action items, "
          f"{merged} would be merged in {hit_meetings} meetings")


main()
