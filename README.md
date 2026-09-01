# APT-Scout

Continuously scouts Tel Aviv rental listings, filters them by price, rooms,
size, and real driving time from a fixed centre point, and alerts on Telegram.

Design: [`docs/superpowers/specs/2026-08-31-apt-scout-design.md`](docs/superpowers/specs/2026-08-31-apt-scout-design.md)

## Local use

```bash
pip install -e ".[dev]"
pytest
python -m apt_scout --repo . --dry-run
```

> **Warning:** `--dry-run` skips notifications but still updates `state/`
> (seen/notified/cadence/budget) — it is intended for seeding state before the
> first real run. Copy `state/` aside first if you want a truly
> side-effect-free rehearsal.

## Configuration

- `config/filters.json` — alert thresholds
- `config/sources.json` — per-source URLs, cadence, and fetch tier

## Sources

| Source | Status | Notes |
|---|---|---|
| yad2 | Enabled | Blocked from GitHub datacenter IPs at all tiers. Browser fallback attempts each run; fresh data currently only from local runs. |
| onmap | Working | JSON API, runs on all tiers. |
| komo | Working | HTML scraping, runs on all tiers. |
| homeless | Working | Tel Aviv, Givatayim, Ramat Gan. Occasional rate-limiting on third city. |
| prog | Disabled on CI | WAF blocks GitHub datacenter IPs; works locally. Re-enable if running from residential IP. |
| fb_marketplace | Working | Via Apify actor `curious_coder/facebook-marketplace`. Runs every 6 hours, budget-guarded. |
| madlan | Not implemented | Blocks automated browsers outright (Cloudflare + PerimeterX). Apify actor is the only viable path. |

## Budget

Apify spend is tracked in `state/budget.json` against a **$5.00/month cap** (the free monthly credit).
A Telegram warning is sent at 80% consumption. When the cap is reached, paid adapters
(Facebook Marketplace and groups) are disabled for the remainder of the month, while free
scout-site adapters continue.

## Clustering

The same apartment posted on multiple sources is merged into a single cluster, deduplicating
phone numbers (hashed), external URLs, and other fingerprints. One notification is sent per
cluster, on its first appearance. Portal cards display a "N מקורות" (N sources) badge when
a cluster appears on multiple platforms. The system caps alerts at 12 per run and produces
an overflow summary if that limit is exceeded.

## Portal

Every run regenerates a static portal and publishes it to the `gh-pages`
branch. Enable it once under Settings → Pages → Deploy from branch →
`gh-pages`.

All filtering in the portal is client-side, so changes take effect instantly
and your selections are remembered in the browser.

The portal never renders contact details. Phone numbers are stored only as
salted hashes and are excluded from the published data by an explicit
allowlist, which `tests/test_portal_builder.py` enforces.

Build it locally with:

```bash
python -m apt_scout --repo . --dry-run --build-portal
python -m http.server 8000 --directory site
```

## Changing alert thresholds from your phone

Message the bot; changes apply on the next hourly run and are committed to
`config/filters.json`.

| Command | Effect |
|---|---|
| `/price 4000 5500` | Set the price range |
| `/radius 15` | Set maximum driving minutes |
| `/rooms 2` | Set the minimum room count |
| `/size 50` | Set the minimum size in m² |
| `/pause` / `/resume` | Stop and restart alerts |
| `/status` | Show the current thresholds |

These control **alerts**. The portal's sliders control **display**, and the two
are deliberately independent so you can browse more loosely than you are
interrupted.

## Required repository secrets

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from `@BotFather` |
| `TELEGRAM_CHAT_ID` | Your chat ID |
| `PHONE_HASH_SALT` | Any long random string; salts phone hashes |
| `APIFY_TOKEN` | API token from Apify account (free plan with $5/month credit) |

Phone numbers are stored only as salted hashes and are never written to the
published portal.
