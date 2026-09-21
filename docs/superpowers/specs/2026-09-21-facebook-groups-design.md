# Facebook groups source — design

Date: 2026-09-21
Status: approved by user in chat (brainstorm), pending spec review
Builds on: `2026-08-31-apt-scout-design.md` (phases 1–4), the yad2 local
feed (`src/apt_scout/local_feed.py`), carry-forward on failure (2026-09-05).

## Goal

Ingest posts from public Facebook rental groups without any Facebook
account or paid API, dedup them against each other and against the other
sources, and keep a per-group yield ledger so the user can drop groups
that never produce a matching apartment.

Decisions made during brainstorming (user's choices in bold):

- **No login.** Anonymous access from a real browser on the user's PC.
  A logged-in profile or an Apify actor may come later; the post record
  is provider-agnostic so either can replace the collector unchanged.
- Yield is measured by **posts that matched the alert filters** (option
  A), credited only to the first group an apartment was seen in.
- Price-less posts **alert like any other source** (option B), subject to
  the global "include price missing" toggle.

## Facts established by probing (2026-09-21)

- Plain HTTP (`curl`, httpx) gets HTTP 400 from `facebook.com/groups/…`.
- A real browser with no login renders a public group's feed: the newest
  3–7 posts with full text, author, relative time; scrolling further opens
  the login dialog. Three groups verified: ApartmentsTelAviv,
  101875683484689, 333022240594651.
- After ~10 anonymous group visits within a few minutes from one IP,
  every group URL redirects to `/login` for that IP, including from fresh
  browser profiles. The block had not lifted 80 minutes later; the
  recovery time is still being measured and sets the defaults in §2.
- The login page triggers a Windows passkey prompt on the user's desktop;
  the collector must abort navigation to `/login` rather than render it.

## 1. Groups and the post record

`config/facebook_groups.json`:

```json
{
  "groups": [
    {"id": "ApartmentsTelAviv", "name": "דירות להשכרה ריקות או שותפים בתל אביב", "enabled": true},
    {"id": "101875683484689", "name": "דירות מפה לאוזן בתל אביב", "enabled": true}
  ]
}
```

- `id` is the path segment after `/groups/` (numeric or slug). The 18
  unique groups from the user's two lists are seeded; duplicates in the
  user's lists (`101875683484689`, `tel.aviv.dirot`, `458499457501175`)
  appear once. `name` is filled from the page title on first visit if
  left empty.
- Disabling a group stops visits but keeps its ledger row.

Post record (what the collector writes, what the adapter reads; the
contract any future provider must meet):

| field | type | notes |
|---|---|---|
| `group_id` | str | config id |
| `post_id` | str | Facebook post id from the permalink |
| `url` | str | `https://www.facebook.com/groups/<group>/posts/<post_id>/` |
| `text` | str | full visible text, "See more" expanded when the page allows it |
| `posted_at` | ISO str \| null | from the relative time label ("5 שעות", "אתמול", "3 ימים") resolved against `fetched_at` |
| `photos` | list[str] | image URLs, may be empty |
| `fetched_at` | ISO str | when the visit happened |

No author name, profile link or avatar is stored anywhere. Phone numbers
in `text` are hashed by the existing enrichment and stripped from
anything published, as for every source.

## 2. PC collector — `apt_scout.fb_groups.collect`

- CLI `python -m apt_scout.fb_groups --repo .`, called by
  `scripts/local_yad2_feed.ps1` right after the yad2 feed (the script is
  renamed in docs as "local feeds" but keeps its filename and task name).
- Config (`config/sources.json` → `fb_groups`): `enabled`, `cadence_hours`
  1 (cloud parse cadence), `feed_file` `state/feeds/facebook_groups.json`,
  `feed_max_age_hours` 24, `batch_size` 3, `min_hours_between_visits` 5,
  `max_post_age_days` 3, `backoff_hours_initial` 1, `backoff_hours_max` 24,
  `visit_gap_seconds` 20. Defaults are placeholders until the probe
  reports; the plan records the measured value.
- Rotation state `state/fb_groups_rotation.json`:
  `{"groups": {<id>: {"last_visit": iso, "last_outcome": "ok|blocked|error|empty"}}, "blocked_until": iso|null, "backoff_hours": float}`.
- One run: if `now < blocked_until` → exit 0 with a log line, no visits.
  Otherwise pick up to `batch_size` enabled groups whose `last_visit` is
  older than `min_hours_between_visits`, least recent first. For each:
  fresh Playwright context (channel `chrome`, headed, window positioned
  off-screen, locale he-IL, no storage), route `**/login*` → abort, goto
  the group URL, wait for `[role=article]` up to 15 s, extract posts,
  close the context, sleep `visit_gap_seconds`.
- Block detection: navigation aborted by the login route, or the page has
  zero articles and contains the login form markers. On block: record the
  outcome, set `blocked_until = now + backoff_hours`, double
  `backoff_hours` (cap `backoff_hours_max`), stop the batch. A clean visit
  resets `backoff_hours` to `backoff_hours_initial`.
- Extraction (DOM, inside the page): for each `[role=article]`: text via
  `innerText` of the message container after clicking a "עוד"/"See more"
  button inside it if present (anonymous pages allow this for text);
  permalink from the first anchor whose href matches `/groups/<id>/posts/<num>`
  or `/posts/<num>`; relative time from that anchor's text or `aria-label`;
  photos from `img` elements inside the article with a `scontent` host.
  A post without a resolvable `post_id` is skipped.
- Feed output: read the existing feed (if any), drop posts older than
  `max_post_age_days` or from groups no longer in the config, upsert this
  run's posts by `(group_id, post_id)` (newer `fetched_at` wins, text
  replaced), write `{"source": "fb_groups", "fetched_at": now,
  "posts": [...]}` atomically. The PS1 script commits and pushes the feed
  file exactly as it does for yad2 (one `git add` for both files).
- Ledger visits: each visit increments `visits` (and `blocked` when it
  was blocked) in `state/fb_groups_yield.json` (§4); `posts_seen`
  increments by the number of posts extracted. The collector is the only
  writer of these three counters; the cloud writes the rest.
- Never raises: any exception in one group is that group's `error`
  outcome; the run continues with the next group. Exit code 0 unless the
  feed file could not be written.

## 3. Cloud adapter — `adapters/fb_groups.py`

- Reads the feed like `Yad2Adapter._load_feed` (source check, freshness
  via `feed_max_age_hours`, list shape). No network path: when the feed is
  missing or stale the adapter returns an error result, and the
  carry-forward-on-failure logic keeps the last listings up to 24 h.
- For each post: skip when `posted_at` is older than `max_post_age_days`;
  skip **seeker** posts (`is_seeker_text` in `enrich/seeker.py`: any of
  "מחפש דירה", "מחפשת דירה", "מחפשים דירה", "מחפש/ת", "looking for a",
  "looking for an apartment", "wanted:", "דרושה דירה", "מעוניין לשכור",
  "מעוניינת לשכור" in the first 200 characters of normalised text and no
  price present); emit
  `Listing(source="fb_groups", source_id=f"{group_id}:{post_id}", url,
  title=first non-empty line (≤120 chars), raw_text=text, photos,
  posted_at, occupancy=UNSURE, sources=[])` with a new field
  `Listing.group_id: str | None` (in `PUBLIC_FIELDS`; the portal maps it to
  the group name from a published `data/groups.json`).
- Everything else is existing machinery: `_fill_from_text` (price, rooms,
  size), occupancy, sublet, phone hash, geocoding (address text is what the
  text contains; often nothing), neighborhood text fallback, distance and
  drive time when coordinates exist, filters, alerts.
- Alert text and the card show "קבוצה: <name>" and link to the permalink.
  A Marketplace-style 7-day age cap is unnecessary: the collector already
  drops posts older than 3 days.

### Dedup

- New strong fingerprint `texthash:<sha1 of normalised text>` emitted for
  any listing whose normalised text is at least 80 characters. Identical
  cross-posts (the common case) merge on it; reworded ones fall back to
  phone (strong) and the struct/geo/text weak pairs. Emitted for all
  sources: an identical description on yad2 and in a group is the same
  apartment.
- The intra-source dedup in the collector (`(group_id, post_id)` upsert)
  handles the same post seen on two visits.

## 4. Yield ledger — `state/fb_groups_yield.json`

```json
{"<group_id>": {"visits": 0, "blocked": 0, "posts_seen": 0,
                "offers": 0, "listings": 0, "matched": 0,
                "last_matched_at": null}}
```

- `visits`, `blocked`, `posts_seen`: written by the collector (§2).
- `offers`: incremented by the adapter per post that survived the age and
  seeker checks (counted once per `(group_id, post_id)` via a
  `counted_offers` id set stored alongside, pruned with the feed window).
- `listings`: same, for offers whose enriched listing has a price or a
  room count (counted in the pipeline after enrichment, keyed by stable
  id, once).
- `matched`: in the pipeline, when a cluster passes `filters.matches` for
  the first time (its cluster id not in `matched_clusters`), and the
  member with the earliest `first_seen_at` is an `fb_groups` listing,
  that member's `group_id` gets +1 and `last_matched_at = now`. Ties on
  `first_seen_at` resolve by source priority then stable id. Re-posts to
  other groups never earn credit; a yad2 listing later cross-posted to a
  group earns the group nothing.
- `matched_clusters` lives in `state/fb_groups_yield.json` under a
  `_clusters` key so the "first time" rule survives across runs.
- Surfaces: portal health footer gets a collapsible "קבוצות פייסבוק"
  table (name, visits, blocked, offers, listings, matched, last matched);
  Telegram `/groups` prints the same, sorted by `matched` descending, plus
  the current backoff state. Removing a group stays a manual config edit.

## 5. Portal and alerts

- Source chip `fb_groups` appears automatically (chips are built from the
  data). Card badge: group name (from `data/groups.json`, published by the
  builder from the config: id → name only). Link text "לפוסט בקבוצה".
- Health footer: `fb_groups` entry uses the existing detail mechanism; the
  collector's block state is written into `state/health.json` detail by
  the adapter ("חסום עד 18:40" when `blocked_until` is in the future).

## 6. Testing

- Post parser: saved DOM fixture (one group page, anonymised text) →
  expected post records; a "See more" case; a post without a permalink is
  skipped; relative-time resolution table (שעות/דקות/אתמול/ימים/English).
- Rotation: least-recent-first selection; `min_hours_between_visits`;
  batch stops on block; backoff doubling and cap; reset on success;
  `blocked_until` skip.
- Feed merge: upsert, age pruning, removed-group pruning, atomic write.
- Seeker classifier table; `texthash` fingerprint threshold and merge;
  adapter parsing incl. stale feed → error result.
- Ledger: each counter's once-only rule; the first-group credit rule with
  a cross-post; `_clusters` persistence.
- Portal builder publishes `data/groups.json`; `group_id` in
  `PUBLIC_FIELDS`; asset tests for the new badge/footer hooks; commands
  test for `/groups`.
- No live Facebook call in CI. A manual smoke script
  `scripts/fb_groups_smoke.py` visits one group and prints the records.

## Out of scope

- Logging in, private groups, scrolling beyond the first screen.
- Apify or any paid provider (the post record is the seam for it).
- Comments, reactions, author identity.
- Automatic removal of low-yield groups.
