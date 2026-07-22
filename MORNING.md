# MORNING.md — supervised checklist (queued from the overnight run)

Items that need approval, admin rights, a voice, a reboot, or a family member.
Each: one line of context + the exact command to resume. ~10 supervised minutes
of the essentials, then the multi-day bake-off/naming rituals. Nothing here was
done overnight because §2.1 / quiet hours / the attic being offline forbade it.

## A. Robot — Phase 0 live rituals (need you present; robot leaves read-only)
- [ ] **Install laptop SSH key on the robot.** Context: enables key-based ssh, precondition
      for deploy/verify. Run: `make robot-keyinstall`  (prompts once for the factory password).
- [ ] **Rotate the factory password** (owner-approved, guardrail 11). Context: robot ships with
      `pollen:root`. Run: `make robot-rotate-pass`  (walks you through it; records nothing secret).
- [ ] **Lower the daemon volume** from the current 100 to the HOUSE.md ceiling. Context: spec
      wants a low default; not changed overnight (read-only). Run: `make robot-set-volume`.
- [ ] **Live smoke tests (audible/motion — announced).** Context: antenna wiggle, one emotion,
      one low sound, one camera snapshot (robot awake). Run: `make smoke`  (asks before each move).
- [ ] **Enumerate the live emotion/dance move list** into PREFLIGHT.md. Run: `make preflight`.

## B. Data dir — interactive init (need your household answers)
- [ ] **`make init-data`** — walks you through USER.md (members, languages, learn-vs-never)
      and `.leakcheck-terms`, then `git init` locally. Context: the overnight build ran against a
      *placeholder* data dir; real personal content only exists after you do this. Run: `make init-data`.
      (The robot's chosen name goes into SOUL.md here.)

## C. Secrets to fill in `.env` (phases that need them auto-skipped overnight)
- [ ] `BRAIN_API_KEY` — generate: `openssl rand -hex 32` → paste into `.env`.
- [ ] Telegram: create the bot with @BotFather; fill `TELEGRAM_BOT_TOKEN`,
      `TELEGRAM_ALLOWED_USER_IDS` (each member's numeric id), `TELEGRAM_FAMILY_CHAT_ID`.
      Then: `make channels-run` (drops --dry-run once you're ready).
- [ ] Search: `SEARCH_API_KEY` (Brave free tier) — or set `SEARCH_API_PROVIDER=searxng` + `SEARXNG_BASE_URL`.
- [ ] Studio (only if/when you enable Phase 8): `YOUTUBE_CLIENT_SECRETS_PATH`, `YOUTUBE_CHANNEL_ID`.

## D. Attic PC — deferred entirely (it was offline tonight)
- [ ] **Attic inventory** (Phase 0): from inside its WSL, gather Windows build, WSL version,
      distro, systemd status, networkingMode, CPU/RAM/GPU, disk. Decides mirrored-vs-portproxy.
      Resume: bring it online, add its reserved IP + WSL ssh (`:2222`) to `.env`, then
      `make attic-inventory BRAIN_HOST=<attic-ip>`.
- [ ] **Phase 4 appliance**: review & run `scripts/windows/setup-attic.ps1` as admin (Task
      Scheduler boot job, networking mode, firewall, power plan). Then `make brain-install`,
      `make migrate-data`, robot autostart unit, and `make verify-boot`. All written, none run.

## E. Phase 2 — voice bake-off (multi-day, with the family)
- [ ] Decide how the Grok brain sits behind the voice pipeline. **Open architecture question**
      (FACTS §3): `speech-to-speech --llm_backend responses-api` speaks the OpenAI *Responses*
      API, but our brain exposes `/v1/chat/completions`. Verify `speech-to-speech --help` live;
      either add a `/v1/responses` shim to the brain or use a chat-completions backend flag.
- [ ] Run one day on Candidate A (local cascade) and one on Candidate B (hosted realtime);
      pick a TTS voice with the family; set `VOICE_BACKEND` + pin the voice in `.env`.
