# APT-Scout — Design Document

**Date:** 2026-08-31
**Status:** Approved design, pending implementation plan

---

## 1. Purpose

A continuously-updating apartment rental scout for the Tel Aviv area. It watches
several listing sources, filters them against criteria the user controls, alerts
the user the moment a genuinely new match appears, and presents everything in a
web portal whose filters can be changed at any time with immediate effect.

The system must run without the user's PC being on.

### Success criteria

1. A new matching listing on any source reaches the user's phone within roughly
   one hour of being posted.
2. The same apartment posted to five different places produces exactly one
   notification and one portal card.
3. The user can change radius, price, rooms, and size in the portal and see the
   result instantly, without a rebuild or a developer.
4. Fixed running cost is zero; variable cost stays inside Apify's free monthly
   credit ($5).
5. Newly-launched subsidized housing projects in the area are surfaced without
   the user having to know they exist.

---

## 2. Search criteria (initial defaults)

These are defaults, not hardcoded values. Every one is adjustable — the alert
thresholds live in a version-controlled config file and can also be changed by
Telegram command; the portal's view filters are client-side and adjustable
without any deploy.

| Criterion | Default |
|---|---|
| Transaction type | Rent only |
| Centre point | Ort Singalovski, Yad Eliyahu, Tel Aviv — `32.056581, 34.804087` |
| Maximum distance | 15 minutes driving time from centre |
| Price | ₪4,000 – ₪5,500 / month |
| Rooms | 2 or more (Israeli room count) |
| Size | 50 m² minimum |
| Occupancy | Whole apartment only — roommate ads excluded |
| City preference | Tel Aviv > Givatayim > Ramat Gan (ranking, not a filter) |

City preference affects sort order and a displayed preference score. It does not
exclude listings, since a good apartment in Ramat Gan should still surface.

---

## 3. Scope

### In scope for v1

- Scout sites: yad2, madlan, komo, onmap, homeless, prog
- Facebook Marketplace (Tel Aviv property rentals)
- Public Facebook groups, keyword-filtered and budget-capped
- Subsidized / young-adult housing project discovery and tracking
- Drive-time based location filtering
- Cross-source deduplication
- Telegram instant alerts and email daily digest
- Static portal with client-side filters

### Explicitly out of scope for v1

- **Private Facebook groups.** These require the user's session cookies, which
  carries account-restriction risk. Facebook Marketplace covers overlapping
  ground for free and without that exposure. Revisit in phase 2 only if group
  yield data shows a specific private group is worth the risk.
- Purchase (sale) listings.
- Automated contact with landlords or agents. The system surfaces listings; the
  user makes contact.
- Any storage or display of scraped contact details in a public location.

---

## 4. Architecture

A hybrid of a free deterministic pipeline and a low-frequency intelligent agent.
The split exists because the two kinds of work have very different cost profiles:
fetching, deduping, geocoding, and notifying are mechanical and should be free
and deterministic; discovering new housing projects, resolving ambiguous listings,
and repairing broken scrapers need judgement and are worth spending Claude usage on.

```
┌──────────────────────────────────────────────────────────────┐
│  GitHub Actions — hourly, free                               │
│                                                              │
│  fetch → normalise → enrich → cluster → filter → notify      │
│                                          │                   │
│                                          └→ build portal     │
└──────────────────────────────────────────────────────────────┘
             │                                     │
             ▼                                     ▼
   state/ (committed JSON)              GitHub Pages portal
             │                                     ▲
             ▼                                     │
┌──────────────────────────────────────────────────────────────┐
│  Claude scheduled cloud agent — daily                        │
│                                                              │
│  discover projects · classify unsure listings ·              │
│  repair failed adapters · compose digest                     │
└──────────────────────────────────────────────────────────────┘
```

**Why GitHub Actions.** Free for public repositories, runs on a cron without any
server, and its checkout/commit cycle gives us durable state for free. The
pipeline commits its own state back to the repo, so there is no database to run
or pay for.

**Why a static portal.** All filtering the user does day-to-day is *view*
filtering over a few hundred listings. That is trivially done in the browser.
Making it client-side means filter changes are instant, work offline, and need no
backend — which is also why no server exists to secure or pay for.

**Why the Claude agent is daily, not hourly.** Hourly agent runs would consume
roughly 720 runs/month of the user's subscription to do work a script does better.
Daily is enough for project discovery and classification, which are not
time-critical.

---

## 5. Components

Each component is a separate module with a defined input and output, testable in
isolation. The pipeline is a straight composition of them.

### 5.1 Source adapters

**Purpose.** Turn one source into a list of `RawListing` records.

**Interface.** Every adapter exposes `fetch(since: datetime) -> list[RawListing]`
and a `health` report. Adapters know nothing about filtering, notification, or
each other.

**Isolation requirement.** An adapter that throws must not stop the run. The
orchestrator catches per-adapter failures, records them, and continues. A run in
which yad2 fails but four other sources succeed is a successful run with a
degraded source.

| Adapter | Method | Notes |
|---|---|---|
| `yad2` | Internal JSON API, direct | Most bot-protected; highest maintenance risk. Built first because it is the highest-value and most likely to break. |
| `madlan` | Internal API / HTML, direct | |
| `komo` | Internal API / HTML, direct | |
| `onmap` | Internal JSON API, direct | Modern SPA, so a JSON API almost certainly backs it. Rejected a plain HTTP probe during design; expected to need browser-like headers. |
| `homeless` | HTML, direct | Long-established Israeli rental board with good landlord-direct volume. Rejected a plain HTTP probe; expected to need browser-like headers. |
| `prog` | Forum classifieds, direct | XenForo-style classifieds board (`לוח נדל"ן להשכרה`). Forum software usually exposes predictable listing URLs and often an RSS feed, which would make this the cheapest adapter to build and the most stable. Rejected a plain HTTP probe; expected to need browser-like headers. |
| `fb_marketplace` | Apify `curious_coder/facebook-marketplace` | Uses Facebook's own filters (price, bedrooms, radius, sort-by-newest) so only pre-matching listings are ever fetched. No cookies. ~$0.50/1,000 listings. |
| `fb_groups` | Apify `swerve/fb-group-scraper` | Public groups only. `keyword` + `postedAfter` filter server-side, so billing covers matching new posts only. `maxPostsPerGroup` acts as a runaway guard. $3.50/1,000 results. |

**Tiered fetching.** During design, plain HTTP probes of onmap, homeless, and prog
were all rejected (403/404), while the same pages are reachable in a normal
browser. Israeli property sites commonly block unrecognised user agents. Adapters
therefore do not issue raw requests themselves; they call a shared fetch layer
that escalates through three tiers:

1. **HTTP with realistic headers** — proper `User-Agent`, `Accept-Language: he-IL`,
   `Referer`, and a session that retains cookies. Expected to resolve most of the
   403s seen above. Cheapest and fastest.
2. **Headless browser** (Playwright, which runs fine on GitHub Actions runners) for
   sites that genuinely require JavaScript execution or issue challenge cookies.
3. **Apify actor** as a last resort, for any site whose protection defeats both,
   subject to the budget guard.

Each adapter declares its lowest working tier in `sources.json`, so we never pay
the cost of a browser where headers suffice. The tier is a configuration value,
not code, so a site tightening its protection is a config change rather than a
rewrite.

**Note on scan frequency and cost.** Because `postedAfter` filters server-side and
billing is per returned result, scanning more often does not increase cost — the
same new posts are returned once regardless. Cost is driven purely by how many
groups are watched and how busy they are.

**Note on the group cap.** `maxPostsPerGroup` tops out at 50 per run. At a
3-hourly cadence that is a 400-posts/day per-group ceiling. If a run returns
exactly the cap, the pipeline emits a warning, because it may have silently
truncated.

### 5.2 Normaliser

**Purpose.** Collapse five different source schemas into one `Listing` record.

Handles Hebrew text normalisation (whitespace, niqqud stripping, digit forms),
price parsing from free text (`4,500 ₪`, `4500 שח`, `4.5k`), room-count parsing
including half-rooms (`3.5 חדרים`), and size extraction (`75 מ"ר`, `75 sqm`).

Where a field cannot be determined it is `None`, never a guess. Missing values are
carried through explicitly so the portal can badge them.

### 5.3 Enrichment

Four independent enrichers, each cached so work is never repeated:

- **Geocoder** — address text to coordinates via Nominatim (free). Results cached
  permanently by normalised address string.
- **Drive-time** — driving minutes from the centre point via OSRM (free public
  instance, with a self-hosted fallback documented). Cached by coordinate pair
  rounded to three decimal places (~100 m), which keeps the cache hit rate high
  without meaningfully affecting drive-time accuracy. This is what implements the "15 minutes drive" criterion
  faithfully rather than approximating it with a straight-line radius.
- **Occupancy classifier** — decides whole-apartment vs. roommates vs. unsure from
  Hebrew keyword heuristics (`שותף`, `שותפה`, `שותפים`, `חדר בדירה`, `מחפשים שותף`).
  Anything not confidently classified is marked `unsure` rather than guessed, and
  handed to the daily Claude agent for proper classification.
- **Price inference** — for listings with no stated price (common in Facebook
  posts), the listing is retained and flagged `price_missing`. If clustering later
  matches it to a priced listing, it inherits that price.

### 5.4 Deduplication and clustering

**Purpose.** Ensure one real apartment produces one card and one notification, no
matter how many places it was posted.

This is a first-class subsystem, not a filter step. Without it the notification
stream is unusable, because popular apartments are cross-posted aggressively.

**Fingerprints.** Each listing yields several:

- `phone` — extracted from text, normalised to `+9725XXXXXXXX`, then **hashed**.
  The strongest available signal in the Israeli market, since the same landlord
  posts the same number everywhere.
- `image_hash` — perceptual hashes (pHash) of listing photos. Robust to
  re-uploading and rewritten text.
- `external_url` — a yad2/madlan link pasted into a Facebook post.
- `source_id` — the source's own identifier, for same-source repeats.
- `structural` — price + rooms + size, rounded.
- `geo` — geohash of the resolved coordinates.
- `text_sim` — normalised-text similarity signature.

**Merge rule.** Any single strong signal merges (`phone`, `image_hash`,
`external_url`, `source_id`). Two or more weak signals merge (`structural`,
`geo` within ~100 m, `text_sim` above threshold). Merging is a union-find over
listings, producing stable `Cluster` records that persist across runs.

**Cluster behaviour.**

- The cluster holds every source sighting, ordered by first-seen.
- Fields are pooled: a cluster inherits the best available price, size, room
  count, and photos from any member. This is the mechanism that rescues
  no-price Facebook posts.
- **Notification fires once per cluster**, on the cluster's first appearance. A
  later sighting on a new source updates the card with an extra source badge and
  does not re-alert.

### 5.5 Filter engine

**Purpose.** Decide which clusters are alert-worthy.

Reads `config/filters.json` (committed, version-controlled). Distinct from the
portal's view filters: this one gates *notifications*, the portal one gates
*display*. Keeping them separate means the user can browse more loosely than they
are alerted.

Supports the criteria in section 2 plus toggles for `include_price_missing` and
`include_unsure_occupancy`.

### 5.6 Notifiers

- **Telegram** — instant, one message per newly-matching cluster, with photo,
  price, rooms, size, drive time, source badges, and links to every original.
  Because Telegram is private to the user, full detail including contact
  information is safe to send here.
- **Email** — a daily digest of the previous 24 hours plus any housing-project
  news, sent via Gmail SMTP using an app password.

**Telegram as a control channel.** Each run polls the bot for commands, letting
the user adjust alert thresholds from their phone:
`/price 4000 6000`, `/radius 20`, `/rooms 3`, `/size 60`, `/pause`, `/resume`,
`/status`, `/groups`. Commands rewrite `config/filters.json` and take effect on
the next run.

### 5.7 Portal builder

**Purpose.** Emit a static site containing recent clusters embedded as JSON.

The site is built into `site/` and published to a dedicated `gh-pages` branch.
Publishing from a separate branch rather than from `docs/` keeps design and
planning documents out of the public site.

Client-side controls, all instant and no reload: drive-time slider, price range,
room count, minimum size, source toggles, include-no-price, include-unsure, and
sort (newest / cheapest / nearest / city preference). Selections persist in
`localStorage`.

Presentation is Hebrew/RTL, card-based, with photos, a "NEW" badge for the last
24 hours, source badges showing every place the apartment appeared, drive time,
and links to each original. A map view via Leaflet with OpenStreetMap tiles
(free, no API key). A footer shows per-source health and last-successful-run
times, so a silently broken scraper is visible rather than looking like a quiet
market.

**Privacy constraint.** GitHub Pages is publicly reachable by URL. The portal
therefore renders **no contact details of any kind**. Phone numbers exist only as
salted hashes in state and are never emitted to the site. To contact a landlord,
the user follows the link to the original post — exactly as they would manually.
Full detail goes to Telegram, which is private.

### 5.8 State store

Committed JSON under `state/`, written back by the Actions run:

- `clusters.json` — all known clusters and their sightings
- `seen.json` — per-source last-seen IDs and timestamps
- `geocache.json`, `drivecache.json` — enrichment caches
- `health.json` — per-adapter success/failure history
- `budget.json` — running month-to-date Apify consumption
- `group_yield.json` — per-group match statistics

Committing state to git is deliberate: it is free, durable, diffable, and gives a
complete audit trail of what the system saw and when.

### 5.9 Budget guard

**Purpose.** Make it impossible to accidentally exceed the Apify free credit.

Tracks month-to-date billed results per actor against a configured cap
(**$5/month**, the free credit). At 80% it warns on Telegram. At 100% it disables
paid Facebook adapters for the remainder of the month while leaving the free
scout-site adapters running, so coverage degrades rather than stopping. Resets on
the first of the month.

### 5.10 Group audit and yield tracking

**Purpose.** Allocate a small budget to the groups that actually pay off.

Because the budget is $5/month, group selection has to be evidence-based rather
than guessed. Two mechanisms:

- **Audit** — a one-off cheap sample (≤50 posts) of a candidate group, scored on
  how many posts pass the filters. Run manually via workflow dispatch when
  considering a new group.
- **Ongoing yield tracking** — permanent per-group statistics: posts billed,
  clusters produced, matches produced, and cost per match. Surfaced in the portal
  and in the monthly digest so unproductive groups can be dropped.

The expected shape is that a few large general groups dominate cost while niche
neighbourhood groups deliver better matches per shekel. The tracking exists to
confirm or refute that with real data rather than assumption.

### 5.11 Housing project tracker

**Purpose.** Cover subsidized and young-adult housing projects, which are not
listings and cannot be scraped on a schedule.

- **Tracked projects** — a committed list, seeded with the two the user already
  knows: the `e-b.co.il` מגדלי הצעירים lottery (application submitted, awaiting
  results) and `young-e.co.il/Students`. Checked daily for status changes,
  deadlines, and results announcements.
- **Discovery** — the daily Claude agent searches for newly-announced projects in
  the area: דיור בר השגה, מחיר למשתכן, young-adult and student housing, municipal
  and Dira Behanacha programmes. New findings are reported and, on user
  confirmation, added to the tracked list.

This is the clearest case for using Claude rather than a scraper: the sources are
heterogeneous, unstructured, and change shape constantly.

### 5.12 Claude daily agent

A single scheduled cloud agent, once per day. Its jobs, in order:

1. Check tracked housing projects for changes; search for new ones.
2. Re-classify listings marked `unsure` by the heuristic occupancy classifier.
3. Inspect `health.json`; where an adapter has failed repeatedly, diagnose the
   breakage, propose or open a fix.
4. Review `group_yield.json` and recommend groups to add or drop.
5. Compose and send the daily email digest.

---

## 6. Data model

```
Listing        source, source_id, url, title, raw_text, price, currency,
               rooms, size_sqm, floor, address_text, lat, lon,
               drive_minutes, photos[], posted_at, first_seen_at,
               occupancy (whole|roommates|unsure),
               price_missing (bool), fingerprints{}

Cluster        cluster_id, listings[], canonical fields (pooled),
               sources[], first_seen_at, last_seen_at,
               notified_at, match_state

SourceHealth   source, last_success, last_failure,
               consecutive_failures, last_error

GroupYield     group_id, group_url, posts_billed, clusters, matches,
               cost_per_match, first_tracked, active
```

---

## 7. Data flow

1. **Fetch** — adapters run concurrently, each bounded by a timeout, each failing
   independently.
2. **Normalise** — raw records become `Listing`s; unparseable fields become
   `None`.
3. **Enrich** — geocode, drive-time, occupancy classification, all cache-backed.
4. **Cluster** — fingerprint, union-find merge, pool fields across each cluster.
5. **Filter** — evaluate clusters against `filters.json`.
6. **Notify** — Telegram for clusters matching and not previously notified.
7. **Build** — regenerate the static portal.
8. **Persist** — commit updated state and portal back to the repository.

---

## 8. Scheduling

| Job | Cadence | Runs on |
|---|---|---|
| Scout sites (yad2, madlan, komo, onmap, homeless, prog) | Hourly | GitHub Actions |
| Facebook Marketplace | Every 3 hours | GitHub Actions |
| Facebook groups | Every 3 hours | GitHub Actions |
| Portal rebuild | Every run | GitHub Actions |
| Telegram command poll | Every run | GitHub Actions |
| Intelligent agent + digest | Daily | Claude scheduled cloud agent |
| Group audit | On demand | Manual workflow dispatch |

There is a single hourly workflow rather than several. Adapters declare their own
cadence and the orchestrator skips those not yet due, so the Facebook adapters
execute on every third run. This keeps scheduling in one place and guarantees that
clustering always sees a consistent snapshot.

---

## 9. Cost model

| Item | Monthly cost |
|---|---|
| GitHub Actions (public repo) | $0 |
| GitHub Pages hosting | $0 |
| Telegram Bot API | $0 |
| Gmail SMTP | $0 |
| Nominatim geocoding | $0 |
| OSRM routing | $0 |
| Leaflet / OpenStreetMap tiles | $0 |
| yad2 / madlan / komo / onmap / homeless / prog scraping | $0 |
| Apify — Facebook Marketplace | ~$0.50 |
| Apify — Facebook groups | remainder of the $5 cap |
| Claude cloud agent | ~30 runs/month of subscription usage |

**Total out-of-pocket: $0**, by design — the budget guard enforces the $5 Apify
free credit as a hard ceiling.

Within that ceiling, Marketplace is nearly free because Facebook's own filters
mean only pre-matching listings are fetched. The residual roughly $4.50 buys
about 1,300 group posts per month, which is why keyword filtering and yield-based
group selection matter rather than being optimisations.

---

## 10. Error handling

- **Per-adapter isolation.** One source failing degrades coverage; it never fails
  the run.
- **Health tracking.** Three consecutive failures of a source triggers a Telegram
  warning and flags it for the daily agent to diagnose.
- **Visible degradation.** The portal footer always shows per-source last-success
  times, so a broken scraper cannot masquerade as a quiet market.
- **Budget exhaustion** disables paid adapters only; free adapters continue.
- **Truncation warning** when a group run returns exactly `maxPostsPerGroup`.
- **Notification failure** does not lose the alert: `notified_at` is only written
  after a confirmed send, so a failed send retries next run.
- **State corruption** is recoverable from git history.

---

## 11. Testing

- **Parser unit tests** against saved HTML/JSON fixtures for every adapter,
  covering Hebrew price formats, half-room counts, and size units.
- **Clustering tests** with hand-built cross-posting scenarios, including the
  no-price-inherits-price case and the must-not-merge case for two genuinely
  different apartments on the same street.
- **Filter tests** covering boundary values on every criterion.
- **Dry-run mode** (`--dry-run`) that runs the full pipeline without sending
  notifications or committing, for safe iteration.
- **Fixture refresh** task so adapter breakage from site redesigns is caught by
  tests rather than by silence.

---

## 12. Privacy, legal, and risk

- **No contact details are ever published.** Phone numbers are salted-hashed for
  matching and never rendered to the public portal. Full details reach only the
  user's private Telegram.
- **No private Facebook groups in v1**, so no session cookies are stored and no
  account-restriction risk is taken.
- Scraping is read-only, at low volume, for personal use. Public-group and
  Marketplace access via Apify uses their infrastructure and proxies.
- The portal contains only listing data already published publicly by its authors,
  minus contact information, and links back to every original.
- Repository secrets (Apify token, Telegram token, Gmail app password) live in
  GitHub Actions secrets and never in committed files.

**Principal risks, acknowledged:**

- yad2 has strong bot protection and is the most likely adapter to break. It is
  built first, and has an Apify fallback path if direct access proves unworkable.
- onmap, homeless, and prog all rejected plain HTTP probes during design. The
  tiered fetch layer exists to absorb this, but if any of them turns out to need
  the Apify tier rather than headers or a headless browser, it would draw on the
  same $5 budget the groups use. Each is validated at tier 1 and 2 before being
  considered for tier 3, and a site that only works at tier 3 will be raised with
  the user rather than silently spending budget.
- Free public OSRM and Nominatim instances impose rate limits; caching keeps usage
  low, and self-hosting is the documented escape hatch.
- $5/month is a genuinely tight group budget. Group coverage in v1 is deliberately
  narrow, and yield data determines whether it should grow.

---

## 13. Repository layout

```
apt-scout/
├── .github/workflows/
│   ├── scan.yml              # hourly pipeline
│   ├── audit-group.yml       # manual group audit
│   └── ...
├── config/
│   ├── filters.json          # alert thresholds
│   ├── sources.json          # groups, URLs, cadences
│   └── projects.json         # tracked housing projects
├── src/apt_scout/
│   ├── adapters/             # one module per source
│   ├── normalise/
│   ├── enrich/               # geocode, drivetime, occupancy, price
│   ├── cluster/              # fingerprints, union-find
│   ├── filters/
│   ├── notify/               # telegram, email
│   ├── portal/               # static site builder
│   ├── budget.py
│   └── pipeline.py
├── state/                    # committed JSON state
├── site/                     # generated portal, published to gh-pages branch
├── docs/                     # design and planning documents (not published)
├── tests/
│   └── fixtures/
└── .claude/
    └── agents/               # daily Claude agent definition
```

---

## 14. Delivery phases

**Phase 1 — Skeleton and one source.** Repo, config, state store, `Listing` model,
yad2 adapter, filter engine, Telegram notifier, hourly Action. At the end of this
phase the user is receiving real alerts.

**Phase 2 — Location intelligence.** Geocoding, drive-time, caching. Filters
become genuinely accurate.

**Phase 3 — Portal.** Static site, client-side filters, map, health footer,
GitHub Pages.

**Phase 4 — Breadth.** The remaining free adapters — madlan, komo, onmap,
homeless, prog — plus Facebook Marketplace. Adapters are independent of one
another, so this phase parallelises well. prog is a good early target within the
phase, since forum software tends to be the most stable and predictable to parse.

**Phase 5 — Clustering.** Fingerprinting, union-find, field pooling,
once-per-cluster notification. Deliberately after multiple sources exist, since it
cannot be tested meaningfully before then.

**Phase 6 — Groups.** Apify group adapter, keyword filtering, budget guard, audit
tooling, yield tracking.

**Phase 7 — Intelligence.** Claude daily agent, project tracking and discovery,
unsure-listing classification, adapter repair, email digest.

Each phase leaves the system working and useful. Alerts start at phase 1, not at
the end.

---

## 15. Setup the user must perform

Each of these will be walked through at the phase that needs it:

1. GitHub repository (free, public — required for free Actions and Pages).
2. Telegram bot via `@BotFather`; store token and chat ID as secrets.
3. Apify account and API token (free plan, $5 monthly credit).
4. Gmail app password for the digest (optional, phase 7).
5. Claude scheduled cloud agent for the daily run (phase 7).

No credentials are entered by the assistant; the user creates each and stores it
as a GitHub Actions secret themselves.
