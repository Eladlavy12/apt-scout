from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Israeli property sites routinely reject unrecognised user agents. These
# headers make a plain HTTP request indistinguishable from a normal browser,
# which is enough for most of them and far cheaper than launching a browser.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

TIER_ORDER = ["http", "browser", "apify"]


class FetchError(Exception):
    """Raised when every available tier failed to retrieve a URL."""


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    tier: str


class Transport(Protocol):
    name: str

    def get(self, url: str, headers: dict | None = None) -> FetchResult: ...


class HttpTransport:
    """Tier 1: plain HTTP with browser-like headers and a persistent session."""

    name = "http"

    def __init__(self, client=None, timeout: float = 20.0):
        if client is None:
            import httpx

            client = httpx.Client(
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                follow_redirects=True,
            )
        self._client = client

    def get(self, url: str, headers: dict | None = None) -> FetchResult:
        response = self._client.get(url, headers=headers)
        return FetchResult(
            url=url, status=response.status_code, text=response.text, tier=self.name
        )


class Fetcher:
    """Retrieves URLs, escalating through tiers until one succeeds.

    Adapters never make network calls directly. Routing every request through
    here means that when a site tightens its bot protection, the fix is a
    configuration change to its minimum tier rather than a code change.
    """

    def __init__(self, transports: dict[str, Transport], order: list[str] | None = None):
        self._transports = transports
        self._order = order or TIER_ORDER

    def get(
        self,
        url: str,
        min_tier: str = "http",
        headers: dict | None = None,
    ) -> FetchResult:
        if min_tier not in self._order:
            raise FetchError(f"Unknown fetch tier {min_tier!r} for {url}")

        attempts: list[str] = []
        start = self._order.index(min_tier)

        for name in self._order[start:]:
            transport = self._transports.get(name)
            if transport is None:
                continue
            try:
                result = transport.get(url, headers)
            except Exception as exc:  # noqa: BLE001 - any transport failure escalates
                attempts.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if result.status == 200:
                return result
            attempts.append(f"{name}: HTTP {result.status}")

        detail = "; ".join(attempts) if attempts else "no transports configured"
        raise FetchError(f"All tiers failed for {url} ({detail})")
