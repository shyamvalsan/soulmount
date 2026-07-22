#!/usr/bin/env bash
# brain_install.sh — install systemd units for the brain box (SPEC §Phase 4).
# Run INSIDE the attic WSL2 distro. Idempotent. Creates system units for the API,
# channels, and a nightly me-time timer; Restart=always; enabled at boot.
# (Deferred overnight — the attic PC was offline. See MORNING.md.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"; load_env

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
USER_NAME="$(id -un)"
BRAIN_BIND="${BRAIN_HOST:-0.0.0.0}"
PORT="${BRAIN_PORT:-8100}"
HOUR="${METIME_HOUR:-23}"
ENVFILE="$ROOT/.env"

info "installing units from repo: $ROOT (uv=$UV, user=$USER_NAME)"
[ -f "$ENVFILE" ] || { err ".env not found at $ENVFILE (secrets + SOULMOUNT_DATA_DIR)"; exit 1; }

unit() { # name  description  execstart  [extra...]
  local name="$1" desc="$2" exec="$3"; shift 3
  sudo tee "/etc/systemd/system/$name" >/dev/null <<EOF
[Unit]
Description=$desc
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$ROOT/brain
EnvironmentFile=$ENVFILE
ExecStart=$exec
Restart=always
RestartSec=3
$*

[Install]
WantedBy=multi-user.target
EOF
}

unit soulmount-brain.service    "soulmount brain API"      "$UV run --project $ROOT/brain soulmount-brain --host $BRAIN_BIND --port $PORT"
unit soulmount-channels.service "soulmount Telegram channels" "$UV run --project $ROOT/brain soulmount-channels"

# me-time as a nightly timer (oneshot service + timer), not a long-running unit.
sudo tee /etc/systemd/system/soulmount-metime.service >/dev/null <<EOF
[Unit]
Description=soulmount nightly me-time
[Service]
Type=oneshot
User=$USER_NAME
WorkingDirectory=$ROOT/brain
EnvironmentFile=$ENVFILE
ExecStart=$UV run --project $ROOT/brain soulmount-metime
EOF
sudo tee /etc/systemd/system/soulmount-metime.timer >/dev/null <<EOF
[Unit]
Description=soulmount me-time nightly at ${HOUR}:00
[Timer]
OnCalendar=*-*-* ${HOUR}:00:00
Persistent=false
[Install]
WantedBy=timers.target
EOF

run sudo systemctl daemon-reload
run sudo systemctl enable --now soulmount-brain.service soulmount-channels.service soulmount-metime.timer
ok "units installed & enabled. Check: systemctl status soulmount-brain"
