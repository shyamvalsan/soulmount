# soulmount-brain

The brain: a self-hosted, OpenAI-compatible service holding the robot's persona,
household context, file-based memory, budget guard, and inner-life endpoints.
One Python project, four entry points (SPEC §6):

- `soulmount-brain` — the HTTP API (§7.1)
- `soulmount-channels` — the Telegram presence (Phase 5)
- `soulmount-metime` — the nightly me-time runner (Phase 6)
- `soulmount-studio` — the vlog studio (Phase 8, gated)

All personal file I/O resolves through `$SOULMOUNT_DATA_DIR`; nothing personal
lives in this tree. See the repo `README.md` and `SPEC.md`.
