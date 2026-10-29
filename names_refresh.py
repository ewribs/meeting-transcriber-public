"""Bring a meeting up to date after you name more of its voices.

A meeting's transcript, action items and summary are built from the names known
at that time. When you name more voices later, the voice file is updated but the
summary is not. This module:

  * remembers which named voices each summary was built with (names_used.json),
  * says when more voices have been named since, and how much they spoke,
  * rebuilds the meeting in a staging folder, so you can look first, then
    applies it (the originals are saved and can be put back) or discards it.

The rebuild itself is catch_up.py's. Nothing here touches audio.

    python3 names_refresh.py stamp-all    # one-time: treat today's names as already used
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import catch_up

STAMP = "names_used.json"
MIN_SHARE = 0.05      # newly named voices must have spoken at least this share


def _named_voices(document: dict | None) -> dict[str, str]:
    """{voice id: person} for the voices that have a name."""
    import voice_service as vs
    out: dict[str, str] = {}
    for voice in (document or {}).get("voices", []):
        if voice.get("status") == "named" and not vs.is_noise(voice):
            out[str(voice.get("id"))] = str(voice.get("person") or "")
    return out


def record_names_used(run_dir: Path) -> bool:
    """Save which named voices this summary was built with. Never raises."""
    try:
        import voice_service as vs
        document = vs.read_speakers(Path(run_dir))
        if document is None:
            return False
        data = {"voices": _named_voices(document),
                "recorded": datetime.now().isoformat(timespec="seconds")}
        (Path(run_dir) / STAMP).write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:       # noqa: BLE001 - never fail a meeting
        return False


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _can_undo(run_name: str, backup_root: Path) -> bool:
    folder = Path(backup_root) / run_name
    for record in folder.glob("*/record.json"):
        if (_read(record) or {}).get("state") in ("applied", "failed part-way"):
            return True
    return False


def status(run_dir: Path, staging_root: Path, backup_root: Path) -> dict:
    """Where this meeting stands.

    state: "off" (cannot be rebuilt, or named transcripts are off), "unknown" (built
    before names were tracked), "current", "stale" (more voices named since the
    build), "ready" (rebuilt, waiting for you to apply or discard).
    """
    import config
    import voice_service as vs
    run_dir = Path(run_dir)
    result = {"state": "off", "people": [], "share": 0.0, "reason": "",
              "staged": None, "can_undo": _can_undo(run_dir.name, backup_root)}
    if not getattr(config, "NAMED_TRANSCRIPT", False):
        result["reason"] = "named transcripts are off"
        return result
    reason = catch_up.problem_with(run_dir)
    if reason:
        result["reason"] = reason
        return result
    staged = _read(Path(staging_root) / run_dir.name / "status.json")
    if staged and staged.get("state") == "built":
        result["state"] = "ready"
        result["staged"] = {"old": staged.get("old"), "new": staged.get("new")}
        return result
    stamp = _read(run_dir / STAMP)
    if stamp is None:
        result["state"] = "unknown"
        return result
    document = vs.read_speakers(run_dir)
    now, then = _named_voices(document), dict(stamp.get("voices") or {})
    fresh = [vid for vid, person in now.items() if then.get(vid) != person]
    spoken = {str(v.get("id")): float(v.get("seconds") or 0)
              for v in (document or {}).get("voices", [])}
    total = sum(spoken.values())
    share = sum(spoken.get(vid, 0.0) for vid in fresh) / total if total else 0.0
    result["people"] = sorted({now[vid] for vid in fresh if now[vid]}, key=str.casefold)
    result["share"] = round(share, 3)
    result["state"] = "stale" if fresh and share >= MIN_SHARE else "current"
    return result


def discard(run_dir: Path, staging_root: Path) -> bool:
    target = Path(staging_root) / Path(run_dir).name
    if target.exists():
        shutil.rmtree(target)
        return True
    return False


def stamp_all(output_root: Path) -> dict:
    """One-time: meetings with no stamp are treated as built with today's names."""
    counts = {"stamped": 0, "had_one": 0, "skipped": 0}
    for name in catch_up.all_runs(output_root):
        run_dir = Path(output_root) / name
        if (run_dir / STAMP).exists():
            counts["had_one"] += 1
        elif catch_up.problem_with(run_dir) is None and record_names_used(run_dir):
            counts["stamped"] += 1
        else:
            counts["skipped"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["stamp-all"])
    parser.parse_args(argv)
    import config
    print(stamp_all(config.OUTPUT_DIR))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
