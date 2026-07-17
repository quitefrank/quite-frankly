# Design Weekly Archive

**Date:** 2026-07-17
**Status:** Approved, ready for implementation planning
**Independent of:** the Tech & AI parking spec (`2026-07-17-park-tech-ai-design.md`)

## Goal

Make the weekend design editions draw from a rolling 7-day pool of design stories instead
of one morning's single feed fetch. Saturday surfaces the week's best *strategic* design
work; Sunday surfaces the week's best *visual* work. The existing strategic/visual split by
feed set stays exactly as-is; the only change is that the pool being ranked is a week deep
instead of a day deep.

## Why this is needed

Every edition today is built from a single fetch of the current feed contents. `fetch_feed`
takes `parsed.entries[:10]` per feed (`pipeline.py`), and that 10-item slice reaches back
wildly different distances per feed (measured 2026-07-17):

| Feed | Entries in feed | 10 entries covers | Day |
|---|---|---|---|
| Sidebar | 20 | **1.1 days** | Sun |
| Design Milk | 12 | **2.9 days** | Sun |
| It's Nice That | 20 | **3.1 days** | Sun |
| UX Collective | 10 | **3.5 days** | Sat |
| Lenny's Newsletter | 20 | 10.9 days | Sat |
| Codrops | 10 | 16.0 days | Sun |
| Smashing Magazine | 40 | 30.8 days | Sat |
| NN/g | 20 | 34.7 days | Sat |
| Trendland | 15 | dates unreliable (junk) | Sun |

Saturday's strategic feeds mostly already cover a week (Smashing, NN/g, Lenny's), but UX
Collective exposes only 10 items total, so no fetch-cap raise reaches a week for it. Sunday's
visual feeds are the real gap — Sidebar is a daily digest reaching back ~1 day. Only daily
accumulation captures a true week for the fast-moving feeds. We chose **uniform accumulation
across all 9 feeds** over a hybrid (raise the cap for slow feeds, archive only fast ones)
because the hybrid's savings are small and two paths to "the week" are harder to debug later.

## Architecture

A new module, `archive.py`, owns one rolling-7-day store, `design_archive.json`. It sits
**outside** the main pipeline's item flow. This is the core safety property: the archive
never touches `record_seen` (`pipeline.py:452`), so weekday editions behave byte-identically
to today apart from anything the parking spec changes.

### Two entry points

```
archive.accumulate()        # called every run, all 7 days, before the main pipeline
archive.pool_for(mode)      # called on weekends only, returns that day's items
```

### Data flow

```
main() [newsletter.py]
  │
  ├─ archive.accumulate()                 ← NEW, every day
  │     fetch all 9 design feeds (cap 30/feed)
  │     upsert into design_archive.json by normalized link
  │     prune entries older than 7 days (by first_seen_ts)
  │     (no triage, no render, no record_seen)
  │
  ├─ if weekend:
  │     all_items = archive.pool_for(mode)   ← REPLACES fetch_all_feeds for weekend
  │  else:
  │     all_items = fetch_all_feeds(feeds)   ← unchanged weekday path
  │
  └─ deduplicate → triage → render → send → record_seen   ← unchanged
```

On weekdays `accumulate()` runs and returns; the weekend branch is not taken, so weekday
editions are untouched. On weekends, `pool_for(mode)` returns the day's feed set drawn from
the archive, and that list enters the **existing** `deduplicate → triage → build_format_input
→ render` path with no changes. `_popularity_score` (`formatting.py:121`) now ranks a week of
candidates. `record_seen(items)` at the end still fires on the rendered weekend items only —
correct, because those are the items actually shown.

## Data design

### `design_archive.json`

A dict keyed by normalized link (same `normalize_url`, `pipeline.py:363`, as the dedup cache),
so http/www/tracking-param variants collapse. Each value:

```json
{
  "https://example.com/article": {
    "title": "...",
    "source": "Design Milk",
    "snippet": "...",
    "image": "...",
    "published_ts": 1782000000.0,   // from feed entry, may be null/unreliable
    "first_seen_ts": 1782100000.0   // when WE first archived it — the prune key
  }
}
```

Item shape must match what `deduplicate`/triage expect downstream (`title`, `link`, `source`,
`snippet`, `image`, `section_label`). `pool_for` reconstructs those fields (the dict key is
`link`; `section_label` is set from `SECTION_MAP` the same way `newsletter.py:44` does).

### Key decisions

1. **Prune by `first_seen_ts`, never publish date.** Publish dates are unreliable (Trendland's
   oldest-of-10 is dated 2023). `first_seen_ts` is authoritative and monotonic. A 7-day window
   matches `SEVEN_DAYS_S` (`config.py:8`).

2. **Junk-date sanity filter on ingest.** When a fetched entry *has* a publish date and it is
   older than 30 days, skip archiving it. This stops Trendland's stale 2023 posts from seeding
   the archive on the very first run. Entries with missing/unparseable dates are still archived
   (we can't judge them), and their freshness is governed by `first_seen_ts`.

3. **Archive fetch cap = 30/feed; render/slice cap stays 10 elsewhere.** Archiving is cheap
   (no LLM), so read deeper than the pipeline's `[:10]`. 30 covers Sidebar's ~18/day with
   headroom and captures the full Smashing/NN/g depth. (`fetch_feed`'s `[:10]` is unchanged for
   the weekday path; the archive uses its own fetch depth.)

4. **Per-source cap of 20 on the weekend pool, most-recent-first by `first_seen_ts`.** Sunday
   is 5 sources; 5 × 20 = 100 items, under `MAX_TRIAGE_INPUT_ITEMS = 120` (`triage.py:22`).
   Without this, a week of Sidebar (~60 items) drowns the other four feeds. `cap_items`
   (`triage.py:78`) does NOT save us here because it round-robins by *section*, and all nine
   design feeds map to the single "Design & Product" section. The per-source cap must live in
   `pool_for`.

5. **Committed by CI alongside `seen_links.json`.** The existing "Save seen_links cache" step
   (`.github/workflows/newsletter.yml:44-50`) is extended to `git add design_archive.json` too.
   The daily cron that already keeps `seen_links` current keeps the archive current.

## Weekend pool selection (`pool_for`)

```
pool_for(mode):
  archive = load()                                    # design_archive.json
  sources = strategic_sources if mode == SATURDAY else visual_sources
  items   = [entry for entry in archive if entry.source in sources]
  group by source; within each source sort by first_seen_ts desc; keep top 20
  return flattened list as pipeline item dicts (link, title, source, snippet, image, section_label)
```

The strategic vs visual source split reuses the existing `FEEDS_SATURDAY_STRATEGIC` /
`FEEDS_SUNDAY_VISUAL` source names (`config.py:89-102`) as the source-membership sets, so
there is one definition of which feed is strategic vs visual.

## Components and boundaries

| Unit | Responsibility | Depends on |
|---|---|---|
| `archive.accumulate()` | fetch 9 design feeds deep, upsert, prune, persist | `pipeline.fetch` primitives, `normalize_url`, `design_archive.json` |
| `archive.pool_for(mode)` | read archive, filter by day's sources, per-source cap, shape items | `design_archive.json`, `config` source sets, `SECTION_MAP` |
| `archive.load/save` | JSON persistence, mirrors `load_seen_links`/`save_seen_links` | filesystem |
| `newsletter.main()` | call `accumulate()` every run; branch weekend to `pool_for` | `archive`, `routing` |

`archive.py` can be understood and unit-tested without touching the render pipeline: give it
a fake feed fetch and a temp JSON path, assert what lands in the archive and what `pool_for`
returns. The pipeline consumes `pool_for`'s output through its existing contract.

## Error handling

- **Empty/missing archive file:** `load()` returns `{}`, `accumulate` creates it, `pool_for`
  returns `[]`. On an empty pool the weekend path should fall back to a live
  `fetch_all_feeds(weekend feeds)` so a cold start or a wiped file still ships an edition
  (degraded to today's behavior) rather than an empty newsletter.
- **A feed fails to fetch during accumulate:** log and skip that feed; the rest still upsert.
  Missing one feed for one day costs at most that feed's newest items (self-heals next run for
  slow feeds; a permanent small loss for Sidebar-class feeds, an accepted tradeoff).
- **Corrupt archive JSON:** treat as empty (same posture as a cold start) and log loudly.

## Testing

- `accumulate` upserts new links, updates nothing on re-seeing a link except leaving
  `first_seen_ts` intact (idempotent first-seen).
- Prune drops entries with `first_seen_ts` older than 7 days; keeps newer ones.
- Junk-date filter: an entry with `published_ts` > 30 days old is skipped; an entry with no
  date is kept.
- `pool_for(SATURDAY)` returns only strategic-source items; `pool_for(SUNDAY)` only visual.
- Per-source cap: 40 archived Sidebar items → `pool_for(SUNDAY)` yields ≤ 20 Sidebar items,
  the 20 most recent by `first_seen_ts`.
- Total Sunday pool with all five feeds full stays ≤ `MAX_TRIAGE_INPUT_ITEMS`.
- Empty-archive fallback: `pool_for` on `{}` triggers the live-fetch fallback in `main`.
- Item dicts from `pool_for` carry every field the downstream `deduplicate`/triage path reads.
- Weekday run: `accumulate` is called and the weekday item flow is byte-identical to pre-change
  (assert `fetch_all_feeds` still drives weekday `all_items`).

## Accepted tradeoffs

- **First week is thin.** The archive bootstraps empty and fills over 7 days; the first
  Saturday/Sunday look roughly like today. No mitigation — it self-corrects by day 8.
- **A missed daily run permanently loses that day's fast-feed items** (Sidebar-class). The
  cron has run every day through 2026-07-17 with one gap (Jun 16), so this is rare. Degrades
  quietly (fewer items), never breaks.

## Out of scope

- Changing the strategic/visual editorial split (kept as-is).
- Any change to weekday editions beyond calling `accumulate()`.
- Archiving non-design (news/tech) feeds.
- Backfilling history — the archive starts empty on first deploy.
