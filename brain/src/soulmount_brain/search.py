"""Web search for me time (SPEC §7.6 SEARCH_API_PROVIDER).

Providers: brave (default), langsearch (free tier, Bearer key), searxng (self-hosted).
Degrades gracefully (``available() == False``) when unconfigured, so an overnight
run with no key simply has no search tool rather than crashing.
"""

from __future__ import annotations

import httpx

from .config import Settings
from .logging_utils import get_logger

log = get_logger("soulmount.search")


class SearchProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.provider = (settings.search_api_provider or "brave").lower()
        self._client = client
        self._owns = client is None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            from .egress import hooks_for
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0), event_hooks=hooks_for(self.settings)
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns:
            await self._client.aclose()
            self._client = None

    def available(self) -> bool:
        if self.provider in ("brave", "langsearch"):
            return bool(self.settings.search_api_key)
        if self.provider == "searxng":
            return bool(self.settings.searxng_base_url)
        return False

    async def search(self, query: str, k: int = 5) -> list[dict]:
        if not self.available():
            return []
        if self.provider == "brave":
            return await self._brave(query, k)
        if self.provider == "langsearch":
            return await self._langsearch(query, k)
        if self.provider == "searxng":
            return await self._searxng(query, k)
        return []

    async def _brave(self, query: str, k: int) -> list[dict]:
        r = await self._c().get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": k},
            headers={"X-Subscription-Token": self.settings.search_api_key,
                     "Accept": "application/json"},
        )
        r.raise_for_status()
        results = (r.json().get("web") or {}).get("results") or []
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": x.get("description")}
                for x in results[:k]]

    async def _langsearch(self, query: str, k: int) -> list[dict]:
        # langsearch web-search: POST + Bearer; results at data.webPages.value[].
        # The API clamps count to 1..10.
        r = await self._c().post(
            "https://api.langsearch.com/v1/web-search",
            headers={"Authorization": f"Bearer {self.settings.search_api_key}",
                     "Content-Type": "application/json"},
            json={"query": query, "count": max(1, min(10, k))},
        )
        r.raise_for_status()
        pages = ((r.json().get("data") or {}).get("webPages") or {}).get("value") or []
        return [{"title": x.get("name"), "url": x.get("url"),
                 "snippet": x.get("snippet") or x.get("summary")}
                for x in pages[:k]]

    async def _searxng(self, query: str, k: int) -> list[dict]:
        base = self.settings.searxng_base_url.rstrip("/")
        r = await self._c().get(f"{base}/search", params={"q": query, "format": "json"})
        r.raise_for_status()
        results = r.json().get("results") or []
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": x.get("content")}
                for x in results[:k]]
