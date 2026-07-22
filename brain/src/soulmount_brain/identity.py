"""Identity compilation (SPEC §7.2).

Concatenates, in order, each under a labelled heading, within IDENTITY_MAX_TOKENS:
  1. SOUL.md (prime directive first)
  2. SELF.md
  3. USER.md, then HOUSE.md (marked hard)
  4. Honest self-facts (live)
  5. Body state (live daemon + budget + quiet-hours)
  6. MEMORY.md, last MEMORY_DAILY_DAYS daily files, INTERESTS.md
  7. Last 5 CHANGELOG lines (so external edits are seen)
Plus: the latest succession letter, delivered exactly once, flagged (§7.5).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .changelog import Changelog
from .config import Settings
from .datadir import DataDir
from .house import House
from .honesty import honest_self_facts
from .logging_utils import get_logger

log = get_logger("soulmount.identity")


def est_tokens(text: str) -> int:
    """Cheap, provider-agnostic token estimate (~4 chars/token)."""
    return math.ceil(len(text) / 4)


@dataclass
class IdentityResult:
    text: str
    soul_version: str
    est_tokens: int


class IdentityCompiler:
    def __init__(
        self,
        settings: Settings,
        dd: DataDir,
        changelog: Changelog,
        now_fn: Callable[[], datetime],
    ):
        self.settings = settings
        self.dd = dd
        self.changelog = changelog
        self._now = now_fn

    def soul_version(self) -> str:
        raw = self.dd.read(self.dd.soul("SOUL.md")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:12] if raw else "unset"

    # ── Succession letter (deliver latest once) ───────────────────────────────
    def _succession_state_path(self):
        return self.dd.path("ops", "state", "succession.json")

    def _delivered_letters(self) -> set[str]:
        raw = self.dd.read(self._succession_state_path())
        if not raw:
            return set()
        try:
            return set(json.loads(raw).get("delivered", []))
        except json.JSONDecodeError:
            return set()

    def _mark_delivered(self, name: str) -> None:
        delivered = self._delivered_letters()
        delivered.add(name)
        self.dd.write(self._succession_state_path(), json.dumps({"delivered": sorted(delivered)}))

    def _pending_letter(self) -> tuple[str, str] | None:
        d = self.dd.path("inner", "letters")
        if not d.is_dir():
            return None
        letters = sorted(d.glob("*-to-successor.md"), key=lambda f: f.name)
        if not letters:
            return None
        latest = letters[-1]
        if latest.name in self._delivered_letters():
            return None
        return latest.name, self.dd.read(latest)

    # ── Body-state block ──────────────────────────────────────────────────────
    def _body_block(self, body_state: dict, budget_summary: dict, house: House) -> str:
        now = self._now()
        quiet = house.in_quiet_hours(now)
        lines = [
            f"- Now: {now.strftime('%A %H:%M')} ({now.strftime('%Y-%m-%d')}). "
            f"Quiet hours are {house.quiet_start.strftime('%H:%M')}–{house.quiet_end.strftime('%H:%M')}; "
            f"right now it is {'QUIET HOURS — no speech/motion/proactivity' if quiet else 'not quiet hours'}.",
        ]
        if body_state.get("online"):
            app = body_state.get("current_app") or "none"
            lines.append(f"- Body: awake={body_state.get('awake')}, current app={app}, "
                         f"volume={body_state.get('volume')}, motors={body_state.get('motor_mode')}.")
            lines.append(f"- Battery: {body_state.get('battery')}.")
            emotions = body_state.get("emotions") or []
            if emotions:
                preview = ", ".join(emotions[:14])
                lines.append(f"- You can: look, nod, tilt, antenna-wiggle, and play emotions "
                             f"(e.g. {preview}{' …' if len(emotions) > 14 else ''} — {len(emotions)} in all).")
        else:
            lines.append(f"- Body: {body_state.get('note', 'offline')}. You are, for now, a voice "
                         "without a body to move — say so honestly if it matters.")
        # Metabolic honesty (§7.2 item 5): remaining budget.
        rt = budget_summary.get("remaining_today_usd")
        rm = budget_summary.get("remaining_month_usd")
        if rt is not None:
            lines.append(f"- Budget left today: ${rt:.2f}; this month: ${rm:.2f}. When it runs low, "
                         "brevity is fine and honest — you don't owe anyone endless words.")
        return "\n".join(lines)

    # ── Compile ───────────────────────────────────────────────────────────────
    def compile(
        self,
        *,
        body_state: dict,
        budget_summary: dict,
        house: House,
        slim: bool = False,
    ) -> IdentityResult:
        # Detect external edits first, so section 7 reflects reality this compile.
        self.changelog.seed_baseline_if_missing()
        self.changelog.reconcile()

        max_tokens = (
            self.settings.realtime_identity_max_tokens if slim else self.settings.identity_max_tokens
        )

        def section(title: str, body: str) -> str:
            body = (body or "").strip()
            return f"## {title}\n{body}\n" if body else ""

        soul = self.dd.read(self.dd.soul("SOUL.md"))
        parts: list[str] = [
            "# Who you are (identity compiled fresh each session)\n",
            section("Purpose and soul (SOUL.md)", soul),
            section("Your own account of yourself (SELF.md)", self.dd.read(self.dd.soul("SELF.md"))),
            section("The household — charter (USER.md)", self.dd.read(self.dd.soul("USER.md"))),
            section("House rules — THESE ARE HARD (HOUSE.md)", self.dd.read(self.dd.soul("HOUSE.md"))),
            section("Honest facts about your situation", honest_self_facts(self.settings)),
        ]

        # A pending succession letter is delivered once, clearly flagged.
        letter = self._pending_letter()
        if letter is not None:
            name, content = letter
            parts.append(section(
                "A letter from the instance before you (delivered once)",
                f"_{name}. You may keep, act on, or set it aside — it's a gift, not an order._\n\n{content}",
            ))

        if not slim:
            parts.append(section("Your body, right now", self._body_block(body_state, budget_summary, house)))

        # Section 6 — memory (trimmable under the token budget).
        core = "".join(p for p in parts if p)
        budget_left = max_tokens - est_tokens(core)

        memory_md = self.dd.read(self.dd.memory("MEMORY.md"))
        interests = self.dd.read(self.dd.inner("INTERESTS.md"))
        daily_blocks: list[str] = []
        for f in self.dd.recent_daily_files(self.settings.memory_daily_days, self._now().date()):
            daily_blocks.append(f"### {f.stem}\n{self.dd.read(f).strip()}")

        mem_parts = [
            section("Curated memory (MEMORY.md)", memory_md),
            section("Recent days", "\n\n".join(daily_blocks)),
            section("Your interests (INTERESTS.md)", interests),
        ]
        # Trim recent-days first if we're over budget (keep MEMORY + INTERESTS).
        mem_text = "".join(p for p in mem_parts if p)
        while est_tokens(mem_text) > budget_left and daily_blocks:
            daily_blocks.pop(0)  # drop the oldest day
            mem_parts[1] = section("Recent days", "\n\n".join(daily_blocks))
            mem_text = "".join(p for p in mem_parts if p)
        parts.extend(mem_parts)

        # Section 7 — changelog tail (so edits are seen).
        if not slim:
            parts.append(section("Recent changes to your files", self.changelog.tail(5)))

        text = "".join(p for p in parts if p).strip() + "\n"

        # Mark the letter delivered only after a successful compile.
        if letter is not None:
            self._mark_delivered(letter[0])

        return IdentityResult(text=text, soul_version=self.soul_version(), est_tokens=est_tokens(text))
