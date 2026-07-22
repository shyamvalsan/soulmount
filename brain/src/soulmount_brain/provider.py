"""Upstream model adapter (SPEC §7.1).

Model-agnostic behind one env var (``BRAIN_PROVIDER``): ``openrouter`` (default),
``anthropic``, or ``openai-compatible``. All three speak the OpenAI
chat-completions wire shape so a direct provider or a future local llama.cpp/vLLM
box slots in without code changes.

Cost accounting: OpenRouter returns the exact per-generation cost **inline** in
``usage.cost`` (both non-stream and the final SSE chunk) — that is authoritative
and what the ledger records. For non-OpenRouter providers that don't report cost,
we fall back to a price-table estimate (``estimated=True``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

import httpx

from .config import Settings
from .logging_utils import get_logger

log = get_logger("soulmount.provider")

# Fallback price table (USD per 1M tokens) for providers that don't report cost.
# OpenRouter never needs this. Values verified live 2026-07-22 (FACTS §4); used
# only when a response carries no usage.cost. Extend via METIME_PRICE_TABLE json.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "x-ai/grok-4.5": {"prompt": 2.0, "completion": 6.0},
    "x-ai/grok-4.20": {"prompt": 1.25, "completion": 2.50},
}

# When a non-OpenRouter provider reports no cost AND the model isn't priced, we must
# NOT record $0 (that would let the hard cap fail OPEN). Use a deliberately high
# fallback so the budget guard decrements aggressively and errs toward sleeping.
_UNKNOWN_PRICE = {"prompt": 15.0, "completion": 45.0}


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    estimated: bool = False  # True when cost came from the price table, not the provider


@dataclass
class ChatResult:
    id: str
    model: str
    text: str
    usage: Usage
    raw: dict = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class UpstreamProvider:
    """One provider instance per process; wraps an httpx.AsyncClient."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.provider = (settings.brain_provider or "openrouter").lower()
        self._client = client
        self._owns_client = client is None
        self._prices = self._load_prices(settings)

    # ── Wiring per provider ───────────────────────────────────────────────────
    @property
    def base_url(self) -> str:
        if self.provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        if self.provider == "anthropic":
            # Anthropic's OpenAI-compatible surface. Best-effort; cost falls back to
            # the price table (verify at first live use — FACTS §4 / MORNING).
            return self.settings.brain_upstream_base_url or "https://api.anthropic.com/v1"
        if self.provider == "openai-compatible":
            if not self.settings.brain_upstream_base_url:
                raise ProviderError("BRAIN_UPSTREAM_BASE_URL required for openai-compatible")
            return self.settings.brain_upstream_base_url.rstrip("/")
        raise ProviderError(f"unknown BRAIN_PROVIDER: {self.provider}")

    @property
    def _api_key(self) -> str:
        if self.provider == "openrouter":
            return self.settings.openrouter_api_key
        if self.provider == "anthropic":
            return self.settings.brain_upstream_api_key or self.settings.anthropic_api_key
        return self.settings.brain_upstream_api_key

    @property
    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        if self.provider == "openrouter":
            # Attribution headers (optional) + a stable app title.
            h["X-Title"] = "soulmount"
            h["HTTP-Referer"] = "https://github.com/soulmount"
        return h

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def is_configured(self) -> bool:
        try:
            return bool(self.base_url) and bool(self._api_key or self.provider == "openai-compatible")
        except ProviderError:
            return False

    # ── Cost ──────────────────────────────────────────────────────────────────
    def _load_prices(self, settings: Settings) -> dict[str, dict[str, float]]:
        prices = dict(_DEFAULT_PRICES)
        if settings.metime_price_table:
            try:
                data = json.loads(Path(settings.metime_price_table).read_text("utf-8"))
                prices.update(data)
            except (OSError, json.JSONDecodeError) as e:
                log.warning("could not load METIME_PRICE_TABLE: %s", e)
        return prices

    def _usage_from_payload(self, model: str, usage_obj: dict | None) -> Usage:
        """Read usage/cost from an OpenAI-shaped ``usage`` object.

        OpenRouter puts the authoritative USD cost in ``usage.cost``. If absent,
        estimate from the price table so the budget guard still has a number.
        """
        u = Usage()
        usage_obj = usage_obj or {}
        u.prompt_tokens = int(usage_obj.get("prompt_tokens") or 0)
        u.completion_tokens = int(usage_obj.get("completion_tokens") or 0)
        u.total_tokens = int(usage_obj.get("total_tokens") or (u.prompt_tokens + u.completion_tokens))
        details = usage_obj.get("prompt_tokens_details") or {}
        u.cached_tokens = int(details.get("cached_tokens") or 0)

        cost = usage_obj.get("cost")
        if cost is not None:
            u.cost_usd = float(cost)
            u.estimated = False
        else:
            u.cost_usd = self._estimate_cost(model, u.prompt_tokens, u.completion_tokens)
            u.estimated = True
        return u

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        row = self._prices.get(model)
        if not row:
            # Fail CLOSED, not open: charge a high fallback rate so the cap still bites.
            log.warning("no provider cost and no price-table entry for %s; using high "
                        "fallback rate so the budget cap still engages", model)
            row = _UNKNOWN_PRICE
        return round(
            prompt_tokens / 1_000_000 * row.get("prompt", 0.0)
            + completion_tokens / 1_000_000 * row.get("completion", 0.0),
            8,
        )

    def completion_price_per_token(self, model: str) -> float:
        """USD per completion token (price table, high fallback if unknown). Used for a
        conservative pre-flight max_tokens bound so a turn can't blow past the cap."""
        row = self._prices.get(model) or _UNKNOWN_PRICE
        return row.get("completion", 0.0) / 1_000_000

    def _estimate_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> Usage:
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=self._estimate_cost(model, prompt_tokens, completion_tokens),
            estimated=True,
        )

    # ── Non-streaming completion ──────────────────────────────────────────────
    async def acomplete(self, payload: dict) -> ChatResult:
        body = dict(payload)
        body["stream"] = False
        client = self._client_or_new()
        try:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=self.headers, json=body
            )
        except httpx.HTTPError as e:
            raise ProviderError(f"upstream request failed: {e}") from e
        if resp.status_code >= 400:
            raise ProviderError(f"upstream {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        model = data.get("model") or body.get("model") or ""
        text = ""
        choices = data.get("choices") or []
        if choices:
            text = (choices[0].get("message") or {}).get("content") or ""
        usage = self._usage_from_payload(model, data.get("usage"))
        return ChatResult(id=data.get("id", ""), model=model, text=text, usage=usage, raw=data)

    # ── Streaming completion ──────────────────────────────────────────────────
    def stream(self, payload: dict) -> "StreamSession":
        body = dict(payload)
        body["stream"] = True
        return StreamSession(self, body)


class StreamSession:
    """Forwards upstream SSE verbatim while capturing usage/cost.

    Call ``start()`` first — it opens the upstream stream and raises ProviderError on
    a 4xx/5xx BEFORE any bytes are relayed, so the caller can return a real error
    status instead of a truncated 200. Then iterate ``iter_sse()``. Always call
    ``finalize()`` afterwards (even on disconnect) so ``usage`` carries a cost for
    the ledger — the budget cap depends on never under-counting (§7.7).
    """

    def __init__(self, provider: UpstreamProvider, body: dict):
        self.provider = provider
        self.body = body
        self.model = body.get("model", "")
        self.usage = Usage()
        self._saw_usage = False
        self._content_chars = 0
        self._cm = None
        self._resp: httpx.Response | None = None

    async def start(self) -> None:
        client = self.provider._client_or_new()
        url = f"{self.provider.base_url}/chat/completions"
        self._cm = client.stream("POST", url, headers=self.provider.headers, json=self.body)
        try:
            self._resp = await self._cm.__aenter__()
        except httpx.HTTPError as e:
            self._cm = None
            raise ProviderError(f"upstream stream failed: {e}") from e
        if self._resp.status_code >= 400:
            err = await self._resp.aread()
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            raise ProviderError(f"upstream {self._resp.status_code}: {err[:500]!r}")

    async def iter_sse(self) -> AsyncIterator[bytes]:
        if self._resp is None:
            await self.start()
        try:
            async for line in self._resp.aiter_lines():  # type: ignore[union-attr]
                self._inspect_line(line)
                yield b"\n" if line == "" else (line + "\n").encode("utf-8")
        except httpx.HTTPError as e:
            raise ProviderError(f"upstream stream failed mid-body: {e}") from e
        finally:
            if self._cm is not None:
                await self._cm.__aexit__(None, None, None)
                self._cm = None

    def finalize(self) -> None:
        """Ensure a cost is recorded even if the stream was cut off before the usage
        chunk (barge-in / client disconnect). Estimate conservatively from the request
        prompt and the content streamed so far, so the cap is never under-counted."""
        if not self._saw_usage:
            prompt_chars = sum(
                len(str((m or {}).get("content") or "")) for m in self.body.get("messages", [])
            )
            self.usage = self.provider._estimate_usage(
                self.model, prompt_chars // 4, self._content_chars // 4
            )

    def _inspect_line(self, line: str) -> None:
        # SSE comment/keepalive lines start with ':' (e.g. ': OPENROUTER PROCESSING').
        if not line.startswith("data:"):
            return
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            return
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return
        for ch in obj.get("choices") or []:
            content = (ch.get("delta") or {}).get("content")
            if content:
                self._content_chars += len(content)
        if obj.get("usage"):
            self.usage = self.provider._usage_from_payload(
                obj.get("model") or self.model, obj["usage"]
            )
            self._saw_usage = True
