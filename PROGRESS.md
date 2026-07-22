# PROGRESS.md — unattended build heartbeat

Append-only. ~Every 30 min or per acceptance item: done / next / blockers / spend.

---

### 2026-07-22 23:35 EEST — kickoff
- **Done:** Read SPEC top-to-bottom. Ground-truthed the live robot read-only (quiet hours):
  daemon healthy, no app running, **no battery API** (resolves §4), volume=100, emotions
  live in HF dataset `pollen-robotics/reachy-mini-emotions-library`. Verified OpenRouter
  `usage.cost` inline readback + grok-4.5/4.20 slugs. Confirmed conversation app is now
  HF-realtime-only (major Phase 3 divergence — see FACTS §3).
- **Owner decisions (pre-sleep):** breadth per §2.1 · attic PC unavailable → defer Phase 4 ·
  test on grok-4.5 within caps, build budget guard early.
- **Next:** finish scaffold (git, hooks, leakcheck, tracking docs), then Phase 1 brain.
- **Blockers:** none (attic + robot-mutating + Phase 2/4 deferred to MORNING.md by design).
- **Spend so far:** $0.00 (all reads were free: OpenRouter /models, robot GETs).

### 2026-07-23 00:15 EEST — Phase 1 brain complete & tested
- **Done:** Full scaffold committed (leakcheck hook live). Brain (Phase 1) committed:
  provider adapter w/ exact `usage.cost` readback, §7.7 budget guard + ledger + sleep
  state, §7.2 identity compilation + changelog attribution, all §7.1 endpoints.
  **32 tests pass** incl. 4 live grok-4.5 tests (OpenAI-client compat non-stream +
  stream, persona golden) — Phase 1 acceptance list is green, including "against real
  upstream". Two clean commits.
- **Next:** Phase 6 me-time runner (in-process, builds on brain modules) → Phase 5
  channels (dry-run) → Phase 3 body fork vs sim → ops scripts → README.
- **Blockers:** none. (Attic/Phase-4, robot-mutating, Phase-2 voice → MORNING.md.)
- **Spend so far:** ~$0.02 (4 short live grok-4.5 calls in the upstream test).

### 2026-07-23 00:25 EEST — Phases 5 & 6 done, live-verified
- **Done:** Phase 6 me-time committed + **run live**: robot journaled, made a valid SVG
  doodle, wrote a reflective SELF.md (all attributed in CHANGELOG); succession dry-run
  letter written and delivered-once into the next identity. Phase 5 channels committed:
  allowlist, DM/family routing, asleep-once notice, say_privately outbox, proactive
  cap→journal, /relay. **40 offline tests + 4 live = 44 total, all green.** Created a
  throwaway dev data dir (~/soulmount-data) from templates for live runs.
- **Next:** Phase 3 body app (fork scaffold vs sim, brain-wired) → ops scripts →
  README → external reviewers.
- **Blockers:** Phase 3 voice loop can't fully run overnight — conversation app is
  HF-realtime-only; the Grok-behind-voice wiring is a MORNING decision (FACTS §3).
  Building the body app's non-voice behaviours + brain integration + house enforcement.
- **Spend so far:** ~$0.05 (me-time \$0.018 + succession \$0.009 + upstream tests).

### 2026-07-23 00:40 EEST — Phase 3 body, ops scripts, README done
- **Done:** Body app (Phase 3) committed — brain connection, startup ritual, sleep
  handling, HOUSE enforcement, instant-ack, voice seam; 12 tests + off-robot lifecycle
  smoke. All ops scripts written (verify_boot gate, preflight, deploy, robot_admin,
  brain_install, init/migrate data, attic_inventory, setup-attic.ps1). `make preflight`
  ran live: **81 emotions enumerated, battery=none, volume=100** — matches research +
  validates bodystate. README written (owner can re-run everything). Added `/v1/house`.
  7 clean commits total; leakcheck green throughout.
- **Next:** external reviewers over the whole change; fix findings; iterate to
  production grade. Then final heartbeat.
- **Blockers:** none for the overnight scope. MORNING.md holds the supervised queue.
- **Spend so far:** ~$0.05 (no new model spend this block; scripts/docs only).
