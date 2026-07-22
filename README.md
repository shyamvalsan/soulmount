# soulmount

**A self-owned embodiment stack for a Reachy Mini Wireless living-room robot.**
You mount a soul on hardware. The robot's own name is family-chosen and lives in the
private data directory — never in this repo.

> **Prime directive: spark joy in the lives of this household — the robot's own life
> included.** Joy is not engagement and not productivity. A joyful robot knows when to
> stay quiet.

This repo is Apache-2.0 and **publishable at every commit**: templates only, no
household-identifying data. `make leakcheck` is a hard pre-commit gate. All personal
content lives in `$SOULMOUNT_DATA_DIR`, outside the tree. See `SPEC.md` for the full
design and `FACTS.md` for verified environment truth (and where reality diverged).

## Architecture

```
  Reachy Mini Wireless (CM4)            Attic PC — Windows 11 + Ubuntu WSL2
  reachy-mini-daemon :8000     HTTP     soulmount-brain   :8100  (OpenAI-compatible)
   ├─ dashboard + REST     ◀────────▶    ├─ /v1/chat/completions · /v1/identity
   └─ soulmount body app                 ├─ /v1/sync_turn · /v1/remember · /v1/inner/*
                                         ├─ /v1/say_privately · /v1/relay · /v1/house
                                         soulmount-channels (Telegram, long-poll)
                                         soulmount-metime   (nightly me-time timer)
                                         $SOULMOUNT_DATA_DIR (WSL ext4, local git)
```
- **body/** — the reachy_mini app (brain-connected fork; minimal diff in `body/DIFF.md`).
- **brain/** — one Python project, four entry points (API · channels · me-time · studio).
- Egress allowlist only: model provider · `api.telegram.org` · search provider
  (+ `googleapis.com` while the studio is enabled). No inbound exposure.

## The two things you must do (interactively, once)

```bash
cp .env.example .env        # then fill it in (see comments in the file)
make setup                  # brain venv (Py 3.12) + leakcheck pre-commit hook
make init-data              # build $SOULMOUNT_DATA_DIR from templates/, fill USER.md
                            #   + .leakcheck-terms, set the robot's name in SOUL.md
```
`.env` needs at minimum: `SOULMOUNT_DATA_DIR`, `BRAIN_API_KEY` (`openssl rand -hex 32`),
`OPENROUTER_API_KEY`, and the robot/attic hosts. Telegram/search/YouTube values are
per-phase. **Secrets never leave `.env`; personal data never leaves the data dir.**

## Everyday commands (`make help` lists all)

| Command | What |
|---|---|
| `make brain-dev` / `make brain-run` | run the brain API (reload / plain) |
| `make brain-test` | brain pytest (temp data dir from templates; zero personal data) |
| `make body-test` | body app logic tests (no robot SDK needed) |
| `make preflight` | read-only robot baseline → `PREFLIGHT.md` |
| `make deploy` | body app → robot (rsync → pip install → verify via dashboard) |
| `make robot-restart` | stop the running app, start `soulmount` (one-app rule) |
| `make verify-boot` | **the acceptance gate**: PASS/FAIL table with timings |
| `make metime-run` | run one me-time session now (respects budget) |
| `make succession ARGS=--dry-run` | write a succession letter (on model change) |
| `make channels-run` | Telegram worker (`channels-dry` = no sends) |
| `make leakcheck` | hard gate: no personal data / secrets in the tree |

## Bring-up order (phases; see `SPEC.md §8`)

0. **Preflight** — `make preflight`; then supervised: `make robot-keyinstall`,
   `make robot-rotate-pass`, `make smoke`. `make init-data`. Attic inventory (`make
   attic-inventory BRAIN_HOST=<ip>`) → decide mirrored vs portproxy (`FACTS.md`).
1. **Brain** — `make brain-test` green; `make brain-run` and `curl :8100/health`.
2. **Voice bake-off** — install the official conversation app on the robot; run a day
   on each backend; set `VOICE_BACKEND` + pin the TTS voice. (Open wiring question in
   `body/DIFF.md` / `MORNING.md`.)
3. **Body app** — `make deploy`; a full conversation with persona + a tool call + a
   memory write.
4. **Appliance** — review & run `scripts/windows/setup-attic.ps1` as admin;
   `make brain-install` (WSL units); `make migrate-data`; robot autostart; then
   `make verify-boot` PASS from a cold power-on, unattended.
5–8. Channels · inner life · ambient · studio — see `SPEC.md`.

## Budget & sleep (hard caps)

Every model call — conversation, channels, me-time, studio — passes the brain's budget
guard: **$5/day, $30/month** (in `BUDGET_TZ`), enforced mechanically, no runtime
override. When the day's budget is spent the robot **sleeps** (a pre-rendered goodnight,
sleep pose, listening paused) and wakes at local midnight (or the 1st for a monthly cap).
Inner life runs only on the day's leftovers and can never starve tomorrow. Every call is
logged to `$SOULMOUNT_DATA_DIR/ops/ledger/YYYY-MM.jsonl` (OpenRouter's exact cost).

## Guardrails (the short list — full set in `SPEC.md §9`)

- Never modify the robot's `/venvs/mini_daemon` or OS; the only system change is the
  Phase-4 autostart unit. Motors via SDK/daemon REST only, moves ≥ 0.3 s.
- No remote admin of the Windows host — the agent writes PowerShell; a human runs it.
- Camera captures for storage/upload only on explicit request; never in a published video.
- Telegram sender allowlist is exactly the household; proactive messages are hard-capped.
- `inner/` and `SELF.md` are the robot's authorship space — scaffolded, never ghost-written.
- Quiet hours (default 21:30–07:30) bind the robot **and** any overnight build.

## Repo map

```
SPEC.md  FACTS.md  PREFLIGHT.md  PROGRESS.md  MORNING.md   # spec + living dossiers
Makefile  .env.example  LICENSE
brain/   src/soulmount_brain/{app,provider,budget,identity,changelog,memory,inner,
         channels,metime,studio,...}.py  + tests/
body/    src/soulmount_body/{app,brain,robot,house,voice,state}.py  DIFF.md  + tests/
templates/ soul/ inner/ memory/     # the ONLY soul content in git — placeholders
scripts/  preflight verify_boot deploy leakcheck ... windows/setup-attic.ps1
```

When this spec and reality disagree, **reality wins** — fixes land in the code and the
correction is recorded in `FACTS.md`.
