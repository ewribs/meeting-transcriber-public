#!/bin/bash
# Meeting Transcriber transparent macOS bootstrap.
#
# This script is intentionally verbose and reviewable. It does not hide network
# activity, pipe downloaded executable code into a shell, or silently elevate
# privileges. Run with --dry-run to see planned changes without modifying the
# machine, or --check for read-only validation only.
#
# Existing installations are treated conservatively: if Meeting Transcriber
# already has storage/model settings, those values become the setup defaults.
# Fresh installs receive documented defaults selected from this Mac's hardware.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PUBLIC_REPO_URL="https://github.com/ewribs/meeting-transcriber-public.git"
WHISPER_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin"
WHISPER_MODEL="$HOME/whisper/models/ggml-medium.en.bin"
SETTINGS_PATH="$HOME/Library/Application Support/Meeting Transcriber/settings.json"

DRY_RUN=0
CHECK_ONLY=0
NON_INTERACTIVE=0
RUN_TESTS=1
BUILD_SWIFT=0
SKIP_MODEL_PULL=0

# These remain empty until command-line arguments and/or existing settings have
# been evaluated. This prevents generic defaults from silently replacing an
# already-configured installation.
LLM_MODEL=""
WORKING_DIR=""
ARCHIVE_DIR=""
RECORDINGS_DIR=""
LLM_MODEL_SET=0
WORKING_DIR_SET=0
ARCHIVE_DIR_SET=0
RECORDINGS_DIR_SET=0

usage() {
  cat <<'EOF_USAGE'
Usage: tools/setup/bootstrap_macos.sh [options]

Options:
  --dry-run                 Non-interactive preview; print planned actions without changing the Mac.
  --check                   Run read-only installation validation only.
  --non-interactive         Use supplied/existing/fresh defaults without prompts.
  --working-dir PATH        Local processing/output directory.
  --archive-dir PATH        Published meeting archive/NAS directory.
  --recordings-dir PATH     Meetings/recordings folder for Add Recordings and native recordings.
  --llm-model MODEL         Ollama model to install/configure.
  --skip-model-pull         Do not run 'ollama pull'.
  --skip-tests              Do not run the Python regression suite.
  --build-swift             Also run an Xcode command-line build if full Xcode exists.
  -h, --help                Show this help.

Default behavior:
  * Existing settings are preserved as the proposed defaults.
  * Fresh installs use ~/Documents/Meeting Transcriber/... storage paths.
  * Fresh-install model selection is hardware-aware: High Performance-class
    Macs (currently 32+ GB unified memory) default to qwen3:14b; smaller Macs
    default to qwen3:8b. The app's Auto profile remains the runtime authority.

Transparency notes:
  * Homebrew itself is NOT installed automatically. If missing, the script stops
    and points to https://brew.sh so you can inspect/install it yourself.
  * The Whisper model is downloaded directly from the documented Hugging Face URL.
  * Ollama is started with 'brew services start ollama' only when its API is down.
  * Existing Meeting Transcriber settings/install metadata are backed up before
    setup changes them.
EOF_USAGE
}

log() { printf '\n==> %s\n' "$*"; }
plan() { printf '    %s\n' "$*"; }

run() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    printf 'DRY RUN: '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

expand_user_path() {
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s/%s' "$HOME" "${1#~/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

prompt_value() {
  local label="$1"
  local current="$2"
  local answer=""

  if [[ "$NON_INTERACTIVE" -eq 1 ]]; then
    printf '%s' "$current"
    return
  fi

  read -r -p "$label [$current]: " answer
  printf '%s' "${answer:-$current}"
}

# Read one existing JSON preference using macOS's built-in plutil. This avoids
# requiring Python or jq merely to preserve an existing installation's values.
existing_setting() {
  local key="$1"
  if [[ ! -f "$SETTINGS_PATH" ]]; then
    return 0
  fi
  /usr/bin/plutil -extract "$key" raw -o - "$SETTINGS_PATH" 2>/dev/null || true
}

# Mirror the application's current Auto-profile memory gates for the sole
# purpose of choosing a sensible model on a *fresh* install. Existing installs
# keep their configured model. Runtime context/chunking still comes from the
# Python performance-profile code, not this shell helper.
fresh_model_default() {
  local memory_bytes memory_gb
  memory_bytes="$(sysctl -n hw.memsize 2>/dev/null || printf '0')"
  if [[ "$memory_bytes" =~ ^[0-9]+$ ]] && [[ "$memory_bytes" -gt 0 ]]; then
    memory_gb=$(( (memory_bytes + 536870912) / 1073741824 ))
  else
    memory_gb=0
  fi

  if [[ "$memory_gb" -ge 32 ]]; then
    printf '%s' 'qwen3:14b'
  else
    printf '%s' 'qwen3:8b'
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; NON_INTERACTIVE=1 ;;
    --check) CHECK_ONLY=1 ;;
    --non-interactive) NON_INTERACTIVE=1 ;;
    --working-dir) WORKING_DIR="$2"; WORKING_DIR_SET=1; shift ;;
    --archive-dir) ARCHIVE_DIR="$2"; ARCHIVE_DIR_SET=1; shift ;;
    --recordings-dir) RECORDINGS_DIR="$2"; RECORDINGS_DIR_SET=1; shift ;;
    --llm-model) LLM_MODEL="$2"; LLM_MODEL_SET=1; shift ;;
    --skip-model-pull) SKIP_MODEL_PULL=1 ;;
    --skip-tests) RUN_TESTS=0 ;;
    --build-swift) BUILD_SWIFT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  # Prefer the project's own virtualenv when it exists. On a not-yet-installed
  # Mac, fall back to any visible python3 only for read-only diagnostics.
  CHECK_PYTHON="$PROJECT_DIR/.venv/bin/python"
  if [[ ! -x "$CHECK_PYTHON" ]]; then
    CHECK_PYTHON="$(command -v python3 || true)"
  fi
  if [[ -z "$CHECK_PYTHON" ]]; then
    echo "Python is not available yet, so --check cannot run the Python validator." >&2
    echo "Run the normal bootstrap after installing Homebrew, then rerun --check." >&2
    exit 2
  fi
  exec "$CHECK_PYTHON" "$PROJECT_DIR/tools/setup/validate_install.py" --run-tests
fi

log "Meeting Transcriber macOS bootstrap"
plan "Repository: $PROJECT_DIR"
plan "Public source repository: $PUBLIC_REPO_URL"
plan "No meeting/transcript content is uploaded by this installer."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer supports macOS only." >&2
  exit 1
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Warning: this project is currently validated primarily on Apple Silicon (arm64)." >&2
fi

if ! xcode-select -p >/dev/null 2>&1; then
  log "Xcode Command Line Tools are missing"
  plan "macOS will open Apple's Command Line Tools installer."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    plan "Would run: xcode-select --install"
  else
    xcode-select --install || true
    echo "Complete the Apple installer, then rerun this script." >&2
  fi
  exit 2
fi

if ! command -v brew >/dev/null 2>&1; then
  log "Homebrew is required but is not installed"
  cat <<'EOF_BREW'
This project deliberately does not execute Homebrew's remote installer for you.
Review and install Homebrew from:
  https://brew.sh

After Homebrew is installed, rerun this script. This keeps third-party bootstrap
code visible and under your control rather than executing a remote script here.
EOF_BREW
  exit 2
fi

# Preserve existing configuration when present. Explicit command-line options
# always win. Empty/missing existing values fall back independently, which also
# lets older partially-configured installs adopt only the values they lack.
if [[ "$WORKING_DIR_SET" -eq 0 ]]; then
  WORKING_DIR="$(existing_setting output_dir)"
  WORKING_DIR="${WORKING_DIR:-$HOME/Documents/Meeting Transcriber/Working}"
fi
if [[ "$ARCHIVE_DIR_SET" -eq 0 ]]; then
  ARCHIVE_DIR="$(existing_setting archive_dir)"
  ARCHIVE_DIR="${ARCHIVE_DIR:-$HOME/Documents/Meeting Transcriber/Archive}"
fi
if [[ "$RECORDINGS_DIR_SET" -eq 0 ]]; then
  RECORDINGS_DIR="$(existing_setting recordings_dir)"
  RECORDINGS_DIR="${RECORDINGS_DIR:-$HOME/Documents/Meeting Transcriber/Meetings}"
fi
if [[ "$LLM_MODEL_SET" -eq 0 ]]; then
  LLM_MODEL="$(existing_setting llm_model)"
  LLM_MODEL="${LLM_MODEL:-$(fresh_model_default)}"
fi

if [[ -f "$SETTINGS_PATH" ]]; then
  log "Existing Meeting Transcriber settings detected"
  plan "Current non-empty settings are preserved as setup defaults."
else
  log "Fresh Meeting Transcriber configuration"
  plan "Using documented fresh-install defaults; model default is hardware-aware."
fi

WORKING_DIR="$(prompt_value "Working directory" "$WORKING_DIR")"
ARCHIVE_DIR="$(prompt_value "Archive directory" "$ARCHIVE_DIR")"
RECORDINGS_DIR="$(prompt_value "Meetings / recordings directory" "$RECORDINGS_DIR")"
LLM_MODEL="$(prompt_value "Ollama model" "$LLM_MODEL")"

WORKING_DIR="$(expand_user_path "$WORKING_DIR")"
ARCHIVE_DIR="$(expand_user_path "$ARCHIVE_DIR")"
RECORDINGS_DIR="$(expand_user_path "$RECORDINGS_DIR")"

log "Planned storage configuration"
plan "Working:    $WORKING_DIR"
plan "Archive:    $ARCHIVE_DIR"
plan "Meetings / recordings: $RECORDINGS_DIR"
plan "LLM model:  $LLM_MODEL"

if [[ "$NON_INTERACTIVE" -eq 0 && "$DRY_RUN" -eq 0 ]]; then
  read -r -p "Continue with these settings? [y/N]: " reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) echo "Setup cancelled before making changes."; exit 0 ;;
  esac
fi

log "Installing/checking local dependencies"

# Python is intentionally checked by formula because the project requires the
# specific 3.13 runtime rather than merely any 'python3' found in PATH.
if brew list --versions python@3.13 >/dev/null 2>&1; then
  plan "python@3.13 already installed"
else
  plan "Installing python@3.13 from Homebrew"
  run brew install python@3.13
fi

# For tools where a functional executable is what the app needs, prefer a real
# command check over Homebrew receipt metadata. This handles renamed formulas,
# linked binaries, and existing compatible installations without proposing an
# unnecessary reinstall.
if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  plan "ffmpeg and ffprobe already available"
else
  plan "Installing ffmpeg from Homebrew"
  run brew install ffmpeg
fi

if command -v whisper-cli >/dev/null 2>&1 && whisper-cli --help >/dev/null 2>&1; then
  plan "whisper-cli already available"
else
  plan "Installing whisper.cpp from Homebrew"
  run brew install whisper.cpp
fi

if command -v ollama >/dev/null 2>&1 && ollama --version >/dev/null 2>&1; then
  plan "Ollama command already available"
else
  plan "Installing Ollama from Homebrew"
  run brew install ollama
fi

PYTHON_PREFIX="$(brew --prefix python@3.13 2>/dev/null || true)"
if [[ -z "$PYTHON_PREFIX" ]]; then
  PYTHON_PREFIX="$(brew --prefix)/opt/python@3.13"
fi
PYTHON_BIN="$PYTHON_PREFIX/bin/python3.13"
if [[ ! -x "$PYTHON_BIN" && "$DRY_RUN" -eq 0 ]]; then
  echo "Python 3.13 was not found after Homebrew installation: $PYTHON_BIN" >&2
  exit 1
fi

log "Creating/updating project Python virtual environment"
if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
  run "$PYTHON_BIN" -m venv "$PROJECT_DIR/.venv"
else
  plan ".venv already exists; keeping it"
fi

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ "$DRY_RUN" -eq 1 && ! -x "$VENV_PYTHON" ]]; then
  VENV_PYTHON="$PYTHON_BIN"
fi
run "$VENV_PYTHON" -m pip install --upgrade pip
run "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"

log "Installing/checking Whisper medium.en model"
plan "Download source: $WHISPER_MODEL_URL"
plan "Destination: $WHISPER_MODEL"
if [[ -s "$WHISPER_MODEL" ]]; then
  plan "Whisper model already present; keeping it"
else
  run mkdir -p "$(dirname "$WHISPER_MODEL")"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    plan "Would download model with curl --fail --location --progress-bar"
  else
    tmp_model="$WHISPER_MODEL.part"
    rm -f "$tmp_model"
    curl --fail --location --progress-bar -o "$tmp_model" "$WHISPER_MODEL_URL"
    mv "$tmp_model" "$WHISPER_MODEL"
  fi
fi

log "Starting/checking local Ollama service"
if curl --silent --fail --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
  plan "Ollama API already responding on localhost:11434"
else
  plan "Starting Ollama using Homebrew services"
  run brew services start ollama
  if [[ "$DRY_RUN" -eq 0 ]]; then
    for _ in {1..20}; do
      if curl --silent --fail --max-time 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        break
      fi
      sleep 1
    done
  fi
fi

if [[ "$SKIP_MODEL_PULL" -eq 0 ]]; then
  log "Installing/checking configured Ollama model"
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$LLM_MODEL"; then
    plan "Ollama model $LLM_MODEL already present; keeping it"
  else
    plan "Network action: ollama pull $LLM_MODEL"
    run ollama pull "$LLM_MODEL"
  fi
else
  plan "Skipping Ollama model pull by request"
fi

create_dir_safely() {
  local target="$1"
  local label="$2"

  if [[ "$target" == /Volumes/* ]]; then
    local rest="${target#/Volumes/}"
    local volume="${rest%%/*}"
    if [[ ! -d "/Volumes/$volume" ]]; then
      plan "$label is on unmounted /Volumes/$volume; not creating a misleading local mount directory"
      return
    fi
  fi

  if [[ -d "$target" ]]; then
    plan "$label already exists; keeping it"
  else
    run mkdir -p "$target"
  fi
}

log "Creating configured storage directories where safe"
create_dir_safely "$WORKING_DIR" "Working directory"
create_dir_safely "$RECORDINGS_DIR" "Meetings / recordings directory"
create_dir_safely "$ARCHIVE_DIR" "Archive directory"

log "Writing transparent local application configuration"
plan "Application Support files are backed up before modification."
run "$VENV_PYTHON" "$PROJECT_DIR/tools/setup/configure_install.py" \
  --project-dir "$PROJECT_DIR" \
  --working-dir "$WORKING_DIR" \
  --archive-dir "$ARCHIVE_DIR" \
  --recordings-dir "$RECORDINGS_DIR" \
  --llm-model "$LLM_MODEL"

if [[ "$RUN_TESTS" -eq 1 ]]; then
  log "Running Python regression suite"
  run "$VENV_PYTHON" -m unittest discover -s "$PROJECT_DIR/tests" -p 'test_*.py'
fi

if [[ "$BUILD_SWIFT" -eq 1 ]]; then
  log "Building native Swift app with Xcode"
  if ! command -v xcodebuild >/dev/null 2>&1; then
    echo "xcodebuild was not found. Install/select full Xcode and rerun with --build-swift." >&2
    exit 1
  fi
  run xcodebuild \
    -project "$PROJECT_DIR/swift/Meeting Transcriber/Meeting Transcriber.xcodeproj" \
    -scheme "Meeting Transcriber" \
    -configuration Debug \
    -derivedDataPath "$PROJECT_DIR/.build/xcode" \
    build
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  log "Final read-only validation"
  VALIDATE_ARGS=()
  if [[ "$RUN_TESTS" -eq 1 ]]; then
    VALIDATE_ARGS+=(--run-tests)
  fi
  "$VENV_PYTHON" "$PROJECT_DIR/tools/setup/validate_install.py" "${VALIDATE_ARGS[@]}" || true
fi

cat <<EOF_DONE

Setup pass complete.

Next steps:
  1. Open the Xcode project and build/run Meeting Transcriber.
  2. Review Settings → Meeting Transcriber Settings.
  3. A 'Transcribe' aggregate audio device is optional unless you want native recording.
     Existing M4A recordings can be queued without moving microphone hardware.

Security/setup documentation:
  $PROJECT_DIR/docs/SETUP_AND_SECURITY.md
EOF_DONE
