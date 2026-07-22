#!/usr/bin/env bash
# leakcheck.sh — hard gate: no household-identifying data or secrets in the repo.
# A leak is a stop-everything bug (SPEC §6.1, guardrail 5). Wired as a pre-commit
# hook in Phase 0 and run by `make leakcheck` before every commit.
#
# Scans committable files for:
#   1) every term in $SOULMOUNT_DATA_DIR/.leakcheck-terms (CASE-INSENSITIVE, substring)
#   2) secret/token patterns (API keys, bot tokens, bearer/BRAIN_API_KEY hex)
# Fails closed: if a repo .env exists (owner's box) but no terms file resolves, the
# term gate BLOCKS rather than silently passing.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

if REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then :; else
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$REPO_ROOT"

# Resolve SOULMOUNT_DATA_DIR from env, else from .env (value only — never echoed).
DATA_DIR="${SOULMOUNT_DATA_DIR:-}"
HAVE_ENV=0
if [ -f .env ]; then HAVE_ENV=1; fi
if [ -z "$DATA_DIR" ] && [ "$HAVE_ENV" = 1 ]; then
  DATA_DIR="$(sed -n 's/^SOULMOUNT_DATA_DIR=//p' .env | head -n1 | tr -d '"'"'"'')"
fi

# Scan set = what could actually be committed: tracked + untracked-not-ignored.
# This includes .env.example (tracked) and EXCLUDES gitignored files like the real
# .env (which legitimately holds secrets). Falls back to find before `git init`.
declare -a SCAN_FILES
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -d '' -t SCAN_FILES < <(git ls-files --cached --others --exclude-standard -z)
else
  mapfile -t SCAN_FILES < <(find . -type f \
    -not -path './.git/*' -not -path '*/.venv/*' -not -path '*/node_modules/*' \
    -not -path '*/__pycache__/*' -not -name '.env' 2>/dev/null | sed 's|^\./||')
fi
[ "${#SCAN_FILES[@]}" -gt 0 ] || { echo -e "${GREEN}✓ leakcheck: nothing to scan${NC}"; exit 0; }

fail=0

# ── 1) Personal terms (case-insensitive) ─────────────────────────────────────
TERMS_FILE="${DATA_DIR:+$DATA_DIR/.leakcheck-terms}"
terms_missing() {
  # Owner's box (has .env) → require real terms; else clean-room contributor → allow.
  if [ "$HAVE_ENV" = 1 ]; then
    echo -e "${RED}✗ leakcheck: .env present but no household terms defined.${NC}"
    echo -e "${RED}  Run 'make init-data' and fill \$SOULMOUNT_DATA_DIR/.leakcheck-terms${NC}"
    echo -e "${RED}  (names, city, chat IDs…). Refusing to pass the term gate with 0 terms.${NC}"
    fail=1
  else
    echo -e "${YELLOW}⚠ No household terms (clean-room) — term scan skipped; secret scan only.${NC}"
  fi
}

if [ -n "$TERMS_FILE" ] && [ -f "$TERMS_FILE" ]; then
  TMP_TERMS="$(mktemp)"; trap 'rm -f "$TMP_TERMS"' EXIT
  grep -vE '^\s*(#|$)' "$TERMS_FILE" | sed 's/[[:space:]]*$//' > "$TMP_TERMS" || true
  if [ -s "$TMP_TERMS" ]; then
    if hits="$(grep -rInHFi -f "$TMP_TERMS" -- "${SCAN_FILES[@]}" 2>/dev/null)"; then
      echo -e "${RED}✗ LEAK: household terms found in the repo:${NC}"
      echo "$hits" | sed 's/^/    /'
      fail=1
    fi
  else
    # File exists but every line is a comment/blank → NOT configured. Fail closed
    # on the owner's box (this was a silent-green hole right after init-data).
    terms_missing
  fi
else
  terms_missing
fi

# ── 2) Secret / token patterns (redacted in output) ──────────────────────────
SECRET_PATTERNS=(
  'sk-or-v[0-9]-[A-Za-z0-9]{16,}'                 # OpenRouter
  'sk-ant-[A-Za-z0-9_-]{20,}'                     # Anthropic
  'sk-[A-Za-z0-9]{32,}'                           # OpenAI-style
  '[0-9]{8,10}:[A-Za-z0-9_-]{35}'                 # Telegram bot token
  'AKIA[0-9A-Z]{16}'                              # AWS
  'AIza[0-9A-Za-z_-]{35}'                         # Google API key
  'GOCSPX-[A-Za-z0-9_-]{20,}'                     # Google OAuth client secret (YouTube)
  'BSA[A-Za-z0-9_-]{24,}'                         # Brave Search API key
  'ghp_[0-9A-Za-z]{36}'                           # GitHub PAT
  'BRAIN_API_KEY[[:space:]]*[=:][[:space:]]*[0-9a-fA-F]{32,}'  # our bearer (scoped)
  'Bearer[[:space:]]+[0-9a-fA-F]{48,}'            # bare-hex bearer (avoids uv.lock sha256:)
)
for pat in "${SECRET_PATTERNS[@]}"; do
  if hits="$(grep -rInHE "$pat" -- "${SCAN_FILES[@]}" 2>/dev/null)"; then
    echo -e "${RED}✗ LEAK: secret-like token pattern in the repo:${NC}"
    echo "$hits" | sed -E "s/${pat}/***REDACTED-SECRET***/g" | sed 's/^/    /'
    fail=1
  fi
done

# ── 3) The ACTUAL values from .env — secrets (any format the patterns miss, e.g. a
#        bare-hex BRAIN_API_KEY) AND household identifiers (home-dir path w/ username,
#        LAN IP, chat IDs, timezone) that aren't secret keys. Never printed. ──
if [ "$HAVE_ENV" = 1 ]; then
  _scan_env_value() {  # $1=value $2=label
    local v="$1" label="$2"
    [ -n "$v" ] || return 0
    case "$v" in 127.0.0.1 | 0.0.0.0 | localhost | reachy-mini.local | UTC) return 0 ;; esac
    if hits="$(grep -rInHF -- "$v" "${SCAN_FILES[@]}" 2>/dev/null)"; then
      echo -e "${RED}✗ LEAK: a $label value from .env appears in a committable file:${NC}"
      echo "${hits//"$v"/***REDACTED-ENV-$label***}" | sed 's/^/    /'
      fail=1
    fi
  }
  while IFS='=' read -r k v; do
    v="$(printf '%s' "$v" | tr -d "\"'" | tr -d '[:space:]')"
    case "$k" in
      *KEY | *TOKEN | *SECRET | *PASSWORD)
        [ "${#v}" -ge 16 ] && _scan_env_value "$v" "SECRET" ;;
      SOULMOUNT_DATA_DIR | REACHY_IP | BRAIN_HOST | TELEGRAM_FAMILY_CHAT_ID | BUDGET_TZ)
        [ "${#v}" -ge 7 ] && _scan_env_value "$v" "IDENTIFIER" ;;
      TELEGRAM_ALLOWED_USER_IDS)
        IFS=',' read -ra _ids <<< "$v"
        for _id in "${_ids[@]}"; do [ "${#_id}" -ge 6 ] && _scan_env_value "$_id" "IDENTIFIER"; done ;;
    esac
  done < <(grep -vE '^\s*(#|$)' .env)
fi

if [ "$fail" -ne 0 ]; then
  echo -e "${RED}━━ leakcheck FAILED — do not commit. Move content into \$SOULMOUNT_DATA_DIR. ━━${NC}"
  exit 1
fi
echo -e "${GREEN}✓ leakcheck passed${NC}"
