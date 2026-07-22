#!/usr/bin/env bash
# robot_admin.sh — SUPERVISED robot admin (SPEC Phase 0, guardrail 11).
#   keyinstall    install the laptop SSH key on the robot (prompts for factory pw)
#   rotate-pass   rotate the factory password (owner-approved)
#   set-volume    set daemon volume to the HOUSE.md ceiling (from brain /v1/house)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"; load_env
HOST="$(robot_host)"; SSH_USER="${REACHY_SSH_USER:-pollen}"

cmd="${1:-}"
case "$cmd" in
  keyinstall)
    info "installing SSH key on $SSH_USER@$HOST (factory password: 'root')"
    [ -f "$HOME/.ssh/id_ed25519.pub" ] || run ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519"
    run ssh-copy-id "$SSH_USER@$HOST"
    ok "key installed; test: ssh $SSH_USER@$HOST true"
    ;;
  rotate-pass)
    confirm "Rotate the factory password on $HOST now?" || { warn "aborted"; exit 0; }
    info "you'll be prompted on the robot to set a new password (keep it OUT of the repo)"
    run ssh -t "$SSH_USER@$HOST" passwd
    ok "password rotated"
    ;;
  set-volume)
    # `|| echo 60` INSIDE the substitution so a brain-down curl/pipe failure can't trip
    # set -e before the numeric guard runs (the guard was previously dead code).
    ceiling="$(curl -s -m 6 -H "Authorization: Bearer ${BRAIN_API_KEY:-}" \
      "http://${BRAIN_HOST:-127.0.0.1}:${BRAIN_PORT:-8100}/v1/house" 2>/dev/null \
      | jq -r '.volume_ceiling // 60' 2>/dev/null || echo 60)"
    [[ "$ceiling" =~ ^[0-9]+$ ]] || { warn "no ceiling from brain; defaulting to 60"; ceiling=60; }
    info "setting robot volume to HOUSE ceiling: $ceiling"
    run curl -s -X POST "http://$HOST:8000/api/volume/set" -H 'content-type: application/json' \
      -d "{\"volume\": $ceiling}"
    ok "volume set to $ceiling"
    ;;
  *) err "usage: robot_admin.sh {keyinstall|rotate-pass|set-volume}"; exit 2 ;;
esac
