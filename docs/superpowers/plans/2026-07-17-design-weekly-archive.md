# Design Weekly Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make weekend design editions draw from a rolling 7-day archive of the 9 design feeds instead of one morning's single fetch, so Saturday shows the week's best strategic work and Sunday the week's best visual work.

**Architecture:** A new `archive.py` module keeps `design_archive.json`, a link-keyed store pruned to 7 days by first-seen time. `accumulate()` runs every day (fetches all 9 design feeds deep, enriches only newly-seen items, upserts, prunes) and sits outside the render pipeline — it never touches `record_seen`, so weekday editions are unchanged. On weekends, `pool_for(mode)` returns that day's source set from the archive as pipeline-shaped item dicts, which flow through the existing `deduplicate → triage → render` path untouched.

**Tech Stack:** Python 3.11, pytest, feedparser. Files: `pipeline.py`, `archive.py` (new), `newsletter.py`, `.github/workflows/newsletter.yml`, `design_archive.json` (new), tests.

**Spec:** `docs/superpowers/specs/2026-07-17-design-weekly-archive-design.md`

**Depends on:** nothing. Independent of the Tech & AI parking plan; can land before or after it.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `pipeline.py` | Modify | `fetch_feed` gains a `limit` param and always emits `published_ts`; add a `_entry_published_ts` helper |
| `archive.py` | Create | The archive: `load`/`save`, `accumulate`, `pool_for`, constants, design-feed/source sets |
| `newsletter.py` | Modify | Call `accumulate()` every run; branch weekend item-source to `pool_for` with a live-fetch fallback |
| `design_archive.json` | Create | Initial `{}` committed so CI's `git add` is clean from day one |
| `.github/workflows/newsletter.yml` | Modify | `git add design_archive.json` in the existing cache-save step |
| `tests/test_pipeline.py` | Modify | `fetch_feed` limit + `published_ts` tests |
| `tests/test_archive.py` | Create | Upsert, junk-date filter, enrich-new, prune, `pool_for` filtering/cap/shape |
| `tests/test_smoke.py` | Modify | Stub `accumulate`/`pool_for` so `main()` stays offline and day-independent |

---

## Task 1: Give `fetch_feed` a depth limit and a published timestamp

The archive must read deeper than the pipeline's `[:10]` and needs each entry's publish
date for the junk-date filter. Both are additive: `limit` defaults to today's 10, and
`published_ts` is a new key downstream code ignores.

**Files:**
- Modify: `pipeline.py:230-257` (`fetch_feed`) and add a helper above it
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline.py` (the `_fake_parsed` helper there builds entries without
dates; add a dated variant next to it):

```python
def _fake_parsed_with_dates(entries):
    # entries: (title, link, summary, published_struct_or_None)
    import time as _t
    parsed = type("Parsed", (), {})()
    parsed.entries = []
    for title, link, summary, published in entries:
        e = type("Entry", (), {})()
        e.title = title
        e.link = link
        e.summary = summary
        if published is not None:
            e.published_parsed = published
        parsed.entries.append(e)
    return parsed


def test_fetch_feed_emits_published_ts_from_entry():
    import calendar, time
    struct = time.gmtime(1_782_000_000)  # a fixed UTC instant
    entries = [("Design systems in 2026", "https://uxdesign.cc/a",
                "A meaningful summary sentence for the formatter to use.", struct)]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed_with_dates(entries)):
        items = fetch_feed({"url": "x", "source": "UX Collective"})
    assert items[0]["published_ts"] == calendar.timegm(struct)


def test_fetch_feed_published_ts_is_none_when_absent():
    entries = [("No date here", "https://uxdesign.cc/b",
                "A meaningful summary sentence for the formatter to use.", None)]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed_with_dates(entries)):
        items = fetch_feed({"url": "x", "source": "UX Collective"})
    assert items[0]["published_ts"] is None


def test_fetch_feed_limit_controls_entry_count():
    entries = [(f"Title {i}", f"https://uxdesign.cc/{i}",
                "A meaningful summary sentence for the formatter to use.", None)
               for i in range(25)]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed_with_dates(entries)):
        assert len(fetch_feed({"url": "x", "source": "UX Collective"})) == 10          # default
        assert len(fetch_feed({"url": "x", "source": "UX Collective"}, limit=30)) == 25  # deeper
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_pipeline.py -k "published_ts or limit_controls" -v`
Expected: FAIL — `KeyError: 'published_ts'` and a `TypeError` for the unexpected `limit` kwarg.

- [ ] **Step 3: Add the published-timestamp helper**

In `pipeline.py`, immediately above `def fetch_feed` (line 230), add:

```python
def _entry_published_ts(entry):
    """UTC epoch seconds for a feed entry, or None if it carries no usable date.

    Prefers published_parsed, falls back to updated_parsed. Uses calendar.timegm
    (not time.mktime) so the struct_time — which feedparser returns in UTC — is
    read as UTC rather than local time."""
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not struct:
        return None
    try:
        return calendar.timegm(struct)
    except (TypeError, ValueError):
        return None
```

Add `import calendar` to the top of `pipeline.py` if not already present.

- [ ] **Step 4: Add the `limit` param and `published_ts` field**

Change `fetch_feed`'s signature and the two touched lines (`pipeline.py:230`, `:236`, and
the appended dict at `:248-254`):

```python
def fetch_feed(feed_config, limit: int = 10):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; QuiteFramkly/1.0)"}
        parsed = feedparser.parse(feed_config["url"], request_headers=headers)
        channel_link = getattr(getattr(parsed, "feed", None), "link", "") or ""
        for entry in parsed.entries[:limit]:
            link  = resolve_entry_link(entry, channel_link)
            title = getattr(entry, "title", "") or ""
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "") or "").strip()
            if title and link and len(summary) >= MIN_SNIPPET_CHARS:
                snippet = summary[:300]
                if feed_config["source"] == "Hacker News" and snippet.startswith("Article URL:"):
                    snippet = ""
                items.append({
                    "title":   title,
                    "link":    link,
                    "snippet": snippet,
                    "image":   extract_image(entry),
                    "source":  feed_config["source"],
                    "published_ts": _entry_published_ts(entry),
                })
    except Exception as e:
        print(f"  Error fetching {feed_config['source']}: {e}")
    return items
```

- [ ] **Step 5: Run the pipeline suite to verify pass and no regressions**

Run: `venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS. Existing `fetch_feed` tests still pass — they assert only on `title`/`snippet`
and never on exact dict equality, so the additive `published_ts` key is invisible to them.

- [ ] **Step 6: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: fetch_feed gains limit param and published_ts field

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Create `archive.py` with load/save and the feed/source sets

**Files:**
- Create: `archive.py`
- Test: `tests/test_archive.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_archive.py`:

```python
import json
import archive
from config import FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "nope.json"))
    assert archive.load() == {}


def test_save_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "a.json"))
    archive.save({"k": {"title": "t"}})
    assert archive.load() == {"k": {"title": "t"}}


def test_design_feeds_and_source_sets_cover_all_nine():
    # DESIGN_FEEDS is the union of the two weekend feed sets.
    assert archive.DESIGN_FEEDS == FEEDS_SATURDAY_STRATEGIC + FEEDS_SUNDAY_VISUAL
    assert archive.STRATEGIC_SOURCES == {f["source"] for f in FEEDS_SATURDAY_STRATEGIC}
    assert archive.VISUAL_SOURCES == {f["source"] for f in FEEDS_SUNDAY_VISUAL}
    assert len(archive.STRATEGIC_SOURCES | archive.VISUAL_SOURCES) == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_archive.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'archive'`.

- [ ] **Step 3: Create the module skeleton**

Create `archive.py`:

```python
"""Rolling 7-day archive of design-feed items for the weekend editions.

Runs alongside — not inside — the main render pipeline. accumulate() is called
on every daily run and only touches design_archive.json; it never calls
record_seen, so weekday editions are unaffected. pool_for() reads the archive on
weekends and returns pipeline-shaped item dicts for that day's source set.
"""

from __future__ import annotations

import json
import os
import time

import pipeline
from config import FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL, SEVEN_DAYS_S, TEST_MODE
from pipeline import normalize_url
from routing import Mode

ARCHIVE_FILE = "design_archive.json"

# Read deeper than the pipeline's [:10] — archiving is cheap (no LLM), and a
# daily digest like Sidebar ships ~18 items/day, so 10 would lose half of it.
ARCHIVE_FETCH_LIMIT = 30

# Cap per source in a weekend pool so one high-volume feed (Sidebar, ~60/week)
# can't crowd out the other four. 5 visual sources * 20 = 100 < MAX_TRIAGE_INPUT_ITEMS.
# cap_items() can't do this — it round-robins by section, and all nine design
# feeds map to the single "Design & Product" section.
ARCHIVE_PER_SOURCE_CAP = 20

# On first sight of a link, skip it if it carries a publish date older than this.
# Trendland's feed ships items dated 2023; first-seen pruning alone would let
# them sit in the archive for 7 days. Items with no/unparseable date are kept
# (we can't judge them) and governed by first_seen_ts.
JUNK_DATE_MAX_AGE_S = 30 * 24 * 60 * 60

DESIGN_FEEDS = FEEDS_SATURDAY_STRATEGIC + FEEDS_SUNDAY_VISUAL
STRATEGIC_SOURCES = {f["source"] for f in FEEDS_SATURDAY_STRATEGIC}
VISUAL_SOURCES = {f["source"] for f in FEEDS_SUNDAY_VISUAL}


def load() -> dict:
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            print(f"  {ARCHIVE_FILE} is corrupt — treating as empty archive")
            return {}
    return {}


def save(archive: dict) -> None:
    with open(ARCHIVE_FILE, "w") as f:
        json.dump(archive, f, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_archive.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add archive.py tests/test_archive.py
git commit -m "feat: archive module skeleton (load/save + feed sets)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement `accumulate()`

Fetch the 9 design feeds deep, filter junk-dated first-sightings, enrich only the
newly-seen items, upsert with an immutable `first_seen_ts`, prune to 7 days.

**Files:**
- Modify: `archive.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_archive.py`:

```python
def _entry(link, source, snippet="a real snippet", image="", published_ts=None):
    return {"title": f"t-{link}", "link": link, "snippet": snippet,
            "image": image, "source": source, "published_ts": published_ts}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "a.json"))


def test_accumulate_upserts_new_items_with_first_seen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    result = archive.accumulate(
        now=1000.0,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Design Milk" else [],
        enrich_fn=lambda items: None,
    )
    key = archive.normalize_url("https://design-milk.com/x")
    assert key in result
    assert result[key]["first_seen_ts"] == 1000.0
    assert result[key]["source"] == "Design Milk"
    assert result[key]["link"] == "https://design-milk.com/x"


def test_accumulate_keeps_original_first_seen_on_reseen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    ff = lambda fc, limit: fetched if fc["source"] == "Design Milk" else []
    archive.accumulate(now=1000.0, fetch_feed_fn=ff, enrich_fn=lambda i: None)
    result = archive.accumulate(now=5000.0, fetch_feed_fn=ff, enrich_fn=lambda i: None)
    key = archive.normalize_url("https://design-milk.com/x")
    assert result[key]["first_seen_ts"] == 1000.0  # unchanged on re-sighting


def test_accumulate_skips_junk_dated_first_sightings(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = 1_000_000_000.0
    stale = now - archive.JUNK_DATE_MAX_AGE_S - 1
    fetched = [_entry("https://trendland.com/old", "Trendland", published_ts=stale)]
    result = archive.accumulate(
        now=now,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Trendland" else [],
        enrich_fn=lambda i: None,
    )
    assert result == {}  # 2023-dated item never enters the archive


def test_accumulate_keeps_undated_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://sidebar.io/z", "Sidebar", published_ts=None)]
    result = archive.accumulate(
        now=1000.0,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Sidebar" else [],
        enrich_fn=lambda i: None,
    )
    assert archive.normalize_url("https://sidebar.io/z") in result


def test_accumulate_prunes_entries_older_than_seven_days(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from config import SEVEN_DAYS_S
    archive.save({"old": {"title": "t", "source": "Sidebar", "link": "https://sidebar.io/old",
                          "snippet": "", "image": "", "published_ts": None,
                          "first_seen_ts": 100.0}})
    now = 100.0 + SEVEN_DAYS_S + 1
    result = archive.accumulate(now=now, fetch_feed_fn=lambda fc, limit: [],
                                enrich_fn=lambda i: None)
    assert "old" not in result


def test_accumulate_enriches_only_new_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = []
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    ff = lambda fc, limit: fetched if fc["source"] == "Design Milk" else []
    archive.accumulate(now=1000.0, fetch_feed_fn=ff, enrich_fn=lambda items: seen.append(len(items)))
    archive.accumulate(now=2000.0, fetch_feed_fn=ff, enrich_fn=lambda items: seen.append(len(items)))
    assert seen == [1, 0]  # enriched 1 new item first run, 0 on the re-sighting
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_archive.py -k accumulate -v`
Expected: FAIL — `AttributeError: module 'archive' has no attribute 'accumulate'`.

- [ ] **Step 3: Implement `accumulate`**

Append to `archive.py`:

```python
def accumulate(*, now: float | None = None, fetch_feed_fn=None, enrich_fn=None) -> dict:
    """Fetch every design feed, add newly-seen items, prune to 7 days, persist.

    Pure with respect to the render pipeline: no triage, no record_seen. Injected
    fetch_feed_fn/enrich_fn keep it unit-testable offline; defaults hit the network.
    Returns the pruned archive (also written to ARCHIVE_FILE unless TEST_MODE).
    """
    now = time.time() if now is None else now
    fetch_feed_fn = fetch_feed_fn or (lambda fc, limit: pipeline.fetch_feed(fc, limit=limit))
    enrich_fn = enrich_fn or pipeline.enrich_from_og_metadata

    archive = load()

    new_pairs: list[tuple[str, dict]] = []
    seen_this_run: set[str] = set()
    for fc in DESIGN_FEEDS:
        try:
            fetched = fetch_feed_fn(fc, ARCHIVE_FETCH_LIMIT)
        except Exception as e:
            print(f"  archive: error fetching {fc['source']}: {e}")
            continue
        for it in fetched:
            key = normalize_url(it.get("link", ""))
            if not key or key in archive or key in seen_this_run:
                continue
            pub = it.get("published_ts")
            if pub is not None and now - pub > JUNK_DATE_MAX_AGE_S:
                continue  # stale backfill (e.g. Trendland's 2023 dates)
            seen_this_run.add(key)
            new_pairs.append((key, it))

    # Enrich only the newly-seen items — fills og image/snippet once per item,
    # so cost tracks new arrivals, not the whole archive, every day.
    enrich_fn([it for _, it in new_pairs])

    for key, it in new_pairs:
        archive[key] = {
            "title": it.get("title", ""),
            "source": it.get("source", ""),
            "snippet": it.get("snippet", ""),
            "image": it.get("image", ""),
            "published_ts": it.get("published_ts"),
            "first_seen_ts": now,
            "link": it.get("link", ""),
        }

    archive = {k: v for k, v in archive.items() if now - v["first_seen_ts"] < SEVEN_DAYS_S}

    if not TEST_MODE:
        save(archive)
    return archive
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_archive.py -k accumulate -v`
Expected: PASS (all six accumulate tests).

- [ ] **Step 5: Commit**

```bash
git add archive.py tests/test_archive.py
git commit -m "feat: archive.accumulate — upsert, junk-date filter, enrich-new, prune

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Implement `pool_for()`

**Files:**
- Modify: `archive.py`
- Test: `tests/test_archive.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_archive.py`:

```python
def _archived(link, source, first_seen_ts):
    return {"title": f"t-{link}", "source": source, "snippet": "s", "image": "",
            "published_ts": None, "first_seen_ts": first_seen_ts, "link": link}


def test_pool_for_saturday_returns_only_strategic_sources(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({
        "a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0),
        "b": _archived("https://design-milk.com/1", "Design Milk", 20.0),
    })
    pool = archive.pool_for(Mode_SAT())
    sources = {i["source"] for i in pool}
    assert sources == {"UX Collective"}


def test_pool_for_sunday_returns_only_visual_sources(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({
        "a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0),
        "b": _archived("https://design-milk.com/1", "Design Milk", 20.0),
    })
    pool = archive.pool_for(Mode_SUN())
    assert {i["source"] for i in pool} == {"Design Milk"}


def test_pool_for_caps_per_source_to_most_recent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    entries = {f"k{i}": _archived(f"https://sidebar.io/{i}", "Sidebar", float(i))
               for i in range(40)}
    archive.save(entries)
    pool = archive.pool_for(Mode_SUN())
    sidebar = [i for i in pool if i["source"] == "Sidebar"]
    assert len(sidebar) == archive.ARCHIVE_PER_SOURCE_CAP
    # Kept the 20 highest first_seen_ts (39..20), newest first.
    links = [i["link"] for i in sidebar]
    assert links[0] == "https://sidebar.io/39"
    assert "https://sidebar.io/0" not in links


def test_pool_for_items_have_pipeline_shape(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({"a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0)})
    item = archive.pool_for(Mode_SAT())[0]
    assert set(item) == {"title", "link", "snippet", "image", "source"}


def test_pool_for_weekday_mode_returns_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({"a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0)})
    assert archive.pool_for(Mode_WEEKDAY()) == []
```

Add these mode helpers at the top of `tests/test_archive.py` (below the imports):

```python
from routing import Mode
def Mode_SAT(): return Mode.SATURDAY_STRATEGIC
def Mode_SUN(): return Mode.SUNDAY_VISUAL
def Mode_WEEKDAY(): return Mode.WEEKDAY_DAILY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_archive.py -k pool_for -v`
Expected: FAIL — `AttributeError: module 'archive' has no attribute 'pool_for'`.

- [ ] **Step 3: Implement `pool_for`**

Append to `archive.py`:

```python
def pool_for(mode: Mode) -> list[dict]:
    """Return this weekend day's design items from the archive as pipeline-shaped
    dicts. Saturday draws strategic sources, Sunday visual. Per source, keep the
    ARCHIVE_PER_SOURCE_CAP most recently first-seen items. Weekday modes get []."""
    if mode == Mode.SATURDAY_STRATEGIC:
        sources = STRATEGIC_SOURCES
    elif mode == Mode.SUNDAY_VISUAL:
        sources = VISUAL_SOURCES
    else:
        return []

    by_source: dict[str, list[dict]] = {}
    for entry in load().values():
        if entry.get("source") in sources:
            by_source.setdefault(entry["source"], []).append(entry)

    pool: list[dict] = []
    for entries in by_source.values():
        entries.sort(key=lambda e: e.get("first_seen_ts", 0), reverse=True)
        for e in entries[:ARCHIVE_PER_SOURCE_CAP]:
            pool.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "snippet": e.get("snippet", ""),
                "image": e.get("image", ""),
                "source": e.get("source", ""),
            })
    return pool
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_archive.py -v`
Expected: PASS (entire archive suite).

- [ ] **Step 5: Commit**

```bash
git add archive.py tests/test_archive.py
git commit -m "feat: archive.pool_for — weekend source filter + per-source cap

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire the archive into `newsletter.main()`

`accumulate()` runs every day. On weekends the item source becomes `pool_for(mode)`, with a
live-fetch fallback when the archive is empty (cold start or wiped file) so an edition still
ships. Weekday item flow is byte-identical to today.

**Files:**
- Modify: `newsletter.py:25` (import) and `newsletter.py:29-40` (main flow)
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Update the smoke test to keep `main()` offline**

`test_smoke.py::test_main_runs_through_two_passes` calls the real `main()` on the real
current date. Once `main` calls `accumulate()` and (on weekends) `pool_for()`, those must be
stubbed or the test hits the network and becomes day-dependent. Add these monkeypatches
inside the test, alongside the existing `newsletter.*` stubs (after line 22):

```python
    # The archive runs every day now; stub it offline and force the weekend
    # branch (if today is a weekend) down to the live-fetch fallback, which is
    # itself stubbed via newsletter.fetch_all_feeds above.
    monkeypatch.setattr(newsletter, "accumulate", lambda: None)
    monkeypatch.setattr(newsletter, "pool_for", lambda mode: [])
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `AttributeError: <module 'newsletter'> does not have the attribute 'accumulate'`
(the monkeypatch target doesn't exist yet).

- [ ] **Step 3: Import the archive functions into newsletter**

In `newsletter.py`, after the existing imports (around line 26, below the `images` import), add:

```python
from archive import accumulate, pool_for
```

- [ ] **Step 4: Call `accumulate` and branch the weekend item source**

In `newsletter.py`, replace the current fetch block (lines 34-37):

```python
    feeds = get_feeds_for_mode(mode)
    with _stage("fetch_feeds"):
        all_items = fetch_all_feeds(feeds)
    print(f"Raw items: {len(all_items)}", flush=True)
```

with:

```python
    # Keep the rolling design archive current on every run (all 7 days). This is
    # out-of-band from the render pipeline and never calls record_seen, so
    # weekday editions are unaffected.
    with _stage("archive_accumulate"):
        accumulate()

    feeds = get_feeds_for_mode(mode)
    with _stage("fetch_feeds"):
        if is_design_mode(mode):
            all_items = pool_for(mode)
            if not all_items:
                print("Design archive empty — falling back to live weekend fetch", flush=True)
                all_items = fetch_all_feeds(feeds)
        else:
            all_items = fetch_all_feeds(feeds)
    print(f"Raw items: {len(all_items)}", flush=True)
```

`is_design_mode` is already imported (`newsletter.py:22`). Downstream is unchanged: the
`section_label` loop (`newsletter.py:43-44`) sets labels from `SECTION_MAP` on whatever
`items` `deduplicate` returns, and `pool_for` items carry the same
`{title, link, snippet, image, source}` shape `fetch_all_feeds` produces, so they flow
through `deduplicate → triage → render → record_seen` identically.

- [ ] **Step 5: Run the smoke test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add newsletter.py tests/test_smoke.py
git commit -m "feat: weekend editions draw items from the design archive

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Persist the archive in CI and seed the initial file

**Files:**
- Create: `design_archive.json`
- Modify: `.github/workflows/newsletter.yml:44-50`

- [ ] **Step 1: Confirm the file is not gitignored**

Run: `git check-ignore design_archive.json; echo "exit=$?"`
Expected: `exit=1` (not ignored). The `.gitignore` lists `comparison/`, `tmp/`, caches — not
this file. If it prints the filename (exit 0), stop and add an exception; otherwise continue.

- [ ] **Step 2: Seed an empty archive**

Create `design_archive.json` with exactly:

```json
{}
```

- [ ] **Step 3: Extend the CI cache-save step**

In `.github/workflows/newsletter.yml`, replace the "Save seen_links cache" step body
(lines 44-50) so it also stages and commits the archive:

```yaml
      - name: Save caches
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add seen_links.json design_archive.json
          git diff --staged --quiet || git commit -m "chore: update caches [skip ci]"
          git push
```

- [ ] **Step 4: Sanity-check the workflow YAML parses**

Run: `venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/newsletter.yml')); print('YAML OK')"`
Expected: `YAML OK`. (If PyYAML isn't installed in the venv, `pip install pyyaml` first or
skip — the change is a two-line edit to an existing valid step.)

- [ ] **Step 5: Commit**

```bash
git add design_archive.json .github/workflows/newsletter.yml
git commit -m "chore: persist design_archive.json in CI cache step

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: End-to-end verification

**Files:** none modified — verification only.

- [ ] **Step 1: Full suite green**

Run: `venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 2: Real accumulate against live feeds (offline-safe read)**

Run:
```bash
venv/bin/python -c "
import archive, tempfile, os
archive.ARCHIVE_FILE = os.path.join(tempfile.gettempdir(), 'arch_smoke.json')
a = archive.accumulate()
print('archived items:', len(a))
from collections import Counter
print(Counter(v['source'] for v in a.values()))
assert all('first_seen_ts' in v for v in a.values())
print('OK — every entry has first_seen_ts')
"
```
Expected: a non-zero count (network permitting), a per-source breakdown across the 9 design
sources, and the OK line. Trendland should contribute few or zero (junk-date filter).

- [ ] **Step 3: Pool shape and cap for both weekend days**

Run:
```bash
venv/bin/python -c "
import archive, os, tempfile
archive.ARCHIVE_FILE = os.path.join(tempfile.gettempdir(), 'arch_smoke.json')
from routing import Mode
for m in (Mode.SATURDAY_STRATEGIC, Mode.SUNDAY_VISUAL):
    pool = archive.pool_for(m)
    from collections import Counter
    c = Counter(i['source'] for i in pool)
    print(m.value, '->', len(pool), 'items', dict(c))
    assert all(cnt <= archive.ARCHIVE_PER_SOURCE_CAP for cnt in c.values())
    assert len(pool) <= 120
    assert all(set(i)=={'title','link','snippet','image','source'} for i in pool)
print('OK — pools within caps and correctly shaped')
"
```
Expected: Saturday shows only strategic sources, Sunday only visual, each source ≤ 20, total
≤ 120, correct item keys, then the OK line.

- [ ] **Step 4: Clean up the smoke archive**

Run: `rm -f "$(venv/bin/python -c 'import tempfile,os;print(os.path.join(tempfile.gettempdir(),"arch_smoke.json"))')"`
Expected: no output.

---

## Self-Review Notes

- **Spec coverage:** daily accumulate outside pipeline (Task 5), 7-day prune by first_seen
  (Task 3), junk-date filter (Task 3), archive fetch depth 30 (Task 1 + Task 3 constant),
  per-source cap 20 (Task 4), reuse of `normalize_url` (Tasks 2-3), item shape matches
  fetch_feed (Task 4 + Task 5 note), empty-archive live-fetch fallback (Task 5), CI persist
  (Task 6), enrich-only-new-items (Task 3). All covered.
- **Deviation from spec, noted:** spec said `pool_for` sets `section_label` from `SECTION_MAP`;
  implementation omits it because `newsletter.main`'s existing `section_label` loop
  (`newsletter.py:43-44`) already sets it on post-`deduplicate` items — adding it in `pool_for`
  would be dead work. Downstream behavior is identical. (DRY/YAGNI.)
- **TEST_MODE:** `accumulate` skips `save()` in TEST_MODE, mirroring `record_seen`'s TEST_MODE
  guard, so `[TEST]` runs don't rewrite the committed archive (keeps CI's `git diff --staged
  --quiet` true, nothing commits). A weekend TEST run reads the prior on-disk archive — an
  accepted, documented degradation.
- **No placeholders:** every code step shows full code.
- **Type consistency:** `fetch_feed(feed_config, limit=10)`, `published_ts`,
  `first_seen_ts`, `accumulate(*, now, fetch_feed_fn, enrich_fn)`,
  `pool_for(mode)`, `ARCHIVE_FETCH_LIMIT`/`ARCHIVE_PER_SOURCE_CAP`/`JUNK_DATE_MAX_AGE_S`,
  `DESIGN_FEEDS`/`STRATEGIC_SOURCES`/`VISUAL_SOURCES` used identically across tasks. The
  injected `fetch_feed_fn` is always called as `fetch_feed_fn(fc, limit)` (positional),
  matching both the default lambda and every test stub.
