from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


MAX_TELEMETRY_RECORDS = 500

TELEMETRY_FIELDS = (
    "profile",
    "mode",
    "inference_calls",
    "chunk_count",
    "estimated_prompt_tokens",
    "direct_token_budget",
    "context_size_tokens",
    "context_reserve_tokens",
    "model_name",
    "model_parameter_billions",
    "model_budget_factor",
    "hardware_label",
    "hardware_performance_class",
    "hardware_budget_factor",
    "calibration_factor",
    "calibration_sample_count",
    "calibration_median_elapsed_seconds",
    "calibration_reason",
)


def default_telemetry_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Meeting Transcriber"
        / "execution_history.jsonl"
    )


def build_execution_record(
    execution_metadata: dict,
    *,
    elapsed_seconds: float,
) -> dict:
    record = {
        "timestamp": datetime.now(
            timezone.utc
        ).isoformat(),
        "elapsed_seconds": round(
            max(0.0, float(elapsed_seconds)),
            3,
        ),
    }

    for field in TELEMETRY_FIELDS:
        if field in execution_metadata:
            record[field] = (
                execution_metadata[field]
            )

    return record


def record_execution_telemetry(
    execution_metadata: dict,
    *,
    elapsed_seconds: float,
    telemetry_path: Path | None = None,
) -> None:
    """
    Persist privacy-safe local execution metrics.

    Only the explicit TELEMETRY_FIELDS whitelist is stored. User prompts,
    session names, meeting titles, transcripts, and model responses are never
    written here.

    Telemetry is best-effort and must never make a successful query fail.
    """

    path = (
        telemetry_path
        if telemetry_path is not None
        else default_telemetry_path()
    )

    try:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        record = build_execution_record(
            execution_metadata,
            elapsed_seconds=elapsed_seconds,
        )

        existing_lines = []

        if path.exists():
            existing_lines = [
                line
                for line in path.read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]

        existing_lines.append(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
            )
        )

        existing_lines = existing_lines[
            -MAX_TELEMETRY_RECORDS:
        ]

        path.write_text(
            "\n".join(existing_lines) + "\n",
            encoding="utf-8",
        )

    except (OSError, TypeError, ValueError):
        return


def load_execution_telemetry(
    telemetry_path: Path | None = None,
) -> list[dict]:
    path = (
        telemetry_path
        if telemetry_path is not None
        else default_telemetry_path()
    )

    if not path.exists():
        return []

    records = []

    try:
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines():
            if not line.strip():
                continue

            value = json.loads(line)

            if isinstance(value, dict):
                records.append(value)

    except (OSError, json.JSONDecodeError):
        return []

    return records
