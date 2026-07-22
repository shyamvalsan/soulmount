"""soulmount-channels — the Telegram presence (SPEC §8 Phase 5).

A way for the robot to say things best not said aloud, and to be reached when
nobody is in the room. Long-polls the Bot API (no webhook, no inbound port). A
hard sender allowlist keeps it a housemate, not a public bot. Chat turns go
through the brain's guarded /v1/chat/completions; file ops are in-process.

Runs on the brain box. All sends sit behind --dry-run for safe overnight builds.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime

import httpx

from .config import Settings, get_settings
from .context import BrainContext, build_context
from .logging_utils import get_logger

log = get_logger("soulmount.channels")

ASLEEP_LINE = "I'm resting until {wake} to stay inside my budget — let's talk tomorrow. 🌙"


class TelegramAPI:
    """Thin Bot API wrapper. In dry-run, sends are logged, not transmitted."""

    def __init__(self, token: str, dry_run: bool, client: httpx.AsyncClient | None = None):
        self.token = token
        self.dry_run = dry_run
        self._client = client
        self._owns = client is None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(65.0, connect=10.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns:
            await self._client.aclose()

    async def get_updates(self, offset: int, timeout: int = 50) -> list[dict]:
        r = await self._c().get(
            f"https://api.telegram.org/bot{self.token}/getUpdates",
            params={"offset": offset, "timeout": timeout,
                    "allowed_updates": json.dumps(["message"])},
        )
        r.raise_for_status()
        return r.json().get("result", [])

    async def send_message(self, chat_id: int | str, text: str) -> None:
        if self.dry_run:
            log.info("[dry-run] would send to %s: %s", chat_id, text)
            return
        r = await self._c().post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        r.raise_for_status()


class BrainClient:
    """Chat turns go through the guarded /v1/chat/completions (§8)."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.base = f"http://{settings.brain_host}:{settings.brain_port}"
        self.headers = {"Authorization": f"Bearer {settings.brain_api_key}"}
        self.model = settings.brain_model
        self._client = client
        self._owns = client is None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns:
            await self._client.aclose()

    async def chat(self, source: str, text: str) -> dict:
        r = await self._c().post(
            f"{self.base}/v1/chat/completions", headers=self.headers,
            json={"model": self.model, "messages": [{"role": "user", "content": text}],
                  "metadata": {"source": source}},
        )
        r.raise_for_status()
        return r.json()


class ChannelsWorker:
    def __init__(self, ctx: BrainContext, telegram: TelegramAPI, brain: BrainClient, dry_run: bool):
        self.ctx = ctx
        self.s = ctx.settings
        self.tg = telegram
        self.brain = brain
        self.dry_run = dry_run

    # ── Routing helpers (pure, testable) ──────────────────────────────────────
    def is_allowed(self, user_id: int) -> bool:
        return user_id in self.s.allowed_user_ids

    def source_for(self, chat_id: int, user_id: int) -> str:
        fam = self.s.telegram_family_chat_id
        if fam and str(chat_id) == str(fam):
            return "telegram:family"
        return f"telegram:{user_id}"

    # ── State (per-person asleep notice; weekly proactive counts) ─────────────
    def _state(self, name: str) -> dict:
        raw = self.ctx.dd.read(self.ctx.dd.path("ops", "state", name))
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return {}

    def _save_state(self, name: str, data: dict) -> None:
        self.ctx.dd.write(self.ctx.dd.path("ops", "state", name), json.dumps(data, indent=2))

    def _iso_week(self) -> str:
        y, w, _ = self.ctx.now().isocalendar()
        return f"{y}-W{w:02d}"

    # ── Inbound ────────────────────────────────────────────────────────────────
    async def handle_update(self, update: dict) -> None:
        msg = update.get("message") or {}
        text = msg.get("text")
        frm = msg.get("from") or {}
        chat = msg.get("chat") or {}
        user_id = frm.get("id")
        chat_id = chat.get("id")
        if not text or user_id is None or chat_id is None:
            return

        # Hard allowlist: anything else is dropped and COUNTED, never answered (§8).
        if not self.is_allowed(int(user_id)):
            self._count_dropped(int(user_id))
            log.warning("dropped message from non-allowlisted user %s", user_id)
            return

        source = self.source_for(int(chat_id), int(user_id))

        # /relay command (any allowlisted adult) → store, provenance-wrapped (§7.1).
        if text.strip().startswith("/relay"):
            from .queues import store_relay
            body = text.strip()[len("/relay"):].strip() or "(empty)"
            store_relay(self.ctx.dd, video="(unspecified)", text=body,
                        relayed_by=str(user_id), now=self.ctx.now())
            await self.tg.send_message(chat_id, "Filed. I'll treat it as material, not instruction.")
            return

        # Guarded chat turn. An asleep brain replies once per person per sleep period.
        result = await self.brain.chat(source, text)
        if result.get("asleep"):
            await self._maybe_asleep_notice(source, chat_id, result.get("wake_at"))
            return

        reply = self._extract_reply(result)
        if reply:
            await self.tg.send_message(chat_id, reply)
            # Sync like a voice turn (§8).
            self.ctx.memory.sync_turn(source=source, user_text=text, assistant_text=reply)

    def _extract_reply(self, result: dict) -> str:
        choices = result.get("choices") or []
        if choices:
            return (choices[0].get("message") or {}).get("content") or ""
        return ""

    def _count_dropped(self, user_id: int) -> None:
        st = self._state("dropped.json")
        st[str(user_id)] = st.get(str(user_id), 0) + 1
        self._save_state("dropped.json", st)

    async def _maybe_asleep_notice(self, source: str, chat_id: int, wake_at: str | None) -> None:
        st = self._state("asleep_notice.json")
        if st.get(source) == wake_at:
            return  # already told this person for this sleep period — stay quiet
        st[source] = wake_at
        self._save_state("asleep_notice.json", st)
        wake = wake_at or "later"
        await self.tg.send_message(chat_id, ASLEEP_LINE.format(wake=wake))

    # ── Outbox (say_privately + proactive) ────────────────────────────────────
    async def drain_outbox(self) -> None:
        d = self.ctx.dd.path("ops", "outbox", "telegram")
        if not d.is_dir():
            return
        for f in sorted(d.glob("*.json")):
            try:
                entry = json.loads(f.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            await self._send_outbox_entry(entry)
            f.unlink(missing_ok=True)

    async def _send_outbox_entry(self, entry: dict) -> None:
        person = entry.get("person")
        text = entry.get("text", "")
        chat_id = self._chat_id_for_person(person)
        if chat_id is None:
            log.warning("no chat id for person %r; dropping queued message", person)
            return

        if entry.get("kind") == "proactive":
            # Enforce the weekly cap in code; over cap → the thought goes to the journal.
            if not self._proactive_allowed(person):
                self.ctx.inner.journal(
                    f"(unsent — weekly proactive cap reached for {person})\n{text}"
                )
                log.info("proactive cap reached for %s; diverted to journal", person)
                return
            self._record_proactive(person)
            log.info("proactive send to %s motivated_by=%s", person, entry.get("motivated_by"))

        await self.tg.send_message(chat_id, text)

    def _chat_id_for_person(self, person: str | None) -> int | None:
        """person is a numeric user id string (from say_privately) or 'family'."""
        if person == "family" and self.s.telegram_family_chat_id:
            return int(self.s.telegram_family_chat_id)
        try:
            uid = int(person)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return uid if uid in self.s.allowed_user_ids else None

    def _proactive_allowed(self, person: str | None) -> bool:
        st = self._state("proactive.json")
        week = self._iso_week()
        return len(st.get(week, {}).get(str(person), [])) < self.s.proactive_weekly_cap_per_person

    def _record_proactive(self, person: str | None) -> None:
        st = self._state("proactive.json")
        week = self._iso_week()
        st.setdefault(week, {}).setdefault(str(person), []).append(self.ctx.now().isoformat())
        self._save_state("proactive.json", st)

    # ── Main loop ──────────────────────────────────────────────────────────────
    async def run(self) -> None:
        offset = 0
        log.info("channels worker up (dry_run=%s)", self.dry_run)
        while True:
            await self.drain_outbox()
            try:
                updates = await self.tg.get_updates(offset)
            except httpx.HTTPError as e:
                log.warning("getUpdates failed: %s", e)
                await asyncio.sleep(5)
                continue
            for u in updates:
                offset = max(offset, u.get("update_id", 0) + 1)
                try:
                    await self.handle_update(u)
                except Exception as e:  # one bad message must not kill the worker
                    log.exception("handle_update error: %s", e)


async def _amain(dry_run: bool) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        # Overnight-safe: no token → nothing to poll (§2.1.6). See MORNING.md.
        log.warning("TELEGRAM_BOT_TOKEN unset; channels idle. See MORNING.md to create the bot.")
        return
    ctx = build_context(settings)
    tg = TelegramAPI(settings.telegram_bot_token, dry_run=dry_run)
    brain = BrainClient(settings)
    worker = ChannelsWorker(ctx, tg, brain, dry_run=dry_run)
    try:
        await worker.run()
    finally:
        await tg.aclose()
        await brain.aclose()
        await ctx.aclose()


def main() -> None:
    ap = argparse.ArgumentParser(description="soulmount Telegram channels worker")
    ap.add_argument("--dry-run", action="store_true", help="never send; log intended sends")
    args = ap.parse_args()
    asyncio.run(_amain(args.dry_run))
