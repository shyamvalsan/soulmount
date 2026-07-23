# FACTS.md — soulmount environment dossier

Living record of ground truth and every place reality diverges from `SPEC.md`.
**No personal data, no secrets, no reserved IPs** (those live in `.env`). Hostnames
generic. When the spec and reality disagree, reality wins (guardrail 14) — this
file records the correction so the code matches the world.

_Last verified: 2026-07-22 (Phase 0 partial, laptop-side; attic PC deferred)._

---

## 0. Session context

- Dev host: Ubuntu laptop on the robot's LAN. `uv`, `ffmpeg`, `jq`, `rsync`, `ssh` present. System Python 3.14; project venvs pin **3.12** for wheel availability (reachy SDK / mujoco / numpy lag on 3.14).
- Attic PC (Windows+WSL2 production brain host): **not reachable this session** (owner decision 2026-07-22). All attic inventory + Phase 4 work deferred to a supervised session — see `MORNING.md`.
- Time of build: inside quiet hours (21:30–07:30). Robot touched **read-only** only.

## 1. Robot (Reachy Mini Wireless)

- `reachy-mini.local` **resolves via mDNS from the laptop** (spec warned mDNS is flaky — that caveat is specifically *from inside WSL2*, not the laptop). Reserved IP recorded in `.env` as `REACHY_IP` (kept out of this file by convention).
- Daemon: FastAPI on `:8000`, `/docs` → 200, `/openapi.json` captured. `daemon/status` → `state: running`, `wireless_version: true`, `simulation_enabled: false`.
- **No app currently running** (`/api/apps/current-app-status` → `null`).
- Motors idle: `/api/motors/status` → `{"mode":"disabled"}` (no app holding them).
- **Volume currently 100 (max).** Spec wants a low default until Phase 4 sets policy; not changed tonight (quiet-hours = read-only). → `MORNING.md`.

### 1.1 Battery API — RESOLVED (spec §4 open question)
- **The daemon exposes NO battery/charge/voltage.** `/api/state/full` keys are only:
  `antennas_position, body_yaw, control_mode, doa, head_joints, head_pose, passive_joints, timestamp`.
  No battery endpoint exists in the OpenAPI. → Honest-self-facts block reports battery as **unknown (LED-only hardware)**; `/v1/identity` body-state omits charge.

### 1.2 Live daemon API vs the spec's sketch (§3 diagram is illustrative)
Code to these **real** paths (from live `/openapi.json`):
- Health: `/health-check` is **POST-only** (`GET` → 405). Cheap liveness = `GET /api/daemon/status` (fast, local).
- Apps: `/api/apps/{list-available,current-app-status,start-app/{name},stop-current-app,restart-current-app,install,remove/{name}}`.
- Moves: `/api/move/{goto,set_target,stop,running}`, `/api/move/play/wake_up`, `/api/move/play/goto_sleep`, `/api/move/play/recorded-move-dataset/{dataset_name:path}/{move_name}`.
- Media/sound: `/api/media/{play_sound,stop_sound,sounds,status,acquire,release}`.
- Volume: `/api/volume/{current,set}`, mic `/api/volume/microphone/{current,set}`.
- State: `/api/state/full`, `/api/state/doa`, `/api/state/present_*`.
- Camera: `/api/camera/specs`; snapshots are via **WebRTC on :8443** (not a plain REST GET), and only useful head-up (awake).

### 1.3 Emotions / moves — how to enumerate & play
- Moves come from **two HF recorded-move datasets** fetched at runtime; the "dataset_name" IS the HF repo id (contains a `/`, hence the `:path` converter):
  - Emotions: `pollen-robotics/reachy-mini-emotions-library` — **81 moves**.
  - Dances: `pollen-robotics/reachy-mini-dances-library` — ~19 moves.
- Enumerate live: `GET /api/move/recorded-move-datasets/list/pollen-robotics/reachy-mini-emotions-library`.
- Play: `POST /api/move/play/recorded-move-dataset/pollen-robotics%2Freachy-mini-emotions-library/{move}` (or SDK `RecordedMoves(...).get(name)` + `reachy.play_move(...)`).
- Full emotion set (for §7.2 movement-vocabulary line): amazed1, anxiety1, attentive1/2, boredom1/2, calming1, cheerful1, come1, confused1, contempt1, curious1, dance1/2/3, disgusted1, displeased1/2, downcast1, dying1, electric1, enthusiastic1/2, exhausted1, fear1, frustrated1, furious1, go_away1, grateful1, helpful1/2, impatient1/2, incomprehensible2, indifferent1, inquiring1/2/3, irritated1/2, laughing1/2, lonely1, lost1, loving1, no1, no_excited1, no_sad1, oops1/2, proud1/2/3, rage1, relief1/2, reprimand1/2/3, resigned1, sad1/2, scared1, serenity1, shy1, sleep1, success1/2, surprised1/2, thoughtful1/2, tired1, uncertain1, uncomfortable1, understanding1/2, welcoming1/2, yes1, yes_sad1. (Re-enumerate live at wire-up; datasets can drift.)

## 2. Reachy SDK / app model (for Phase 3)

- PyPI package **`reachy-mini`** (dev line `1.10.0.dev0`; conversation app pins `>=1.10.0rc2`). Install: `uv pip install "reachy-mini[mujoco]"` for the simulator.
- **SPEC CORRECTION**: there is **no `gstreamer` pip extra**. GStreamer is a *system* dependency (apt), not a pip extra. Spec §4 `reachy_mini[gstreamer,wireless-version]` is wrong; correct extras are `wireless-version`, `mujoco`, `opencv`, etc.
- App contract: subclass `reachy_mini.apps.app.ReachyMiniApp`, implement `run(self, reachy_mini, stop_event)`; ship `wrapped_run()` in a `__main__` block. Entry-point group **`reachy_mini_apps`** (matches spec). Daemon launches the app as a subprocess, sends **SIGINT** to stop, and **re-homes** the robot afterward. One app at a time.
- Simulator: **`reachy-mini-daemon --sim`** (MuJoCo), dashboard at `http://127.0.0.1:8000/`. Dev-run an app directly with `python -m <pkg>.main`.
- Scaffolder: `reachy-mini-app-assistant create <name> <path>` (matches spec).

## 2.1 ROBOT ACTUAL STACK (verified live 2026-07-23) — older than GitHub `main`
The overnight research read GitHub `main` (reachy_mini 1.10.0rc2, conversation_app 0.10.0).
The physical robot is OLDER and pinned:
- `reachy_mini` **1.6.3** in BOTH `/venvs/mini_daemon` and `/venvs/apps_venv`, Python
  3.12.12, Debian 13 (trixie). Daemon `/update/available` offers **1.6.3 → 1.9.0**.
- 1.6.3 DOES have our app contract: `reachy_mini.apps.app.ReachyMiniApp.run(self,
  reachy_mini, stop_event)`, `wrapped_run`, `stop`, entry-point group `reachy_mini_apps`.
  → **our body app is compatible with 1.6.3 as-is** (body `[robot]` pin relaxed to `>=1.6`).
- `reachy_mini_conversation_app` **0.3.0** installed (not 0.10.0). It is ALSO realtime-
  based: `config.py` `MODEL_NAME=gpt-realtime`, and `openai_realtime.py` does
  `AsyncOpenAI(api_key=...)` with **NO base_url** → hardwired to OpenAI's Realtime API.
  So 0.3.0 can't be pointed at our brain by config alone (would need a patch or an
  `OPENAI_BASE_URL` redirect to a local OpenAI-Realtime-compatible server).
- Other installed apps incl. hello_world, emotions, dances, etc. (20 total).
- **Daemon launches apps WITHOUT the app-dir `.env`** (verified 2026-07-23): a
  daemon-started subprocess has none of `BRAIN_HOST`/`BRAIN_API_KEY`/… in its
  environment, so a config that only reads `os.environ` silently falls back to
  defaults (`127.0.0.1`) and the body app droops against the robot's own localhost.
  Fix: `body/config.py::load_config()` now LOADS the `.env` itself (`$SOULMOUNT_BODY_ENV`
  or walks up from the package to `soulmount-body/.env`); process env still wins.
  Only a Phase-4 systemd `EnvironmentFile` would inject it at launch — the daemon does not.

**Implication for voice (Phase 2):** the clean speech-to-speech `--llm_backend
chat-completions` path (FACTS §3) targets the 0.10.0 line's `HF_REALTIME_WS_URL` local
mode. On 0.3.0 that config knob isn't present. So voice needs an OWNER DECISION: update
the robot toward the current line, or patch/redirect 0.3.0. Deploying the body app
does NOT require this — it works on 1.6.3 now.

## 3. Conversation app (Phase 2/3 fork base) — MAJOR SPEC DIVERGENCE

- Repo `pollen-robotics/reachy_mini_conversation_app`, **Apache-2.0**, pin fork to SHA
  **`52892f36cac42416689da44b4511f243f3be4393`** (v0.10.0, 2026-07-22). Deps: `reachy-mini>=1.10.0rc2`, `openai==2.28.0`, `huggingface-hub>=1.17.0`.
- **The app is now Hugging-Face-realtime-ONLY.** The old `BACKEND_PROVIDER`/`MODEL_NAME`
  multi-backend env vars were **removed** (now warn). The app speaks the **OpenAI Realtime
  protocol over WebSocket** via the `openai` SDK. So the spec's Phase 3 image of "just add
  a brain backend option to the app" no longer maps cleanly.
- **Two real ways to put our own (Grok) brain behind it** — this is the Phase 2 bake-off, decided with the owner:
  1. **Candidate A (local cascade):** run HF's separate **`speech-to-speech`** server (VAD→STT→LLM→TTS, exposes an OpenAI-Realtime-compatible `/v1/realtime` WS). Point *it* at an OpenAI-compatible LLM with `--responses_api_base_url` / `--llm_backend`. Then point the conversation app at the cascade via `HF_REALTIME_CONNECTION_MODE=local` + `HF_REALTIME_WS_URL=ws://host:port/v1/realtime`. **The `--responses_api_base_url` flag lives on `speech-to-speech`, NOT on the conversation app.**
  2. **Candidate B (hosted realtime):** the app's default deployed HF realtime endpoint (or OpenAI Realtime). Model chosen server-side. Spend sits outside the §7.7 guard.
- **RESOLVED (2026-07-23, morning research):** NO `/v1/responses` shim is needed. HF
  `speech-to-speech` has a first-class **`--llm_backend chat-completions`** that calls
  `POST /v1/chat/completions` in standard OpenAI shape (via the OpenAI SDK) — it consumes
  our brain as-is. `responses-api` is only the *default* of four backends, not the only one.
  - Wiring (Candidate A): `speech-to-speech --mode realtime --llm_backend chat-completions
    --model_name <BRAIN_MODEL> --responses_api_base_url http://<brain>:<port>/v1
    --responses_api_api_key <BRAIN_API_KEY> --responses_api_stream` (the connection flags are
    prefixed `--responses_api_*` for BOTH backends — a shared-naming gotcha, not a hint).
  - Conversation app: `HF_REALTIME_CONNECTION_MODE=local`,
    `HF_REALTIME_WS_URL=ws://<host>:8765/v1/realtime`.
  - Brain requirements — all already met (verified by `test_tools_and_extra_body_passthrough`):
    (1) faithful passthrough of `tools`/`tool_choice`/`tool`-role messages — the robot's
    motion tools (dance, play_emotion, move_head, head_tracking) are advertised over the
    Realtime session and must reach the LLM; (2) tolerate provider `extra_body` keys
    (`chat_template_kwargs`, `reasoning_effort`) — we forward them; if OpenRouter rejects
    them, pass `--responses_api_disable_thinking false` + omit `--responses_api_reasoning_effort`
    at Phase 2; (3) standard SSE with a final usage chunk — OpenRouter provides it.
  - So the voice integration is a Phase-2 *deployment* job (install s2s, pick STT/TTS+voice,
    bake-off), NOT a brain code change.
- **Identity injection fork point** (`prompts.py::get_session_instructions`): final instructions = `"{memory_prompt}\n\n{instructions}"`, where `instructions` = the resolved profile's `instructions.txt`. Cleanest, lowest-blast-radius fork: **ship a bundled custom profile dir** + set `REACHY_MINI_CUSTOM_PROFILE` (or `REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY`), rather than patching upstream code. Greeting from `greeting.txt` (else default); voice from `voice.txt` (default `"Aiden"`; other voices: Ryan, Dylan, Eric, Serena, Vivian, …) — the chosen voice is pinned in `.env` and must never drift (spec §7 / Phase 2).
- Useful app env: `REACHY_MINI_CUSTOM_PROFILE`, `REACHY_MINI_EXTERNAL_PROFILES_DIRECTORY`, `REACHY_MINI_EXTERNAL_TOOLS_DIRECTORY`, `AUTOLOAD_EXTERNAL_TOOLS`, `REACHY_MINI_APP_TIMEOUT_MINUTES` (default 1440), `REACHY_MINI_SKIP_DOTENV`. App data dir: `~/.local/share/reachy_mini_conversation_app/`.

## 4. Upstream model provider (OpenRouter) — for Phase 1

- Base `https://openrouter.ai/api/v1`; auth `Authorization: Bearer $OPENROUTER_API_KEY`.
- **Exact cost is returned INLINE** in `usage.cost` (USD) on every response — non-stream body
  and the **final SSE chunk** when `stream:true`. The old `usage:{include:true}` /
  `stream_options:{include_usage:true}` flags are **deprecated no-ops**; usage is always present.
  `GET /api/v1/generation?id=` still exists but is no longer needed for cost. → The ledger reads `usage.cost` directly.
- Cache hits: `usage.prompt_tokens_details.cached_tokens`. Grok/xAI **auto-caches** (reads 0.25×, writes free) — good for the identity blob; pin provider routing with `session_id`/`x-session-id` to maximize hits.
- SSE: `data: ` JSON chunks; skip comment lines starting with `:` (keepalive `: OPENROUTER PROCESSING`); terminator `data: [DONE]`; mid-stream errors arrive as a `data:` event with `error` (HTTP stays 200).
- **Model slugs verified live 2026-07-22**: `x-ai/grok-4.5` ($2/$6 per Mtok, cache-read $0.30, 500K ctx) ✓; `x-ai/grok-4.20` ($1.25/$2.50, cache-read $0.20, 2M ctx) ✓; also `x-ai/grok-4.3`, `x-ai/grok-4.20-multi-agent`, `x-ai/grok-build-0.1`. Re-query before hardcoding — OpenRouter rotates slugs.

## 5. Telegram (Phase 5)

- Long-polling `getUpdates` (offset = max(update_id)+1, `timeout` for held-open poll, `allowed_updates`) is **pure outbound HTTPS** to `api.telegram.org` — **no webhook, no inbound port** (sidesteps WSL inbound networking entirely). Long-poll and webhook are mutually exclusive; `deleteWebhook` first if one was ever set.
- Sender id: `update.message.from.id`; chat id: `update.message.chat.id`. Reply: `POST /bot<token>/sendMessage` with `chat_id` + `text`.

## 7. Resolved gaps & accepted limitations (from the code review)
- **EUR↔USD (spec gap, resolved):** budget caps are USD, me-time/studio caps EUR, no
  rate given. Introduced `EUR_USD_RATE` (default 1.08) in config; the EUR caps convert
  to USD for the §7.7 leftover-allowance math. Override in `.env`.
- **`/v1/house` (justified addition):** the robot has no local data dir, so the body
  app fetches machine-readable HOUSE values from the brain to enforce them in code.
- **Budget TOCTOU (accepted, single-robot):** `decide()`→call→`record()` isn't locked,
  so two truly-concurrent turns could overshoot the cap by ≤ one turn (~cents),
  absorbed by the goodnight reserve. Not serialized (would make a Telegram DM wait
  behind a long voice stream). Revisit only if multi-client concurrency grows.
- **Succession letter delivery is optimistic on `/v1/identity`:** the body app's
  session-start fetch is treated as delivery; a fetch that is lost before the model
  reads it could drop the one-shot letter. Accepted — the letter is a gift, not a
  safety property; me-time and chat paths mark it only after the model actually
  received it, so double-delivery is prevented.
- **Identity has a template floor:** SOUL (prime directive), HOUSE (hard rules), and the
  honest-self-facts block are always emitted whole — they can't be trimmed. The growable,
  robot-authored sections (SELF.md, succession letter, memory/recent-days) ARE clipped to
  the token budget. So `IDENTITY_MAX_TOKENS` / `REALTIME_IDENTITY_MAX_TOKENS` must be set
  at or above that floor (~1.5k tokens); the spec's "~IDENTITY_MAX_TOKENS" allows the slack.
- **Cost fail-closed:** if a non-OpenRouter provider reports no cost and the model
  isn't priced, a deliberately HIGH fallback rate is charged (never $0) so the hard
  cap engages rather than failing open.

## 6. Structure clarifications (minor)
- Spec §6 shows `templates/{soul,inner}`; the data dir §6.1 also has `memory/`. We ship
  `templates/memory/` too (MEMORY.md, CHANGELOG.md, daily/) so `init-data` and the test
  harness can build a complete data dir from templates. Non-behavioral clarification.
- `.leakcheck-terms` lives at the **data-dir root** (§6.1). The repo ships
  `templates/leakcheck-terms.example` (committed, illustrative only); the real file is
  created by `init-data` inside `$SOULMOUNT_DATA_DIR` and never committed.
