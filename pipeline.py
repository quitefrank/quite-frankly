"""RSS fetching and deduplication for the newsletter pipeline."""

from __future__ import annotations

import json
import os
import re
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import feedparser
import requests

from config import (
    FEEDS,
    MIN_SNIPPET_CHARS,
    SEEN_LINKS_FILE,
    SEVEN_DAYS_S,
    SOURCES_SKIP_OG_IMAGE,
    TEST_MODE,
)


OG_IMAGE_TIMEOUT_S = 3.0
OG_IMAGE_MAX_BYTES = 16384  # <meta property="og:image"> lives in <head>; 16KB is enough.
OG_IMAGE_MAX_WORKERS = 10   # Concurrent og:image fetches in fetch_all_feeds.
FEED_FETCH_MAX_WORKERS = 10  # Concurrent feedparser.parse calls in fetch_all_feeds.

_META_TAG_RE = re.compile(r'<meta\b[^>]+>', re.IGNORECASE)
_OG_IMAGE_FAMILY_RE = re.compile(r'\bog:image\b', re.IGNORECASE)
_OG_IMAGE_SIBLING_RE = re.compile(r'\bog:image:[A-Za-z_]', re.IGNORECASE)
# Match content= followed by a double-quoted, single-quoted, or bare value.
_CONTENT_ATTR_RE = re.compile(
    r'''\bcontent\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))''',
    re.IGNORECASE,
)


def _extract_og_image_from_html(html: str) -> str:
    """Return the og:image URL from an HTML snippet, or '' if none."""
    for tag_match in _META_TAG_RE.finditer(html):
        tag = tag_match.group(0)
        if not _OG_IMAGE_FAMILY_RE.search(tag):
            continue
        # Skip og:image:width / og:image:height / og:image:secure_url — those
        # are siblings, not the image URL itself.
        if _OG_IMAGE_SIBLING_RE.search(tag):
            continue
        c = _CONTENT_ATTR_RE.search(tag)
        if c:
            return c.group(1) or c.group(2) or c.group(3) or ""
    return ""


_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _browser_headers(article_url: str) -> dict[str, str]:
    """Headers that look like a real browser request — some sites (notably
    BetterDwelling, which 403's our bot UA from GitHub Actions IPs) check
    User-Agent and/or Referer before serving the page."""
    parsed = urlparse(article_url)
    referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else article_url
    return {
        "User-Agent": _BROWSER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": referer,
    }


def _fetch_og_image(article_url: str, timeout: float = OG_IMAGE_TIMEOUT_S) -> str:
    """Fetch the article page and pull og:image from <head>. Returns "" on any failure."""
    try:
        with requests.get(
            article_url,
            timeout=timeout,
            stream=True,
            headers=_browser_headers(article_url),
        ) as r:
            r.raise_for_status()
            chunks = []
            total = 0
            for chunk in r.iter_content(chunk_size=4096):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= OG_IMAGE_MAX_BYTES:
                    break
            html = b"".join(chunks).decode("utf-8", errors="replace")
            url = _extract_og_image_from_html(html)
            if not url:
                print(f"  og:image missing in <head> for {article_url}")
            return url
    except Exception as e:
        print(f"  og:image fetch failed for {article_url}: {type(e).__name__}: {e}")
    return ""


def extract_image(entry):
    """Return an image URL from the RSS entry's own fields, or '' if none.

    og:image is no longer fetched here — it's done in parallel later by
    enrich_images_with_og_image after every feed has been read.
    """
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
            if title and link and len(summary) >= MIN_SNIPPET_CHARS:
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


def enrich_images_with_og_image(items: list[dict]) -> None:
    """Populate `item['image']` for items whose RSS gave us nothing.

    Runs og:image fetches concurrently with a bounded ThreadPoolExecutor so
    the ~150 fallback fetches per daily run finish in ~30 seconds instead of
    the ~6 minutes the old sequential path took. Mutates `items` in place.
    """
    candidates = [
        item for item in items
        if not item.get("image")
        and item.get("link")
        and item.get("source") not in SOURCES_SKIP_OG_IMAGE
    ]
    if not candidates:
        return
    start = time.time()
    enriched = 0
    with ThreadPoolExecutor(max_workers=OG_IMAGE_MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(_fetch_og_image, item["link"]): item
            for item in candidates
        }
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                url = future.result()
            except Exception:
                url = ""
            if url:
                item["image"] = url
                enriched += 1
    elapsed = time.time() - start
    print(f"  og:image enrichment: {enriched}/{len(candidates)} resolved in {elapsed:.1f}s")


def fetch_all_feeds(feeds=None):
    if feeds is None:
        feeds = FEEDS  # back-compat
    all_items: list[dict] = []
    # Fetch feeds in parallel. Each feed gets one HTTP request to its own
    # origin, so polite per-host concurrency is automatic. Order isn't
    # preserved but downstream code doesn't depend on it.
    with ThreadPoolExecutor(max_workers=FEED_FETCH_MAX_WORKERS) as executor:
        future_to_feed = {executor.submit(fetch_feed, fc): fc for fc in feeds}
        for future in as_completed(future_to_feed):
            fc = future_to_feed[future]
            try:
                items = future.result()
            except Exception as e:
                print(f"  Error fetching {fc['source']}: {e}")
                items = []
            print(f"  {fc['source']}: {len(items)} items")
            all_items.extend(items)
    # Drop within-batch link duplicates. Some feeds (e.g., NBC Meet the Press)
    # publish multiple RSS entries that point to the same show landing URL;
    # without this, both end up clustered together downstream and both get
    # featured. The cross-day cache in deduplicate() doesn't catch this
    # because the link only appears once outside the current batch.
    seen_links: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        link = item.get("link", "")
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        deduped.append(item)
    enrich_images_with_og_image(deduped)
    return deduped


def load_seen_links():
    if os.path.exists(SEEN_LINKS_FILE):
        with open(SEEN_LINKS_FILE) as f:
            return json.load(f)
    return {}


def save_seen_links(seen):
    with open(SEEN_LINKS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def deduplicate(items):
    """Return items not seen in the last SEVEN_DAYS_S window.

    Read-only: callers must invoke record_seen(fresh_items) after the email
    successfully ships, so a failed run doesn't lock items out of retries.
    """
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

    return fresh


def record_seen(items):
    """Persist items to the seen-links cache. Call after send_email succeeds."""
    if TEST_MODE or not items:
        return
    seen = load_seen_links()
    now = time.time()
    seen = {url: ts for url, ts in seen.items() if now - ts < SEVEN_DAYS_S}
    for item in items:
        link = item.get("link")
        if link:
            seen[link] = now
    save_seen_links(seen)


def assign_ids(items: list[dict]) -> dict[int, dict]:
    by_id = {}
    for idx, item in enumerate(items):
        item["id"] = idx
        by_id[idx] = item
    return by_id


def monday_dedup_bypass(items: list[dict], seen: dict) -> list[dict]:
    """On Mondays, re-admit items already in `seen` only if cluster_size >= 3."""
    return [i for i in items if i["link"] in seen and i.get("cluster_size", 0) >= 3]
