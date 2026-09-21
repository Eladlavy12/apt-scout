from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .groups import group_url
from .posts import post_record

# Off-screen so an hourly unattended visit never steals focus on the PC.
_CHROME_ARGS = ["--window-position=-32000,-32000", "--window-size=1280,900"]
_LOGIN_MARKER = "/login"

# Click every "See more" inside each post first; Facebook renders the full
# text on click even without a session.
EXPAND_JS = """() => {
  let clicked = 0;
  for (const art of document.querySelectorAll('[role=article]')) {
    for (const b of art.querySelectorAll('[role=button]')) {
      const t = (b.textContent || '').trim();
      if (t === 'עוד' || t === 'הצג עוד' || t === 'See more' || t === 'See More') {
        try { b.click(); clicked += 1; } catch (e) {}
      }
    }
  }
  return clicked;
}"""

# Stable hooks only: ARIA roles, permalink href shapes, the message
# container's data attribute, and the CDN host of real photos. No CSS
# class names (they are minified and rotate).
EXTRACT_JS = """() => {
  const posts = [];
  for (const art of document.querySelectorAll('[role=article]')) {
    let postId = null, timeLabel = null;
    for (const a of art.querySelectorAll('a[href]')) {
      const href = a.getAttribute('href') || '';
      const m = href.match(/\\/posts\\/(\\d+)/) || href.match(/\\/permalink\\/(\\d+)/) || href.match(/[?&]multi_permalinks=(\\d+)/);
      if (m) { postId = m[1]; timeLabel = a.getAttribute('aria-label') || a.textContent || null; break; }
    }
    const msg = art.querySelector('[data-ad-comet-preview="message"], [data-ad-preview="message"]');
    const text = ((msg ? msg.innerText : art.innerText) || '').trim();
    const photos = [];
    for (const img of art.querySelectorAll('img[src]')) {
      const src = img.getAttribute('src') || '';
      if (/^https:\\/\\/scontent[^/]*\\.fbcdn\\.net\\//.test(src)) photos.push(src);
    }
    posts.push({post_id: postId, text, time_label: timeLabel, photos});
  }
  const login = !!document.querySelector('form[action*="login"], #login_form, input[name="email"][type], input#email');
  return {posts, title: document.title || null, login, articles: posts.length};
}"""


@dataclass
class VisitResult:
    outcome: str  # ok | blocked | error | empty
    posts: list[dict] = field(default_factory=list)
    title: str | None = None
    error: str | None = None


def records_from_extraction(raw: dict, group_id: str, now: datetime) -> list[dict]:
    posts = raw.get("posts") if isinstance(raw, dict) else None
    if not isinstance(posts, list):
        return []
    records: list[dict] = []
    for item in posts:
        if not isinstance(item, dict) or not item.get("post_id"):
            continue
        records.append(post_record(group_id, item["post_id"], item.get("text") or "", item.get("time_label"), item.get("photos") or [], now))
    return records


def visit_group(group_id: str, now: datetime, *, url: str | None = None, timeout_ms: int = 45000, headless: bool = False) -> VisitResult:
    """One anonymous visit: fresh context, login redirect aborted, posts read."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return VisitResult("error", error=f"playwright missing: {exc}")

    target = url or group_url(group_id)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=headless, args=_CHROME_ARGS)
            try:
                context = browser.new_context(locale="he-IL", viewport={"width": 1280, "height": 900})
                page = context.new_page()
                page.route(f"**{_LOGIN_MARKER}**", lambda route: route.abort())
                try:
                    page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as exc:  # noqa: BLE001
                    if "ERR_FAILED" in str(exc) or "abort" in str(exc).lower():
                        return VisitResult("blocked", error="login redirect aborted")
                    return VisitResult("error", error=str(exc)[:200])
                if _LOGIN_MARKER in page.url:
                    return VisitResult("blocked", error="redirected to login")
                try:
                    page.wait_for_selector("[role=article]", timeout=15000)
                except Exception:  # noqa: BLE001 - no posts is a legitimate outcome
                    pass
                page.evaluate(EXPAND_JS)
                page.wait_for_timeout(800)
                raw = page.evaluate(EXTRACT_JS)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - a browser failure is an outcome, not a crash
        return VisitResult("error", error=str(exc)[:200])

    title = raw.get("title") if isinstance(raw, dict) else None
    posts = records_from_extraction(raw, group_id, now)
    if not posts:
        if isinstance(raw, dict) and raw.get("login"):
            return VisitResult("blocked", title=title, error="login form shown")
        return VisitResult("empty", title=title)
    return VisitResult("ok", posts=posts, title=title)
