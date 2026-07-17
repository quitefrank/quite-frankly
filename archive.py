"""Rolling 7-day archive of design-feed items for the weekend editions.

Runs alongside, not inside, the main render pipeline. accumulate() is called on
every daily run and only touches design_archive.json; it never calls record_seen,
so weekday editions are unaffected. pool_for() reads the archive on weekends and
returns pipeline-shaped item dicts for that day's source set.
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

# Read deeper than the pipeline's [:10]. Archiving is cheap (no LLM), and a daily
# digest like Sidebar ships ~18 items/day, so 10 would lose half of it.
ARCHIVE_FETCH_LIMIT = 30

# Cap per source in a weekend pool so one high-volume feed (Sidebar, ~60/week)
# cannot crowd out the other four. 5 visual sources * 20 = 100 < MAX_TRIAGE_INPUT_ITEMS.
# cap_items() cannot do this: it round-robins by section, and all nine design
# feeds map to the single "Design & Product" section.
ARCHIVE_PER_SOURCE_CAP = 20

# On first sight of a link, skip it if it carries a publish date older than this.
# Trendland's feed ships items dated 2023; first-seen pruning alone would let them
# sit in the archive for 7 days. Items with no or unparseable date are kept (we
# cannot judge them) and governed by first_seen_ts.
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
            print(f"  {ARCHIVE_FILE} is corrupt; treating as empty archive")
            return {}
    return {}


def save(archive: dict) -> None:
    with open(ARCHIVE_FILE, "w") as f:
        json.dump(archive, f, indent=2)


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

    # Enrich only the newly-seen items. Fills og image/snippet once per item, so
    # cost tracks new arrivals, not the whole archive, every day.
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

    archive = {k: v for k, v in archive.items()
               if now - v.get("first_seen_ts", 0) < SEVEN_DAYS_S}

    if not TEST_MODE:
        save(archive)
    return archive
