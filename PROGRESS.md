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

### 2026-07-23 01:10 EEST — review round 1 applied
- **Done:** Ran 3 clean-context reviewers (brain / body+scripts / leak+guardrails).
  Validated findings (2 false positives discarded with reasoning). Fixed the lot,
  most important: streaming cost recorded on disconnect (hard-cap safety), stream
  errors → 502, succession letter consumed only on delivery, goodnight-once, leakcheck
  now case-insensitive + git-tracked scan + fail-closed + BRAIN_API_KEY pattern,
  setup-attic boot task runs as the distro user (not SYSTEM), verify_boot actually
  polls, deploy-code no longer wipes robot .env. **48 brain + 12 body + 4 live pass.**
- **Next:** re-run the SAME reviewers (round 2) until clean.
- **Spend so far:** ~$0.06 (one more live test run, 4 grok calls).

### 2026-07-23 01:40 EEST — review round 2 applied
- **Done:** Re-ran all 3 reviewers (same prompts). Fixed a batch incl. a bug I'd
  introduced (identity trim evicted the newest day), cost-fails-closed for unpriced
  providers, me-time consuming the succession letter (no double-delivery), non-blocking
  changelog reconcile, atomic tracked writes, setup-attic SYSTEM→user for BOTH tasks +
  BOM-less .wslconfig, brain bind 0.0.0.0, leakcheck fail-closed on zero-term file,
  body mid-session brain-death recovery. **50 brain + 12 body + 4 live pass.** Design
  decisions (say_privately scope, anti-triangulation, egress backstop, key rotation)
  → MORNING.md for the owner. Accepted single-robot limits → FACTS §7.
- **Next:** review round 3 to confirm convergence, then declare overnight scope done.
- **Spend so far:** ~$0.07 (another live run).

### 2026-07-23 02:30 EEST — review round 3 applied; converging
- **Done:** 3rd re-review. Fixed: cap-overshoot pre-flight max_tokens clamp, ledger
  mtime-cache, goodnight-marker per-reason (bug I introduced in r2), succession letter
  needs ?deliver=true (no inspection burn), baseline seeding on first tracked write,
  root-logger redaction + httpx quiet, Telegram chat-scope gate, leakcheck scans real
  .env secret VALUES (verified against a planted key), setup-attic mirrored capability
  check, verify-boot degraded-exit no longer a make error. **52 brain + 12 body + 4
  live pass.** All 3 reviewers now say "leak-clean & publishable"; residual items are
  owner-decisions (MORNING §F) + accepted single-robot limits (FACTS §7).
- **Next:** round 4 convergence check, then declare overnight scope done.
- **Spend so far:** ~$0.08.

### 2026-07-23 03:30 EEST — review round 4 applied
- **Done:** 4th re-review found 2 real NEW bugs in never-run paths — verify_boot masked
  a broken-but-reachable brain as merely "degraded" (gate would green-light a down
  brain); body startup treated health-OK as ready (bad BRAIN_API_KEY → silent default
  house rules + empty persona). Both fixed. Plus: egress allowlist now enforced in code
  (§9.6, httpx event-hook), atomic DataDir.write, disconnect estimate counts reasoning/
  tool bytes, ledger runner tagged channels-vs-conversation, leakcheck scans .env
  identifier values, several cheap hardenings. **56 brain + 12 body + 4 live pass.**
- **Next:** round 5 — because round 4 was not clean, keep iterating.
- **Spend so far:** ~$0.09.

### 2026-07-23 04:30 EEST — review round 5 applied (a self-caught CRITICAL)
- **Done:** 5th re-review caught that my round-4 verify_boot fix was BROKEN (ATTIC_UP set
  in a command-sub subshell never propagated → g6/g7 could never FAIL). Rewrote so g6/g7
  re-test attic reachability themselves (bounded nc-free _tcp). Also: identity clips
  growable sections (SELF/letter), succession deliver-once by default (?inspect to peek),
  egress hooks on all brain clients, leakcheck git-HISTORY scan (all commits verified
  clean) + bare-username scan, body-app log redaction, setup-attic idempotency/active-
  hours, smoke volume restore. **57 brain + 12 body + 4 live pass; leakcheck tree+history
  clean.** Core (budget/auth/streaming/leak/identity) confirmed sound by all 3 reviewers.
- **Next:** round 6 = final full-scope confirmation (round 5 had a Critical → verify no
  regression in the fixes). Then converge.
- **Spend so far:** ~$0.10.

### 2026-07-23 05:10 EEST — review round 6 applied; loop converged; overnight scope DONE
- **Done:** 6th re-review. Fixed a spec-mandated verify_boot gate-5 gap (distinguish
  "attic off" vs "WSL didn't boot" + the exact §Phase4 diagnosis), an SSH-user regression
  in migrate/inventory, a netsh portproxy bug, clipped INTERESTS in identity, offloaded
  the flock write off the event loop, disabled brain dev-docs, tightened me-time token
  clamp + body mid-session recovery, added 4 body startup-ritual tests, extended
  leakcheck --history to .env values.
- **Convergence call:** brain-core + leak dimensions are CONVERGED (round-6 reviewers:
  "critical guarantees hold" / "clean, production-grade, no active leak"). All remaining
  review churn was in the attic/Phase-4 ops scripts, which CANNOT be executed overnight
  (no attic PC) — their real acceptance is the owner's morning reboot drills (§Phase 4).
  Stopping the full-sweep loop here is the honest call: further blind static-fix cycles on
  un-runnable code have diminishing returns + regression risk (round 5 caught a round-4
  regression). 6 rounds, same prompts, never narrowed; every validated finding fixed.
- **Final state:** 18 commits, leakcheck tree+history green at HEAD. **61 automated tests
  pass** (57 brain offline + 4 live grok-4.5) + **16 body** = 77 total; live-verified:
  OpenAI-client compat (stream+non-stream), persona golden, me-time (journal/doodle/
  SELF/succession). Total model spend for the night ≈ **$0.10**.
- **Next (owner, morning):** MORNING.md checklist — robot key/password + smoke, `make
  init-data`, attic inventory + Phase 4 reboot drills, Phase 2 voice bake-off, and the
  §F design decisions. Rotate the dev OpenRouter key if desired (not leaked; gitignored).

### 2026-07-23 11:50 EEST — morning session (live, supervised)
- **Robot smoke (owner-approved, past quiet hours):** volume lowered 100→60 (verified);
  emotion `cheerful1` played (HTTP 200, motion confirmed). Sound skipped — daemon has NO
  built-in sound files (upload one for the goodnight clip in Phase 2/3). Camera = WebRTC
  :8443, deferred. → Phase 0 motion/volume paths validated live.
- **Owner decisions:** attic still offline (Phase 4 stays deferred); owner runs `make
  init-data` themselves; voice-wiring research (speech-to-speech ↔ brain) launched.
- **Flagged:** commit author is a real name+email on a to-be-public repo (MORNING §F).
- **Next:** owner runs init-data (reset dev dir first); then key install + deploy; voice
  research result → decide the Phase-2 backend + any /v1/responses shim.
