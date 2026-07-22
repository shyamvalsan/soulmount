#!/usr/bin/env bash
# init_data.sh — build $SOULMOUNT_DATA_DIR from templates/ and walk the owner
# through USER.md + .leakcheck-terms, then `git init` locally (SPEC §6.1).
# INTERACTIVE — never invents personal data (guardrail 12). Idempotent-ish: refuses
# to clobber an existing dir unless you confirm.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
source "$HERE/lib.sh"; load_env

DEST="${SOULMOUNT_DATA_DIR:-$HOME/soulmount-data}"
info "data dir: $DEST"

if [ -e "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  warn "$DEST already exists and is non-empty."
  confirm "Fill/refresh USER.md + .leakcheck-terms in place (does NOT overwrite existing content)?" || { warn "aborted"; exit 0; }
else
  info "creating $DEST from templates/"
  run mkdir -p "$DEST"
  run cp -rn "$ROOT/templates/soul"   "$DEST/soul"
  run cp -rn "$ROOT/templates/inner"  "$DEST/inner"
  run cp -rn "$ROOT/templates/memory" "$DEST/memory"
  run cp -n  "$ROOT/templates/leakcheck-terms.example" "$DEST/.leakcheck-terms"
fi

echo
info "Now fill these IN A TEXT EDITOR (this script won't write personal data for you):"
echo "  - $DEST/soul/USER.md   (members, languages, learn-vs-never; set the robot's name in SOUL.md)"
echo "  - $DEST/soul/SOUL.md   (<robot name>, <city, country>, household block)"
echo "  - $DEST/soul/HOUSE.md  (quiet hours, volume ceiling, <child> references)"
echo "  - $DEST/.leakcheck-terms  (every household-identifying string, one per line)"
echo
confirm "Open USER.md in \$EDITOR now?" && "${EDITOR:-nano}" "$DEST/soul/USER.md" || true
confirm "Open .leakcheck-terms now?" && "${EDITOR:-nano}" "$DEST/.leakcheck-terms" || true

if [ ! -d "$DEST/.git" ]; then
  info "git init (local; no remote — adding one is your choice, never the default)"
  ( cd "$DEST" && git init -q && git add -A && git -c user.name=soulmount -c user.email=soul@localhost commit -q -m "init soul from templates" )
fi
ok "data dir ready. Run 'make leakcheck' to confirm no terms leak into the repo."
