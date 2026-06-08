"""RSS fetching and deduplication for the newsletter pipeline."""

from __future__ import annotations

import html as html_module
import json
import os
import re
import time

from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urlparse

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


_OG_DESCRIPTION_RE = re.compile(r'\bog:description\b', re.IGNORECASE)
_TW_DESCRIPTION_RE = re.compile(r'\btwitter:description\b', re.IGNORECASE)
_NAME_DESCRIPTION_RE = re.compile(r'\bname\s*=\s*["\']?description\b', re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _extract_og_description_from_html(html: str) -> str:
    """Return the best article description from an HTML <head> snippet, or ''.

    Priority: og:description, then twitter:description, then meta name=description.
    HTML entities are unescaped and whitespace collapsed so the value reads like
    the RSS snippets it stands in for.
    """
    og = tw = name = ""
    for tag_match in _META_TAG_RE.finditer(html):
        tag = tag_match.group(0)
        c = _CONTENT_ATTR_RE.search(tag)
        if not c:
            continue
        val = (c.group(1) or c.group(2) or c.group(3) or "").strip()
        if not val:
            continue
        if _OG_DESCRIPTION_RE.search(tag):
            og = og or val
        elif _TW_DESCRIPTION_RE.search(tag):
            tw = tw or val
        elif _NAME_DESCRIPTION_RE.search(tag):
            name = name or val
    best = og or tw or name
    return _WS_RE.sub(" ", html_module.unescape(best)).strip() if best else ""


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


def _fetch_og_meta(article_url: str, timeout: float = OG_IMAGE_TIMEOUT_S) -> dict:
    """Fetch the article <head> once and pull og:image + og:description.

    Returns {"image": str, "description": str}; either field is "" if absent or
    on any failure. One fetch serves both the image fallback and the snippet
    backfill, so a title-only item (e.g. an HN link-post) costs no extra HTTP.
    """
    out = {"image": "", "description": ""}
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
            out["image"] = _extract_og_image_from_html(html)
            out["description"] = _extract_og_description_from_html(html)
            if not out["image"]:
                print(f"  og:image missing in <head> for {article_url}")
    except Exception as e:
        print(f"  og:meta fetch failed for {article_url}: {type(e).__name__}: {e}")
    return out


def extract_image(entry):
    """Return an image URL from the RSS entry's own fields, or '' if none.

    og:image is no longer fetched here — it's done in parallel later by
    enrich_from_og_metadata after every feed has been read.
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
                snippet = summary[:300]
                # hnrss.org ships a metadata-only description on every link
                # post (Article URL / Comments URL / Points / # Comments).
                # Strip it so renderers and the LLM see no snippet rather
                # than a URL dump. Ask HN posts carry real prose and stay.
                if feed_config["source"] == "Hacker News" and snippet.startswith("Article URL:"):
                    snippet = ""
                items.append({
                    "title":   title,
                    "link":    link,
                    "snippet": snippet,
                    "image":   extract_image(entry),
                    "source":  feed_config["source"],
                })
    except Exception as e:
        print(f"  Error fetching {feed_config['source']}: {e}")
    return items


OG_DESCRIPTION_SNIPPET_CAP = 300  # Match fetch_feed's RSS-snippet cap.


def enrich_from_og_metadata(items: list[dict]) -> None:
    """Backfill `item['image']` and `item['snippet']` from the article's <head>.

    One fetch per item supplies both: the og:image fallback for items whose RSS
    carried no image, and an og:description snippet for items that arrived
    title-only (notably HN link-posts, whose hnrss snippet is stripped at
    ingest). A populated snippet is what lets triage cluster cross-publisher
    duplicates and the token backstop catch clustering misses, so this directly
    strengthens dedup as well as rendering. Only fetches when image OR snippet
    is missing; never overwrites an existing snippet. Mutates `items` in place.

    Runs concurrently with a bounded ThreadPoolExecutor so the fallback fetches
    per daily run finish in ~30s instead of the ~6 minutes a sequential path
    took.
    """
    candidates = [
        item for item in items
        if item.get("link")
        and item.get("source") not in SOURCES_SKIP_OG_IMAGE
        and (not item.get("image") or not item.get("snippet"))
    ]
    if not candidates:
        return
    start = time.time()
    images = snippets = 0
    with ThreadPoolExecutor(max_workers=OG_IMAGE_MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(_fetch_og_meta, item["link"]): item
            for item in candidates
        }
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            try:
                meta = future.result()
            except Exception:
                meta = {"image": "", "description": ""}
            if not item.get("image") and meta.get("image"):
                item["image"] = meta["image"]
                images += 1
            if not item.get("snippet") and meta.get("description"):
                item["snippet"] = meta["description"][:OG_DESCRIPTION_SNIPPET_CAP]
                snippets += 1
    elapsed = time.time() - start
    print(
        f"  og:meta enrichment: {images} image(s), {snippets} snippet(s) "
        f"from {len(candidates)} fetches in {elapsed:.1f}s"
    )


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
    # Keyed on normalize_url so the same article carrying different tracking
    # params (or an http/www variant) across two feeds collapses to one item.
    seen_links: set[str] = set()
    deduped: list[dict] = []
    for item in all_items:
        link = item.get("link", "")
        key = normalize_url(link)
        if key and key in seen_links:
            continue
        if key:
            seen_links.add(key)
        deduped.append(item)
    enrich_from_og_metadata(deduped)
    return deduped


# Query params that track a click and never identify the article. Stripped
# before a URL becomes a dedup key. utm_* is matched by prefix. Content-bearing
# params (?p=, ?id=, ?storyId=) are deliberately NOT here — stripping them would
# collapse every article on a query-id site into one key.
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "yclid", "twclid",
    "mc_cid", "mc_eid", "igshid", "_ga", "ref_src", "ref_url",
})
_AMP_PATH_RE = re.compile(r"/amp/?$", re.IGNORECASE)


def normalize_url(url: str) -> str:
    """Return a canonical dedup key for a URL, or '' if there's nothing to key on.

    Collapses the variations that make one article look like two distinct links:
    the scheme (http vs https), a www/m/amp host prefix, a trailing slash or
    /amp path segment, tracking query params (utm_*, fbclid, gclid, mc_cid, …),
    and the fragment. Remaining query params are kept and sorted, so distinct
    articles on query-id sites (?p=, ?id=) stay distinct.

    The result is used only for comparison; item['link'] keeps its original URL
    so the newsletter still links to the real, clickable page.
    """
    url = (url or "").strip()
    if not url:
        return ""
    # urlparse only fills netloc when a scheme (or //) is present. Feed links
    # always carry a scheme; the prefix guards the defensive bare-host case.
    if "://" not in url:
        url = "//" + url
    parts = urlparse(url)
    host = (parts.netloc or "").lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    for prefix in ("www.", "m.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    path = _AMP_PATH_RE.sub("/", parts.path or "")
    if path == "/":
        path = ""
    elif len(path) > 1:
        path = path.rstrip("/")
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
        and not any(k.lower().startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    kept.sort()
    norm = host + path
    if kept:
        norm += "?" + urlencode(kept)
    return norm


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
    # Normalize every cached key on read so legacy raw entries (written before
    # normalize_url existed) still match today's normalized incoming links.
    # Keep the newest timestamp when two raw keys collapse to one normal form.
    seen_norm: dict[str, float] = {}
    for url, ts in seen.items():
        if now - ts >= SEVEN_DAYS_S:
            continue
        key = normalize_url(url)
        if key and ts > seen_norm.get(key, 0):
            seen_norm[key] = ts

    fresh = [i for i in items if normalize_url(i["link"]) not in seen_norm]

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
    # Store the normalized key so http/www/tracking-param variants of an
    # article seen today are recognized as duplicates on future runs.
    for item in items:
        key = normalize_url(item.get("link", ""))
        if key:
            seen[key] = now
    save_seen_links(seen)


def assign_ids(items: list[dict]) -> dict[int, dict]:
    by_id = {}
    for idx, item in enumerate(items):
        item["id"] = idx
        by_id[idx] = item
    return by_id


# ---- Content-similarity primitives for the clustering-miss backstop ----

_YOUTUBE_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "are", "its", "it", "this", "that", "as", "at", "by", "from", "how", "why",
    "what", "new", "up", "out", "his", "her", "she", "he", "they", "you", "your",
    "i", "we", "s", "was", "were", "has", "have", "will",
})


def youtube_id(text: str) -> str:
    """Return an 11-char YouTube video id found in text, or '' if none."""
    m = _YOUTUBE_RE.search(text or "")
    return m.group(1) if m else ""


def canonical_key(item: dict) -> str:
    """A high-confidence same-story key, or '' if none can be derived.

    Keys off a shared YouTube video id found in the item's link or snippet.
    Two items with the same non-empty key are the same story with near
    certainty. (When article-body fetching lands, og:url / rel=canonical and
    body-embedded video ids can feed in here too.)
    """
    vid = youtube_id(item.get("link", "")) or youtube_id(item.get("snippet", ""))
    return f"yt:{vid}" if vid else ""


def normalize_text(text: str) -> frozenset:
    """Lowercased significant-token set for fuzzy story matching.

    Drops stopwords and tokens of 2 chars or fewer so similarity reflects the
    proper nouns and content words that identify a story (people, companies,
    products), not boilerplate.
    """
    return frozenset(
        t for t in _TOKEN_RE.findall((text or "").lower())
        if t not in _STOPWORDS and len(t) > 2
    )
