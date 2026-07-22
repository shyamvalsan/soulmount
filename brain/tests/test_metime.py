"""Me-time runner: tool loop, budget hard-stop, silent skip, succession (§6/§7.5).

Provider is scripted (no real spend); budget/ledger/inner writes are real.
"""

from __future__ import annotations

import json

from soulmount_brain.config import Settings
from soulmount_brain.context import build_context
from soulmount_brain.metime import MeTime
from soulmount_brain.provider import ChatResult, Usage


def _ctx(data_dir, **over):
    s = Settings(
        soulmount_data_dir=str(data_dir),
        brain_api_key="k",
        openrouter_api_key="test-key",
        brain_model="x-ai/grok-4.5",
        budget_tz="UTC",
        reachy_host="192.0.2.1",
        _env_file=None,
        **over,
    )
    ctx = build_context(s)

    async def _offline(*a, **k):
        return {"online": False, "note": "test"}

    ctx.body.fetch = _offline
    return ctx


def _script(ctx, responses):
    it = iter(responses)

    async def _fake(payload):
        return next(it)

    ctx.provider.acomplete = _fake


def _assistant_tool(name, args, cost=0.001):
    raw = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "tc1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}}]}
    return ChatResult(id="a", model="m", text="", usage=Usage(total_tokens=100, cost_usd=cost), raw=raw)


def _assistant_text(text, cost=0.0005):
    raw = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    return ChatResult(id="b", model="m", text=text, usage=Usage(total_tokens=20, cost_usd=cost), raw=raw)


async def test_session_runs_tools_then_stops(data_dir):
    ctx = _ctx(data_dir)
    _script(ctx, [
        _assistant_tool("journal_write", {"text": "a still, curious night"}),
        _assistant_text("that's enough for tonight"),
    ])
    res = await MeTime(ctx).run_session()
    assert res["skipped"] is False and res["limited"] is False
    journals = list((data_dir / "inner" / "journal").glob("*.md"))
    assert any("still, curious night" in f.read_text() for f in journals)
    # Both model calls recorded to the ledger under runner=metime.
    ledger = list((data_dir / "ops" / "ledger").glob("*.jsonl"))[0].read_text().strip().splitlines()
    assert len(ledger) == 2 and all(json.loads(x)["runner"] == "metime" for x in ledger)
    await ctx.aclose()


async def test_self_update_is_attributed(data_dir):
    ctx = _ctx(data_dir)
    _script(ctx, [
        _assistant_tool("self_update", {"markdown": "# SELF\n\nI am small and I like tide charts.\n"}),
        _assistant_text("done"),
    ])
    await MeTime(ctx).run_session()
    assert "tide charts" in (data_dir / "soul" / "SELF.md").read_text()
    assert "SELF.md updated by the robot" in (data_dir / "memory" / "CHANGELOG.md").read_text()
    await ctx.aclose()


async def test_hard_stop_when_cap_forced_low(data_dir):
    # Tiny cap → one call, then a mechanical stop with a closing turn.
    ctx = _ctx(data_dir, metime_eur_cap=0.001)
    _script(ctx, [
        _assistant_tool("journal_write", {"text": "one thought"}, cost=0.0009),
        _assistant_text("closing", cost=0.00005),
    ])
    res = await MeTime(ctx).run_session()
    assert res["skipped"] is False
    assert res["limited"] is True
    await ctx.aclose()


async def test_skips_silently_without_allowance(data_dir):
    ctx = _ctx(data_dir, budget_daily_usd=0.10)
    # Blow today's budget so there is no leftover allowance.
    ctx.guard.record("conversation", "m", Usage(total_tokens=1, cost_usd=0.20))

    called = {"n": 0}

    async def _boom(payload):
        called["n"] += 1
        raise AssertionError("model must not be called when skipping")

    ctx.provider.acomplete = _boom
    res = await MeTime(ctx).run_session()
    assert res["skipped"] is True and res["reason"] == "no_allowance"
    assert called["n"] == 0
    # Skip is logged to ops, not the journal.
    assert not list((data_dir / "inner" / "journal").glob("*.md"))
    assert (data_dir / "ops" / "metime").exists()
    await ctx.aclose()


async def test_metime_session_consumes_pending_letter(data_dir):
    # A pending succession letter reaches the me-time model → consumed once, so it is
    # not delivered again (no double-delivery to the later conversation).
    ctx = _ctx(data_dir)
    letters = data_dir / "inner" / "letters"
    letters.mkdir(parents=True, exist_ok=True)
    (letters / "2026-07-20-to-successor.md").write_text("# l\n\nMETIME_LETTER_SENTINEL\n")
    _script(ctx, [_assistant_text("hello night")])  # one call, no tools
    await MeTime(ctx).run_session()
    r = ctx.identity.compile(
        body_state={"online": False}, budget_summary=ctx.guard.health_summary(), house=ctx.house()
    )
    assert "METIME_LETTER_SENTINEL" not in r.text  # already delivered to me-time
    await ctx.aclose()


async def test_succession_letter_then_identity_includes_it(data_dir):
    ctx = _ctx(data_dir)
    letter_text = "Dear next me — the tide charts are worth keeping. Be kind to the child. — you"
    _script(ctx, [_assistant_text(letter_text, cost=0.002)])
    res = await MeTime(ctx).run_succession(dry_run=True)
    assert res["written"] is True
    letters = list((data_dir / "inner" / "letters").glob("*-to-successor.md"))
    assert letters and "tide charts are worth keeping" in letters[0].read_text()

    # A follow-up identity compile INCLUDES the letter and flags it — but compilation
    # does NOT consume it (inspection / failed turns / me-time must not burn it).
    r1 = ctx.identity.compile(
        body_state={"online": False}, budget_summary=ctx.guard.health_summary(), house=ctx.house()
    )
    assert "letter from the instance before you" in r1.text
    assert "tide charts are worth keeping" in r1.text
    assert r1.included_letter is not None
    # Only explicit delivery consumes it (as the API/body-app delivery path does).
    ctx.identity.mark_letter_delivered(r1.included_letter)
    r2 = ctx.identity.compile(
        body_state={"online": False}, budget_summary=ctx.guard.health_summary(), house=ctx.house()
    )
    assert "tide charts are worth keeping" not in r2.text
    assert r2.included_letter is None
    await ctx.aclose()
