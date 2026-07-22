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
