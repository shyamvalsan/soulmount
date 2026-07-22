#!/usr/bin/env bash
# leakcheck.sh — hard gate: no household-identifying data or secrets in the repo.
# A leak is a stop-everything bug (SPEC §6.1, guardrail 5). Wired as a pre-commit
# hook in Phase 0 and run by `make leakcheck` before every commit.
#
# Scans the repo tree for:
#   1) every term listed in $SOULMOUNT_DATA_DIR/.leakcheck-terms (case-insensitive)
#   2) obvious secret/token patterns (API keys, bot tokens, bearer tokens)
# Exits non-zero on the first category that finds anything.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; GRAY='\033[0;90m'; NC='\033[0m'

# Repo root: prefer git, fall back to this script's parent dir.
if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then :; else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT"

# Resolve SOULMOUNT_DATA_DIR from the environment, else from .env (value only —
# we never echo secrets).
DATA_DIR="${SOULMOUNT_DATA_DIR:-}"
if [ -z "$DATA_DIR" ] && [ -f .env ]; then
  DATA_DIR="$(sed -n 's/^SOULMOUNT_DATA_DIR=//p' .env | head -n1 | tr -d '"'"'"'')"
fi

# Files to scan: everything tracked/untracked EXCEPT ignored + noise dirs. Using
# a find-based list keeps this working before `git init` too.
mapfile -t SCAN_FILES < <(
  find . -type f \
    -not -path './.git/*' \
    -not -path './.venv/*' -not -path '*/.venv/*' \
    -not -path '*/node_modules/*' \
    -not -path '*/__pycache__/*' \
    -not -path '*/.pytest_cache/*' -not -path '*/.ruff_cache/*' \
    -not -path '*/dist/*' -not -path '*/build/*' \
    -not -name '.env' -not -name '.env.*' \
    2>/dev/null | sed 's|^\./||'
)
# Never scan the data dir even if it sits under the repo root by accident.
if [ -n "$DATA_DIR" ]; then
  REAL_DATA="$(cd "$DATA_DIR" 2>/dev/null && pwd || true)"
  if [ -n "$REAL_DATA" ]; then
    FILTERED=(); for f in "${SCAN_FILES[@]}"; do
      case "$(cd "$(dirname "$f")" 2>/dev/null && pwd)/" in "$REAL_DATA"/*) continue;; esac
      FILTERED+=("$f")
    done
    SCAN_FILES=("${FILTERED[@]}")
  fi
fi

fail=0

# ── 1) Personal terms ────────────────────────────────────────────────────────
TERMS_FILE="${DATA_DIR:+$DATA_DIR/.leakcheck-terms}"
if [ -n "$TERMS_FILE" ] && [ -f "$TERMS_FILE" ]; then
  # Strip comments/blank lines into a temp pattern file.
  TMP_TERMS="$(mktemp)"; trap 'rm -f "$TMP_TERMS"' EXIT
  grep -vE '^\s*(#|$)' "$TERMS_FILE" | sed 's/[[:space:]]*$//' > "$TMP_TERMS" || true
  if [ -s "$TMP_TERMS" ] && [ "${#SCAN_FILES[@]}" -gt 0 ]; then
    if hits="$(grep -rInHF -f "$TMP_TERMS" -- "${SCAN_FILES[@]}" 2>/dev/null)"; then
      echo -e "${RED}✗ LEAK: household terms found in the repo:${NC}"
      echo "$hits" | sed 's/^/    /'
      fail=1
    fi
  fi
else
  echo -e "${YELLOW}⚠ No .leakcheck-terms found (SOULMOUNT_DATA_DIR unset or init-data not run).${NC}"
  echo -e "${YELLOW}  Term-based scan skipped; running secret-pattern scan only.${NC}"
fi

# ── 2) Secret / token patterns ───────────────────────────────────────────────
# Redact the matched value in output so leakcheck itself never prints a secret.
SECRET_PATTERNS=(
  'sk-or-v[0-9]-[A-Za-z0-9]{16,}'           # OpenRouter key
  'sk-ant-[A-Za-z0-9_-]{20,}'               # Anthropic key
  'sk-[A-Za-z0-9]{32,}'                     # OpenAI-style key
  '[0-9]{8,10}:[A-Za-z0-9_-]{35}'           # Telegram bot token
  'AKIA[0-9A-Z]{16}'                        # AWS access key id
  'AIza[0-9A-Za-z_-]{35}'                   # Google API key
  'ghp_[0-9A-Za-z]{36}'                     # GitHub PAT
)
if [ "${#SCAN_FILES[@]}" -gt 0 ]; then
  for pat in "${SECRET_PATTERNS[@]}"; do
    if hits="$(grep -rInHE "$pat" -- "${SCAN_FILES[@]}" 2>/dev/null)"; then
      # Redact the secret body, keep file:line.
      redacted="$(echo "$hits" | sed -E "s/${pat}/***REDACTED-SECRET***/g")"
      echo -e "${RED}✗ LEAK: secret-like token pattern in the repo:${NC}"
      echo "$redacted" | sed 's/^/    /'
      fail=1
    fi
  done
fi

if [ "$fail" -ne 0 ]; then
  echo -e "${RED}━━ leakcheck FAILED — do not commit. Move the content into \$SOULMOUNT_DATA_DIR. ━━${NC}"
  exit 1
fi
echo -e "${GREEN}✓ leakcheck passed${NC}"
