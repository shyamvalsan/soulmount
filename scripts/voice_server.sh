#!/usr/bin/env bash
# voice_server.sh — Phase 2 voice, candidate A: local cascade on the COMPANION HOST (laptop).
#
# Runs the voice-service (voice/voice_service.py): the robot streams a 16 kHz mic WAV to
# POST /voice and gets back the robot's reply — faster-whisper (STT) -> brain (voice mode) ->
# kokoro af_heart (TTS, 16 kHz) — plus the *asterisk* motion cues for the body to act out.
#
#   voice_server.sh setup   # py3.12 venv + deps + kokoro model + espeak-ng
#   voice_server.sh run     # serve on :8200 (reads BRAIN_API_KEY etc. from .env)
#
# NB: the HF `speech-to-speech` framework won't build on modern Python (numba<3.10 pin),
# so this is our own minimal cascade. Secrets/hosts come from .env at runtime (leak-safe).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"; load_env

VENV="$ROOT/.venv-voice"
PORT="${VOICE_SERVICE_PORT:-8200}"
KOKORO_DIR="${KOKORO_DIR:-$HOME/.cache/kokoro-onnx}"
KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

setup() {
  command -v uv >/dev/null || { err "uv not found"; exit 1; }
  info "creating python 3.12 venv at $VENV (laptop default is 3.14; ML wheels need 3.12)"
  run uv venv --python 3.12 "$VENV"
  info "installing voice deps"
  run uv pip install --python "$VENV/bin/python" -r "$ROOT/voice/requirements.txt"
  info "fetching kokoro model (~340MB, one-time) -> $KOKORO_DIR"
  mkdir -p "$KOKORO_DIR"
  [ -s "$KOKORO_DIR/kokoro-v1.0.onnx" ] || run curl -fL -o "$KOKORO_DIR/kokoro-v1.0.onnx" "$KOKORO_BASE/kokoro-v1.0.onnx"
  [ -s "$KOKORO_DIR/voices-v1.0.bin" ] || run curl -fL -o "$KOKORO_DIR/voices-v1.0.bin" "$KOKORO_BASE/voices-v1.0.bin"
  command -v espeak-ng >/dev/null || { info "installing espeak-ng (kokoro g2p)"; run sudo apt-get install -y espeak-ng; }
  ok "setup done -> voice_server.sh run"
}

run_service() {
  [ -x "$VENV/bin/python" ] || { err "run setup first"; exit 1; }
  [ -n "${BRAIN_API_KEY:-}" ] || { err "BRAIN_API_KEY not set in .env"; exit 1; }
  export KOKORO_DIR VOICE_KOKORO="${VOICE_KOKORO:-af_heart}" BRAIN_API_KEY
  export BRAIN_URL="http://127.0.0.1:${BRAIN_PORT:-8100}/v1/chat/completions"
  curl -s -m5 "http://127.0.0.1:${BRAIN_PORT:-8100}/health" >/dev/null || warn "brain not answering on :${BRAIN_PORT:-8100} — start it (make brain-run)"
  info "voice-service on :$PORT (STT=faster-whisper, TTS=kokoro $VOICE_KOKORO, brain=$BRAIN_URL)"
  cd "$ROOT"
  run "$VENV/bin/python" -m uvicorn voice.voice_service:app --host 0.0.0.0 --port "$PORT"
}

case "${1:-}" in
  setup) setup ;;
  run)   run_service ;;
  *) err "usage: voice_server.sh {setup|run}"; exit 2 ;;
esac
