# APT-Scout

Continuously scouts Tel Aviv rental listings, filters them by price, rooms,
size, real driving time from a fixed centre point, and a 5 km straight-line
cap from that same point, and alerts on Telegram. Sublet and short-term ads
are detected and excluded by default.

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
| yad2 | Enabled | Blocked from GitHub datacenter IPs at all tiers. Fed by a PC-side helper (see "Local yad2 feed" below) when its feed file is fresh; otherwise falls back to the (usually failing) direct fetch. |
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

## Local yad2 feed (PC helper)

yad2 blocks GitHub's servers at every fetch tier, but works fine from a real
Chrome on a residential connection. Rather than run the whole pipeline
locally, a small helper on your PC does exactly one thing: fetch yad2 fresh
through a real browser and commit the raw listings to
`state/feeds/yad2.json`. The cloud's hourly run treats that file as yad2's
input whenever it's fresh (within `feed_max_age_hours`, default 6h, see
`config/sources.json`) and does everything else - enrich, cluster, alert,
build the portal - as usual. No secrets need to live on the PC, and the
local job owns exactly one file, so there is no state conflict with the
cloud run.

Install the scheduled task (runs hourly at :45, only while you're logged
in - it needs a real desktop session for the browser):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_yad2_task.ps1
```

Check on it:

```powershell
Get-ScheduledTask -TaskName "APT-Scout yad2 feed"
Get-Content "$env:LOCALAPPDATA\apt-scout\feed.log" -Tail 20
```

Remove it:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_yad2_task.ps1 -Unregister
```

You can also run the fetch by hand at any time:

```powershell
$env:APT_SCOUT_BROWSER_HEADED = "1"
.venv\Scripts\python.exe -m apt_scout.local_feed --repo .
```

### Known limitations

If pushes fail for many consecutive hours (e.g. the PC is offline, or a
conflicting change lands upstream), `scripts\local_yad2_feed.ps1` self-heals:
it detects a rebase left stuck by a failed `git pull --rebase` and runs
`git rebase --abort` so the repo is never left mid-rebase for the next run.
Nothing is lost in the meantime - the feed is always regenerated from
scratch on each run, so the next successful push simply overwrites
`state/feeds/yad2.json` with the latest listings.

## Changing alert thresholds from your phone

Message the bot; changes apply on the next hourly run and are committed to
`config/filters.json`.

| Command | Effect |
|---|---|
| `/price 4000 5500` | Set the price range |
| `/radius 15` | Set maximum driving minutes |
| `/km 5` | Set the maximum straight-line distance from the centre point (km) |
| `/rooms 2` | Set the minimum room count |
| `/size 50` | Set the minimum size in m² |
| `/sublets on\|off` | Show (`on`) or hide (`off`, default) sublet/short-term ads |
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
