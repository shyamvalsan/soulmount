#!/usr/bin/env bash
# attic_inventory.sh — Phase 0 read-only inventory of the attic WSL host (§4.1).
# Run from the laptop; ssh's into the attic WSL and uses Windows interop where needed.
# Decides mirrored-vs-portproxy; append the findings to FACTS.md.
# (Deferred overnight — attic offline. See MORNING.md.)
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"; load_env

ATTIC="${BRAIN_HOST:?set BRAIN_HOST (attic reserved IP) — e.g. make attic-inventory BRAIN_HOST=192.168.x.y}"
SSHP="${BRAIN_SSH_PORT:-2222}"
USER_NAME="${REACHY_SSH_USER:-$USER}"
S="ssh -o ConnectTimeout=8 -p $SSHP $USER_NAME@$ATTIC"

info "querying attic WSL at $USER_NAME@$ATTIC:$SSHP"
echo "== Windows build ==";      $S 'cmd.exe /c ver' 2>/dev/null
echo "== WSL version ==";        $S 'wsl.exe --version' 2>/dev/null
echo "== distro / systemd ==";   $S 'cat /etc/os-release | sed -n "s/^PRETTY_NAME=//p"; echo -n "systemd: "; ps -p 1 -o comm=' 2>/dev/null
echo "== networkingMode ==";     $S 'wsl.exe --version 2>/dev/null | grep -i default || echo "check %UserProfile%\\.wslconfig"' 2>/dev/null
echo "== CPU/RAM ==";            $S 'nproc; free -h | sed -n 2p' 2>/dev/null
echo "== GPU (nvidia?) ==";      $S 'command -v nvidia-smi >/dev/null && nvidia-smi -L || echo "no nvidia-smi"' 2>/dev/null
echo "== disk (WSL ext4) ==";    $S 'df -h ~ | sed -n 2p' 2>/dev/null

cat <<'NOTE'

Decision guide (record in FACTS.md §0):
- Windows 11 22H2/23H2+ and WSL 2.0+  -> prefer MIRRORED networking (.wslconfig
  networkingMode=mirrored) + Hyper-V firewall inbound-allow for 8100/2222.
- Older build -> PORTPROXY fallback (netsh interface portproxy + firewall + a
  scheduled refresh script, since the WSL IP changes each boot).
- GPU present -> local voice (Candidate A) + generative render capacity is viable.
NOTE
