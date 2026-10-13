#!/bin/bash
# Clone the public Meeting Transcriber repository, then hand off to the reviewed
# in-repository macOS bootstrap script. Nothing is piped directly from the
# internet into a shell by this script.

set -euo pipefail

PUBLIC_REPO_URL="${MEETING_TRANSCRIBER_REPO_URL:-https://github.com/ewribs/meeting-transcriber-public.git}"
INSTALL_DIR="${MEETING_TRANSCRIBER_INSTALL_DIR:-$HOME/Projects/meeting-transcriber}"
UPDATE_EXISTING=0

usage() {
  cat <<'EOF'
Usage: install_from_github.sh [--install-dir PATH] [--update] [bootstrap options]

This script performs only two high-level actions:
  1. clone (or explicitly update) the public Git repository; and
  2. run tools/setup/bootstrap_macos.sh from that checkout.

Use --dry-run among the bootstrap options to review setup actions first.
EOF
}

FORWARD_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift ;;
    --update) UPDATE_EXISTING=1 ;;
    -h|--help) usage; exit 0 ;;
    *) FORWARD_ARGS+=("$1") ;;
  esac
  shift
done

printf 'Public repository: %s\n' "$PUBLIC_REPO_URL"
printf 'Install directory: %s\n' "$INSTALL_DIR"

if ! command -v git >/dev/null 2>&1; then
  echo "git is unavailable. Install Apple's Xcode Command Line Tools, then rerun." >&2
  echo "Command: xcode-select --install" >&2
  exit 2
fi

if [[ -d "$INSTALL_DIR/.git" ]]; then
  if [[ "$UPDATE_EXISTING" -eq 1 ]]; then
    echo "Updating existing checkout with: git pull --ff-only"
    git -C "$INSTALL_DIR" pull --ff-only
  else
    echo "Existing Git checkout found; leaving it unchanged. Use --update to pull." 
  fi
elif [[ -e "$INSTALL_DIR" ]]; then
  echo "Install path exists but is not a Git checkout: $INSTALL_DIR" >&2
  exit 1
else
  mkdir -p "$(dirname "$INSTALL_DIR")"
  echo "Cloning public repository..."
  git clone "$PUBLIC_REPO_URL" "$INSTALL_DIR"
fi

exec "$INSTALL_DIR/tools/setup/bootstrap_macos.sh" "${FORWARD_ARGS[@]}"
