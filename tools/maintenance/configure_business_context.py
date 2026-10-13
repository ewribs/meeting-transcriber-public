#!/usr/bin/env python3
"""Create or validate the private local business-context configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from business_context_config import load_business_context_config


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--init-example",
        action="store_true",
        help="Create business_context.local.json from the public example if it does not exist.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    local_path = root / "business_context.local.json"
    example_path = root / "business_context.example.json"

    if args.init_example and not local_path.exists():
        data = json.loads(example_path.read_text(encoding="utf-8"))
        local_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            local_path.chmod(0o600)
        except OSError:
            pass
        print("Created business_context.local.json from the generic example.")

    config = load_business_context_config(local_path)
    print(
        f"Business context valid: {len(config['topic_normalization_rules'])} topic normalization rule(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
