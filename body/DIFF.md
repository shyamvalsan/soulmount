# body/DIFF.md — the soulmount fork, enumerated

Fork base: **`pollen-robotics/reachy_mini_conversation_app`**, Apache-2.0,
pinned upstream SHA **`52892f36cac42416689da44b4511f243f3be4393`** (v0.10.0,
2026-07-22). Deps at that SHA: `reachy-mini>=1.10.0rc2`, `openai==2.28.0`.

## What overnight built (this package)

The soulmount body app is a `reachy_mini_apps` entry point (`soulmount =
soulmount_body.app:SoulmountApp`). It integrates with the brain and enforces the
house rules mechanically. The modules are deliberately SDK-light so the logic is
unit-tested off-robot; the Reachy SDK is the `[robot]` extra.

Enumerated diff (SPEC §Phase 3), by item:

1. **Brain backend/connection** — `brain.py::BrainConnection`: fetch `/v1/identity`
   at session start; `/v1/sync_turn` after each exchange, **fire-and-forget** so
   body threads never block on the network; `/v1/house` for hard-rule values; tools
   (`remember`, `say_privately`, `journal`). Works regardless of `VOICE_BACKEND`.
2. **Startup ritual** — `app.py::_startup_ritual`: check brain `/health`; healthy →
   wake animation + one-line greeting; unhealthy → antenna-droop pose + periodic
   retry, never a crash; auto-recovers when the brain returns.
3. **Tools wired for the LLM** — `remember`, `say_privately` (queues to channels;
   the robot says "I'll text you" aloud), `journal`. Executed in `brain.py`.
4. **House enforcement in code** — `house.py`: quiet hours, volume ceiling, and the
   camera capture-on-request-only rule are read from `/v1/house` and enforced
   mechanically in `_main_loop`, not merely suggested to the model (guardrail 10).
5. **Sleep-state handling** — `app.py::_main_loop` + `state.py::sleep_info`: on an
   asleep brain (seen via `/health` budget state or an `asleep` chat payload), play
   a wind-down + sleep pose, pause the listening loop, and wake with a stretch.
   (The *pre-rendered goodnight audio clip* is a MORNING asset — see below.)
6. **Instant acknowledgment** — `robot.py::instant_ack`: a quick local daemon-REST
   gesture bridging the brain's response gap (no tokens, no brain call).

Motion/rituals go through the **daemon REST** (verified shapes, FACTS §1.2) rather
than guessing SDK method names; the daemon runs on `localhost:8000` on the robot.

## What is deferred to the morning (voice-dependent) — see MORNING.md

The upstream conversation app is now **Hugging-Face-realtime-ONLY** (FACTS §3): the
old `BACKEND_PROVIDER`/`MODEL_NAME` vars were removed; it speaks the OpenAI Realtime
protocol over WebSocket. So the actual conversation turn is a **seam**
(`voice.py::VoiceBackend`, currently `NullVoiceBackend`) wired once the Phase 2
bake-off picks a backend:

- **local** — run HF `speech-to-speech` (VAD→STT→LLM→TTS) pointed at the brain.
  **RESOLVED (FACTS §3):** use `--llm_backend chat-completions` (NOT the default
  `responses-api`) — it calls our `/v1/chat/completions` as-is; no `/v1/responses` shim.
  `speech-to-speech --mode realtime --llm_backend chat-completions --model_name $BRAIN_MODEL
  --responses_api_base_url http://<brain>:<port>/v1 --responses_api_api_key $BRAIN_API_KEY
  --responses_api_stream`, then connect the app via `HF_REALTIME_CONNECTION_MODE=local`
  + `HF_REALTIME_WS_URL=ws://<host>:8765/v1/realtime`. Brain passes tools/extra_body through
  faithfully (tested) — the robot's motion tools work over the voice loop.
- **realtime** — the hosted HF/OpenAI realtime endpoint; optional `ask_brain` tool
  routing hard/memory questions to the Grok brain.

**Identity injection** for whichever backend: ship a bundled custom profile
(`instructions.txt` sourced from the brain's `/v1/identity`) and set
`REACHY_MINI_CUSTOM_PROFILE`, keeping upstream code unpatched (lowest blast radius).
Pin the chosen TTS voice in `.env` (it must never drift).

Also MORNING: the pre-rendered goodnight audio clip (upload via
`/api/media/sounds/upload`), and verifying `/api/volume/set` behaviour on the robot.
