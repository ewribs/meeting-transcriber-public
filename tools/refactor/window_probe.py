#!/usr/bin/env python3
"""Does the model find an item when it reads only the passage around it?

    .venv/bin/python tools/refactor/window_probe.py TRANSCRIPT.md "phrase from the passage" [--words 500]

Runs the extraction step (before the second look) on a short window of the
transcript around the phrase, and prints everything it finds and drops.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import config  # noqa: E402
import signals_pass  # noqa: E402
from ai import ask_llm  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript", type=Path)
    parser.add_argument("phrase")
    parser.add_argument("--words", type=int, default=500, help="words on each side")
    args = parser.parse_args()
    text = args.transcript.read_text(encoding="utf-8")
    at = text.casefold().find(args.phrase.casefold())
    if at < 0:
        sys.exit("phrase not found")
    before = text[:at].split()[-args.words:]
    after = text[at:].split()[:args.words]
    window = " ".join(before + after)
    dropped: list = []
    found = signals_pass.extract(window, "probe", ask_llm, config.SELF_NAME,
                                 chunk_words=10000, dropped=dropped)
    for kind, items in found.items():
        print(f"\n== {kind} ({len(items)})")
        for item in items:
            print(f"- {item['text']}\n    quote: {item['evidence'][:160]}")
    print("\n== dropped")
    for _n, kind, reason, text_ in dropped:
        print(f"- {kind}: {reason} - {text_[:140]}")


main()
