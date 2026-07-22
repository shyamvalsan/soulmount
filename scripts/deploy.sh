#!/usr/bin/env bash
# deploy.sh — deploy body/ to the robot (SPEC §Phase 3). SUPERVISED (mutates the
# robot: installs the app, may start/stop apps). One app at a time (guardrail 4).
#   deploy.sh full     rsync -> pip install -e .[robot] -> push .env -> verify
#   deploy.sh code     rsync only (fast path)
#   deploy.sh restart  stop current app, start soulmount (via REST)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"; load_env

MODE="${1:-full}"
HOST="$(robot_host)"
SSH_USER="${REACHY_SSH_USER:-pollen}"
REMOTE_DIR="/home/$SSH_USER/soulmount-body"
APPS_VENV="/venvs/apps_venv"
RBASE="http://$HOST:8000"

stop_current() {
  info "stopping current app (one-app rule)"
  run curl -s -m 10 -X POST "$RBASE/api/apps/stop-current-app" >/dev/null || warn "no app running / stop failed"
}
start_soulmount() {
  info "starting soulmount via dashboard REST"
  run curl -s -m 15 -X POST "$RBASE/api/apps/start-app/soulmount" >/dev/null
}
verify() {
  sleep 3
  # Parse the actual current-app field rather than substring-matching raw JSON.
  if curl -s -m 8 "$RBASE/api/apps/current-app-status" \
       | jq -e '(.app_name // .name // .app // "")|test("soulmount";"i")' >/dev/null 2>&1; then
    ok "soulmount visible in dashboard"
  else
    err "soulmount not visible after start"; return 1
  fi
}
rsync_code() {
  info "rsync body/ -> $SSH_USER@$HOST:$REMOTE_DIR"
  # NB: exclude .env so --delete never wipes the robot-side EnvironmentFile pushed
  # by push_env (a bug where `deploy-code` left the app with default config).
  run rsync -az --delete \
    --exclude '.env' --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
    "$ROOT/body/" "$SSH_USER@$HOST:$REMOTE_DIR/"
}
push_env() {
  # Robot-side .env for the autostart unit's EnvironmentFile (secret, not committed).
  info "pushing robot-side .env (BRAIN_HOST etc.)"
  local tmp; tmp="$(mktemp)"
  # EXIT (not RETURN): under set -e a failing scp exits the shell without returning, so a
  # RETURN trap wouldn't fire — EXIT guarantees the bearer key never lingers in /tmp.
  trap 'rm -f "$tmp"' EXIT
  {
    echo "BRAIN_HOST=${BRAIN_HOST:-127.0.0.1}"
    echo "BRAIN_PORT=${BRAIN_PORT:-8100}"
    echo "BRAIN_API_KEY=${BRAIN_API_KEY:-}"
    echo "DAEMON_URL=http://127.0.0.1:8000"
    echo "VOICE_BACKEND=${VOICE_BACKEND:-local}"
  } > "$tmp"
  run scp "$tmp" "$SSH_USER@$HOST:$REMOTE_DIR/.env"
}
pip_install() {
  info "pip install -e .[robot] into $APPS_VENV (git-lfs deps → pip, not uv)"
  # Quote the whole spec so [robot] isn't glob-expanded by the remote shell.
  run ssh "$SSH_USER@$HOST" "$APPS_VENV/bin/pip install -e \"$REMOTE_DIR[robot]\""
}

case "$MODE" in
  full)    rsync_code; push_env; pip_install; stop_current; start_soulmount; verify ;;
  code)    rsync_code; ok "code synced (no reinstall/restart)" ;;
  restart) stop_current; start_soulmount; verify ;;
  *) err "usage: deploy.sh {full|code|restart}"; exit 2 ;;
esac
