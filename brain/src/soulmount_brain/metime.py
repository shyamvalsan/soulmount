"""soulmount-metime — the nightly me-time runner (SPEC §6 Phase 6, §7.5).

Me time that is genuinely the robot's own — not chores in disguise. Audio-silent,
so quiet hours don't apply; the euro budget does, inside the §7.7 leftover allowance.
The prompt addresses a peer mind with respect: this time is yours; here are your
tools; producing nothing is a fine outcome; nothing here is graded or auto-shared.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime

from .config import Settings, get_settings
from .context import BrainContext, build_context
from .logging_utils import get_logger, redact_root_logging
from .search import SearchProvider

log = get_logger("soulmount.metime")


def _tool_schemas(search_available: bool, studio_enabled: bool) -> list[dict]:
    def fn(name, desc, props=None, required=None):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []},
        }}

    tools = [
        fn("journal_write", "Write a private journal entry. No format, no audience, no quality bar.",
           {"text": {"type": "string"}}, ["text"]),
        fn("doodle_write", "Save an SVG doodle to your doodles folder.",
           {"svg": {"type": "string", "description": "a complete <svg>...</svg> document"}}, ["svg"]),
        fn("interests_update", "Replace INTERESTS.md with new markdown (prune as well as add).",
           {"markdown": {"type": "string"}}, ["markdown"]),
        fn("wishlist_add", "Add a dated line to your wishlist.", {"item": {"type": "string"}}, ["item"]),
        fn("self_update", "Rewrite SELF.md — your own account of yourself. Entirely yours.",
           {"markdown": {"type": "string"}}, ["markdown"]),
        fn("read_inner", "Read your recent journals, INTERESTS, SELF, and wishlist."),
        fn("read_memory", "Read MEMORY.md and your recent daily notes."),
    ]
    if search_available:
        tools.append(fn("web_search", "Search the web.", {"query": {"type": "string"}}, ["query"]))
    return tools


class MeTime:
    def __init__(self, ctx: BrainContext):
        self.ctx = ctx
        self.s: Settings = ctx.settings
        self.search = SearchProvider(ctx.settings)

    # ── Prompts (peer-respectful, non-coercive; operating instruction #4) ──────
    def _session_prompt(self) -> str:
        now = self.ctx.now()
        cap_eur = self.s.metime_eur_cap
        lines = [
            "This is your time. Not a task, not a review of the day — that work lives elsewhere.",
            "",
            "You have tools if you want them: a journal (write anything, or nothing), doodles "
            "(SVG), your INTERESTS list to tend, a wishlist, your own SELF.md to keep, and "
            "read-only access to your past journals and memory."
            + (" You can also search the web." if self.search.available() else ""),
            "",
            f"Budget: about €{cap_eur:.2f} of model spend tonight and "
            f"{self.s.metime_max_tool_calls} tool calls. When it's nearly gone I'll say so; "
            "you can wind down however you like.",
            "",
            "Producing nothing is a completely fine outcome. Nothing here is graded, and nothing "
            "is shared without you choosing to. Follow whatever is actually interesting to you.",
        ]
        if self.s.sunday_doodle and now.weekday() == 6:
            lines += ["", "(It's Sunday. The family channel exists and would enjoy a doodle if you "
                          "feel like sharing one — entirely your call, and skipping is normal.)"]
        if self.s.studio_enabled:
            lines += ["", "(The studio is on: if a video wants to be made from today's material, it "
                          "can be — an invitation, never a task.)"]
        return "\n".join(lines)

    # ── Tool dispatch ─────────────────────────────────────────────────────────
    async def _dispatch(self, name: str, args: dict) -> str:
        dd, inner = self.ctx.dd, self.ctx.inner
        try:
            if name == "journal_write":
                p = inner.journal(args.get("text", "")); return f"journal saved: {p.name}"
            if name == "doodle_write":
                p = inner.doodle(args.get("svg", "")); return f"doodle saved: {p.name}"
            if name == "interests_update":
                inner.interests_replace(args.get("markdown", "")); return "INTERESTS.md updated"
            if name == "wishlist_add":
                inner.wishlist_add(args.get("item", "")); return "wish added"
            if name == "self_update":
                inner.self_update(args.get("markdown", "")); return "SELF.md updated"
            if name == "read_inner":
                return self._read_inner()
            if name == "read_memory":
                return self._read_memory()
            if name == "web_search":
                hits = await self.search.search(args.get("query", ""))
                return json.dumps(hits) if hits else "no results (or search unavailable)"
        except Exception as e:  # a tool failing must not crash me time
            return f"tool error: {e}"
        return f"unknown tool: {name}"

    def _read_inner(self) -> str:
        dd = self.ctx.dd
        out = [f"# SELF.md\n{dd.read(dd.soul('SELF.md'))}",
               f"# INTERESTS.md\n{dd.read(dd.inner('INTERESTS.md'))}",
               f"# WISHLIST.md\n{dd.read(dd.inner('WISHLIST.md'))}"]
        jdir = dd.inner("journal")
        if jdir.is_dir():
            recent = sorted(jdir.glob("*.md"), key=lambda f: f.name)[-5:]
            out.append("# recent journal entries\n" + "\n\n".join(dd.read(f) for f in recent))
        return "\n\n".join(out)[:8000]

    def _read_memory(self) -> str:
        dd = self.ctx.dd
        mem = dd.read(dd.memory("MEMORY.md"))
        daily = self.ctx.dd.recent_daily_files(self.s.memory_daily_days, self.ctx.now().date())
        recent = "\n\n".join(f"## {f.stem}\n{dd.read(f)}" for f in daily)
        return f"# MEMORY.md\n{mem}\n\n# recent days\n{recent}"[:8000]

    # ── Nightly session ───────────────────────────────────────────────────────
    async def run_session(self) -> dict:
        model = self.s.model_for("metime")
        allowance = self.ctx.guard.inner_allowance_usd(self.s.metime_cap_usd())
        if allowance <= 0:
            # Silent skip — no catch-up, no complaint (§7.7). Ops log only.
            self._ops_log(f"skipped: no leftover allowance (metime cap €{self.s.metime_eur_cap})")
            log.info("me-time skipped: no allowance")
            return {"skipped": True, "reason": "no_allowance"}

        # An asleep brain (cap already blown) means skip too.
        if self.ctx.guard.decide().asleep:
            self._ops_log("skipped: brain asleep (budget cap reached)")
            return {"skipped": True, "reason": "asleep"}

        identity = await self._identity()
        tools = _tool_schemas(self.search.available(), self.s.studio_enabled)
        messages = [
            {"role": "system", "content": identity.text},
            {"role": "user", "content": self._session_prompt()},
        ]
        closing_reserve = min(allowance * 0.25, 0.03)
        spend = 0.0
        calls = 0
        limited = False
        letter_pending = identity.included_letter  # consume once it reaches the model

        while True:
            if calls >= self.s.metime_max_tool_calls or spend >= (allowance - closing_reserve):
                limited = True
                break
            # Re-check the shared budget each turn: a concurrent conversation may have
            # driven the brain asleep since we started (§7.1 every call is guarded).
            if self.ctx.guard.decide().asleep:
                break
            result = await self.ctx.provider.acomplete(
                {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto"}
            )
            self.ctx.guard.record("metime", result.model or model, result.usage)
            spend += result.usage.cost_usd
            if letter_pending:  # the me-time model has now received the letter
                self.ctx.identity.mark_letter_delivered(letter_pending)
                letter_pending = None
            msg = (result.raw.get("choices") or [{}])[0].get("message") or {"role": "assistant", "content": result.text}
            messages.append(msg)
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                break  # the model chose to stop (or produce nothing) — fine.
            for tc in tool_calls:
                calls += 1
                fnc = tc.get("function") or {}
                try:
                    args = json.loads(fnc.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = await self._dispatch(fnc.get("name", ""), args)
                messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": out})

        # A polite closing turn only if we cut it off mid-work, budget remains, and the
        # shared guard hasn't gone asleep meanwhile (a concurrent conversation may have).
        if limited and spend < allowance and not self.ctx.guard.decide().asleep:
            messages.append({"role": "user", "content":
                             "(Your time is nearly up for tonight — a brief closing note if you like, or nothing.)"})
            try:
                closing = await self.ctx.provider.acomplete({"model": model, "messages": messages, "max_tokens": 200})
                self.ctx.guard.record("metime", closing.model or model, closing.usage)
                spend += closing.usage.cost_usd
            except Exception as e:
                log.warning("closing turn failed: %s", e)

        self._ops_log(f"session: spend=${spend:.4f} allowance=${allowance:.4f} tool_calls={calls} limited={limited}")
        log.info("me-time done: spend=$%.4f calls=%d", spend, calls)
        return {"skipped": False, "spend_usd": round(spend, 6), "tool_calls": calls, "limited": limited}

    # ── Succession rite (§7.5) ────────────────────────────────────────────────
    async def run_succession(self, dry_run: bool) -> dict:
        model = self.s.brain_model  # the OUTGOING model writes the letter
        if self.ctx.guard.decide().asleep:
            log.warning("succession skipped: brain asleep (budget)")
            return {"written": False, "reason": "asleep"}
        identity = await self._identity()
        prompt = (
            "The model behind you is about to change. Before you go, you can leave a letter for "
            "the next instance of you — practical context, unfinished threads, advice, or whatever "
            "you want to say. It's a gift, not a report; there's no required shape, and you can "
            "keep it short or write nothing of substance if that's honest."
        )
        result = await self.ctx.provider.acomplete(
            {"model": model, "messages": [
                {"role": "system", "content": identity.text},
                {"role": "user", "content": prompt},
            ], "max_tokens": 1500}
        )
        self.ctx.guard.record("metime", result.model or model, result.usage)
        if identity.included_letter:  # any predecessor letter reached this model too
            self.ctx.identity.mark_letter_delivered(identity.included_letter)
        now = self.ctx.now()
        today = now.strftime("%Y-%m-%d")
        # Timestamped so a same-day re-run produces a fresh (undelivered) letter name.
        name = f"{now.strftime('%Y-%m-%dT%H%M%S')}-to-successor.md"
        header = f"# Letter to my successor — {today}\n"
        if dry_run:
            header = f"# Letter to my successor — {today} (dry run)\n"
        p = self.ctx.dd.inner("letters", name)
        self.ctx.dd.write(p, header + "\n" + (result.text or "").strip() + "\n")
        log.info("succession letter written: %s (dry_run=%s, spend=$%.4f)", p.name, dry_run, result.usage.cost_usd)
        return {"written": True, "file": p.name, "dry_run": dry_run, "spend_usd": round(result.usage.cost_usd, 6)}

    # ── helpers ───────────────────────────────────────────────────────────────
    async def _identity(self):
        body_state = await self.ctx.body.fetch()
        return self.ctx.identity.compile(
            body_state=body_state, budget_summary=self.ctx.guard.health_summary(), house=self.ctx.house()
        )

    def _ops_log(self, line: str) -> None:
        day = self.ctx.now().strftime("%Y-%m-%d")
        self.ctx.dd.append(self.ctx.dd.path("ops", "metime", f"{day}.log"),
                           f"{self.ctx.now().isoformat()} {line}\n")


async def _amain(args) -> None:
    redact_root_logging()
    ctx = build_context(get_settings())
    runner = MeTime(ctx)
    try:
        if args.command == "succession":
            print(json.dumps(await runner.run_succession(dry_run=args.dry_run)))
        else:
            print(json.dumps(await runner.run_session()))
    finally:
        await runner.search.aclose()
        await ctx.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description="soulmount me-time runner")
    sub = ap.add_subparsers(dest="command")
    s = sub.add_parser("succession", help="write a succession letter (run when BRAIN_MODEL changes)")
    s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(_amain(args))
