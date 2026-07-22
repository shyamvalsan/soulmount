#!/usr/bin/env bash
# verify_boot.sh — THE Phase 4 acceptance gate (SPEC §Phase 4). Run from the laptop.
# POLLS (re-evaluating every 5s) until all gates pass or a 180 s deadline, then prints
# a PASS/FAIL table with per-gate timings. Read-only. Degrade-aware: core robot gates
# (1-4) must PASS; the attic-dependent gates (5,6,7) report DEGRADED when the attic PC
# is offline. Exit 0=full pass, 2=core pass + degraded, 1=a core gate failed.
#
#   ./verify_boot.sh            # gates 1-7
#   ./verify_boot.sh --audio    # + assert the greeting log line (gate 8)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"
load_env

AUDIO=0; [ "${1:-}" = "--audio" ] && AUDIO=1
HOST="$(robot_host)"
RBASE="http://$HOST:8000"
RUSER="${REACHY_SSH_USER:-pollen}"
ATTIC="${BRAIN_HOST:-127.0.0.1}"
BPORT="${BRAIN_PORT:-8100}"
SSHP="${BRAIN_SSH_PORT:-2222}"
AUSER="${BRAIN_SSH_USER:-$USER}"   # attic WSL account (distinct from the robot user)
SSHO="-o BatchMode=yes -o ConnectTimeout=4"  # short so a degraded round can't overrun 180s much

# Each gate prints PASS / FAIL / DEGRADED. Robot gates (1-4) always FAIL on failure.
# Attic gates (6,7) FAIL when the attic IS reachable but the brain/units are down — a
# broken-but-reachable brain must NOT pass — and only DEGRADE when the attic itself is
# offline (the tolerated degraded-mode drill). NB: gates run inside a command-sub
# subshell, so g6/g7 re-test attic reachability with _tcp themselves rather than trust a
# variable a subshell can't export.
_tcp(){ timeout 4 bash -c "exec 3<>/dev/tcp/$1/$2" 2>/dev/null; }  # bounded, nc-free
g1(){ getent hosts "$HOST" >/dev/null 2>&1 || python3 -c "import socket;socket.gethostbyname('$HOST')" >/dev/null 2>&1 && echo PASS || echo FAIL; }
g2(){ [ "$(curl -s -m5 -o /dev/null -w '%{http_code}' "$RBASE/docs")" = 200 ] && echo PASS || echo FAIL; }
g3(){ [ "$(ssh $SSHO "$RUSER@$HOST" 'systemctl is-active reachy-mini-daemon' 2>/dev/null)" = active ] && echo PASS || echo FAIL; }
g4(){ curl -s -m5 "$RBASE/api/apps/current-app-status" 2>/dev/null \
     | jq -e '(.app_name // .name // .app // "")|test("soulmount";"i")' >/dev/null 2>&1 && echo PASS || echo FAIL; }
g5(){ _tcp "$ATTIC" "$SSHP" && echo PASS || echo DEGRADED; }
g6(){ # all soulmount units active inside WSL (brain + channels + metime timer)
  local out; out="$(ssh $SSHO -p "$SSHP" "$AUSER@$ATTIC" \
     'systemctl is-active soulmount-brain soulmount-channels soulmount-metime.timer' 2>/dev/null)"
  if [ "$(printf '%s' "$out" | grep -c '^active$')" = 3 ]; then echo PASS
  elif _tcp "$ATTIC" "$SSHP"; then echo FAIL; else echo DEGRADED; fi; }
g7(){ # robot -> brain LAN path (proves mirrored networking / portproxy) — key gate
  if ssh $SSHO "$RUSER@$HOST" "curl -s -m5 -o /dev/null -w '%{http_code}' http://$ATTIC:$BPORT/health" 2>/dev/null | grep -q 200
  then echo PASS
  elif _tcp "$ATTIC" "$SSHP"; then echo FAIL; else echo DEGRADED; fi; }
g8(){ # greeting: the app runs UNDER reachy-mini-daemon (assumed captured in its journal;
      # verify at wire-up). Accept the greeting line OR the quiet-hours suppression line —
      # a correct quiet-hours boot legitimately plays no greeting (SPEC §Phase 4 tests this).
  ssh $SSHO "$RUSER@$HOST" \
     "journalctl -u reachy-mini-daemon -n 600 --no-pager 2>/dev/null | grep -Eqi 'greeting played|quiet hours .*no greeting'" \
     && echo PASS || echo FAIL; }

NAMES=("robot host resolves ($HOST)" "daemon /docs 200" "daemon service active"
       "soulmount app running" "attic WSL sshd :$SSHP" "WSL soulmount units active (brain+channels+metime)"
       "robot->brain /health (LAN path)")
FNS=(g1 g2 g3 g4 g5 g6 g7)
if [ "$AUDIO" -eq 1 ]; then NAMES+=("greeting played (daemon journal)"); FNS+=(g8); fi

declare -a RESULTS TIMES
DEADLINE=$(( $(date +%s) + 180 ))
round=0
while :; do
  round=$((round+1))
  allgood=1
  for i in "${!FNS[@]}"; do
    s=$(date +%s.%N); RESULTS[$i]="$(${FNS[$i]})"; e=$(date +%s.%N)
    TIMES[$i]="$(printf '%.2f' "$(echo "$e - $s" | bc 2>/dev/null || echo 0)")"
    [ "${RESULTS[$i]}" = PASS ] || allgood=0
  done
  [ "$allgood" = 1 ] && break
  [ "$(date +%s)" -ge "$DEADLINE" ] && break
  sleep 5
done

echo
printf "%-58s %-9s %6s\n" "GATE (round $round)" "RESULT" "TIME"
printf '%.0s─' {1..76}; echo
fails=0; degraded=0
for i in "${!NAMES[@]}"; do
  r="${RESULTS[$i]}"; c="$GREEN"
  [ "$r" = FAIL ] && { c="$RED"; fails=$((fails+1)); }
  [ "$r" = DEGRADED ] && { c="$YELLOW"; degraded=$((degraded+1)); }
  printf "%-58s ${c}%-9s${NC} %5ss\n" "${NAMES[$i]}" "$r" "${TIMES[$i]}"
done
echo
if [ "$fails" -gt 0 ]; then err "verify-boot: $fails FAIL, $degraded degraded (${round} rounds)"; exit 1
elif [ "$degraded" -gt 0 ]; then warn "verify-boot: core PASS, $degraded degraded (attic offline?)"; exit 2
else ok "verify-boot: FULL PASS (${round} rounds)"; exit 0; fi
