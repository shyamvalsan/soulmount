#!/usr/bin/env bash
# voice_server.sh — Phase 2 voice bake-off (candidate A: local cascade).
#
# Stands up the HuggingFace `speech-to-speech` server ON THE LAPTOP (companion host),
# pointed at our brain's OpenAI-compatible /v1/chat/completions. The robot's stock
# conversation app (0.9.x) then connects to this server's realtime WS. Nothing here
# makes the robot move or speak — that only happens once the robot app connects.
#
#   voice_server.sh setup   # create a py3.12 venv + install s2s + dump `--help`
#   voice_server.sh run     # launch the server (Kokoro TTS, voice af_bella)
#
# The laptop is on Python 3.14 (ML wheels lag) → we pin a dedicated 3.12 venv via uv.
# Secrets/hosts come from .env at runtime (never hard-coded here) so this stays leak-safe.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"; load_env

VENV="$ROOT/.venv-voice"
PYVER="3.12"

# ── Config (edit here after confirming exact flag names via `setup`'s --help dump) ──
BRAIN_PORT="${BRAIN_PORT:-8100}"
BRAIN_MODEL="${BRAIN_MODEL:-x-ai/grok-4.5}"
BRAIN_URL="http://127.0.0.1:${BRAIN_PORT}/v1"   # s2s and brain are both on the laptop → loopback
S2S_STT="${VOICE_STT:-faster-whisper}"          # light + CPU-friendly (RAM-constrained laptop);
                                                # NB confirm the model-size flag (default may be large) in --help
S2S_TTS="kokoro"                                # CPU-friendly, many EN voices
S2S_VOICE="${VOICE_KOKORO:-af_bella}"           # owner pick (2026-07-23)

usage() { echo "usage: voice_server.sh {setup|run}"; exit 2; }

setup() {
  command -v uv >/dev/null || { err "uv not found"; exit 1; }
  info "creating python $PYVER venv at $VENV (laptop default is 3.14; ML wheels need 3.12)"
  run uv venv --python "$PYVER" "$VENV"
  info "installing speech-to-speech (+ CPU torch) — multi-GB, one-time"
  run uv pip install --python "$VENV/bin/python" speech-to-speech
  info "dumping --help so we can confirm exact flag names (STT model size, WS bind host)"
  "$VENV/bin/speech-to-speech" --help > "$ROOT/.venv-voice-help.txt" 2>&1 || true
  ok "setup done. Review .venv-voice-help.txt, then: voice_server.sh run"
}

run_server() {
  [ -x "$VENV/bin/speech-to-speech" ] || { err "run setup first"; exit 1; }
  [ -n "${BRAIN_API_KEY:-}" ] || { err "BRAIN_API_KEY not set in .env"; exit 1; }
  # Brain must be up (this server calls it every turn).
  curl -s -m 5 "http://127.0.0.1:${BRAIN_PORT}/health" >/dev/null || warn "brain not answering on :$BRAIN_PORT — start it first (make brain-run)"
  info "launching speech-to-speech realtime server (STT=$S2S_STT TTS=$S2S_TTS voice=$S2S_VOICE → brain $BRAIN_URL)"
  # Verified flags (FACTS/research): --mode realtime, --llm_backend chat-completions,
  # --responses_api_base_url/api_key/stream, --tts kokoro, --kokoro_voice, --model_name.
  # UNVERIFIED (confirm in --help before relying on): the WS bind-host flag (server must bind
  # 0.0.0.0 so the robot can reach ws://<laptop-lan-ip>:8765/v1/realtime, not just localhost),
  # and the faster-whisper model-size flag.
  run "$VENV/bin/speech-to-speech" \
    --mode realtime \
    --stt "$S2S_STT" \
    --llm_backend chat-completions \
    --tts "$S2S_TTS" \
    --kokoro_voice "$S2S_VOICE" \
    --model_name "$BRAIN_MODEL" \
    --responses_api_base_url "$BRAIN_URL" \
    --responses_api_api_key "$BRAIN_API_KEY" \
    --responses_api_stream
}

case "${1:-}" in
  setup) setup ;;
  run)   run_server ;;
  *)     usage ;;
esac

# ── Robot side (morning, after this server is up) ──────────────────────────────────
# The stock conversation app 0.9.x must be installed on the robot and launched with:
#   HF_REALTIME_CONNECTION_MODE=local
#   HF_REALTIME_WS_URL=ws://$BRAIN_HOST:8765/v1/realtime   (BRAIN_HOST = this laptop's LAN IP)
# The daemon launches apps WITHOUT their .env (see FACTS 2.1) — so these must reach the app's
# process env another way (daemon app-config, or a wrapper). Resolve at wire-up time.
