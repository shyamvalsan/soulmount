#!/usr/bin/env bash
# migrate_data.sh — Phase 4 cutover: move the data dir laptop -> attic WSL, verify,
# then mark the laptop copy read-only (single source of truth from then on). §6.1.
# SUPERVISED (attic offline overnight — see MORNING.md).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/lib.sh"; load_env

SRC="${SOULMOUNT_DATA_DIR:?set SOULMOUNT_DATA_DIR}"
ATTIC="${BRAIN_HOST:?set BRAIN_HOST (attic reserved IP)}"
SSHP="${BRAIN_SSH_PORT:-2222}"
USER_NAME="${REACHY_SSH_USER:-$USER}"
DEST="\$HOME/soulmount-data"   # WSL ext4, never under /mnt/c (§4.1)

confirm "Migrate data dir $SRC -> $USER_NAME@$ATTIC:$DEST (WSL ext4)?" || { warn "aborted"; exit 0; }

info "rsync -> attic WSL"
run rsync -az -e "ssh -p $SSHP" "$SRC/" "$USER_NAME@$ATTIC:$DEST/"

info "verify file counts + git history"
local_count="$(find "$SRC" -type f -not -path '*/.git/*' | wc -l)"
remote_count="$(ssh -p "$SSHP" "$USER_NAME@$ATTIC" "find $DEST -type f -not -path '*/.git/*' | wc -l")"
echo "  local=$local_count remote=$remote_count"
[ "$local_count" = "$remote_count" ] || { err "file count mismatch"; exit 1; }
ssh -p "$SSHP" "$USER_NAME@$ATTIC" "cd $DEST && git log --oneline | head -3" || warn "no git history on remote"

info "marking the laptop copy read-only (single source of truth is now the attic)"
run chmod -R a-w "$SRC"
ok "migration complete. Point .env SOULMOUNT_DATA_DIR to the WSL path on the attic."
