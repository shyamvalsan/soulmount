"""soulmount-brain — the HTTP API (SPEC §7.1).

OpenAI-compatible, bearer-authed, LAN-bound. The single chokepoint for every model
call, so the §7.7 budget guard and sleep state live in the /v1/chat/completions path.
All personal file I/O resolves through $SOULMOUNT_DATA_DIR.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import __version__
from .bodystate import BodyStateProbe
from .budget import BudgetGuard
from .changelog import Changelog
from .config import Settings, get_settings
from .datadir import DataDir
from .house import House, load_house
from .identity import IdentityCompiler
from .inner import Inner
from .logging_utils import get_logger
from .memory import Memory
from .provider import ProviderError, UpstreamProvider
from .queues import enqueue_telegram_dm, store_relay
from .schemas import (
    InterestsIn,
    JournalIn,
    RelayIn,
    RememberIn,
    SayPrivatelyIn,
    SyncTurnIn,
    WishlistIn,
)

log = get_logger("soulmount.brain")


@dataclass
class BrainContext:
    settings: Settings
    dd: DataDir
    provider: UpstreamProvider
    guard: BudgetGuard
    changelog: Changelog
    identity: IdentityCompiler
    body: BodyStateProbe
    memory: Memory
    inner: Inner
    started_at: float

    def now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    def house(self) -> House:
        return load_house(self.dd)


def build_context(settings: Settings) -> BrainContext:
    dd = DataDir.from_settings(settings)
    now_fn = lambda: datetime.now(settings.timezone)  # noqa: E731
    changelog = Changelog(dd, now_fn)
    return BrainContext(
        settings=settings,
        dd=dd,
        provider=UpstreamProvider(settings),
        guard=BudgetGuard(settings, dd, now_fn),
        changelog=changelog,
        identity=IdentityCompiler(settings, dd, changelog, now_fn),
        body=BodyStateProbe(settings),
        memory=Memory(dd, now_fn),
        inner=Inner(dd, changelog, now_fn),
        started_at=time.monotonic(),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.ctx = build_context(settings)
    log.info("brain up: provider=%s model=%s", settings.brain_provider, settings.brain_model)
    try:
        yield
    finally:
        await app.state.ctx.provider.aclose()
        await app.state.ctx.body.aclose()


app = FastAPI(title="soulmount-brain", version=__version__, lifespan=lifespan)


def ctx(request: Request) -> BrainContext:
    return request.app.state.ctx


def require_auth(request: Request) -> None:
    settings = request.app.state.ctx.settings
    if not settings.brain_api_key:
        # Fail closed: never serve /v1 wide open.
        raise HTTPException(503, "brain not configured: BRAIN_API_KEY unset")
    if request.headers.get("authorization", "") != f"Bearer {settings.brain_api_key}":
        raise HTTPException(401, "invalid or missing bearer token")


# ── Identity assembly ─────────────────────────────────────────────────────────
async def _compile_identity(c: BrainContext, slim: bool = False):
    body_state = await c.body.fetch()
    budget_summary = c.guard.health_summary()
    return c.identity.compile(
        body_state=body_state, budget_summary=budget_summary, house=c.house(), slim=slim
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────
@app.get("/health")
async def health(request: Request):
    """< 100 ms, no upstream call (SPEC §7.1)."""
    c = ctx(request)
    try:
        soul_version = c.identity.soul_version()
        budget = c.guard.health_summary()
        status = "ok"
    except Exception as e:  # data dir missing/unreadable — report, don't crash
        return {"status": "unconfigured", "detail": str(e), "upstream_provider": c.settings.brain_provider}
    return {
        "status": status,
        "upstream_provider": c.settings.brain_provider,
        "model": c.settings.brain_model,
        "soul_version": soul_version,
        "uptime_s": round(time.monotonic() - c.started_at, 1),
        "budget": budget,
    }


@app.get("/v1/identity", dependencies=[Depends(require_auth)])
async def identity(request: Request, slim: bool = False):
    c = ctx(request)
    result = await _compile_identity(c, slim=slim)
    return {"instructions": result.text, "soul_version": result.soul_version}


@app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
async def chat_completions(request: Request):
    c = ctx(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "invalid JSON body")
    if not isinstance(body, dict) or "messages" not in body:
        raise HTTPException(400, "missing 'messages'")

    # Budget/sleep gate FIRST — asleep means zero upstream (§7.7).
    decision = c.guard.decide()
    if decision.asleep:
        return JSONResponse(
            {
                "asleep": True,
                "reason": decision.reason,
                "wake_at": decision.wake_at.isoformat() if decision.wake_at else None,
            }
        )

    body.setdefault("model", c.settings.brain_model)
    # Inject identity as system prompt when the caller sends none (§7.1).
    messages = body.get("messages") or []
    if not any((m or {}).get("role") == "system" for m in messages):
        result = await _compile_identity(c)
        body["messages"] = [{"role": "system", "content": result.text}, *messages]

    # Goodnight: force a short, graceful final turn.
    if decision.state == "goodnight" and decision.max_tokens_hint:
        existing = body.get("max_tokens")
        body["max_tokens"] = min(existing, decision.max_tokens_hint) if existing else decision.max_tokens_hint

    stream = bool(body.get("stream"))
    if not c.provider.is_configured():
        raise HTTPException(503, "upstream provider not configured (missing API key/base URL)")

    if stream:
        session = c.provider.stream(body)

        async def gen():
            try:
                async for chunk in session.iter_sse():
                    yield chunk
            finally:
                c.guard.record("conversation", session.model, session.usage)

        return StreamingResponse(gen(), media_type="text/event-stream")

    try:
        result = await c.provider.acomplete(body)
    except ProviderError as e:
        raise HTTPException(502, f"upstream error: {e}")
    c.guard.record("conversation", result.model, result.usage)
    return JSONResponse(result.raw or {
        "id": result.id,
        "model": result.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result.text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": result.usage.prompt_tokens, "completion_tokens": result.usage.completion_tokens, "total_tokens": result.usage.total_tokens},
    })


@app.post("/v1/sync_turn", dependencies=[Depends(require_auth)])
async def sync_turn(request: Request, payload: SyncTurnIn):
    c = ctx(request)
    p = c.memory.sync_turn(payload.source, payload.user_text, payload.assistant_text, payload.ts)
    return {"ok": True, "file": p.name}


@app.post("/v1/remember", dependencies=[Depends(require_auth)])
async def remember(request: Request, payload: RememberIn):
    c = ctx(request)
    p = c.memory.remember(payload.note)
    return {"ok": True, "file": p.name}


@app.post("/v1/inner/journal", dependencies=[Depends(require_auth)])
async def inner_journal(request: Request, payload: JournalIn):
    c = ctx(request)
    if payload.svg:
        p = c.inner.doodle(payload.svg)
        return {"ok": True, "kind": "doodle", "file": p.name}
    if payload.text:
        p = c.inner.journal(payload.text)
        return {"ok": True, "kind": "journal", "file": p.name}
    raise HTTPException(400, "provide 'text' or 'svg'")


@app.post("/v1/inner/wishlist", dependencies=[Depends(require_auth)])
async def inner_wishlist(request: Request, payload: WishlistIn):
    c = ctx(request)
    c.inner.wishlist_add(payload.item)
    return {"ok": True}


@app.post("/v1/inner/interests", dependencies=[Depends(require_auth)])
async def inner_interests(request: Request, payload: InterestsIn):
    c = ctx(request)
    c.inner.interests_replace(payload.markdown)
    return {"ok": True}


@app.post("/v1/say_privately", dependencies=[Depends(require_auth)])
async def say_privately(request: Request, payload: SayPrivatelyIn):
    c = ctx(request)
    p = enqueue_telegram_dm(c.dd, payload.person, payload.text, c.now())
    return {"ok": True, "queued": p.name}


@app.post("/v1/relay", dependencies=[Depends(require_auth)])
async def relay(request: Request, payload: RelayIn):
    c = ctx(request)
    p = store_relay(c.dd, payload.video, payload.text, payload.relayed_by, c.now())
    return {"ok": True, "stored": p.name}


def main() -> None:
    import argparse

    import uvicorn

    ap = argparse.ArgumentParser(description="soulmount brain API")
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--host", default=None, help="bind host (default BRAIN_HOST)")
    ap.add_argument("--port", type=int, default=None, help="bind port (default BRAIN_PORT)")
    args = ap.parse_args()
    s = get_settings()
    host = args.host or s.brain_host
    port = args.port or s.brain_port
    log.info("binding brain to %s:%s", host, port)
    uvicorn.run("soulmount_brain.app:app", host=host, port=port, reload=args.reload)
