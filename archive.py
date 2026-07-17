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
