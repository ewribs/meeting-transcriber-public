#!/usr/bin/env python3
"""Create/update the private local identity configuration interactively."""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
IDENTITY_PATH = PROJECT_DIR / "identity.local.json"


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def main() -> int:
    existing: dict[str, object] = {}
    if IDENTITY_PATH.exists():
        try:
            data = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = data
        except (OSError, json.JSONDecodeError):
            pass

    current_name = str(existing.get("self_name", "")).strip()
    current_refs = existing.get("self_reference_names", [])
    if not isinstance(current_refs, list):
        current_refs = []
    current_label = str(existing.get("self_speaker_label", "Mic")).strip() or "Mic"

    print("Meeting Transcriber private identity setup")
    print("This file is local-only and ignored by Git.\n")

    self_name = _prompt("Preferred self name", current_name)
    if not self_name:
        raise SystemExit("A preferred self name is required.")

    default_refs = ", ".join(str(v) for v in current_refs if str(v).strip())
    refs_text = _prompt(
        "Names/nicknames that may refer to you (comma-separated)",
        default_refs or self_name,
    )
    refs = [part.strip() for part in refs_text.split(",") if part.strip()]
    speaker_label = _prompt("Local transcript speaker label", current_label)

    payload = {
        "self_name": self_name,
        "self_reference_names": refs,
        "self_speaker_label": speaker_label,
    }
    IDENTITY_PATH.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"\nSaved private identity configuration: {IDENTITY_PATH}")
    print("Git ignores this file; do not add it to source control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
