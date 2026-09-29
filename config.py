"""
==========================================================
Meeting Transcriber Configuration
==========================================================
Runtime settings may be overridden by app Preferences.
"""

from pathlib import Path

from app_settings import load_app_settings
from identity_config import load_identity_config
from business_context_config import load_business_context_config
from performance_profile import resolve_performance_profile

# ---------------------------------------------------------
# Application Metadata
# ---------------------------------------------------------

APP_NAME = "Meeting Transcriber"
APP_VERSION = "0.1.0"


# ---------------------------------------------------------
# Local User Identity
# ---------------------------------------------------------

# Real user names are intentionally kept out of source control.
# identity.local.json is private/local and is loaded at runtime.
_IDENTITY = load_identity_config(Path(__file__).parent / "identity.local.json")

SELF_NAME = str(_IDENTITY["self_name"])
SELF_REFERENCE_NAMES = tuple(_IDENTITY["self_reference_names"])
SELF_SPEAKER_LABEL = str(_IDENTITY["self_speaker_label"])

# Organization-specific business vocabulary is private/local.
_BUSINESS_CONTEXT = load_business_context_config(
    Path(__file__).parent / "business_context.local.json"
)
TOPIC_NORMALIZATION_RULES = tuple(
    _BUSINESS_CONTEXT["topic_normalization_rules"]
)

# ---------------------------------------------------------
# Project Paths / Storage Locations
# ---------------------------------------------------------

PROJECT_DIR = Path(__file__).parent

_APP_SETTINGS = load_app_settings()

OUTPUT_DIR = Path(
    _APP_SETTINGS.get("output_dir")
    or (PROJECT_DIR / "output")
).expanduser()

LOCAL_OUTPUT_DIR = OUTPUT_DIR

ARCHIVE_DIR = Path(
    _APP_SETTINGS.get("archive_dir")
    or "/Volumes/Transcribe"
).expanduser()

ONENOTE_IMPORT_DIR = (
    ARCHIVE_DIR / "OneNote_Import"
)

MEETINGS_DIR = Path(
    _APP_SETTINGS.get("recordings_dir")
    or (PROJECT_DIR / "meetings")
).expanduser()

LOGS_DIR = PROJECT_DIR / "logs"
PROMPTS_DIR = PROJECT_DIR / "prompts"

# ---------------------------------------------------------
# Whisper Configuration
# ---------------------------------------------------------

WHISPER_DIR = Path.home() / "whisper"

WHISPER_CLI = Path("/opt/homebrew/bin/whisper-cli")
WHISPER_MODEL = Path.home() / "whisper" / "models" / "ggml-medium.en.bin"
WHISPER_OUTPUT_FORMAT = "vtt"
WHISPER_CHUNK_MINUTES = 5

# ---------------------------------------------------------
# AI Configuration
# ---------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/generate"
LLM_MODEL = str(
    _APP_SETTINGS.get("llm_model")
    or "qwen3:8b"
).strip()

PERFORMANCE_PROFILE = str(
    _APP_SETTINGS.get("performance_profile")
    or "Auto"
).strip()

# 0 means use the selected performance profile's context size.
LLM_CONTEXT_SIZE_OVERRIDE = int(
    _APP_SETTINGS.get("llm_context_size")
    or 0
)

_RESOLVED_PERFORMANCE_PROFILE = resolve_performance_profile(
    PERFORMANCE_PROFILE,
    context_size_override=LLM_CONTEXT_SIZE_OVERRIDE,
)

LLM_CONTEXT_SIZE = (
    _RESOLVED_PERFORMANCE_PROFILE.context_size_tokens
)

# ---------------------------------------------------------
# Retention
# ---------------------------------------------------------

M4A_RETENTION_DAYS = int(
    _APP_SETTINGS.get("m4a_retention_days")
    or 30
)

ARCHIVED_M4A_RETENTION_DAYS = int(
    _APP_SETTINGS.get("archived_m4a_retention_days")
    if _APP_SETTINGS.get("archived_m4a_retention_days")
    is not None
    else 365
)

# ---------------------------------------------------------
# Audio Channels (0-based)
# ---------------------------------------------------------

REMOTE_CHANNEL = 0
MIC_CHANNEL = 4

# ---------------------------------------------------------
# Processing Options
# ---------------------------------------------------------

REMOVE_SILENCE = True
GENERATE_SUMMARY = True
GENERATE_MARKDOWN = True

# ---------------------------------------------------------
# Audio Settings
# ---------------------------------------------------------

SAMPLE_RATE = 16000

REMOTE_AUDIO = "remote.wav"
MIC_AUDIO = "mic.wav"

# ---------------------------------------------------------
# Transcript Cleanup
# ---------------------------------------------------------

MAX_MERGE_GAP_SECONDS = 10.0
MAX_PARAGRAPH_CHARS = 500
