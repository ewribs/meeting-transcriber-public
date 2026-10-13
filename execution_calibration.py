from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from execution_telemetry import load_execution_telemetry


MIN_CALIBRATION_SAMPLES = 5
STRONG_CALIBRATION_SAMPLES = 10
MIN_PROMPT_UTILIZATION = 0.50
FAST_MEDIAN_SECONDS = 20.0
SLOW_MEDIAN_SECONDS = 60.0


@dataclass(frozen=True)
class ExecutionCalibration:
    factor: float = 1.0
    sample_count: int = 0
    median_elapsed_seconds: float | None = None
    reason: str = "insufficient comparable history"


def _record_matches(
    record: dict,
    *,
    profile: str,
    model_name: str,
    context_size_tokens: int,
    hardware_label: str,
) -> bool:
    return (
        record.get("mode") == "direct"
        and record.get("profile") == profile
        and record.get("model_name") == model_name
        and int(record.get("context_size_tokens") or 0)
        == int(context_size_tokens or 0)
        and record.get("hardware_label") == hardware_label
    )


def _is_meaningful_budget_sample(record: dict) -> bool:
    try:
        prompt_tokens = float(
            record.get("estimated_prompt_tokens") or 0
        )
        direct_budget = float(
            record.get("direct_token_budget") or 0
        )
        elapsed_seconds = float(
            record.get("elapsed_seconds") or 0
        )
    except (TypeError, ValueError):
        return False

    if direct_budget <= 0 or elapsed_seconds <= 0:
        return False

    return (
        prompt_tokens / direct_budget
        >= MIN_PROMPT_UTILIZATION
    )


def get_execution_calibration(
    *,
    profile: str,
    model_name: str,
    context_size_tokens: int,
    hardware_label: str,
    records: list[dict] | None = None,
) -> ExecutionCalibration:
    """
    Return a conservative local-history adjustment for Auto execution.

    Only comparable direct runs are considered, and only when their prompt
    consumed at least half of the then-current direct budget. This prevents
    tiny/easy prompts from teaching Auto that much larger prompts are safe.

    Five comparable samples are required before history has any effect. Ten
    samples allow a slightly stronger adjustment. Median elapsed time is used
    so one unusually fast or slow query cannot move the budget by itself.
    """

    if records is None:
        records = load_execution_telemetry()

    comparable = [
        record
        for record in records
        if _record_matches(
            record,
            profile=profile,
            model_name=model_name,
            context_size_tokens=context_size_tokens,
            hardware_label=hardware_label,
        )
        and _is_meaningful_budget_sample(record)
    ]

    sample_count = len(comparable)

    if sample_count < MIN_CALIBRATION_SAMPLES:
        return ExecutionCalibration(
            sample_count=sample_count,
        )

    elapsed_values = [
        float(record["elapsed_seconds"])
        for record in comparable
    ]
    median_elapsed = median(elapsed_values)

    if sample_count >= STRONG_CALIBRATION_SAMPLES:
        if median_elapsed <= FAST_MEDIAN_SECONDS:
            factor = 1.10
            reason = "local direct runs are consistently fast"
        elif median_elapsed >= SLOW_MEDIAN_SECONDS:
            factor = 0.90
            reason = "local direct runs are consistently slow"
        else:
            factor = 1.00
            reason = "local direct performance is in the normal range"
    else:
        if median_elapsed <= FAST_MEDIAN_SECONDS:
            factor = 1.05
            reason = "local direct runs are trending fast"
        elif median_elapsed >= SLOW_MEDIAN_SECONDS:
            factor = 0.95
            reason = "local direct runs are trending slow"
        else:
            factor = 1.00
            reason = "local direct performance is in the normal range"

    return ExecutionCalibration(
        factor=factor,
        sample_count=sample_count,
        median_elapsed_seconds=round(
            median_elapsed,
            3,
        ),
        reason=reason,
    )
