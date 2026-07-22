# CHANGELOG.md

Append-only log of changes to `soul/` and `memory/`, so edits are *seen* rather
than silently experienced as a gap. The brain maintains this by hashing those
files at each identity compile and attributing changes (via-endpoint = the
robot itself; otherwise "edited externally, likely by the household").
