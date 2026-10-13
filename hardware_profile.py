from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class HardwareProfile:
    system: str
    architecture: str
    chip_name: str
    memory_bytes: int
    memory_gb: int
    performance_class: str
    budget_factor: float

    @property
    def display_label(self) -> str:
        chip = self.chip_name or self.architecture or self.system
        memory = (
            f"{self.memory_gb} GB"
            if self.memory_gb > 0
            else "memory unknown"
        )
        return f"{chip} · {memory}"


def _run_sysctl(key: str) -> str:
    try:
        completed = subprocess.run(
            ["sysctl", "-n", key],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (
        OSError,
        subprocess.SubprocessError,
    ):
        return ""

    if completed.returncode != 0:
        return ""

    return completed.stdout.strip()


def _detect_chip_name(
    system: str,
    architecture: str,
) -> str:
    if system == "Darwin":
        chip_name = _run_sysctl(
            "machdep.cpu.brand_string"
        )

        if chip_name:
            return chip_name

        # Some Apple Silicon/macOS combinations do not expose
        # machdep.cpu.brand_string. system_profiler is slower, so use it
        # only as a fallback and cache the final profile.
        try:
            completed = subprocess.run(
                [
                    "system_profiler",
                    "SPHardwareDataType",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (
            OSError,
            subprocess.SubprocessError,
        ):
            completed = None

        if (
            completed is not None
            and completed.returncode == 0
        ):
            for line in completed.stdout.splitlines():
                stripped = line.strip()

                if stripped.startswith(
                    "Chip:"
                ):
                    return (
                        stripped.split(
                            ":",
                            1,
                        )[1]
                        .strip()
                    )

    processor = platform.processor().strip()

    if processor:
        return processor

    return architecture


def _detect_memory_bytes(
    system: str,
) -> int:
    if system == "Darwin":
        value = _run_sysctl(
            "hw.memsize"
        )

        try:
            return int(value)
        except (
            TypeError,
            ValueError,
        ):
            pass

    try:
        page_size = os.sysconf(
            "SC_PAGE_SIZE"
        )
        page_count = os.sysconf(
            "SC_PHYS_PAGES"
        )
        return int(
            page_size * page_count
        )
    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ):
        return 0


def benchmark_informed_budget_factor(
    chip_name: str,
    memory_gb: int,
) -> tuple[float, str]:
    """
    Return a conservative local-inference budget factor.

    M2 Pro with 16 GB is intentionally the 1.00 baseline because that is
    the project's current proven configuration. Apple Silicon Max/Ultra
    parts receive modestly larger practical prompt budgets, reflecting
    their materially higher memory bandwidth in published Apple specs and
    community llama.cpp measurements. Memory adds a smaller adjustment.

    These factors are intentionally much smaller than raw benchmark speed
    ratios. They tune when Auto should chunk; they are not predictions of
    tokens/second.
    """

    normalized = (
        chip_name or ""
    ).lower()

    if "apple" not in normalized:
        return 1.0, "Generic"

    if "ultra" in normalized:
        chip_factor = 1.25
        performance_class = "Apple Silicon Ultra"
    elif "max" in normalized:
        chip_factor = 1.15
        performance_class = "Apple Silicon Max"
    elif "pro" in normalized:
        chip_factor = 1.00
        performance_class = "Apple Silicon Pro"
    else:
        chip_factor = 0.85
        performance_class = "Apple Silicon"

    if memory_gb <= 0:
        memory_factor = 1.00
    elif memory_gb <= 16:
        memory_factor = 1.00
    elif memory_gb <= 32:
        memory_factor = 1.05
    elif memory_gb <= 64:
        memory_factor = 1.12
    else:
        memory_factor = 1.20

    factor = (
        chip_factor
        * memory_factor
    )

    factor = max(
        0.75,
        min(
            1.30,
            factor,
        ),
    )

    return factor, performance_class


@lru_cache(maxsize=1)
def detect_hardware_profile() -> HardwareProfile:
    system = platform.system()
    architecture = platform.machine()
    chip_name = _detect_chip_name(
        system,
        architecture,
    )
    memory_bytes = _detect_memory_bytes(
        system
    )

    memory_gb = 0

    if memory_bytes > 0:
        memory_gb = max(
            1,
            round(
                memory_bytes
                / (1024 ** 3)
            ),
        )

    (
        factor,
        performance_class,
    ) = benchmark_informed_budget_factor(
        chip_name,
        memory_gb,
    )

    return HardwareProfile(
        system=system,
        architecture=architecture,
        chip_name=chip_name,
        memory_bytes=memory_bytes,
        memory_gb=memory_gb,
        performance_class=(
            performance_class
        ),
        budget_factor=factor,
    )
