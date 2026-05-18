"""RSS fetching and deduplication for the newsletter pipeline."""

from __future__ import annotations

import json
import os
import re
import time

import feedparser

from config import FEEDS, SEEN_LINKS_FILE, SEVEN_DAYS_S, TEST_MODE


def extract_image(entry):
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if m.get("type", "").startswith("image") or url.lower().endswith(("jpg", "jpeg", "png", "webp")):
                return url

    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")

    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href", enc.get("url", ""))

    summary = getattr(entry, "summary", "") or ""
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)

    return ""


def fetch_feed(feed_config):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; QuiteFramkly/1.0)"}
        parsed = feedparser.parse(feed_config["url"], request_headers=headers)
        for entry in parsed.entries[:10]:
            link  = getattr(entry, "link",  "") or ""
            title = getattr(entry, "title", "") or ""
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "") or "").strip()
            if title and link:
                items.append({
                    "title":   title,
                    "link":    link,
                    "snippet": summary[:300],
                    "image":   extract_image(entry),
                    "source":  feed_config["source"],
                })
    except Exception as e:
        print(f"  Error fetching {feed_config['source']}: {e}")
    return items


def fetch_all_feeds(feeds=None):
    if feeds is None:
        feeds = FEEDS  # back-compat
    all_items = []
    for feed_config in feeds:
        items = fetch_feed(feed_config)
        print(f"  {feed_config['source']}: {len(items)} items")
        all_items.extend(items)
        time.sleep(0.5)
    return all_items


def load_seen_links():
    if os.path.exists(SEEN_LINKS_FILE):
        with open(SEEN_LINKS_FILE) as f:
            return json.load(f)
    return {}


def save_seen_links(seen):
    with open(SEEN_LINKS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def deduplicate(items):
    if TEST_MODE:
        print("[TEST MODE] Bypassing dedup cache; subject will be prefixed [TEST]")
        return items

    seen = load_seen_links()
    now  = time.time()
    seen = {url: ts for url, ts in seen.items() if now - ts < SEVEN_DAYS_S}

    fresh = [i for i in items if i["link"] not in seen]

    if not fresh:
        print("  All items seen before - using full list (likely a test run)")
        fresh = items

    for item in fresh:
        seen[item["link"]] = now

    save_seen_links(seen)
    return fresh


def assign_ids(items: list[dict]) -> dict[int, dict]:
    by_id = {}
    for idx, item in enumerate(items):
        item["id"] = idx
        by_id[idx] = item
    return by_id


def monday_dedup_bypass(items: list[dict], seen: dict) -> list[dict]:
    """On Mondays, re-admit items already in `seen` only if cluster_size >= 3."""
    return [i for i in items if i["link"] in seen and i.get("cluster_size", 0) >= 3]
