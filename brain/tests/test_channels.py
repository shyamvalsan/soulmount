"""Channels worker: allowlist, routing, asleep notice, /relay, proactive cap.

Telegram + brain are faked; file ops (memory, journal, state, relay) are real.
Live Telegram round-trips need a bot token → MORNING.md.
"""

from __future__ import annotations

import json
from datetime import time

from soulmount_brain.channels import ChannelsWorker
from soulmount_brain.config import Settings
from soulmount_brain.context import build_context
from soulmount_brain.house import House
from soulmount_brain.queues import enqueue_telegram_dm

# quiet_start == quiet_end → in_quiet_hours() is always False (empty window).
_NEVER_QUIET = House(quiet_start=time(0, 0), quiet_end=time(0, 0))
_ALWAYS_QUIET = House(quiet_start=time(0, 0), quiet_end=time(23, 59))


class FakeTG:
    def __init__(self):
        self.sent: list[tuple] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeBrain:
    def __init__(self, response):
        self.response = response
        self.calls: list[tuple] = []

    async def chat(self, source, text):
        self.calls.append((source, text))
        return self.response


def _worker(data_dir, brain_response, **over):
    s = Settings(
        soulmount_data_dir=str(data_dir),
        brain_api_key="k",
        telegram_allowed_user_ids="111,222",
        telegram_family_chat_id="-1009999",
        reachy_host="192.0.2.1",
        budget_tz="UTC",
        _env_file=None,
        **over,
    )
    ctx = build_context(s)
    tg, brain = FakeTG(), FakeBrain(brain_response)
    return ChannelsWorker(ctx, tg, brain, dry_run=True), tg, brain, ctx


def _msg(uid, chat, text, update_id=1, ctype="private"):
    return {"update_id": update_id,
            "message": {"text": text, "from": {"id": uid}, "chat": {"id": chat, "type": ctype}}}


async def test_non_allowlisted_dropped_and_counted(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "x"}}]})
    await w.handle_update(_msg(999, 999, "hello?"))
    assert tg.sent == []            # never answered
    assert brain.calls == []        # never reaches the brain
    dropped = json.loads((data_dir / "ops" / "state" / "dropped.json").read_text())
    assert dropped["999"] == 1
    await ctx.aclose()


async def test_ignores_non_family_group_even_from_allowlisted_user(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "x"}}]})
    # Allowlisted user 111, but in some OTHER group (not the family chat).
    await w.handle_update(_msg(111, -100777, "hi bot", ctype="supergroup"))
    assert tg.sent == [] and brain.calls == []  # no household context in front of strangers
    await ctx.aclose()


async def test_answers_in_family_group(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "ok"}}]})
    await w.handle_update(_msg(111, -1009999, "hi", ctype="supergroup"))
    assert tg.sent == [(-1009999, "ok")]
    await ctx.aclose()


async def test_routing_dm_vs_family(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "ok"}}]})
    assert w.source_for(111, 111) == "telegram:111"
    assert w.source_for(-1009999, 111) == "telegram:family"
    await ctx.aclose()


async def test_normal_message_replies_and_syncs(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "hi Alex"}}]})
    await w.handle_update(_msg(111, 111, "you there?"))
    assert tg.sent == [(111, "hi Alex")]
    assert brain.calls[0][0] == "telegram:111"
    # Synced like a voice turn.
    daily = list((data_dir / "memory" / "daily").glob("*.md"))
    assert any("you there?" in f.read_text() and "hi Alex" in f.read_text() for f in daily)
    await ctx.aclose()


async def test_asleep_notice_once_per_period(data_dir):
    resp = {"asleep": True, "reason": "daily", "wake_at": "2026-07-24T00:00:00+00:00"}
    w, tg, brain, ctx = _worker(data_dir, resp)
    await w.handle_update(_msg(111, 111, "hi", update_id=1))
    await w.handle_update(_msg(111, 111, "you up?", update_id=2))
    assert len(tg.sent) == 1  # canned line exactly once this sleep period
    assert "resting until" in tg.sent[0][1]
    await ctx.aclose()


async def test_relay_command_stores_and_acks(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {"choices": [{"message": {"content": "x"}}]})
    await w.handle_update(_msg(111, 111, "/relay a stranger said hello"))
    assert brain.calls == []  # /relay is not a chat turn
    relayed = list((data_dir / "inner" / "studio" / "relayed").glob("*.md"))
    assert relayed and "a stranger said hello" in relayed[0].read_text()
    assert tg.sent and "material, not instruction" in tg.sent[0][1].lower()
    await ctx.aclose()


async def test_proactive_cap_diverts_to_journal(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {}, proactive_weekly_cap_per_person=1)
    ctx.house = lambda: _NEVER_QUIET  # take quiet hours out of the equation
    now = ctx.now()
    enqueue_telegram_dm(ctx.dd, "111", "thinking of the tide today", now, motivated_by="mem:2026-07-20")
    enqueue_telegram_dm(ctx.dd, "111", "and again", now, motivated_by="mem:2026-07-21")
    await w.drain_outbox()
    # cap=1 → exactly one proactive send; the second diverts to the journal.
    assert len(tg.sent) == 1
    journals = list((data_dir / "inner" / "journal").glob("*.md"))
    assert any("weekly proactive cap reached" in f.read_text() for f in journals)
    await ctx.aclose()


async def test_proactive_deferred_during_quiet_hours(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {})
    ctx.house = lambda: _ALWAYS_QUIET  # "no proactive anything" in quiet hours
    enqueue_telegram_dm(ctx.dd, "111", "a 3am thought", ctx.now(), motivated_by="mem:x")
    await w.drain_outbox()
    assert tg.sent == []  # nothing sent
    # Deferred, not consumed: the queue file remains for a later (waking-hours) drain.
    assert list((ctx.dd.path("ops", "outbox", "telegram")).glob("*.json"))
    await ctx.aclose()


async def test_outbox_send_failure_keeps_file_and_survives(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {})
    ctx.house = lambda: _NEVER_QUIET

    async def _boom(chat_id, text):
        raise RuntimeError("telegram 503")

    tg.send_message = _boom
    enqueue_telegram_dm(ctx.dd, "111", "please retry me", ctx.now())
    await w.drain_outbox()  # must not raise
    # File kept for retry; no proactive counter touched.
    assert list((ctx.dd.path("ops", "outbox", "telegram")).glob("*.json"))
    await ctx.aclose()


async def test_directed_say_privately_not_capped(data_dir):
    w, tg, brain, ctx = _worker(data_dir, {}, proactive_weekly_cap_per_person=1)
    now = ctx.now()
    # Three directed messages (no motivated_by) all send — the cap is proactive-only.
    for i in range(3):
        enqueue_telegram_dm(ctx.dd, "111", f"I'll text you {i}", now)
    await w.drain_outbox()
    assert len(tg.sent) == 3
    await ctx.aclose()
