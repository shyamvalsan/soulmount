"""Budget guard, ledger, and sleep state (SPEC §7.7).

The brain is the single chokepoint for every model call, so the hard caps are
enforced here, mechanically. Hard means hard: no runtime override, no top-up.
Changing a cap is editing .env and restarting (an owner-only act).

Clock is injectable (``now_fn``) so rollover behaviour can be tested by injecting
time, per the Phase 1 acceptance list.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from .config import Settings
from .datadir import DataDir
from .logging_utils import get_logger
from .provider import Usage

log = get_logger("soulmount.budget")

# Cap the graceful "goodnight" turn so at most one short completion fits the reserve.
GOODNIGHT_MAX_TOKENS = 256


@dataclass
class BudgetDecision:
    state: str                     # "awake" | "goodnight" | "asleep"
    reason: str | None             # "daily" | "monthly" | None
    wake_at: datetime | None
    remaining_today_usd: float
    remaining_month_usd: float
    max_tokens_hint: int | None    # set in "goodnight" to force a short turn

    @property
    def asleep(self) -> bool:
        return self.state == "asleep"


class BudgetGuard:
    def __init__(
        self,
        settings: Settings,
        datadir: DataDir,
        now_fn: Callable[[], datetime] | None = None,
    ):
        self.settings = settings
        self.dd = datadir
        self._now = now_fn or (lambda: datetime.now(settings.timezone))

    # ── Time helpers ──────────────────────────────────────────────────────────
    def now(self) -> datetime:
        return self._now()

    def _month_key(self, when: datetime) -> str:
        return f"{when.year:04d}-{when.month:02d}"

    def _next_midnight(self, when: datetime) -> datetime:
        tomorrow = (when + timedelta(days=1)).date()
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=when.tzinfo)

    def _first_of_next_month(self, when: datetime) -> datetime:
        if when.month == 12:
            y, m = when.year + 1, 1
        else:
            y, m = when.year, when.month + 1
        return datetime(y, m, 1, tzinfo=when.tzinfo)

    def _days_left_in_month(self, when: datetime) -> int:
        last = calendar.monthrange(when.year, when.month)[1]
        return max(1, last - when.day + 1)  # includes today

    # ── Ledger reads ──────────────────────────────────────────────────────────
    def _iter_ledger(self, month_key: str):
        f = self.dd.ledger_file(month_key)
        if not f.exists():
            return
        for line in f.read_text("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # tolerate a partially-written last line

    def spent_month(self, when: datetime | None = None) -> float:
        when = when or self.now()
        return round(sum(float(e.get("usd") or 0.0) for e in self._iter_ledger(self._month_key(when))), 8)

    def spent_today(self, when: datetime | None = None) -> float:
        when = when or self.now()
        today = when.date().isoformat()
        total = 0.0
        for e in self._iter_ledger(self._month_key(when)):
            ts = str(e.get("ts") or "")
            if ts[:10] == today:
                total += float(e.get("usd") or 0.0)
        return round(total, 8)

    def remaining_today_usd(self, when: datetime | None = None) -> float:
        return round(self.settings.budget_daily_usd - self.spent_today(when), 8)

    def remaining_month_usd(self, when: datetime | None = None) -> float:
        return round(self.settings.budget_monthly_usd - self.spent_month(when), 8)

    # ── The decision (§7.7) ───────────────────────────────────────────────────
    def decide(self, when: datetime | None = None) -> BudgetDecision:
        when = when or self.now()
        rem_day = self.remaining_today_usd(when)
        rem_month = self.remaining_month_usd(when)
        reserve = self.settings.budget_goodnight_reserve_usd
        effective = min(rem_day, rem_month)

        if effective <= 0:
            # Monthly cap dominates (longer sleep) when both are blown.
            if rem_month <= 0:
                return BudgetDecision("asleep", "monthly", self._first_of_next_month(when),
                                      rem_day, rem_month, None)
            return BudgetDecision("asleep", "daily", self._next_midnight(when),
                                  rem_day, rem_month, None)

        if effective <= reserve:
            # Into the reserve — permit ONE final short completion, then sleep.
            reason = "monthly" if rem_month <= reserve else "daily"
            wake = self._first_of_next_month(when) if reason == "monthly" else self._next_midnight(when)
            if self._goodnight_used(when):
                return BudgetDecision("asleep", reason, wake, rem_day, rem_month, None)
            return BudgetDecision("goodnight", reason, None, rem_day, rem_month, GOODNIGHT_MAX_TOKENS)

        return BudgetDecision("awake", None, None, rem_day, rem_month, None)

    # Goodnight is granted at most once per day (SPEC §7.7: "one final short completion").
    def _goodnight_path(self):
        return self.dd.path("ops", "state", "goodnight.json")

    def _goodnight_used(self, when: datetime) -> bool:
        raw = self.dd.read(self._goodnight_path())
        if not raw:
            return False
        try:
            return json.loads(raw).get("date") == when.date().isoformat()
        except json.JSONDecodeError:
            return False

    def mark_goodnight_used(self, when: datetime | None = None) -> None:
        when = when or self.now()
        self.dd.write(self._goodnight_path(), json.dumps({"date": when.date().isoformat()}))

    # ── Ledger writes ─────────────────────────────────────────────────────────
    def record(self, runner: str, model: str, usage: Usage, when: datetime | None = None) -> dict:
        when = when or self.now()
        entry = {
            "ts": when.isoformat(),
            "runner": runner,
            "model": model,
            "tokens": usage.total_tokens,
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "cached_tokens": usage.cached_tokens,
            "usd": round(usage.cost_usd, 8),
            "estimated": usage.estimated,
        }
        self.dd.append(self.dd.ledger_file(self._month_key(when)), json.dumps(entry) + "\n")
        return entry

    # ── Inner-life leftover allowance (§7.7) ──────────────────────────────────
    def inner_allowance_usd(self, per_activity_cap_usd: float, when: datetime | None = None) -> float:
        """min(activity cap, today's remaining − reserve, remaining month ÷ days left).

        Inner life runs on the day's leftovers and can never starve tomorrow's
        conversation or breach the month.
        """
        when = when or self.now()
        rem_day = self.remaining_today_usd(when) - self.settings.budget_goodnight_reserve_usd
        fair_month_share = self.remaining_month_usd(when) / self._days_left_in_month(when)
        allowance = min(per_activity_cap_usd, rem_day, fair_month_share)
        return round(max(0.0, allowance), 8)

    # ── Health summary (§7.1 /health) ─────────────────────────────────────────
    def health_summary(self, when: datetime | None = None) -> dict:
        when = when or self.now()
        d = self.decide(when)
        return {
            "state": d.state,
            "remaining_today_usd": round(d.remaining_today_usd, 6),
            "remaining_month_usd": round(d.remaining_month_usd, 6),
            "daily_cap_usd": self.settings.budget_daily_usd,
            "monthly_cap_usd": self.settings.budget_monthly_usd,
            "wake_at": d.wake_at.isoformat() if d.wake_at else None,
        }
