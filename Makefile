# soulmount — every operational task lives here. No bespoke shell knowledge needed.
# `make help` lists targets. Robot/attic-mutating targets announce themselves and
# respect the house rules (quiet hours, one-app, read-only unless supervised).

SHELL := /bin/bash

# Load .env if present so targets see SOULMOUNT_DATA_DIR, REACHY_HOST, etc.
# (.env is gitignored; secrets are never echoed by these targets.)
ifneq (,$(wildcard .env))
include .env
export
endif

# Host resolution: prefer mDNS REACHY_HOST, fall back to REACHY_IP.
REACHY_HOST ?= reachy-mini.local
ROBOT       := $(if $(REACHY_IP),$(REACHY_IP),$(REACHY_HOST))
REACHY_SSH_USER ?= pollen
BRAIN_HOST  ?= 127.0.0.1
BRAIN_PORT  ?= 8100
BRAIN_SSH_PORT ?= 2222
UV          := uv

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Guardrails / hooks ───────────────────────────────────────────────────────
.PHONY: hooks leakcheck
hooks: ## Install the leakcheck pre-commit hook (git core.hooksPath)
	@git config core.hooksPath scripts/git-hooks && echo "pre-commit hook wired."

leakcheck: ## Hard gate: no personal data / secrets in the repo tree
	@bash scripts/leakcheck.sh

leakcheck-history: ## Also scan ALL git history — run once before the first public push
	@bash scripts/leakcheck.sh --history

# ── Environment setup ────────────────────────────────────────────────────────
.PHONY: setup brain-venv sdk-venv
setup: brain-venv hooks ## One-time laptop setup (brain venv + hooks)
	@echo "setup complete."

brain-venv: ## Create/sync the brain venv (Python 3.12)
	@cd brain && $(UV) sync

sdk-venv: ## Create a venv with the Reachy SDK + simulator (Python 3.12)
	@$(UV) venv --python 3.12 .venv-sdk \
	  && $(UV) pip install --python .venv-sdk "reachy-mini[mujoco]"

# ── Phase 0: preflight & smoke (robot-mutating steps are gated/announced) ─────
.PHONY: preflight smoke robot-shell robot-logs sim
preflight: ## Resolve robot, curl daemon, record PREFLIGHT.md (read-only reads)
	@bash scripts/preflight.sh

smoke: ## Live smoke tests (antenna/emotion/sound/camera) — ANNOUNCES, asks first
	@$(UV) run --project brain python scripts/smoke_wiggle.py --host "$(ROBOT)"

sim: ## Run the Reachy simulator on the laptop (MuJoCo), dashboard :8000
	@.venv-sdk/bin/reachy-mini-daemon --sim

robot-shell: ## SSH into the robot
	@ssh $(REACHY_SSH_USER)@$(ROBOT)

robot-logs: ## Tail daemon + app logs on the robot
	@ssh $(REACHY_SSH_USER)@$(ROBOT) 'journalctl -u reachy-mini-daemon -n 100 --no-pager'

# ── Data directory (personal; outside the repo) ──────────────────────────────
.PHONY: init-data migrate-data
init-data: ## Interactive: build $SOULMOUNT_DATA_DIR from templates/, fill USER.md + terms
	@bash scripts/init_data.sh

migrate-data: ## Phase 4 cutover: rsync data dir laptop → WSL, verify, mark laptop read-only
	@bash scripts/migrate_data.sh

# ── Brain service (Phase 1) ──────────────────────────────────────────────────
.PHONY: brain-dev brain-test brain-run
brain-dev: ## Run the brain with autoreload (dev)
	@cd brain && $(UV) run soulmount-brain --reload

brain-run: ## Run the brain (no reload)
	@cd brain && $(UV) run soulmount-brain

brain-test: ## pytest (offline; temp data dir from templates/, no model spend)
	@cd brain && $(UV) run pytest -q -m "not upstream"

brain-test-live: ## pytest incl. real-upstream tests (costs a few cents on BRAIN_MODEL)
	@cd brain && $(UV) run pytest -q

body-test: ## pytest the body app logic (light; no robot SDK needed)
	@cd body && PYTHONPATH=$$PWD/src $(UV) run --no-project \
	  --with pytest --with pytest-asyncio --with respx --with httpx pytest -q

# ── Channels (Phase 5) ───────────────────────────────────────────────────────
.PHONY: channels-run channels-dry
channels-dry: ## Telegram worker, DRY-RUN (no sends) — safe overnight
	@cd brain && $(UV) run soulmount-channels --dry-run

channels-run: ## Telegram worker, live (needs TELEGRAM_* in .env)
	@cd brain && $(UV) run soulmount-channels

# ── Me time (Phase 6) ────────────────────────────────────────────────────────
.PHONY: metime-run succession
metime-run: ## Run one me-time session now (respects budget + leftover allowance)
	@cd brain && $(UV) run soulmount-metime

succession: ## Write a succession letter when BRAIN_MODEL changes. Dry run: `make succession ARGS=--dry-run`
	@cd brain && $(UV) run soulmount-metime succession $(ARGS)

# ── Deploy to the robot (Phase 3/4) ──────────────────────────────────────────
.PHONY: deploy deploy-code robot-restart
deploy: ## Full deploy of body/ to the robot (rsync → pip install -e → verify via dashboard)
	@bash scripts/deploy.sh full
deploy-code: ## Fast path: rsync body/ code only
	@bash scripts/deploy.sh code
robot-restart: ## Stop the running app (one-app rule) and start soulmount via REST
	@bash scripts/deploy.sh restart

# ── Appliance (Phase 4) ──────────────────────────────────────────────────────
.PHONY: brain-install verify-boot attic-inventory
brain-install: ## Install systemd units for brain/channels/metime inside WSL (needs BRAIN_HOST)
	@bash scripts/brain_install.sh
verify-boot: ## THE acceptance gate — PASS/FAIL table with timings (exit 2=degraded is OK)
	@bash scripts/verify_boot.sh || { ec=$$?; [ $$ec -eq 2 ] && exit 0 || exit $$ec; }
attic-inventory: ## Read-only inventory of the attic WSL host (needs BRAIN_HOST + ssh)
	@bash scripts/attic_inventory.sh

# ── Morning supervised helpers (robot leaves read-only) ──────────────────────
ARGS ?=
.PHONY: robot-keyinstall robot-rotate-pass robot-set-volume
robot-keyinstall: ## Install the laptop SSH key on the robot (prompts for factory password)
	@bash scripts/robot_admin.sh keyinstall
robot-rotate-pass: ## Rotate the factory password (owner-approved)
	@bash scripts/robot_admin.sh rotate-pass
robot-set-volume: ## Set the daemon volume to the HOUSE.md ceiling
	@bash scripts/robot_admin.sh set-volume
