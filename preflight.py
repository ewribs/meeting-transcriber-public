from pathlib import Path
import shutil
import urllib.error
import urllib.request
import json

from config import (
    LLM_MODEL,
    MEETINGS_DIR,
    OLLAMA_URL,
    OUTPUT_DIR,
    WHISPER_CLI,
    WHISPER_MODEL,
)


def run_preflight() -> None:
    """
    Verify that required files, tools, directories,
    and local services are available.
    """

    print()
    print("Running preflight checks...")
    print()

    if not MEETINGS_DIR.exists():
        raise RuntimeError(
            f"Meetings directory not found: {MEETINGS_DIR}"
        )

    print(f"Meeting directory ............ OK")

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Output directory ........ OK")

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found in PATH."
        )

    print("ffmpeg .................. OK")

    if not Path(WHISPER_CLI).exists():
        raise RuntimeError(
            f"whisper-cli was not found: {WHISPER_CLI}"
        )

    print("whisper-cli ............. OK")

    if not Path(WHISPER_MODEL).exists():
        raise RuntimeError(
            f"Whisper model was not found: {WHISPER_MODEL}"
        )

    print("Whisper model ........... OK")

    ollama_tags_url = "http://localhost:11434/api/tags"

    try:
        with urllib.request.urlopen(
            ollama_tags_url,
            timeout=5,
        ) as response:
            ollama_data = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Ollama is not responding at {ollama_tags_url}: {error}"
        ) from error

    print("Ollama .................. OK")

    installed_models = {
        model.get("name", "")
        for model in ollama_data.get("models", [])
    }

    if LLM_MODEL not in installed_models:
        raise RuntimeError(
            f"LLM model is not installed: {LLM_MODEL}\n"
            f"Installed models: {', '.join(sorted(installed_models))}"
        )

    print(f"LLM model ............... OK ({LLM_MODEL})")
    print()
    print()
