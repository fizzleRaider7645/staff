#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { printf "${GREEN}=>${RESET} %s\n" "$*"; }
warn()  { printf "${YELLOW}=>${RESET} %s\n" "$*"; }
error() { printf "${RED}=>${RESET} %s\n" "$*" >&2; }

echo ""
echo "${BOLD}staff${RESET} — setup"
echo ""

# Check prerequisites
if ! command -v jq >/dev/null 2>&1; then
  error "jq is required. Install it:"
  echo "  brew install jq    (macOS)"
  echo "  apt install jq     (Debian/Ubuntu)"
  exit 1
fi
info "jq found"

if ! command -v git >/dev/null 2>&1; then
  error "git is required"
  exit 1
fi
info "git found"

# Create ~/.local/bin if needed
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# Symlink the CLI
STAFF_BIN="$SCRIPT_DIR/bin/staff"
LINK_PATH="$BIN_DIR/staff"

if [ -L "$LINK_PATH" ] || [ -f "$LINK_PATH" ]; then
  rm -f "$LINK_PATH"
fi

chmod +x "$STAFF_BIN"
ln -s "$STAFF_BIN" "$LINK_PATH"
info "Linked staff CLI -> $LINK_PATH"

# Check PATH
if ! echo "$PATH" | tr ':' '\n' | grep -q "^$BIN_DIR$"; then
  warn "$BIN_DIR is not in your PATH"
  echo ""
  echo "Add this to your shell profile (~/.zshrc or ~/.bashrc):"
  echo ""
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
  echo ""
fi

# Create state directory
STATE_DIR="$HOME/.staff"
mkdir -p "$STATE_DIR"
if [ ! -f "$STATE_DIR/installed.json" ]; then
  echo '{"installations":[]}' > "$STATE_DIR/installed.json"
fi
info "State directory ready: $STATE_DIR"

# Rebuild registry
info "Rebuilding registry..."
"$STAFF_BIN" registry rebuild

echo ""
echo "${BOLD}Setup complete!${RESET}"
echo ""
echo "Usage:"
echo "  staff list              List projects"
echo "  staff init <cat> <name> Scaffold a new project"
echo "  staff install <project> Install a project"
echo "  staff doctor            Check health"
echo ""
