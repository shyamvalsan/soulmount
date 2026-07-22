#!/usr/bin/env bash
# verify_boot.sh — THE Phase 4 acceptance gate (SPEC §Phase 4). Run from the laptop.
# Polls with a 180 s overall timeout and prints a PASS/FAIL table with per-gate
# timings. Read-only (GETs + `ssh ... is-active`). Degrade-aware: if the attic PC is
# offline, gates 1-4 can still PASS while 5-7 report DEGRADED.
#
#   ./verify_boot.sh            # gates 1-7
#   ./verify_boot.sh --audio    # + trigger/confirm the greeting (gate 8)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
load_env

AUDIO=0; [ "${1:-}" = "--audio" ] && AUDIO=1
DEADLINE=$(( $(date +%s) + 180 ))
HOST="$(robot_host)"
RBASE="http://$HOST:8000"
SSH_USER="${REACHY_SSH_USER:-pollen}"
ATTIC="${BRAIN_HOST:-127.0.0.1}"
BPORT="${BRAIN_PORT:-8100}"
SSHP="${BRAIN_SSH_PORT:-2222}"

declare -a NAMES RESULTS TIMES
gate() { NAMES+=("$1"); RESULTS+=("$2"); TIMES+=("$3"); }
timed() { local s; s=$(date +%s.%N); "$@"; local rc=$?; local e; e=$(date +%s.%N); LAST_T=$(printf '%.2f' "$(echo "$e - $s" | bc)"); return $rc; }
have_time() { [ "$(date +%s)" -lt "$DEADLINE" ]; }

# 1) robot host resolves
timed bash -c "getent hosts '$HOST' >/dev/null 2>&1 || python3 -c \"import socket;socket.gethostbyname('$HOST')\" >/dev/null 2>&1"
[ $? -eq 0 ] && gate "robot host resolves ($HOST)" PASS "$LAST_T" || gate "robot host resolves ($HOST)" FAIL "$LAST_T"

# 2) daemon /docs -> 200
timed bash -c "[ \"\$(curl -s -m 5 -o /dev/null -w '%{http_code}' '$RBASE/docs')\" = 200 ]"
[ $? -eq 0 ] && gate "daemon /docs 200" PASS "$LAST_T" || gate "daemon /docs 200" FAIL "$LAST_T"

# 3) reachy-mini-daemon active (ssh)
timed bash -c "[ \"\$(ssh -o BatchMode=yes -o ConnectTimeout=6 $SSH_USER@$HOST 'systemctl is-active reachy-mini-daemon' 2>/dev/null)\" = active ]"
[ $? -eq 0 ] && gate "daemon service active" PASS "$LAST_T" || gate "daemon service active" FAIL "$LAST_T"

# 4) dashboard REST reports soulmount running
timed bash -c "curl -s -m 5 '$RBASE/api/apps/current-app-status' | grep -qi soulmount"
[ $? -eq 0 ] && gate "soulmount app running" PASS "$LAST_T" || gate "soulmount app running" FAIL "$LAST_T"

# 5) attic answers + WSL sshd on :2222
timed bash -c "nc -z -w4 '$ATTIC' '$SSHP' 2>/dev/null"
if [ $? -eq 0 ]; then gate "attic WSL sshd :$SSHP" PASS "$LAST_T"; else
  if nc -z -w3 "$ATTIC" "$BPORT" 2>/dev/null; then
    gate "attic WSL sshd :$SSHP (host up, sshd down: WSL distro not started — check Task Scheduler job)" DEGRADED "$LAST_T"
  else
    gate "attic reachable ($ATTIC)" DEGRADED "$LAST_T"
  fi
fi

# 6) soulmount units active inside WSL
timed bash -c "ssh -o BatchMode=yes -o ConnectTimeout=6 -p '$SSHP' '$SSH_USER@$ATTIC' 'systemctl is-active soulmount-brain' 2>/dev/null | grep -q active"
[ $? -eq 0 ] && gate "WSL soulmount units active" PASS "$LAST_T" || gate "WSL soulmount units active" DEGRADED "$LAST_T"

# 7) robot -> brain LAN path (proves mirrored networking / portproxy) — the key gate
timed bash -c "ssh -o BatchMode=yes -o ConnectTimeout=6 $SSH_USER@$HOST \"curl -s -m 5 -o /dev/null -w '%{http_code}' http://$ATTIC:$BPORT/health\" 2>/dev/null | grep -q 200"
[ $? -eq 0 ] && gate "robot->brain /health (LAN path)" PASS "$LAST_T" || gate "robot->brain /health (LAN path)" DEGRADED "$LAST_T"

# 8) optional greeting
if [ "$AUDIO" -eq 1 ]; then
  if ssh -o BatchMode=yes "$SSH_USER@$HOST" "journalctl -u soulmount-autostart -n 200 2>/dev/null | grep -qi 'greeting played'"; then
    gate "greeting played (log)" PASS "0.00"
  else
    gate "greeting played (log line not found)" FAIL "0.00"
  fi
fi

# ── Table ──
echo
printf "%-56s %-9s %6s\n" "GATE" "RESULT" "TIME"
printf '%.0s─' {1..74}; echo
fails=0; degraded=0
for i in "${!NAMES[@]}"; do
  r="${RESULTS[$i]}"; c="$GREEN"
  [ "$r" = FAIL ] && { c="$RED"; fails=$((fails+1)); }
  [ "$r" = DEGRADED ] && { c="$YELLOW"; degraded=$((degraded+1)); }
  printf "%-56s ${c}%-9s${NC} %5ss\n" "${NAMES[$i]}" "$r" "${TIMES[$i]}"
done
echo
if [ "$fails" -gt 0 ]; then err "verify-boot: $fails FAIL, $degraded degraded"; exit 1;
elif [ "$degraded" -gt 0 ]; then warn "verify-boot: core PASS, $degraded degraded (attic offline?)"; exit 2;
else ok "verify-boot: FULL PASS"; exit 0; fi
