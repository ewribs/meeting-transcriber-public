from __future__ import annotations

import json
import re
from dataclasses import dataclass

from hardware_profile import HardwareProfile
from performance_profile import (
    PERFORMANCE_PROFILE_NAMES,
    PROFILE_CONFIGS,
    resolve_performance_profile,
)


# These are practical local-inference budgets, not the model's advertised
# context-window limits. Auto resolves to a capability tier and manual
# profiles provide deterministic overrides.
DEFAULT_EXECUTION_PROFILE = "Auto"
MIN_CONTEXT_RESERVE_TOKENS = 2048
CONTEXT_RESERVE_FRACTION = 0.20

# Keep this public name for existing callers/tests while profile values now
# come from the centralized performance-profile module.
EXECUTION_PROFILES = {
    "Auto": {},
    **{
        name: {
            "direct_token_budget": config.direct_token_budget,
            "chunk_source_token_budget": config.chunk_source_token_budget,
            "context_size_tokens": config.context_size_tokens,
            "chunk_overlap_tokens": config.chunk_overlap_tokens,
        }
        for name, config in PROFILE_CONFIGS.items()
    },
}

DEFAULT_DIRECT_PROMPT_TOKEN_BUDGET = (
    PROFILE_CONFIGS["Balanced"].direct_token_budget
)
DEFAULT_CHUNK_SOURCE_TOKEN_BUDGET = (
    PROFILE_CONFIGS["Balanced"].chunk_source_token_budget
)

# Practical budget multipliers for larger models on the same hardware.
# Unknown model sizes preserve the selected profile budget.
MODEL_BUDGET_FACTORS = (
    (8.0, 1.00),
    (14.0, 0.85),
    (32.0, 0.70),
    (float("inf"), 0.55),
)


@dataclass(frozen=True)
class ExecutionProfile:
    name: str
    resolved_name: str
    direct_token_budget: int
    chunk_source_token_budget: int
    chunk_overlap_tokens: int = 0
    llm_call_timeout_seconds: int = 120
    profile_reason: str = ""
    context_size_tokens: int = 0
    context_reserve_tokens: int = 0
    model_name: str = ""
    model_parameter_billions: float | None = None
    model_budget_factor: float = 1.0
    hardware_label: str = ""
    hardware_performance_class: str = ""
    hardware_budget_factor: float = 1.0
    calibration_factor: float = 1.0
    calibration_sample_count: int = 0
    calibration_median_elapsed_seconds: float | None = None
    calibration_reason: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    mode: str
    estimated_prompt_tokens: int
    direct_token_budget: int


def infer_model_parameter_billions(
    model_name: str,
) -> float | None:
    """
    Infer parameter count from common Ollama tags such as qwen3:8b or
    qwen2.5:14b-instruct. Return None when the name does not encode it.
    """

    match = re.search(
        r"(?:^|[:_\-])(\d+(?:\.\d+)?)b(?:$|[_\-])",
        (model_name or "").lower(),
    )

    if match is None:
        return None

    try:
        return float(match.group(1))
    except ValueError:
        return None


def model_budget_factor(
    model_name: str,
) -> tuple[float, float | None]:
    parameter_billions = infer_model_parameter_billions(model_name)

    if parameter_billions is None:
        return 1.0, None

    for upper_bound, factor in MODEL_BUDGET_FACTORS:
        if parameter_billions <= upper_bound:
            return factor, parameter_billions

    return 1.0, parameter_billions


def context_reserve_tokens(
    context_size_tokens: int,
) -> int:
    if context_size_tokens <= 0:
        return 0

    return max(
        MIN_CONTEXT_RESERVE_TOKENS,
        int(context_size_tokens * CONTEXT_RESERVE_FRACTION),
    )


def get_execution_profile(
    profile_name: str = DEFAULT_EXECUTION_PROFILE,
    *,
    context_size_tokens: int = 0,
    model_name: str = "",
    hardware_profile: HardwareProfile | None = None,
    hardware_label: str = "",
    hardware_performance_class: str = "",
    hardware_budget_factor: float = 1.0,
    calibration_factor: float = 1.0,
    calibration_sample_count: int = 0,
    calibration_median_elapsed_seconds: float | None = None,
    calibration_reason: str = "",
) -> ExecutionProfile:
    requested = str(profile_name or DEFAULT_EXECUTION_PROFILE).strip()

    # Preserve compatibility with settings written by the earlier profile UI.
    if requested == "Aggressive":
        requested = "High Performance"

    if requested not in PERFORMANCE_PROFILE_NAMES:
        raise ValueError(f"Unknown execution profile: {profile_name}")

    resolved = resolve_performance_profile(
        requested,
        context_size_override=context_size_tokens,
        hardware=hardware_profile,
    )

    factor, parameter_billions = model_budget_factor(model_name)

    # Hardware chooses the profile under Auto. It does not multiply the
    # budget a second time. Local calibration and model size can still tune
    # the resolved profile conservatively.
    combined_budget_factor = factor * calibration_factor

    direct_token_budget = max(
        1024,
        int(resolved.direct_token_budget * combined_budget_factor),
    )
    chunk_source_token_budget = max(
        512,
        int(resolved.chunk_source_token_budget * combined_budget_factor),
    )

    effective_context_size = resolved.context_size_tokens
    reserve_tokens = context_reserve_tokens(effective_context_size)
    usable_context_tokens = max(
        1024,
        effective_context_size - reserve_tokens,
    )

    direct_token_budget = min(direct_token_budget, usable_context_tokens)
    chunk_source_token_budget = min(
        chunk_source_token_budget,
        max(512, usable_context_tokens),
    )

    detected_label = hardware_label or resolved.hardware_label
    detected_class = hardware_performance_class
    if not detected_class and hardware_profile is not None:
        detected_class = hardware_profile.performance_class

    return ExecutionProfile(
        name=resolved.requested_name,
        resolved_name=resolved.resolved_name,
        direct_token_budget=direct_token_budget,
        chunk_source_token_budget=chunk_source_token_budget,
        chunk_overlap_tokens=resolved.chunk_overlap_tokens,
        llm_call_timeout_seconds=resolved.llm_call_timeout_seconds,
        profile_reason=resolved.reason,
        context_size_tokens=effective_context_size,
        context_reserve_tokens=reserve_tokens,
        model_name=model_name,
        model_parameter_billions=parameter_billions,
        model_budget_factor=factor,
        hardware_label=detected_label,
        hardware_performance_class=detected_class,
        hardware_budget_factor=hardware_budget_factor,
        calibration_factor=calibration_factor,
        calibration_sample_count=calibration_sample_count,
        calibration_median_elapsed_seconds=calibration_median_elapsed_seconds,
        calibration_reason=calibration_reason,
    )

def estimate_tokens(value: object) -> int:
    """
    Return a conservative, dependency-free token estimate.

    Local Qwen tokenization is not imported here on purpose. Four UTF-8-ish
    characters per token is a common rough estimate; adding a small floor
    keeps very short strings from being reported as zero-cost.
    """

    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    return max(
        1,
        (len(text) + 3) // 4,
    )


def choose_execution_plan(
    prompt: str,
    *,
    can_chunk: bool,
    direct_token_budget: int = DEFAULT_DIRECT_PROMPT_TOKEN_BUDGET,
) -> ExecutionPlan:
    estimated_tokens = estimate_tokens(
        prompt
    )

    mode = "direct"

    if (
        can_chunk
        and estimated_tokens
        > direct_token_budget
    ):
        mode = "chunked"

    return ExecutionPlan(
        mode=mode,
        estimated_prompt_tokens=(
            estimated_tokens
        ),
        direct_token_budget=(
            direct_token_budget
        ),
    )


def build_execution_metadata(
    execution_plan: ExecutionPlan,
    *,
    chunk_count: int = 0,
    profile_name: str = DEFAULT_EXECUTION_PROFILE,
    resolved_profile_name: str = "",
    profile_reason: str = "",
    chunk_overlap_tokens: int = 0,
    context_size_tokens: int = 0,
    context_reserve_tokens: int = 0,
    model_name: str = "",
    model_parameter_billions: float | None = None,
    model_budget_factor: float = 1.0,
    hardware_label: str = "",
    hardware_performance_class: str = "",
    hardware_budget_factor: float = 1.0,
    calibration_factor: float = 1.0,
    calibration_sample_count: int = 0,
    calibration_median_elapsed_seconds: float | None = None,
    calibration_reason: str = "",
    llm_call_timeout_seconds: int = 120,
) -> dict:
    inference_calls = 1

    if execution_plan.mode == "chunked":
        inference_calls = chunk_count + 1

    return {
        "profile": profile_name,
        "resolved_profile": resolved_profile_name or profile_name,
        "profile_reason": profile_reason,
        "chunk_overlap_tokens": chunk_overlap_tokens,
        "context_size_tokens": context_size_tokens,
        "context_reserve_tokens": context_reserve_tokens,
        "model_name": model_name,
        "model_parameter_billions": model_parameter_billions,
        "model_budget_factor": model_budget_factor,
        "hardware_label": hardware_label,
        "hardware_performance_class": (
            hardware_performance_class
        ),
        "hardware_budget_factor": hardware_budget_factor,
        "calibration_factor": calibration_factor,
        "calibration_sample_count": calibration_sample_count,
        "calibration_median_elapsed_seconds": (
            calibration_median_elapsed_seconds
        ),
        "calibration_reason": calibration_reason,
        "direct_token_budget": execution_plan.direct_token_budget,
        "mode": execution_plan.mode,
        "estimated_prompt_tokens": (
            execution_plan.estimated_prompt_tokens
        ),
        "chunk_count": chunk_count,
        "inference_calls": inference_calls,
        "llm_call_timeout_seconds": int(llm_call_timeout_seconds),
    }


def _meeting_source_tokens(
    meeting_memory: tuple[str, dict],
    selected_item: dict,
) -> int:
    meeting_run, memory = meeting_memory

    payload = {
        "meeting_run": meeting_run,
        "display_title": selected_item.get(
            "display_title",
            meeting_run,
        ),
        "participants": selected_item.get(
            "participants",
            [],
        ),
        "memory": memory,
    }

    return estimate_tokens(payload)


def chunk_meeting_sources(
    meeting_memories: list[tuple[str, dict]],
    selected_meetings: list[dict],
    *,
    chunk_source_token_budget: int = DEFAULT_CHUNK_SOURCE_TOKEN_BUDGET,
) -> list[
    tuple[
        list[tuple[str, dict]],
        list[dict],
    ]
]:
    """
    Split chronological meeting memories into bounded chronological chunks.

    A single oversized meeting remains intact in its own chunk. Session data
    is copied, not mutated.
    """

    if not meeting_memories:
        return []

    selected_by_run = {
        item.get("meeting_run"): item
        for item in selected_meetings
        if item.get("meeting_run")
    }

    chunks = []
    current_memories = []
    current_selected = []
    current_tokens = 0

    for meeting_memory in meeting_memories:
        meeting_run, _ = meeting_memory

        selected_item = dict(
            selected_by_run.get(
                meeting_run,
                {
                    "meeting_run": meeting_run,
                    "display_title": meeting_run,
                    "relevance_weight": 1,
                },
            )
        )

        item_tokens = _meeting_source_tokens(
            meeting_memory,
            selected_item,
        )

        if (
            current_memories
            and current_tokens + item_tokens
            > chunk_source_token_budget
        ):
            chunks.append(
                (
                    current_memories,
                    current_selected,
                )
            )
            current_memories = []
            current_selected = []
            current_tokens = 0

        current_memories.append(
            meeting_memory
        )
        current_selected.append(
            selected_item
        )
        current_tokens += item_tokens

    if current_memories:
        chunks.append(
            (
                current_memories,
                current_selected,
            )
        )

    return chunks


def build_chunk_evidence_prompt(
    resolved_user_prompt: str,
    today: str,
    chunk_memory: dict,
    chunk_number: int,
    chunk_count: int,
) -> str:
    return f"""
You are extracting source-grounded evidence from one chronological subset
of machine-readable business meeting memories.

This is chunk {chunk_number} of {chunk_count}.

The eventual user request is:

{resolved_user_prompt}

Rules:
- Use only facts in the supplied meeting memory.
- Extract only information materially relevant to the eventual request.
- Preserve the latest status represented inside this chunk.
- Preserve important names, dates, numbers, decisions, risks, and status.
- Do not invent facts, actions, commitments, recommendations, or questions.
- Do not provide advice.
- Do not try to synthesize across chunks you have not seen.
- Return concise evidence notes, maximum 12 bullets.
- If this chunk contains nothing relevant, return exactly: NO RELEVANT EVIDENCE

Current date for resolving the user's relative-date wording: {today}

Meeting memory for this chunk:

{json.dumps(chunk_memory, indent=2, ensure_ascii=False, default=str)}

FINAL INSTRUCTION

Extract evidence only for this request:

{resolved_user_prompt}
""".strip()


def build_chunk_synthesis_prompt(
    resolved_user_prompt: str,
    today: str,
    chunk_findings: list[str],
    conversation_history: list[dict] | None = None,
) -> str:
    history_text = json.dumps(
        conversation_history or [],
        indent=2,
        ensure_ascii=False,
        default=str,
    )

    findings_text = "\n\n".join(
        f"===== CHUNK {index} =====\n{finding}"
        for index, finding in enumerate(
            chunk_findings,
            start=1,
        )
        if finding.strip()
        and finding.strip()
        != "NO RELEVANT EVIDENCE"
    )

    if not findings_text:
        findings_text = (
            "No chunk contained relevant evidence."
        )

    return f"""
You are answering a user's question from source-grounded evidence notes that
were extracted from chronological business meeting memories.

SOURCE OF TRUTH
- Use only the supplied chunk evidence for meeting facts.
- The chunk evidence is ordered chronologically.
- Prefer later evidence when it clearly updates, resolves, supersedes, or
  changes an earlier status.
- Do not invent facts, decisions, owners, dates, commitments, or conclusions.
- If the evidence is insufficient, say so.

SCOPE
- Answer only what the user asked for.
- If the user asks for one sentence, return exactly one sentence.
- If the user asks for a specific number of items, return no more than that
  number.
- If the user asks for a brief answer, keep it brief.
- Do not add recommendations, actions, next steps, questions, tables, or extra
  sections unless requested.

CONVERSATION HISTORY
The history below is only for resolving conversational references. Never use
it as a meeting-fact source.

{history_text}

CURRENT DATE
{today}

CHRONOLOGICAL CHUNK EVIDENCE

{findings_text}

FINAL RESPONSE INSTRUCTION

The user's current request is:

{resolved_user_prompt}

Answer that request directly. The current request overrides any tendency to
provide a general meeting summary.
""".strip()
