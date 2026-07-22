#!/usr/bin/env bash
# Shared helpers for soulmount scripts: coloured, transparent command execution.
# Source this: `source "$(dirname "$0")/lib.sh"`.

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; GRAY='\033[0;90m'; BLUE='\033[0;34m'; NC='\033[0m'

# Execute a command visibly (prints it first; reports failure with context).
run() {
  printf >&2 "${GRAY}$(pwd) >${NC} "
  printf >&2 "${YELLOW}"; printf >&2 "%q " "$@"; printf >&2 "${NC}\n"
  if ! "$@"; then
    local ec=$?
    echo -e >&2 "${RED}[ERROR] command failed (exit ${ec}): $*${NC}"
    return $ec
  fi
}

info()  { echo -e "${BLUE}• $*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
err()   { echo -e "${RED}✗ $*${NC}"; }

# Load repo-root .env if present (values only; never echo secrets).
load_env() {
  local root; root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if [ -f "$root/.env" ]; then
    set -a; # shellcheck disable=SC1090
    source <(grep -vE '^\s*(#|$)' "$root/.env"); set +a
  fi
}

# Resolve the robot host: prefer mDNS REACHY_HOST, fall back to REACHY_IP.
robot_host() {
  local h="${REACHY_HOST:-reachy-mini.local}"
  if getent hosts "$h" >/dev/null 2>&1 || python3 -c "import socket,sys; socket.gethostbyname('$h')" >/dev/null 2>&1; then
    echo "$h"
  elif [ -n "${REACHY_IP:-}" ]; then
    echo "$REACHY_IP"
  else
    echo "$h"  # last resort; caller handles failure
  fi
}

# Ask the owner y/N (auto-No when non-interactive, so unattended runs never block).
confirm() {
  local prompt="$1"
  if [ ! -t 0 ]; then warn "non-interactive: skipping '$prompt'"; return 1; fi
  read -r -p "$prompt [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]]
}
