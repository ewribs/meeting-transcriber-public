from __future__ import annotations

from dataclasses import dataclass

from hardware_profile import HardwareProfile, detect_hardware_profile


PERFORMANCE_PROFILE_NAMES = (
    "Auto",
    "Conservative",
    "Balanced",
    "High Performance",
)

PERFORMANCE_PROFILE_DESCRIPTIONS = {
    "Auto": (
        "Automatically selects a profile from this Mac's detected unified memory "
        "and hardware class. This is the recommended default."
    ),
    "Conservative": (
        "Uses smaller direct contexts and chunks sooner to reduce memory pressure "
        "and latency on lower-memory Macs."
    ),
    "Balanced": (
        "Uses moderate direct contexts and chunk sizes for a middle ground between "
        "speed, memory use, and context depth."
    ),
    "High Performance": (
        "Uses the largest direct contexts before chunking. Best suited to Macs with "
        "ample unified-memory headroom."
    ),
}

LEGACY_PROFILE_ALIASES = {
    "Aggressive": "High Performance",
}

MIN_CONTEXT_RESERVE_TOKENS = 2048
CONTEXT_RESERVE_FRACTION = 0.20


@dataclass(frozen=True)
class PerformanceProfileConfig:
    name: str
    context_size_tokens: int
    direct_token_budget: int
    chunk_source_token_budget: int
    chunk_overlap_tokens: int
    llm_call_timeout_seconds: int


PROFILE_CONFIGS = {
    "Conservative": PerformanceProfileConfig(
        name="Conservative",
        context_size_tokens=16384,
        direct_token_budget=9000,
        chunk_source_token_budget=3000,
        chunk_overlap_tokens=256,
        llm_call_timeout_seconds=240,
    ),
    "Balanced": PerformanceProfileConfig(
        name="Balanced",
        context_size_tokens=24576,
        direct_token_budget=18000,
        chunk_source_token_budget=5000,
        chunk_overlap_tokens=384,
        llm_call_timeout_seconds=180,
    ),
    "High Performance": PerformanceProfileConfig(
        name="High Performance",
        context_size_tokens=40960,
        direct_token_budget=32000,
        chunk_source_token_budget=7000,
        chunk_overlap_tokens=512,
        llm_call_timeout_seconds=150,
    ),
}


@dataclass(frozen=True)
class ResolvedPerformanceProfile:
    requested_name: str
    resolved_name: str
    context_size_tokens: int
    direct_token_budget: int
    chunk_source_token_budget: int
    chunk_overlap_tokens: int
    llm_call_timeout_seconds: int
    hardware_label: str
    hardware_memory_gb: int
    reason: str

    @property
    def display_label(self) -> str:
        if self.requested_name == "Auto":
            return f"Auto → {self.resolved_name}"
        return self.resolved_name


def performance_profile_options() -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "description": PERFORMANCE_PROFILE_DESCRIPTIONS[name],
        }
        for name in PERFORMANCE_PROFILE_NAMES
    ]

def normalize_performance_profile(value: str | None) -> str:
    raw = str(value or "").strip()
    raw = LEGACY_PROFILE_ALIASES.get(raw, raw)

    if raw in PERFORMANCE_PROFILE_NAMES:
        return raw

    return "Auto"


def auto_profile_name(hardware: HardwareProfile) -> tuple[str, str]:
    """
    Choose a capability tier without hard-coding a specific Mac model.

    Unified-memory headroom is the primary gate because model weights,
    context/KV cache, macOS, and the app share that memory. Chip class is
    retained in the explanation and can be used by later measured tuning.
    """

    memory_gb = int(hardware.memory_gb or 0)

    if memory_gb >= 32:
        name = "High Performance"
        reason = (
            f"Auto selected High Performance from {memory_gb} GB unified memory; "
            "large direct contexts have sufficient memory headroom."
        )
    elif memory_gb >= 20:
        name = "Balanced"
        reason = (
            f"Auto selected Balanced from {memory_gb} GB unified memory to preserve "
            "room for model weights, context, and macOS."
        )
    elif memory_gb > 0:
        name = "Conservative"
        reason = (
            f"Auto selected Conservative from {memory_gb} GB unified memory so "
            "larger workloads chunk before memory and latency become uncomfortable."
        )
    else:
        name = "Balanced"
        reason = (
            "Auto could not determine unified memory, so it selected the portable "
            "Balanced profile."
        )

    if hardware.performance_class:
        reason += f" Detected class: {hardware.performance_class}."

    return name, reason


def usable_context_tokens(context_size_tokens: int) -> int:
    context_size = max(0, int(context_size_tokens or 0))
    if context_size <= 0:
        return 0

    reserve = max(
        MIN_CONTEXT_RESERVE_TOKENS,
        int(context_size * CONTEXT_RESERVE_FRACTION),
    )
    return max(1024, context_size - reserve)


def resolve_performance_profile(
    requested_name: str | None = "Auto",
    *,
    context_size_override: int = 0,
    hardware: HardwareProfile | None = None,
) -> ResolvedPerformanceProfile:
    requested = normalize_performance_profile(requested_name)
    detected = hardware or detect_hardware_profile()

    if requested == "Auto":
        resolved_name, reason = auto_profile_name(detected)
    else:
        resolved_name = requested
        reason = f"Manual {resolved_name} performance profile selected."

    config = PROFILE_CONFIGS[resolved_name]

    context_size = int(context_size_override or 0)
    if context_size <= 0:
        context_size = config.context_size_tokens
    else:
        reason += f" Context override: {context_size:,} tokens."

    usable_context = usable_context_tokens(context_size)
    direct_budget = min(config.direct_token_budget, usable_context)
    chunk_budget = min(config.chunk_source_token_budget, usable_context)

    return ResolvedPerformanceProfile(
        requested_name=requested,
        resolved_name=resolved_name,
        context_size_tokens=context_size,
        direct_token_budget=direct_budget,
        chunk_source_token_budget=chunk_budget,
        chunk_overlap_tokens=config.chunk_overlap_tokens,
        llm_call_timeout_seconds=config.llm_call_timeout_seconds,
        hardware_label=detected.display_label,
        hardware_memory_gb=int(getattr(detected, "memory_gb", 0) or 0),
        reason=reason,
    )
