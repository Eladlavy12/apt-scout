# APT-Scout Phase 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four free listing sources (onmap, komo, homeless, prog) and Facebook Marketplace, dedupe the same apartment across sources into one cluster with one alert, and upgrade the portal with sorting and source controls — restoring live alerts without the user's PC.

**Architecture:** Each new source is an isolated adapter conforming to the existing `SourceAdapter` protocol, built fixture-first from reconnaissance recipes captured from the live sites. A budget guard gates the one paid source (Apify). A clustering subsystem (fingerprints + union-find) sits between enrichment and notification, so alerts fire once per real apartment, not once per posting. Per-source cadence scheduling stops paid sources running hourly.

**Tech Stack:** Existing stack (Python 3.11, httpx, pytest) plus `beautifulsoup4` for the HTML adapters. Apify REST API (no SDK) for Marketplace.

## Global Constraints

- Python 3.11+; type hints on all public functions (including `-> None` on constructors and `Any` on duck-typed params).
- Unknown field values are `None`, never guessed. Missing data fails open in filters, except price (toggle).
- Every network call goes through `Fetcher`. Adapters report failure via `AdapterResult.error`, never by raising; one broken source never fails a run.
- **No contact details may ever reach `site/`**: phone numbers only as salted hashes internally; free-text fields are phone-scrubbed before publishing (Task 7).
- Notifications are exactly-once per cluster; notified state persists immediately after each confirmed send.
- All committed JSON: `ensure_ascii=False, indent=2, sort_keys=True`.
- Paid (Apify) calls respect the budget guard: hard stop at $5.00/month, Telegram warning at 80%.
- Suite must stay green at every commit: `C:\Github\Apt-scout\.venv\Scripts\python.exe -m pytest tests/ -q` (currently 247 passing).

## Reconnaissance inputs (already captured, 2026-08-31)

Recon agents probed all sites and wrote recipes + real captured fixtures under
`C:\Users\eladl\AppData\Local\Temp\claude\C--Github-Apt-scout\ca165331-4dfd-4025-b9f3-678d2a0873e9\scratchpad\phase4\`
(subdirectories `onmap/`, `komo/`, `homeless/`, `prog/`, `madlan/`, each with `RECIPE.md`, fixtures, and a proven `extract_demo.py`).
**Implementers of adapter tasks MUST read their source's RECIPE.md first** — it is the authoritative parse spec, verified against the live site. Key verified facts:

- **onmap** — public JSON API, no auth: `GET https://phoenix.onmap.co.il/v1/properties/mixed_search?option=rent,rent-short&city=tel-aviv-yafo&min={price_min}&max={price_max}&rooms[]=2&rooms[]=3&rooms[]=4&rooms[]=5&$limit=50&$skip=0`. Fields: `.id`, `.price`, `.additional_info.rooms`, `.additional_info.area.base`, `.address.location.{lat,lon}`, `.images[].full`, `.created_at`. Listing URL: `https://www.onmap.co.il/search/homes/rent?property={id}`.
- **komo** — tier-1 HTML, server-side filters: `https://www.komo.co.il/code/nadlan/apartments-for-rent.asp?nehes=1&cityName={url-encoded Hebrew city}&fromPrice={price_min}&toPrice={price_max}&fromRooms={rooms_min}&currPage={n}`. UTF-8. Listing block: `div.modaaRowAd` with `id="modaaRowDv{id}"`; price in `div.price`; rooms/size regex on `div.description` (`{rooms} חדרים ({size} מ"ר)`); link `a[href*="/code/nadlan/details/?modaaNum="]`. 20/page. Exclude sponsored cards lacking the id pattern.
- **homeless** — tier-1 HTML (needs browser UA headers): `https://www.homeless.co.il/rent/city={url-encoded Hebrew city}` (+`/2` etc. for pages, which need warm cookies — the shared `HttpTransport` client already persists cookies). Price/rooms NOT server-filterable — filter client-side. Rows: `<tr id="ad_{id}">`, cells in order type/city/neighborhood/street/rooms/floor/price/entry-date/publish-date; detail link `/rent/viewad,{id}.aspx`. UTF-8.
- **prog** — tier-1 HTML, XenForo classifieds, category page `https://www.prog.co.il/classifieds/categories/%D7%9C%D7%95%D7%97-%D7%A0%D7%93%D7%9C-%D7%9F-%D7%9C%D7%94%D7%A9%D7%9B%D7%A8%D7%94.52/`. No RSS (confirmed dead end). Board entries: `div.structItem--listing` blocks (dedupe by id — featured items appear twice); structured price on board; **detail pages carry structured custom fields** `dl.pairs--customField[data-field=...]`: price, city (`SITI`), neighborhood, rooms, floor, size m², brokerage. Nationwide board — rely on our drive-time filter. Title `<a>` selection must skip the optional city-badge `<a>`.
- **madlan** — BLOCKED (Cloudflare BM + PerimeterX detects automation even in headed real Chrome; SSR state served empty). Out of phase 4; documented in `madlan/RECIPE.md`.
- **Facebook Marketplace** — `facebook.com/marketplace/telaviv/propertyrentals` is publicly readable; scraped via Apify actor `curious_coder/facebook-marketplace` (~$0.50/1,000 basic results). `APIFY_TOKEN` is already a repo secret and env var in the workflow (Task 9 adds it to the workflow env).

---

## File Structure

| Path | Responsibility |
|---|---|
| `src/apt_scout/adapters/onmap.py` | onmap JSON API adapter |
| `src/apt_scout/adapters/komo.py` | komo HTML adapter |
| `src/apt_scout/adapters/homeless.py` | homeless HTML adapter |
| `src/apt_scout/adapters/prog.py` | prog board+detail adapter |
| `src/apt_scout/adapters/fb_marketplace.py` | Apify-backed Marketplace adapter |
| `src/apt_scout/budget.py` | Monthly paid-usage guard |
| `src/apt_scout/cluster/__init__.py`, `fingerprints.py`, `engine.py` | Cross-source clustering |
| `src/apt_scout/scheduler.py` | Per-source cadence gating |
| `src/apt_scout/pipeline.py` (modify) | Cluster-aware notification |
| `src/apt_scout/portal/builder.py` (modify) | Cluster export + phone scrubbing |
| `src/apt_scout/portal/assets/*` (modify) | Sort, source toggles, cluster badges |
| `config/sources.json` (modify) | New source entries + cadences |
| `tests/fixtures/` | One real captured fixture per source |

---

## Task 1: onmap adapter

**Files:**
- Create: `src/apt_scout/adapters/onmap.py`
- Create: `tests/fixtures/onmap_search.json` (copy from `<scratchpad>/phase4/onmap/fixture.json`)
- Test: `tests/test_onmap.py`

**Interfaces:**
- Consumes: `Listing`, `Occupancy` (models), `AdapterResult` (adapters.base), `Fetcher`/`FetchResult`/`FetchError` (fetch)
- Produces: `OnmapAdapter()` with `.name == "onmap"` and `.fetch(fetcher, config, since) -> AdapterResult`; `parse_onmap_payload(payload: list | dict) -> list[Listing]`

- [ ] **Step 1: Read the recipe and copy the fixture**

Read `<scratchpad>/phase4/onmap/RECIPE.md` (scratchpad path above). Copy `fixture.json` to `tests/fixtures/onmap_search.json` unchanged.

- [ ] **Step 2: Write the failing test**

Create `tests/test_onmap.py` following the exact structure of `tests/test_yad2.py` (read it first — same FakeFetcher, same test classes). Required tests, with a synthetic payload plus the real fixture:

```python
import json
from pathlib import Path

from apt_scout.adapters.base import AdapterResult
from apt_scout.adapters.onmap import OnmapAdapter, parse_onmap_payload
from apt_scout.fetch import FetchError, FetchResult
from apt_scout.models import Occupancy

FIXTURE = Path(__file__).parent / "fixtures" / "onmap_search.json"


def sample_item(**overrides):
    base = {
        "id": "abc-123",
        "price": 5200,
        "additional_info": {"rooms": 3, "area": {"base": 68}},
        "address": {
            "city": {"he_name": "תל אביב יפו"},
            "street": {"he_name": "אבן גבירול"},
            "location": {"lat": 32.08, "lon": 34.781},
        },
        "images": [{"full": "https://img.onmap.co.il/1.jpg"}],
        "created_at": "2026-08-30T10:00:00.000Z",
    }
    base.update(overrides)
    return base


class TestParsing:
    def test_extracts_core_fields(self):
        listing = parse_onmap_payload([sample_item()])[0]
        assert listing.source == "onmap"
        assert listing.source_id == "abc-123"
        assert listing.price == 5200
        assert listing.rooms == 3.0
        assert listing.size_sqm == 68.0
        assert listing.lat == 32.08
        assert listing.lon == 34.781
        assert listing.photos == ["https://img.onmap.co.il/1.jpg"]
        assert listing.occupancy is Occupancy.WHOLE
        assert listing.posted_at is not None

    def test_builds_a_listing_url_containing_the_id(self):
        listing = parse_onmap_payload([sample_item()])[0]
        assert "abc-123" in listing.url and listing.url.startswith("https://")

    def test_missing_fields_become_none(self):
        listing = parse_onmap_payload([{"id": "x"}])[0]
        assert listing.price is None and listing.rooms is None
        assert listing.lat is None and listing.photos == []

    def test_items_without_an_id_are_skipped(self):
        assert parse_onmap_payload([{"price": 5000}]) == []

    def test_accepts_wrapped_dict_payloads(self):
        # Feathers.js sometimes wraps results as {"data": [...]}
        assert len(parse_onmap_payload({"data": [sample_item()]})) == 1

    def test_parses_real_fixture(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        listings = parse_onmap_payload(payload)
        assert len(listings) >= 5
        assert all(l.source_id for l in listings)
        assert all(l.url.startswith("https://") for l in listings)
        priced = [l for l in listings if l.price is not None]
        assert priced, "real fixture must contain priced listings"
```

Plus a `TestAdapter` class mirroring `tests/test_yad2.py::TestAdapter` exactly: success path, configured `min_tier` honored, `FetchError` → error result, malformed JSON → error result, missing `url_template` → error result (guarded like yad2's). The adapter's `url_template` placeholders are `{price_min}`, `{price_max}` (rooms are fixed `rooms[]` params in the template itself since the API takes a list).

- [ ] **Step 3: Run to verify it fails** — `...python.exe -m pytest tests/test_onmap.py -v` → ModuleNotFoundError.

- [ ] **Step 4: Implement `onmap.py`**

Model it exactly on `src/apt_scout/adapters/yad2.py` (read it first): same `_get`/`_as_float` helper style, same error-isolation structure in `fetch`, same config-driven URL build. `parse_onmap_payload` accepts either a bare list or `{"data": [...]}`. Parse `created_at` with `datetime.fromisoformat` (strip trailing `Z` → `+00:00`), `None` on failure. Occupancy: onmap lists whole properties → `Occupancy.WHOLE`. Adjust field paths to the REAL fixture if the synthetic guesses differ (e.g. address name keys) — fix the parser AND the synthetic payload to match reality; the fixture test is authoritative.

- [ ] **Step 5: Run to verify pass**, then full suite.
- [ ] **Step 6: Commit** — `feat: add onmap adapter`

---

## Task 2: komo adapter

**Files:**
- Create: `src/apt_scout/adapters/komo.py`
- Create: `tests/fixtures/komo_search.html` (copy from `<scratchpad>/phase4/komo/fixture.html`)
- Modify: `pyproject.toml` (add `beautifulsoup4>=4.12` to core dependencies)
- Test: `tests/test_komo.py`

**Interfaces:**
- Consumes: same as Task 1
- Produces: `KomoAdapter()` (`.name == "komo"`); `parse_komo_html(html: str) -> list[Listing]`

- [ ] **Step 1: Read `<scratchpad>/phase4/komo/RECIPE.md` and `extract_demo.py`; copy the fixture.** Install bs4 into the venv: `...python.exe -m pip install beautifulsoup4` and add it to `pyproject.toml` dependencies.

- [ ] **Step 2: Write the failing test** (`tests/test_komo.py`)

Structure as in Task 1. Parsing tests use a minimal synthetic HTML snippet (one listing card built per the recipe selectors: `div.modaaRowAd` with `id="modaaRowDv12345"`, `div.price` "4,500 ₪", `div.description` containing "3 חדרים (65 מ"ר)", link `<a href="/code/nadlan/details/?modaaNum=12345">`) asserting: source "komo", source_id "12345", price 4500, rooms 3.0, size 65.0, absolute https URL containing modaaNum=12345, occupancy WHOLE, city taken from config-independent parse or None. Edge tests: card without price → price None; sponsored card without the `modaaRowDv` id → skipped; empty page → `[]`. Real-fixture test: ≥10 listings, all with source_id, all prices (where present) between 1000 and 50000. Adapter tests: same five as Task 1; `url_template` placeholders `{city}`, `{price_min}`, `{price_max}`, `{rooms_min}`, and the adapter iterates `currPage` up to `config.get("max_pages", 2)`, concatenating results and stopping early on an empty page (test with a FakeFetcher returning two pages then empty).

- [ ] **Step 3: Verify fail.**
- [ ] **Step 4: Implement** with BeautifulSoup (`html.parser` backend). Multi-page fetch inside one `fetch()` call; each page failure after the first page degrades (return what was parsed so far), first-page failure → error result.
- [ ] **Step 5: Verify pass + full suite.**
- [ ] **Step 6: Commit** — `feat: add komo adapter with server-side filtering`

---

## Task 3: homeless adapter

**Files:**
- Create: `src/apt_scout/adapters/homeless.py`
- Create: `tests/fixtures/homeless_search.html` (copy from `<scratchpad>/phase4/homeless/fixture.html`)
- Test: `tests/test_homeless.py`

**Interfaces:**
- Consumes: same as Task 1
- Produces: `HomelessAdapter()` (`.name == "homeless"`); `parse_homeless_html(html: str) -> list[Listing]`

- [ ] **Step 1: Read `<scratchpad>/phase4/homeless/RECIPE.md`; copy fixture.**

- [ ] **Step 2: Write the failing test.** Synthetic row per recipe (a `<table>` with header `<th orderfield=...>` columns and one `<tr id="ad_98765">` whose cells carry type/city/neighborhood/street/rooms/floor/price/entry-date/publish-date, plus `<a href="/rent/viewad,98765.aspx">`): assert source "homeless", source_id "98765", rooms/floor/price parsed as numbers, address_text combining street+neighborhood+city, url absolute, occupancy classified from the type cell text (a row typed "שותפים" → ROOMMATES; ordinary "דירה" → WHOLE). Price with comma "4,800" → 4800. Missing price cell → None. Real-fixture test: ≥20 rows, all ids numeric. Adapter tests: five standard ones; config has `cities: ["תל אביב", "גבעתיים", "רמת גן"]` and the adapter fetches page 1 for EACH city (url pattern `{base}/rent/city={city}`), concatenating; one city failing degrades, all failing → error result (test each). No price/rooms in URL — server can't filter; the pipeline's filter engine handles it (that is already fail-open — no adapter-side filtering).

- [ ] **Step 3: Verify fail.**
- [ ] **Step 4: Implement** with BeautifulSoup. Column mapping by header `orderfield` attributes, not positional index, so column reordering doesn't silently corrupt fields; fall back to positional only when headers absent. Dates: parse publish-date cell (dd/mm/yyyy) into `posted_at`, None on failure.
- [ ] **Step 5: Verify pass + full suite.**
- [ ] **Step 6: Commit** — `feat: add homeless adapter`

---

## Task 4: prog adapter

**Files:**
- Create: `src/apt_scout/adapters/prog.py`
- Create: `tests/fixtures/prog_board.html`, `tests/fixtures/prog_detail.html` (copy from `<scratchpad>/phase4/prog/fixture_board.html` and `fixture_detail.html`)
- Test: `tests/test_prog.py`

**Interfaces:**
- Consumes: same as Task 1, plus `StateStore` is NOT consumed — the pipeline's seen-tracking handles novelty; the adapter uses `since`-independent board scraping
- Produces: `ProgAdapter()` (`.name == "prog"`); `parse_prog_board(html: str) -> list[dict]` (id, url, title, price_text, city_badge, date); `parse_prog_detail(html: str, board_entry: dict) -> Listing`

**Design note:** the board (~15 entries) gives id/url/title/price; the structured fields (rooms, size, city, floor) live on detail pages. Fetching ~15 detail pages hourly is wasteful and impolite. The adapter therefore: parses the board; for entries whose detail is already cached in `config`-independent memory — no. Simpler, correct approach: the adapter fetches details ONLY for board entries not present in `config["known_ids"]`, a list the pipeline passes in from prior state? No — adapters don't get state. **Decision: the adapter fetches the board every run and detail pages for at most `config.get("max_details", 5)` entries per run, newest first, skipping entries whose ids appear in `config.get("skip_ids", [])`.** The runtime wiring (Task 5) injects `skip_ids` from `StateStore.seen_ids()` filtered to `prog:` prefixes. This keeps the adapter stateless while avoiding re-fetching known details.

- [ ] **Step 1: Read `<scratchpad>/phase4/prog/RECIPE.md` and `extract_demo.py`; copy both fixtures.**

- [ ] **Step 2: Write the failing test.** Board parsing (real fixture): ≥10 unique entries, deduped by id (featured duplicates collapse — assert no duplicate ids), each with id/url/title; price present on entries that have it (`₪N,NNN.00` → int) and None for the "no price" sentinel; the title link must not be the city-badge link (assert no title equals a known badge city name from the fixture). Detail parsing (real fixture): builds a full `Listing` with source "prog", price/rooms/size/city from the `dl.pairs--customField[data-field=...]` blocks (exact data-field names are in RECIPE.md — read them), occupancy from classify_occupancy over title+fields, address_text from city+neighborhood. Synthetic tests for: missing custom fields → None; expired/duplicate featured entries dropped. Adapter tests: board fetch fails → error result; board ok + one detail fetch fails → that listing is emitted from board data alone (price/title/url, occupancy UNSURE) rather than dropped; `skip_ids` respected (no detail fetch for skipped id — but a board-level Listing IS still emitted for it); `max_details` cap honored (FakeFetcher counts detail requests).

- [ ] **Step 3: Verify fail.**
- [ ] **Step 4: Implement** with BeautifulSoup per recipe (including the title-link-vs-badge pitfall and id-dedupe).
- [ ] **Step 5: Verify pass + full suite.**
- [ ] **Step 6: Commit** — `feat: add prog board adapter with structured detail fields`

---

## Task 5: Runtime wiring and per-source cadence scheduling

**Files:**
- Create: `src/apt_scout/scheduler.py`
- Modify: `src/apt_scout/__main__.py` (register 4 adapters; inject prog skip_ids; apply fetch-window override only to sources that declare it)
- Modify: `config/sources.json` (add onmap/komo/homeless/prog entries with real URLs from the recipes; add `"cadence_hours": 1` to each; yad2 keeps its entries)
- Modify: `src/apt_scout/pipeline.py` (consult the scheduler before running an adapter)
- Test: `tests/test_scheduler.py`, additions to `tests/test_pipeline.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `StateStore`
- Produces: `CadenceGate(store: StateStore)` with `.is_due(source: str, cadence_hours: float, now: datetime) -> bool` and `.mark_ran(source: str, now: datetime) -> None`; `run_pipeline(..., gate: Any | None = None)` new optional param — when provided, a source whose cadence isn't due is skipped silently (no health record, not an error, and skipping must not affect portal building logic: a skipped source doesn't count as "errored" in `should_build_portal`).

- [ ] **Step 1: Failing tests.** `CadenceGate`: due when never ran; not due 30min after a 1h-cadence run; due again after 61min; `mark_ran` persists across instances; 5-minute slack (due at 57min for a 1h cadence, so hourly crons that drift never skip a run: `is_due` compares elapsed >= cadence_hours*3600 - 300). Pipeline: gated-out adapter neither fetches nor records health (stub adapter's fetch not called); due adapter runs and `mark_ran` is called only on a non-exception outcome (error results still mark ran — a failing source shouldn't retry more often than its cadence). `build_runtime`: sources_config now yields 5 enabled sources; prog config receives `skip_ids` derived from `store.seen_ids()` (test with pre-seeded state, assert only `prog:`-prefixed bare ids passed); the yad2 fetch-window override still applies only to yad2 (config entries carry `"follows_filters": true` on yad2/onmap/komo — those three get price bounds injected; homeless/prog don't, they have no such params).

- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement.** `config/sources.json` new entries (exact URLs from the recon section above; komo cities via three url_templates? No — komo takes one city per request: give komo `cities` list like homeless and let its adapter iterate cities × pages with max_pages 1 per city beyond Tel Aviv's 2).
- [ ] **Step 4: Verify pass + full suite.**
- [ ] **Step 5: Commit** — `feat: wire four new sources with per-source cadence scheduling`

**CONTROLLER CHECKPOINT after this task:** run locally (`--dry-run --build-portal`), then push and trigger the CI workflow; verify from run logs which of the four sources succeed from GitHub IPs; record per-source outcomes in the ledger; only then continue. If a source is CI-blocked, set `"enabled": false` with a comment-in-README note rather than deleting anything, and inform the user in the wrap-up.

---

## Task 6: Budget guard

**Files:**
- Create: `src/apt_scout/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Consumes: `StateStore`
- Produces: `BudgetGuard(store: StateStore, monthly_cap_usd: float = 5.0, notifier: Any | None = None)` with:
  - `.can_spend(source: str) -> bool` (False once spent >= cap)
  - `.record(source: str, results: int, cost_usd: float) -> None`
  - `.spent_this_month() -> float`
  - month key derived from a `now: datetime` param on each method (`now` explicit for testability)
  - at >= 80% of cap, `.record` sends ONE Telegram warning per month via `notifier.send_text` (state-tracked flag, reset on month rollover)

- [ ] **Step 1: Failing tests.** Fresh month → can_spend True, spent 0. Record 300 results at $0.0005 each → spent 0.15. Spending to $4.10 (82%) triggers exactly one warning even across multiple records; crossing months resets spent, the warning flag, and can_spend. At $5.00+ can_spend False. State persists across instances. No notifier → no crash.
- [ ] **Step 2: Verify fail.** **Step 3: Implement** (state file `budget.json`: `{"month": "2026-09", "spent_usd": ..., "by_source": {...}, "warned": bool}`). **Step 4: Verify + suite.** **Step 5: Commit** — `feat: add monthly budget guard for paid sources`

---

## Task 7: Phone-scrubbing of published free text

**Files:**
- Modify: `src/apt_scout/portal/builder.py` (`listing_to_public_dict`)
- Test: additions to `tests/test_portal_builder.py`

**Interfaces:**
- Consumes: `strip_phones` from `apt_scout.normalise.text` (exists)
- Produces: published `title` and `address_text` are phone-free

- [ ] **Step 1: Failing tests.** A listing with `title='למכירה! חייגו 052-1234567 עכשיו'` and `address_text='הרצל 10, 03-5551234'` publishes with no phone digits anywhere in the emitted JSON (byte-level check like the existing `test_no_phone_number_appears_anywhere_in_the_output`); non-phone numbers (price "4500", house number "10") survive scrubbing.
- [ ] **Step 2-5:** fail → implement (`strip_phones` + whitespace collapse on those two fields inside `listing_to_public_dict`) → pass + suite → commit `fix: scrub phone numbers from published free-text fields`.

---

## Task 8: Facebook Marketplace adapter (Apify)

**Files:**
- Create: `src/apt_scout/adapters/fb_marketplace.py`
- Create: `tests/fixtures/fb_marketplace.json` (captured in Step 1)
- Modify: `.github/workflows/scan.yml` (add `APIFY_TOKEN: ${{ secrets.APIFY_TOKEN }}` to the Run scan env), `config/sources.json` (marketplace entry, `"cadence_hours": 6`), `src/apt_scout/__main__.py` (register adapter; construct `BudgetGuard` and pass it via config)
- Test: `tests/test_fb_marketplace.py`

**Interfaces:**
- Consumes: `BudgetGuard` (Task 6), `Listing`, `AdapterResult`, `classify_occupancy`, parsers
- Produces: `FbMarketplaceAdapter(budget: Any)` (`.name == "fb_marketplace"`); `parse_marketplace_items(items: list[dict]) -> list[Listing]`

- [ ] **Step 1: Capture a real fixture (live discovery, ~$0.02).** With the local env var `APIFY_TOKEN` (ask the controller — it equals the repo secret), run the actor once via REST:
  `POST https://api.apify.com/v2/acts/curious_coder~facebook-marketplace/run-sync-get-dataset-items?token=...` with JSON input per the actor's input schema (fetch `https://api.apify.com/v2/acts/curious_coder~facebook-marketplace` to read the schema first): a startUrl of `https://www.facebook.com/marketplace/telaviv/propertyrentals?minPrice=4000&maxPrice=5500&sortBy=creation_time_descend&exact=false`, count/limit ≈ 20. Save the dataset-items response as `tests/fixtures/fb_marketplace.json`. If `run-sync-get-dataset-items` times out (sync cap 300s), use the async run + poll + dataset endpoints and note that in the adapter design. Document the exact working request in the module docstring.
- [ ] **Step 2: Failing tests.** Parsing (real fixture): ≥3 listings, source "fb_marketplace", ids present, urls facebook.com/marketplace/item links, prices integers (actor returns strings/amounts — normalize; ILS only, skip USD-priced anomalies), occupancy from `classify_occupancy(title+description)` — NOT forced WHOLE (Marketplace has roommate posts). Synthetic tests: missing price → None; item without id skipped. Adapter: budget `can_spend` False → `AdapterResult` with error "budget exhausted" and NO HTTP call (FakeFetcher asserts no requests); success path records `budget.record("fb_marketplace", n_items, n_items * 0.0005)`; HTTP failure → error result. The adapter takes the Apify token from `config["token"]` (injected by `build_runtime` from env `APIFY_TOKEN`; absent token → error result, not a crash).
- [ ] **Step 3-6:** fail → implement (call through `fetcher.get`? No — Apify needs POST with body; the adapter may use httpx directly HERE as a documented exception? **No.** Extend nothing: add a tiny `post_json(url, payload, timeout) -> tuple[int, str]` helper INSIDE the adapter module using httpx, with the module docstring noting the Fetcher tier system targets bot-protected scraping, while Apify is a cooperative API — this exception is deliberate and localized) → pass + suite → commit `feat: add Facebook Marketplace adapter behind the budget guard`.

---

## Task 9: Clustering — fingerprints and engine

**Files:**
- Create: `src/apt_scout/cluster/__init__.py`, `src/apt_scout/cluster/fingerprints.py`, `src/apt_scout/cluster/engine.py`
- Test: `tests/test_fingerprints.py`, `tests/test_cluster_engine.py`

**Interfaces:**
- Consumes: `Listing`, `normalise_text`, `extract_phone`/`hash_phone`
- Produces:
  - `fingerprints(listing: Listing, salt: str) -> dict[str, list[str]]` returning keys `"strong"` and `"weak"`, each a list of opaque fingerprint strings:
    - strong: `phone:{hash}` (from raw_text/title), `exturl:{normalized-url}` for any yad2/madlan/onmap listing URL found inside raw_text
    - weak: `struct:{price}|{rooms}|{size-bucket-of-10sqm}` (only when price AND rooms present), `geo:{lat:.3f},{lon:.3f}` (only with coords), `text:{16-char blob}` — a similarity key built from the 8 rarest normalized tokens of raw_text sorted (only when raw_text ≥ 40 chars)
  - `ClusterEngine()` with `.cluster(listings: list[Listing], salt: str) -> list[Cluster]` where `Cluster` is a dataclass in `engine.py`: `cluster_id: str` (stable: sha1 of the sorted member stable_ids' minimum), `members: list[Listing]`, `canonical: Listing` (pooled: each field taken from the first member that has it non-None, members ordered yad2 > onmap > komo > homeless > fb_marketplace > prog then by stable_id), `sources: list[str]`
  - merge rule: union-find over listings; any shared strong fingerprint merges; sharing >= 2 DISTINCT weak fingerprints merges; one shared weak alone does not

**Explicit spec deviation:** the spec (§5.4) also lists perceptual image hashes
as a strong signal. Deferred — computing pHashes means downloading every listing
photo on every CI run, which is heavy and impolite at hourly cadence. Phone,
external-URL, and the weak-pair rule cover the dominant cross-posting patterns;
image hashing can be added later as one more strong fingerprint without
touching the engine. Record this deferral in Task 12's spec edit as well.

- [ ] **Step 1: Failing tests — this is the core logic, test it hard.**

```python
# tests/test_cluster_engine.py — the scenarios, all with explicit Listing builders:
# 1. same phone in raw_text on a yad2 and a facebook listing -> one cluster, 2 sources
# 2. facebook post containing the yad2 listing's URL -> merged
# 3. same price+rooms+size AND same geo cell -> merged (two weak)
# 4. same price+rooms+size but 3km apart -> NOT merged (one weak)
# 5. two different apartments, same street, different price/rooms -> NOT merged
# 6. pooling: fb member without price + yad2 member with price 4800 -> canonical.price == 4800
# 7. pooling priority: canonical.url comes from the yad2 member when present
# 8. singleton listing -> cluster of one, canonical is the listing itself
# 9. transitive merge: A~B via phone, B~C via exturl -> one 3-member cluster
# 10. cluster_id stability: same members in different input order -> same cluster_id
# 11. phone fingerprint uses the salted hash (raw number not in any fingerprint string)
```

Fingerprint tests: struct absent when price or rooms missing; geo rounding equates 32.0801/32.0803; text key identical for reordered same words, absent for short text; exturl found for `https://www.yad2.co.il/realestate/item/abc123` inside Facebook prose and normalized (scheme/host lowercased, no query).

- [ ] **Step 2: Verify fail.** **Step 3: Implement** (plain union-find with path compression; ~60 lines for the engine). **Step 4: Verify + full suite.** **Step 5: Commit** — `feat: add cross-source clustering engine`

---

## Task 10: Clustering — pipeline and portal integration

**Files:**
- Modify: `src/apt_scout/pipeline.py`, `src/apt_scout/portal/builder.py`, `src/apt_scout/state.py` (only if a helper is genuinely needed), `src/apt_scout/__main__.py`
- Test: additions to `tests/test_pipeline.py`, `tests/test_portal_builder.py`

**Interfaces:**
- Consumes: `ClusterEngine`, `Cluster` (Task 9)
- Produces:
  - `run_pipeline(..., cluster_salt: str = "")` clusters AFTER enrichment, BEFORE filtering; filtering and notification operate on `cluster.canonical`
  - notification exactly-once semantics move to clusters: a cluster is notified if ANY member's stable_id is in `notified_ids()` (this makes existing seeded state keep suppressing alerts); after a confirmed send, ALL member ids are marked notified immediately
  - **flood cap:** at most `max_alerts_per_run = 12` cluster alerts per run; overflow sends ONE summary text: `"+ עוד N דירות תואמות — ראו בפורטל"`; overflowed clusters are NOT marked notified (they retry next run, naturally draining)
  - `RunReport.listings` becomes the canonical listings (one per cluster) each carrying `sources: list[str]` — implement by adding a `sources` field with default `[]` to `Listing` in models.py; portal export publishes it (extend `PUBLIC_FIELDS`)
- [ ] **Step 1: Failing tests.** Two-source same-phone stubs → one notification, both ids marked notified, portal export row has `sources == ["yad2", "fb_marketplace"]` and the pooled price; a cluster with one member already in notified state → no re-alert when a second source appears (test: seed notified with the yad2 id, run with yad2+facebook members → notified 0); flood cap: 15 matching singleton clusters → 12 sends + 1 summary text + exactly 12 clusters' ids marked; the 3 overflowed notify on the following run. Existing pipeline tests must pass unmodified except where they assert internal call shapes (update surgically, never weaken behavioral assertions).
- [ ] **Step 2: Verify fail.** **Step 3: Implement.** **Step 4: Verify + FULL suite.** **Step 5: Commit** — `feat: notify once per cluster with pooled fields and flood cap`

---

## Task 11: Portal — sort, source toggles, cluster badges

**Files:**
- Modify: `src/apt_scout/portal/assets/index.html`, `app.js`, `style.css`
- Test: additions to `tests/test_portal_assets.py`

**Interfaces:**
- Consumes: `data/listings.json` rows now carrying `sources: [...]`
- Produces: sort select `id="sort"` (options: `newest`, `cheapest`, `nearest`, `preference`), a source-toggle chip row `id="source-toggles"` built dynamically from the data's distinct sources, and a per-card badge showing `sources.length > 1` as `"N מקורות"`

- [ ] **Step 1: Failing tests** (static, matching the existing test style): `id="sort"` present with the four option values; `source-toggles` container present; app.js references `sources` and sorts by `drive_minutes`, `price`, `first_seen_at`; still no `innerHTML` anywhere; preference sort mentions the city ranking (`תל אביב`, `גבעתיים`, `רמת גן` appear in app.js as the ranking table).
- [ ] **Step 2: Verify fail.** **Step 3: Implement** — DOM-built only (match the existing createElement style): sort comparator map; preference = city rank (תל אביב יפו/תל אביב → 0, גבעתיים → 1, רמת גן → 2, else 3) then newest; source chips toggle inclusion, persisted in the localStorage state object; multi-source badge `span.badge.multi`. Sort choice persisted too. **Step 4: Verify + suite. Step 5:** visual check is the CONTROLLER's job (skip). **Step 6: Commit** — `feat: portal sorting, source toggles, and multi-source badges`

---

## Task 12: Documentation and config truth

**Files:**
- Modify: `README.md` (sources table with per-source status incl. madlan-blocked and yad2-CI-blocked notes; budget section; clustering explanation one paragraph), `docs/superpowers/specs/2026-08-31-apt-scout-design.md` (mark madlan deferred with one-line reason in §5.1)
- Test: none (docs)

- [ ] **Step 1: Update the docs as above.** Keep the README's existing structure; add, don't rewrite.
- [ ] **Step 2: Full suite one final time.**
- [ ] **Step 3: Commit** — `docs: phase 4 sources, budget, and clustering`

---

## Execution notes for the controller

- Tasks 1-4 are independent of each other (still execute serially — same repo).
- The CI checkpoint after Task 5 gates everything: adapters may behave differently from GitHub IPs than from recon.
- Task 8 Step 1 needs the `APIFY_TOKEN` value passed into the implementer's environment.
- After Task 10, re-seed state locally (dry-run) before the next CI run if the new sources would flood — the flood cap makes this optional but a seed keeps the first alerts meaningful.
- Final whole-branch review on the most capable model, as in phases 1-3.
