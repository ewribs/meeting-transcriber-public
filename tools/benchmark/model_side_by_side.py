#!/usr/bin/env python3
"""Side-by-side page of the model benchmark.

    python3 tools/benchmark/model_side_by_side.py

Reads private_benchmarks/model_bench/<model>/<meeting>/work/meeting_memory.json
and writes private_benchmarks/model_bench/side_by_side.html (private; never committed).
Run it again when more models have finished.
"""
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "private_benchmarks" / "model_bench"
MODELS = [("baseline", "Current (Qwen3 30B 6-bit)"), ("qwen38", "Qwen3.8 27B 4-bit"),
          ("mistral", "Mistral Small 3.2 24B")]
KINDS = [("commitments", "Action items"), ("decisions", "Decisions"),
         ("open_questions", "Open questions"), ("risks", "Risks"),
         ("other_next_steps", "Other next steps (unconfirmed)"),
         ("other_decisions", "Possible decisions (unconfirmed)"),
         ("other_risks", "Possible risks (unconfirmed)"),
         ("other_questions", "Possible questions (unconfirmed)")]


def text(item) -> str:
    if isinstance(item, str):
        return item
    owner = item.get("owner")
    body = (item.get("action") or item.get("decision") or item.get("risk")
            or item.get("question") or item.get("text") or json.dumps(item))
    due = item.get("due")
    return (f"{owner}: " if owner else "") + body + (f"  (due: {due})" if due else "")


def seconds(model: str) -> dict:
    out = {}
    path = ROOT / model / "seconds.txt"
    if path.exists():
        for line in path.read_text().splitlines():
            name, _, value = line.rpartition(" ")
            out[name or "total"] = int(value)
    return out


def main() -> None:
    present = [(m, label) for m, label in MODELS if (ROOT / m).is_dir()]
    meetings = sorted({p.name for m, _ in present for p in (ROOT / m).iterdir() if p.is_dir()},
                      reverse=True)
    parts = ["<!doctype html><meta charset=utf-8><title>Model side by side</title><style>"
             "body{font:14px/1.4 -apple-system,sans-serif;margin:20px;max-width:1800px}"
             "h2{margin-top:40px;border-top:3px solid #888;padding-top:10px}"
             "h3{margin:18px 0 4px;font-size:15px}table{border-collapse:collapse;width:100%;"
             "table-layout:fixed}td,th{border:1px solid #ccc;vertical-align:top;padding:6px}"
             "th{background:#eee;text-align:left}ul{margin:0;padding-left:16px}li{margin:3px 0}"
             ".none{color:#999}.n{color:#666;font-weight:normal}</style>"
             "<h1>Model benchmark: side by side</h1>"]
    parts.append("<p>Total time for the five meetings: " + ", ".join(
        f"<b>{html.escape(label)}</b> {seconds(m).get('total', 0) // 60} min"
        for m, label in present if seconds(m).get("total")) + "</p>")
    for meeting in meetings:
        parts.append(f"<h2>{html.escape(meeting)}</h2><table><tr>"
                     + "".join(f"<th>{html.escape(label)}<br><span class=n>"
                               f"{seconds(m).get(meeting, '-')} s</span></th>"
                               for m, label in present) + "</tr>")
        memories = {}
        for m, _ in present:
            path = ROOT / m / meeting / "work" / "meeting_memory.json"
            memories[m] = json.loads(path.read_text()) if path.exists() else None
        for key, title in KINDS:
            if not any(memories[m] and memories[m].get(key) for m, _ in present):
                continue
            parts.append(f"<tr><td colspan={len(present)}><h3>{title}</h3></td></tr><tr>")
            for m, _ in present:
                mem = memories[m]
                if mem is None:
                    parts.append("<td class=none>not run yet</td>")
                    continue
                items = mem.get(key) or []
                body = "".join(f"<li>{html.escape(text(i))}</li>" for i in items)
                parts.append(f"<td><b>{len(items)}</b><ul>{body}</ul></td>" if items
                             else "<td class=none>none</td>")
            parts.append("</tr>")
        parts.append("</table>")
    out = ROOT / "side_by_side.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(out)


main()
