from __future__ import annotations

"""Tier-2 fetch: drive a real browser through a site's own search page and
capture the JSON its frontend requests.

Bot protection that defeats plain HTTP (ShieldSquare on yad2) usually passes a
real Chrome executing the site's JavaScript. Navigating the human-facing page
and sniffing the API response it triggers is more reliable than requesting the
API URL directly, which never runs the challenge script.
"""

import os

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_STEALTH_INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)


def sniff_json(
    page_url: str,
    capture_substring: str,
    timeout_ms: int = 45000,
    channel: str | None = "chrome",
) -> str | None:
    """Navigate to `page_url` in a real browser and return the body text of the
    first JSON response whose URL contains `capture_substring`, or None.

    Never raises: missing playwright, a launch failure, a navigation timeout,
    or no matching response all just mean "tier 2 unavailable" to the caller,
    which should fall back to reporting the original tier-1 error.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        with sync_playwright() as playwright:
            headless = os.environ.get("APT_SCOUT_BROWSER_HEADED") != "1"
            launch_args = ["--disable-blink-features=AutomationControlled", "--lang=he-IL"]

            browser = None
            if channel:
                try:
                    browser = playwright.chromium.launch(
                        channel=channel, headless=headless, args=launch_args
                    )
                except Exception:  # noqa: BLE001 - fall back to bundled chromium
                    browser = None
            if browser is None:
                browser = playwright.chromium.launch(headless=headless, args=launch_args)

            try:
                context = browser.new_context(
                    locale="he-IL",
                    timezone_id="Asia/Jerusalem",
                    user_agent=_USER_AGENT,
                    viewport={"width": 1366, "height": 850},
                )
                context.add_init_script(_STEALTH_INIT_SCRIPT)
                page = context.new_page()

                captured: dict[str, str] = {}

                def _on_response(response) -> None:
                    if "captured" in captured:
                        return
                    if capture_substring not in response.url:
                        return
                    content_type = response.headers.get("content-type", "")
                    if "json" not in content_type:
                        return
                    try:
                        captured["captured"] = response.text()
                    except Exception:  # noqa: BLE001 - body may be gone by now
                        return

                page.on("response", _on_response)

                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:  # noqa: BLE001 - navigation timeout is not fatal
                    pass

                waited_ms = 0
                while "captured" not in captured and waited_ms < 15000:
                    page.wait_for_timeout(1000)
                    waited_ms += 1000

                return captured.get("captured")
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - tier 2 is best-effort, never raise
        return None
