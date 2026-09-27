from __future__ import annotations

import subprocess


def parse_ollama_list(output: str) -> list[str]:
    models: list[str] = []

    for raw_line in output.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        parts = line.split()

        if not parts:
            continue

        name = parts[0]

        if name.upper() == "NAME":
            continue

        if name not in models:
            models.append(name)

    return models


def discover_installed_ollama_models(
    timeout_seconds: float = 5.0,
) -> tuple[list[str], str | None]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return [], "Ollama command not found"
    except subprocess.TimeoutExpired:
        return [], "Ollama model discovery timed out"
    except OSError as exc:
        return [], str(exc)

    if result.returncode != 0:
        error = (
            result.stderr.strip()
            or "Unable to query installed Ollama models"
        )
        return [], error

    models = parse_ollama_list(
        result.stdout
    )

    if not models:
        return [], "No installed Ollama models found"

    return models, None
