# soulmount-body

The Reachy Mini presence: a brain-connected fork of the official conversation app,
kept to a minimal, enumerated diff (see `DIFF.md`). Installs as a `reachy_mini_apps`
entry point (`soulmount`). Core logic is SDK-light and unit-tested off-robot; the
Reachy SDK is the `[robot]` extra installed into `/venvs/apps_venv` on the robot.

The conversation turn itself is a voice-backend seam wired at the Phase 2 bake-off
(the upstream app is HF-realtime-only). Everything else — startup ritual, brain-down
droop/retry, sleep handling, house-rule enforcement, instant-ack — is implemented.
