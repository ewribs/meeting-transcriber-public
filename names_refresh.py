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
import re
import shutil
import time
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

    state: "off" (cannot be rebuilt, or named transcripts are off), "current",
    "stale" (more voices named since the build), "ready" (rebuilt, waiting for you
    to apply or discard). A meeting with no record of the names it was built with
    was built without any (for example, voice recognition could not run), so every
    voice named since counts as new.
    """
    import config
    import voice_service as vs
    run_dir = Path(run_dir)
    result = {"state": "off", "people": [], "share": 0.0, "reason": "",
              "staged": None, "can_undo": _can_undo(run_dir.name, backup_root),
              "progress": _progress(staging_root, run_dir.name)}
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
        result["progress"] = ""
        result["staged"] = {"old": staged.get("old"), "new": staged.get("new")}
        return result
    stamp = _read(run_dir / STAMP) or {}
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


# ----------------------------------------------------------------- progress --

PROGRESS = "progress.txt"
PROGRESS_FRESH_SECONDS = 15 * 60


def progress_text(line: str) -> str:
    """A plain-words step for one line the rebuild printed ("" when it says nothing)."""
    text = line.strip()
    chunk = re.search(r"Cleaning chunk (\d+)/(\d+)", text)
    if chunk:
        return f"Cleaning the transcript (part {chunk.group(1)} of {chunk.group(2)})"
    if "Cleaning" in text and "chunks" in text:
        return "Cleaning the transcript"
    if "action items" in text.casefold():
        return "Finding action items"
    if "decisions, risks" in text.casefold():
        return "Finding decisions, risks and open questions"
    if "ummar" in text:
        return "Writing the summary"
    return ""


class ProgressTee:
    """Stands in for stdout during a rebuild: passes the text on and keeps the
    latest step in a small file the app can read while the rebuild runs."""

    def __init__(self, stream, path: Path):
        self.stream = stream
        self.path = Path(path)
        self._pending = ""

    def write(self, text: str) -> int:
        self.stream.write(text)
        self._pending += text
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            step = progress_text(line)
            if step:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(step, encoding="utf-8")
                except OSError:
                    pass
        return len(text)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return False


def _progress(staging_root: Path, run_name: str) -> str:
    path = Path(staging_root) / run_name / PROGRESS
    try:
        if time.time() - path.stat().st_mtime > PROGRESS_FRESH_SECONDS:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ------------------------------------------------------------------ preview --

_KEY_SECTIONS = ("decision", "action item", "next step", "risk", "concern", "open question")
_EMPTY = re.compile(r"^none( identified| found| mentioned)?\.?$", re.IGNORECASE)
_HEADING = re.compile(r"^(?:#{2,3}\s+(.+?)|\*\*([^*]+)\*\*)\s*$")


def _sections(markdown: str) -> dict[str, list[str]]:
    """{heading: its lines} for a summary, bullets stripped."""
    found: dict[str, list[str]] = {}
    heading = ""
    for raw in markdown.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _HEADING.match(line)
        if match:
            heading = (match.group(1) or match.group(2)).strip()
            found.setdefault(heading, [])
            continue
        item = re.sub(r"^[-*\u2022]\s+", "", line)
        if not _EMPTY.match(item):          # "None identified." is an empty section
            found.setdefault(heading, []).append(item)
    return found


def _same(line: str) -> str:
    return re.sub(r"[\s.]+$", "", re.sub(r"\s+", " ", line.casefold()))


def summary_changes(current: str, rebuilt: str) -> dict:
    """What differs in the sections people act on (decisions, action items, risks,
    open questions and their unconfirmed lists), as markdown plus counts."""
    old, new = _sections(current), _sections(rebuilt)
    headings = [h for h in new if h in old or h in new] + [h for h in old if h not in new]
    blocks, added_total, removed_total = [], 0, 0
    for heading in headings:
        if not any(word in heading.casefold() for word in _KEY_SECTIONS):
            continue
        before, after = old.get(heading, []), new.get(heading, [])
        seen_before = {_same(x) for x in before}
        seen_after = {_same(x) for x in after}
        added = [x for x in after if _same(x) not in seen_before]
        removed = [x for x in before if _same(x) not in seen_after]
        if not added and not removed:
            continue
        added_total += len(added)
        removed_total += len(removed)
        block = [f"### {heading}"]
        block += [f"- **Added:** {line}" for line in added]
        block += [f"- **Removed:** {line}" for line in removed]
        blocks.append("\n".join(block))
    text = "\n\n".join(blocks) if blocks else (
        "No differences in the decisions, action items, risks or open questions.")
    return {"changes": text, "added": added_total, "removed": removed_total}


def preview(run_dir: Path, staging_root: Path) -> dict:
    """The current and the rebuilt summary, and what changed between them."""
    run_dir = Path(run_dir)
    staged = Path(staging_root) / run_dir.name / "work" / "meeting_summary.md"
    if not staged.exists():
        raise catch_up.CatchUpError("There is no rebuilt summary to preview. Update the meeting first.")
    current_path = run_dir / "meeting_summary.md"
    current = current_path.read_text(encoding="utf-8") if current_path.exists() else ""
    rebuilt = staged.read_text(encoding="utf-8")
    return {"current": current, "rebuilt": rebuilt, **summary_changes(current, rebuilt)}


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
