#!/usr/bin/env python3
"""Private end-to-end benchmark harness for Meeting Transcriber memory quality.

Real benchmark cases live under ``private_benchmarks/`` which is gitignored.
The harness replays the cleaned transcript through the current memory pipeline
without rerunning Whisper or the GUI, captures detailed stage traces, and scores
final memory against a small human-authored expected-memory file.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_CASE_ROOT = _REPO_ROOT / "private_benchmarks"
DEFAULT_RUN_ROOT = _REPO_ROOT / "benchmark_runs"
REQUIRED_SOURCE_FILES = (
    "meeting_metadata.json",
    "meeting_summary.md",
    "meeting_transcript_cleaned.md",
)
CATEGORY_CONFIG = {
    "commitments": {"text_key": "action", "owner_key": "owner"},
    "decisions": {"text_key": "decision", "owner_key": None},
    "risks": {"text_key": "risk", "owner_key": None},
    "open_questions": {"text_key": "question", "owner_key": None},
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def _item_text(category: str, item: Any) -> str:
    cfg = CATEGORY_CONFIG[category]
    if isinstance(item, dict):
        return str(item.get(cfg["text_key"], "")).strip()
    return str(item or "").strip()


def _item_owner(category: str, item: Any) -> str:
    cfg = CATEGORY_CONFIG[category]
    key = cfg.get("owner_key")
    if not key or not isinstance(item, dict):
        return ""
    return str(item.get(key, "")).strip()


def _item_match_text(category: str, item: Any) -> str:
    """Return the searchable benchmark text for one predicted memory item.

    Human gold specs often describe details that belong in exact/supporting
    evidence rather than the normalized Action label itself.  Match expected
    terms against the complete item payload while still reporting the primary
    Action/Decision/Risk/Question text separately.
    """

    values = [_item_text(category, item)]
    if isinstance(item, dict):
        evidence = item.get("evidence", "")
        if isinstance(evidence, list):
            values.extend(str(value) for value in evidence if value)
        elif evidence:
            values.append(str(evidence))
        supporting = item.get("supporting_evidence", []) or []
        if isinstance(supporting, list):
            values.extend(str(value) for value in supporting if value)
        elif supporting:
            values.append(str(supporting))
    return " ".join(value for value in values if value)


def _matches_spec(category: str, item: Any, spec: dict[str, Any]) -> bool:
    text = _normalize_text(_item_match_text(category, item))
    owner = _normalize_text(_item_owner(category, item))

    wanted_owner = _normalize_text(spec.get("owner", ""))
    if wanted_owner and owner != wanted_owner:
        return False

    all_terms = [_normalize_text(v) for v in spec.get("text_contains_all", []) if str(v).strip()]
    if any(term not in text for term in all_terms):
        return False

    any_terms = [_normalize_text(v) for v in spec.get("text_contains_any", []) if str(v).strip()]
    if any_terms and not any(term in text for term in any_terms):
        return False

    not_terms = [_normalize_text(v) for v in spec.get("text_excludes", []) if str(v).strip()]
    if any(term in text for term in not_terms):
        return False

    pattern = str(spec.get("text_regex", "")).strip()
    if pattern and re.search(pattern, _item_text(category, item), flags=re.IGNORECASE) is None:
        return False

    return True


def _score_category(category: str, predicted: list[Any], expected: list[dict[str, Any]]) -> dict[str, Any]:
    used: set[int] = set()
    matches: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for spec in expected:
        matched_index = None
        for index, item in enumerate(predicted):
            if index in used:
                continue
            if _matches_spec(category, item, spec):
                matched_index = index
                break
        if matched_index is None:
            missing.append(spec)
            continue
        used.add(matched_index)
        matches.append({
            "expected": spec,
            "predicted_index": matched_index,
            "predicted": predicted[matched_index],
        })

    unexpected = [item for index, item in enumerate(predicted) if index not in used]
    true_positive = len(matches)
    precision = true_positive / len(predicted) if predicted else (1.0 if not expected else 1.0)
    recall = true_positive / len(expected) if expected else 1.0

    return {
        "predicted_count": len(predicted),
        "expected_count": len(expected),
        "matched_count": true_positive,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "matches": matches,
        "missing": missing,
        "unexpected": unexpected,
    }


def score_memory(memory: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    expected_root = gold.get("expected", {}) or {}
    category_scores: dict[str, Any] = {}
    for category in CATEGORY_CONFIG:
        predicted = list(memory.get(category, []) or [])
        expected = list(expected_root.get(category, []) or [])
        category_scores[category] = _score_category(category, predicted, expected)

    forbidden = gold.get("forbidden", {}) or {}
    violations: list[dict[str, Any]] = []
    forbidden_owners = {_normalize_text(v) for v in forbidden.get("owners", []) if str(v).strip()}
    for item in memory.get("commitments", []) or []:
        owner = _normalize_text(_item_owner("commitments", item))
        if owner and owner in forbidden_owners:
            violations.append({"type": "forbidden_owner", "owner": _item_owner("commitments", item), "item": item})

    for category in CATEGORY_CONFIG:
        key = f"{category}_text_contains_any"
        terms = [_normalize_text(v) for v in forbidden.get(key, []) if str(v).strip()]
        if not terms:
            continue
        for item in memory.get(category, []) or []:
            text = _normalize_text(_item_text(category, item))
            hit = next((term for term in terms if term in text), None)
            if hit:
                violations.append({"type": "forbidden_text", "category": category, "term": hit, "item": item})

    thresholds = gold.get("thresholds", {}) or {}
    failures: list[str] = []
    for category, score in category_scores.items():
        category_threshold = thresholds.get(category, {}) or {}
        min_precision = float(category_threshold.get("precision", 1.0))
        min_recall = float(category_threshold.get("recall", 1.0))
        if score["precision"] < min_precision:
            failures.append(f"{category} precision {score['precision']:.2f} < {min_precision:.2f}")
        if score["recall"] < min_recall:
            failures.append(f"{category} recall {score['recall']:.2f} < {min_recall:.2f}")
    if violations:
        failures.append(f"{len(violations)} forbidden-output violation(s)")

    return {
        "passed": not failures,
        "categories": category_scores,
        "forbidden_violations": violations,
        "failures": failures,
    }


def _trace_counts(trace: dict[str, Any]) -> dict[str, Any]:
    windows = trace.get("windows", []) or []
    pass2 = trace.get("pass2_proposed", {}) or {}
    verified = trace.get("verified_result", {}) or {}
    final = trace.get("final_memory", {}) or {}
    return {
        "windows": len(windows),
        "window_proposed_events": sum(len(w.get("proposed_events", []) or []) for w in windows),
        "window_grounded_events": sum(len(w.get("grounded_events", []) or []) for w in windows),
        "merged_events": len(trace.get("merged_events", []) or []),
        "pass2_proposed": {key: len(value or []) for key, value in pass2.items()},
        "verified": {key: len(value or []) for key, value in verified.items()},
        "final": {key: len(final.get(key, []) or []) for key in CATEGORY_CONFIG},
    }


def _load_case(case_dir: Path) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    for filename in REQUIRED_SOURCE_FILES:
        path = case_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing benchmark source file: {path}")
    expected_path = case_dir / "expected_memory.json"
    if not expected_path.exists():
        raise FileNotFoundError(f"Missing benchmark gold file: {expected_path}")

    metadata = json.loads((case_dir / "meeting_metadata.json").read_text(encoding="utf-8"))
    summary = (case_dir / "meeting_summary.md").read_text(encoding="utf-8")
    transcript = (case_dir / "meeting_transcript_cleaned.md").read_text(encoding="utf-8")
    gold = json.loads(expected_path.read_text(encoding="utf-8"))
    return metadata, summary, transcript, gold


def run_case(case_dir: Path, run_root: Path = DEFAULT_RUN_ROOT) -> dict[str, Any]:
    metadata, summary, transcript, gold = _load_case(case_dir)

    from ai import (
        build_complete_meeting_memory,
        get_last_memory_resolution_diagnostics,
        get_last_memory_resolution_trace,
        set_memory_resolution_trace_enabled,
    )

    participants = metadata.get("participants", []) or []
    meeting_label = str(metadata.get("display_title") or metadata.get("meeting_run") or case_dir.name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = run_root / timestamp / case_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    set_memory_resolution_trace_enabled(True)
    try:
        memory = build_complete_meeting_memory(
            meeting_label=meeting_label,
            meeting_summary=summary,
            transcript=transcript,
            participants=participants,
        )
        diagnostics = get_last_memory_resolution_diagnostics()
        trace = get_last_memory_resolution_trace()
    finally:
        set_memory_resolution_trace_enabled(False)
    elapsed = time.perf_counter() - start

    score = score_memory(memory, gold)
    result = {
        "case": case_dir.name,
        "meeting_label": meeting_label,
        "elapsed_seconds": round(elapsed, 3),
        "score": score,
        "trace_counts": _trace_counts(trace),
        "diagnostics": diagnostics,
    }

    (output_dir / "actual_memory.json").write_text(json.dumps(memory, indent=2), encoding="utf-8")
    (output_dir / "memory_trace.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")
    (output_dir / "processing_diagnostics.json").write_text(json.dumps(diagnostics, indent=2), encoding="utf-8")
    (output_dir / "benchmark_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output_dir / "benchmark_report.md").write_text(_render_report(result), encoding="utf-8")
    result["output_dir"] = str(output_dir)
    return result


def _render_report(result: dict[str, Any]) -> str:
    score = result["score"]
    lines = [
        f"# Memory Benchmark — {result['case']}",
        "",
        f"Status: **{'PASS' if score['passed'] else 'FAIL'}**",
        f"Elapsed: {result['elapsed_seconds']:.1f}s",
        "",
        "## Quality",
        "",
        "| Category | Expected | Predicted | Matched | Precision | Recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for category, values in score["categories"].items():
        lines.append(
            f"| {category} | {values['expected_count']} | {values['predicted_count']} | "
            f"{values['matched_count']} | {values['precision']:.2f} | {values['recall']:.2f} |"
        )
    lines.extend(["", "## Pipeline counts", "", "```json", json.dumps(result["trace_counts"], indent=2), "```", ""])
    if score["failures"]:
        lines.extend(["## Failures", ""])
        lines.extend(f"- {failure}" for failure in score["failures"])
        lines.append("")
    for category, values in score["categories"].items():
        if values["missing"] or values["unexpected"]:
            lines.extend([f"## {category}", ""])
            if values["missing"]:
                lines.append("Missing expected items:")
                lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in values["missing"])
            if values["unexpected"]:
                lines.append("Unexpected predicted items:")
                lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in values["unexpected"])
            lines.append("")
    if score["forbidden_violations"]:
        lines.extend(["## Forbidden output", ""])
        lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in score["forbidden_violations"])
    return "\n".join(lines).rstrip() + "\n"


def init_case(source_dir: Path, case_name: str, case_root: Path = DEFAULT_CASE_ROOT) -> Path:
    destination = case_root / case_name
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"Benchmark case already exists and is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for filename in REQUIRED_SOURCE_FILES:
        source = source_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"Source meeting is missing: {source}")
        shutil.copy2(source, destination / filename)

    expected_path = destination / "expected_memory.json"
    expected_path.write_text(json.dumps({
        "description": "PRIVATE benchmark gold. Edit expected items before running.",
        "thresholds": {
            category: {"precision": 1.0, "recall": 1.0}
            for category in CATEGORY_CONFIG
        },
        "expected": {category: [] for category in CATEGORY_CONFIG},
        "forbidden": {
            "owners": ["Remote", "Mic"],
        },
    }, indent=2), encoding="utf-8")
    return destination


def discover_cases(case_root: Path) -> list[Path]:
    if not case_root.exists():
        return []
    return sorted(
        path for path in case_root.iterdir()
        if path.is_dir() and (path / "expected_memory.json").exists()
    )


def _print_result(result: dict[str, Any]) -> None:
    score = result["score"]
    print()
    print(f"{result['case']}: {'PASS' if score['passed'] else 'FAIL'} ({result['elapsed_seconds']:.1f}s)")
    for category, values in score["categories"].items():
        print(
            f"  {category:14s} P={values['precision']:.2f} R={values['recall']:.2f} "
            f"matched={values['matched_count']}/{values['expected_count']} predicted={values['predicted_count']}"
        )
    if score["failures"]:
        for failure in score["failures"]:
            print(f"  FAIL: {failure}")
    print(f"  Trace: {result['output_dir']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay and score private meeting-memory benchmark cases.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a private benchmark case from an existing meeting run folder.")
    init_parser.add_argument("--source", type=Path, required=True)
    init_parser.add_argument("--case", required=True)
    init_parser.add_argument("--case-root", type=Path, default=DEFAULT_CASE_ROOT)

    run_parser = subparsers.add_parser("run", help="Run one or all private benchmark cases through the current memory pipeline.")
    run_parser.add_argument("--case")
    run_parser.add_argument("--all", action="store_true")
    run_parser.add_argument("--case-root", type=Path, default=DEFAULT_CASE_ROOT)
    run_parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)

    score_parser = subparsers.add_parser("score", help="Score an existing actual_memory.json without calling the LLM.")
    score_parser.add_argument("--actual", type=Path, required=True)
    score_parser.add_argument("--expected", type=Path, required=True)

    args = parser.parse_args()

    if args.command == "init":
        destination = init_case(args.source, args.case, args.case_root)
        print(f"Created private benchmark case: {destination}")
        print(f"Edit: {destination / 'expected_memory.json'}")
        return 0

    if args.command == "score":
        memory = json.loads(args.actual.read_text(encoding="utf-8"))
        gold = json.loads(args.expected.read_text(encoding="utf-8"))
        score = score_memory(memory, gold)
        print(json.dumps(score, indent=2))
        return 0 if score["passed"] else 1

    if not args.all and not args.case:
        parser.error("run requires --case NAME or --all")

    if args.all:
        cases = discover_cases(args.case_root)
    else:
        cases = [args.case_root / args.case]

    if not cases:
        print(f"No benchmark cases found under {args.case_root}", file=sys.stderr)
        return 2

    passed = True
    for case_dir in cases:
        result = run_case(case_dir, args.run_root)
        _print_result(result)
        passed = passed and result["score"]["passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
