"""RSS fetching and deduplication for the newsletter pipeline."""

from __future__ import annotations

import json
import os
import re
import time

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


def extract_image(entry, skip_og_fallback: bool = False):
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

    # Last resort: fetch the article page and pull og:image. WordPress-based
    # feeds (e.g., BetterDwelling) ship no image fields in RSS but expose
    # og:image in the article's <head>. Sources whose feed link points at a
    # podcast/audio endpoint (not an article) opt out via skip_og_fallback.
    if skip_og_fallback:
        return ""
    link = getattr(entry, "link", "") or ""
    if link:
        return _fetch_og_image(link)

    return ""


def fetch_feed(feed_config):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; QuiteFramkly/1.0)"}
        parsed = feedparser.parse(feed_config["url"], request_headers=headers)
        skip_og = feed_config["source"] in SOURCES_SKIP_OG_IMAGE
        for entry in parsed.entries[:10]:
            link  = getattr(entry, "link",  "") or ""
            title = getattr(entry, "title", "") or ""
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "") or "").strip()
            if title and link and len(summary) >= MIN_SNIPPET_CHARS:
                items.append({
                    "title":   title,
                    "link":    link,
                    "snippet": summary[:300],
                    "image":   extract_image(entry, skip_og_fallback=skip_og),
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
