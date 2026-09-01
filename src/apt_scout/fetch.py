from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Protocol

if TYPE_CHECKING:
    import httpx

# Israeli property sites routinely reject unrecognised user agents. These
# headers make a plain HTTP request indistinguishable from a normal browser,
# which is enough for most of them and far cheaper than launching a browser.
#
# No Accept-Encoding here on purpose: advertise only what the client can
# actually decode. onmap's API responds with brotli whenever a request
# claims "br" support, and httpx (no brotli package installed) then hands
# back undecodable text instead of raising. Omitting the header lets httpx
# negotiate its own (gzip), which it can always decode.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

TIER_ORDER = ["http", "curl", "browser", "apify"]


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

    def __init__(self, client: "httpx.Client | None" = None, timeout: float = 20.0) -> None:
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


class CurlTransport:
    """Tier 1.5: shell out to curl.

    Some WAFs fingerprint the TLS client stack itself and reject Python's
    ssl while accepting curl (prog.co.il does exactly this). curl is present
    on dev machines and GitHub runners, making it a cheap escalation that
    needs no browser.
    """

    name = "curl"

    def __init__(
        self,
        timeout: float = 20.0,
        runner: Callable[..., "subprocess.CompletedProcess[str]"] = subprocess.run,
    ) -> None:
        self._timeout = timeout
        self._runner = runner

    def get(self, url: str, headers: dict | None = None) -> FetchResult:
        merged_headers = dict(DEFAULT_HEADERS)
        if headers:
            merged_headers.update(headers)

        argv = [
            "curl",
            "-sS",
            "--max-time",
            str(self._timeout),
            "--compressed",
            "-w",
            "\n%{http_code}",
        ]
        for key, value in merged_headers.items():
            argv += ["-H", f"{key}: {value}"]
        argv.append(url)

        # Explicit UTF-8: without it Windows decodes subprocess output with
        # the ANSI code page (cp1252), which chokes on Hebrew page bytes.
        completed = self._runner(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"curl exited {completed.returncode} for {url}: "
                f"{(completed.stderr or '').strip()}"
            )

        stdout = completed.stdout or ""
        split_at = stdout.rfind("\n")
        if split_at == -1:
            raise RuntimeError(f"curl produced no parsable status line for {url}")

        body = stdout[:split_at]
        status_text = stdout[split_at + 1 :].strip()
        try:
            status = int(status_text)
        except ValueError as exc:
            raise RuntimeError(
                f"curl produced an unparsable status code {status_text!r} for {url}"
            ) from exc

        return FetchResult(url=url, status=status, text=body, tier=self.name)


class Fetcher:
    """Retrieves URLs, escalating through tiers until one succeeds.

    Adapters never make network calls directly. Routing every request through
    here means that when a site tightens its bot protection, the fix is a
    configuration change to its minimum tier rather than a code change.
    """

    def __init__(self, transports: dict[str, Transport], order: list[str] | None = None) -> None:
        self._transports = transports
        self._order = order if order is not None else TIER_ORDER

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
