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

## Configuration

- `config/filters.json` — alert thresholds
- `config/sources.json` — per-source URLs, cadence, and fetch tier

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

Phone numbers are stored only as salted hashes and are never written to the
published portal.
