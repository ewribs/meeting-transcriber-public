#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT="$ROOT/swift/Meeting Transcriber/Meeting Transcriber.xcodeproj"
SCHEME="Meeting Transcriber"
CONFIGURATION="Release"
DERIVED_DATA="$ROOT/.build/xcode"
DESTINATION_DIR="${MEETING_TRANSCRIBER_APP_DIR:-$HOME/Applications}"
LAUNCH_AFTER_INSTALL=1

usage() {
  cat <<'EOF'
Usage: tools/install_local_app.sh [options]

Build and install Meeting Transcriber as a normal macOS .app bundle.
The Python backend remains in the repository and is located through
Application Support/install.json.

Options:
  --destination DIR       Install directory (default: ~/Applications).
  --configuration NAME    Xcode configuration (default: Release).
  --no-launch             Install without launching the app afterward.
  -h, --help              Show this help.

Environment:
  MEETING_TRANSCRIBER_APP_DIR  Alternate default install directory.
EOF
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --destination)
      [[ $# -ge 2 ]] || die "--destination requires a directory."
      DESTINATION_DIR="$2"
      shift 2
      ;;
    --configuration)
      [[ $# -ge 2 ]] || die "--configuration requires a value."
      CONFIGURATION="$2"
      shift 2
      ;;
    --no-launch)
      LAUNCH_AFTER_INSTALL=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "Unknown option: $1"
      ;;
  esac
done

command -v xcodebuild >/dev/null 2>&1 || die "xcodebuild was not found. Install/select full Xcode first."
command -v ditto >/dev/null 2>&1 || die "ditto was not found."
command -v python3 >/dev/null 2>&1 || die "python3 was not found."

PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || die "Project virtualenv Python not found: $PYTHON"
[[ -d "$PROJECT" ]] || die "Xcode project not found: $PROJECT"

printf 'Building %s (%s)...\n' "$SCHEME" "$CONFIGURATION"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration "$CONFIGURATION" \
  -derivedDataPath "$DERIVED_DATA" \
  build

SOURCE_APP="$DERIVED_DATA/Build/Products/$CONFIGURATION/$SCHEME.app"
[[ -d "$SOURCE_APP" ]] || die "Built app not found: $SOURCE_APP"

# Record the repository location without changing the user's other settings.
PYTHONPATH="$ROOT" "$PYTHON" -c \
  'from install_config import save_install_config; import sys; print(f"Backend project location: {save_install_config(sys.argv[1], backup_existing=False)}")' \
  "$ROOT"

DESTINATION_DIR="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DESTINATION_DIR")"
mkdir -p "$DESTINATION_DIR"

DEST_APP="$DESTINATION_DIR/$SCHEME.app"
STAGE_APP="$DESTINATION_DIR/.${SCHEME}.app.new.$$"
BACKUP_APP="$DESTINATION_DIR/.${SCHEME}.app.previous.$$"

rm -rf "$STAGE_APP" "$BACKUP_APP"
ditto "$SOURCE_APP" "$STAGE_APP"

# Build and stage completely before disturbing a working installed copy.
if [[ -d "$DEST_APP" ]]; then
  osascript -e 'tell application "Meeting Transcriber" to quit' >/dev/null 2>&1 || true
  sleep 1
  mv "$DEST_APP" "$BACKUP_APP"
fi

if mv "$STAGE_APP" "$DEST_APP"; then
  rm -rf "$BACKUP_APP"
else
  if [[ -d "$BACKUP_APP" && ! -d "$DEST_APP" ]]; then
    mv "$BACKUP_APP" "$DEST_APP"
  fi
  die "Unable to install the new app bundle. The previous copy was restored when possible."
fi

printf '\nInstalled: %s\n' "$DEST_APP"
printf 'Backend:   %s\n' "$ROOT"

if [[ "$LAUNCH_AFTER_INSTALL" -eq 1 ]]; then
  open "$DEST_APP"
  printf 'Launched Meeting Transcriber. Use Dock > Options > Keep in Dock for normal daily access.\n'
fi
