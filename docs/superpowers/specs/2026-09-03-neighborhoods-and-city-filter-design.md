# Neighborhood intelligence and city filter — design

Date: 2026-09-03
Status: approved by user in chat (brainstorm), pending spec review
Builds on: `2026-08-31-apt-scout-design.md` (phases 1–4 shipped)

## Goal

Give every listing a neighborhood, a consensus reputation and pros/cons,
and let the user filter by city and by neighborhood — in the portal and
for Telegram alerts. No per-listing AI calls, no paid imagery, no scoring.

Decisions made during brainstorming (user's choices in bold):

- Neighborhood insight is a **static curated profile** (not per-listing AI).
- Street-level context is a **Street View link only** on each card (no OSM
  POI context, no imagery analysis) — deferred, see "Out of scope".
- City filter lives in **portal chips and a Telegram command**.
- Profile shows as **card badge + expandable panel + neighborhood filter
  chips**, with a **consensus reputation tier** reflecting general opinion
  (the user noted there is broad common consent about some neighborhoods).
- Assignment is **point-in-polygon with real boundaries**, text match as
  fallback for listings without coordinates.

## 1. Knowledge base — `data/neighborhoods.json`

A single versioned JSON object keyed by neighborhood id (ASCII slug).
Hand-curated; edited by humans, read by code. Entry schema:

| field        | type        | notes |
|--------------|-------------|-------|
| `names`      | list[str]   | Hebrew first, then English/aliases. Used for display (first) and text-fallback matching (all). |
| `city`       | str         | One of the canonical city strings (section 2). |
| `reputation` | enum        | `sought_after` \| `solid` \| `mixed` \| `weak`. Consensus tier, not a computed score. |
| `summary`    | str         | 1–3 Hebrew sentences: character of the area and the reasoning behind the tier. |
| `pros`       | list[str]   | 2–5 short Hebrew bullets. |
| `cons`       | list[str]   | 2–5 short Hebrew bullets. |
| `tags`       | list[str]   | From the fixed vocabulary below, max 5, most defining first. |
| `sources`    | list[str]   | Keys into `docs/neighborhoods-sources.md`. |
| `notes`      | str         | Optional free text for the user's own remarks. Never displayed. |

Tag vocabulary (fixed, validated by a test): `quiet`, `nightlife`, `family`,
`young`, `beach`, `green`, `light_rail`, `renewal`, `old_buildings`,
`noisy`, `parking_hard`, `expensive`, `value`, `religious`,
`industrial_edge`. Hebrew labels for tags and reputation tiers live in one
mapping in the portal JS and one in the Telegram formatter (the JSON
stores English keys only).

Coverage target: every Tel Aviv neighborhood any part of which lies within
the 5 km circle around the reference point, all Givatayim neighborhoods,
and Ramat Gan neighborhoods within the circle. Expected 45–55 entries.
A polygon without a knowledge-base entry is a test failure; an entry
without a polygon is allowed (text-only match).

Research process (a real plan task, not an afterthought): read the six
links the user supplied (homemarket guide, two Secret Tel Aviv threads,
Hebrew Quora thread, r/Israel thread, DIY Tel Aviv guide) plus roughly ten
further sources (Madlan/Yad2 neighborhood pages, municipality profiles,
Hebrew blogs and news on light-rail and urban-renewal status). Record what
informed each reputation call in `docs/neighborhoods-sources.md` so the
user can disagree with specifics. Where sources conflict, the tier follows
the majority view and `summary` names the disagreement.

## 2. Geography — `data/neighborhoods.geojson` and `enrich/neighborhood.py`

### Boundary data

- Tel Aviv: the municipality's open GIS neighborhoods layer (official
  boundaries). Givatayim and Ramat Gan: OpenStreetMap boundaries
  (`place=neighbourhood`/`suburb` or admin level 10 where present).
- A one-off script `scripts/build_neighborhoods_geojson.py` downloads,
  clips to a 7 km box around the reference point, simplifies (target
  ≤ 300 KB), assigns each feature a `properties.id` matching the knowledge
  base, and writes the GeoJSON. The output is committed; the script is
  re-run only when boundaries change. Manual id mapping lives in the
  script (source name → id) so re-runs are deterministic.
- Only `Polygon` and `MultiPolygon` features; WGS84 lon/lat.

### Model change

- `Listing.neighborhood: str | None` — the knowledge-base id. `None` when
  unresolved. Added to `serialise`/`deserialise`, to `PUBLIC_FIELDS`, and to
  cluster pooling (canonical member's value; if the canonical has `None`,
  the first member with a value).

### City normalisation

- `enrich/city.py` exposes `normalise_city(text) -> str | None` mapping
  known variants to three canonical strings: `"תל אביב יפו"`,
  `"גבעתיים"`, `"רמת גן"`. Variants include hyphenated and abbreviated
  Hebrew forms (`תל אביב`, `תל-אביב`, `תל אביב-יפו`, `ת"א`, `יפו`),
  English (`Tel Aviv`, `Tel Aviv-Yafo`, `Givatayim`, `Giv'atayim`,
  `Ramat Gan`), and surrounding whitespace/punctuation. Unknown input
  returns `None`.
- The enricher overwrites `listing.city` with the canonical form when
  `normalise_city` matches, otherwise leaves the raw value untouched.
- When the polygon lookup resolves a neighborhood, the polygon's city wins
  over the source's text (sources mislabel border streets).

### Neighborhood enricher

- `NeighborhoodEnricher(store, index)` follows the existing enricher
  contract (`enrich(listing) -> None`, never raises; pipeline isolates it).
- Resolution order: (1) point-in-polygon when `lat`/`lon` present;
  (2) text fallback — longest `names` alias found as a whole word in
  `address_text` then `title`, restricted to entries whose city matches
  the listing's canonical city when that is known; (3) `None`.
- Geometry: pure Python. Bounding-box prefilter per feature, then
  ray-casting with hole support for polygons/multipolygons. No new
  dependency.
- Cache: `store` key `neighborhoods` mapping `stable_id -> id | null`, same
  pattern as `geocache`. A `None` result from a listing that had no
  coordinates is not cached (coordinates may arrive on a later run after
  geocoding); a `None` from a successful point-in-polygon miss is cached.
- Runs after geocoding and distance in the enricher list.

## 3. Filters and Telegram

### `Filters`

- `cities: list[str]` — canonical city names; default
  `["תל אביב יפו", "גבעתיים", "רמת גן"]`; empty list means "no city
  restriction".
- `excluded_neighborhoods: list[str]` — knowledge-base ids; default `[]`.
- Semantics in `matches`: a listing with `city is None` passes the city
  check (fail open); a listing whose canonical city is set and not in a
  non-empty `cities` list fails. A listing with `neighborhood is None`
  passes the neighborhood check; one whose id is in
  `excluded_neighborhoods` fails.
- `config/filters.json` keeps sorted keys; both fields are written on save.
  Loading a file without these keys yields the defaults (backward
  compatible with the committed state file).

### Telegram commands (`notify/commands.py`)

| command | effect |
|---------|--------|
| `/cities <a>, <b>` | Set `cities` to the canonical forms of the comma-separated names (via `normalise_city`); unknown names are rejected with a reply listing the three valid cities. |
| `/cities all` | Clear the restriction. |
| `/exclude <name>` | Add the neighborhood matching any alias (case/whitespace-insensitive) to `excluded_neighborhoods`; ambiguous or unknown → reply with suggestions. |
| `/include <name>` | Remove it. |
| `/status` | Gains lines for cities and excluded neighborhoods (Hebrew display names). |

Only the configured chat id is honored, as today. Alert text gains one
line after the address: `שכונה: <name> · <reputation label> · <tag1>, <tag2>`
when a neighborhood is resolved; nothing otherwise.

## 4. Portal

### Data

- The builder copies `data/neighborhoods.json` to `site/data/neighborhoods.json`
  with `notes` and `sources` stripped (they are not needed client-side;
  everything else is public-safe by construction — no PII exists in the
  file). `listings.json` carries only the `neighborhood` id per listing;
  the profile is joined client-side.
- `defaults` in `listings.json` gains `cities` and `excluded_neighborhoods`.

### Filter bar

- City chips: one per canonical city present in the data, plus an
  "אחר" chip when any listing has a non-canonical or missing city. Default
  all on. A listing passes if its city's chip is on (missing/unknown city
  falls under "אחר").
- Neighborhood chips: a collapsible group per city, each chip labelled
  `<name> (<count>)`, default all on. Listings with no neighborhood are
  never hidden by this group. Reset re-enables everything.
- State persists in localStorage under the existing key; unknown ids in
  saved state are ignored, missing ids default to on (same rule as source
  chips).

### Card

- Below the address: neighborhood display name, a reputation pill
  colour-coded by tier (green / blue / amber / grey), up to three tag chips
  in Hebrew.
- A `<details>` disclosure "פרטים על השכונה" reveals `summary`, then
  `pros` and `cons` as two short lists.
- A "Street View" link (`https://www.google.com/maps?layer=c&cbll=<lat>,<lon>`)
  when coordinates exist. Plain link, opens in a new tab, no API key.
- Cards without a resolved neighborhood show only the Street View link.
- All rendering stays DOM-only (`textContent`, `createElement`), no
  `innerHTML`; URLs pass through `safeHttpUrl`.

### Map

- Popup gains the neighborhood display name. No other change.

## 5. Testing

- `enrich/neighborhood`: point inside a polygon, on a border pixel (either
  neighbour acceptable but deterministic), outside all polygons, in a
  hole, multipolygon; no coordinates → text fallback hit and miss; caching
  behaviour (miss-with-coords cached, miss-without-coords not cached);
  never raises on malformed listing.
- `enrich/city`: table test over all variants and a few negatives.
- Knowledge-base validation test: every entry has all required fields,
  `reputation` in enum, tags in vocabulary, `city` canonical, at least two
  pros and two cons, at least one source key present in
  `docs/neighborhoods-sources.md`; every GeoJSON feature id exists in the
  knowledge base; GeoJSON parses, features are (Multi)Polygon, file
  ≤ 300 KB.
- `Filters`: city and neighborhood semantics including fail-open, default
  values, load from a legacy file without the new keys, round-trip.
- Commands: each new command, unknown/ambiguous names, chat-id guard.
- Serialise/deserialise round-trip and cluster pooling for `neighborhood`.
- Portal builder: `neighborhood` in `PUBLIC_FIELDS`, `neighborhoods.json`
  published with `notes`/`sources` stripped, defaults include the new
  filter fields.
- Existing suite (552 tests) stays green.

## Out of scope (recorded so they are not re-litigated)

- Personal fit scoring / "best fit" sort.
- OSM POI context (parks, transit, café density, main-road proxy).
- Street View imagery download or vision analysis.
- Per-listing AI write-ups (candidate for the phase-5 daily Claude agent).
- Neighborhoods outside Tel Aviv-Yafo, Givatayim, Ramat Gan.
- Editing the knowledge base from Telegram or the portal.

## Amendments (as built, 2026-09-05)

- Boundaries come from OpenStreetMap `place=suburb|neighbourhood|quarter`
  for all three cities; the municipality administrative-boundary layer is
  not used.
- The GeoJSON carries the three city boundaries as `kind: "city"` fallback
  features, so a listing that lands inside a city but outside every mapped
  neighborhood resolves to the city-level profile (`tel_aviv_yafo`,
  `givatayim`, `ramat_gan`) instead of `None`.
- `/exclude` and `/include` resolve a typed name by exact alias match
  (after normalisation), replying "not found" or listing the ambiguous
  options — not fuzzy suggestions.
- Portal neighborhood chips default to all-on regardless of
  `excluded_neighborhoods`; that filter only gates Telegram alerts, not
  what the portal displays.
- Text-fallback neighborhood matches (no usable coordinates) are never
  cached and never overwrite the listing's own city — only a point-in-
  polygon match is trusted enough for both.
