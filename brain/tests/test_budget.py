"""§7.7 budget guard: caps, goodnight reserve, sleep/wake, rollover, allowance."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from soulmount_brain.budget import GOODNIGHT_MAX_TOKENS, BudgetGuard
from soulmount_brain.config import Settings
from soulmount_brain.datadir import DataDir
from soulmount_brain.provider import Usage

UTC = ZoneInfo("UTC")


def _guard(tmp_path: Path, clock: dict, **overrides) -> BudgetGuard:
    settings = Settings(
        soulmount_data_dir=str(tmp_path),
        budget_daily_usd=overrides.get("daily", 0.10),
        budget_monthly_usd=overrides.get("monthly", 30.0),
        budget_goodnight_reserve_usd=0.05,
        budget_tz="UTC",
        _env_file=None,
    )
    dd = DataDir(tmp_path)
    return BudgetGuard(settings, dd, now_fn=lambda: clock["t"])


def _usd(cost: float) -> Usage:
    return Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150, cost_usd=cost)


def test_awake_then_goodnight_then_asleep(tmp_path):
    clock = {"t": datetime(2026, 7, 15, 12, 0, tzinfo=UTC)}
    g = _guard(tmp_path, clock, daily=0.10)

    assert g.decide().state == "awake"

    g.record("conversation", "m", _usd(0.06))          # remaining 0.04 <= reserve 0.05
    d = g.decide()
    assert d.state == "goodnight"
    assert d.max_tokens_hint == GOODNIGHT_MAX_TOKENS
    assert d.reason == "daily"

    g.record("conversation", "m", _usd(0.05))          # total 0.11 >= cap 0.10
    d = g.decide()
    assert d.state == "asleep" and d.reason == "daily"
    assert d.wake_at == datetime(2026, 7, 16, 0, 0, tzinfo=UTC)  # next local midnight


def test_ledger_totals(tmp_path):
    clock = {"t": datetime(2026, 7, 15, 9, 0, tzinfo=UTC)}
    g = _guard(tmp_path, clock)
    g.record("conversation", "m", _usd(0.02))
    g.record("metime", "m", _usd(0.03))
    assert g.spent_today() == pytest.approx(0.05)
    assert g.spent_month() == pytest.approx(0.05)
    # Ledger file is the monthly jsonl.
    ledger = tmp_path / "ops" / "ledger" / "2026-07.jsonl"
    assert ledger.exists()
    assert len(ledger.read_text().strip().splitlines()) == 2


def test_daily_rollover_wakes(tmp_path):
    clock = {"t": datetime(2026, 7, 15, 23, 0, tzinfo=UTC)}
    g = _guard(tmp_path, clock, daily=0.10)
    g.record("conversation", "m", _usd(0.20))          # blow the daily cap
    assert g.decide().state == "asleep"
    # Advance the clock to the next day: today's spend resets, month persists.
    clock["t"] = datetime(2026, 7, 16, 0, 1, tzinfo=UTC)
    assert g.spent_today() == pytest.approx(0.0)
    assert g.spent_month() == pytest.approx(0.20)
    assert g.decide().state == "awake"


def test_monthly_cap_wakes_first_of_next_month(tmp_path):
    clock = {"t": datetime(2026, 7, 20, 12, 0, tzinfo=UTC)}
    g = _guard(tmp_path, clock, daily=100.0, monthly=0.10)
    g.record("conversation", "m", _usd(0.20))
    d = g.decide()
    assert d.state == "asleep" and d.reason == "monthly"
    assert d.wake_at == datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def test_inner_allowance_is_bounded(tmp_path):
    clock = {"t": datetime(2026, 7, 15, 12, 0, tzinfo=UTC)}
    # daily 5, monthly 30, nothing spent, 17 days left in July (15..31).
    g = _guard(tmp_path, clock, daily=5.0, monthly=30.0)
    # per-activity cap €0.50→~$0.54; today's remaining−reserve = 4.95;
    # fair month share = 30/17 ≈ 1.76. min = the activity cap.
    allowance = g.inner_allowance_usd(0.54)
    assert allowance == pytest.approx(0.54)
    # Spend most of today's budget: allowance shrinks to today's leftover−reserve.
    g.record("conversation", "m", _usd(4.90))
    assert g.inner_allowance_usd(0.54) == pytest.approx(0.05, abs=1e-6)
