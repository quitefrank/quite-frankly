"""Thumbnail acquisition for the Everything Else section.

Every external step (download, decode) degrades to None on failure. A row that
resolves nothing falls back to a per-source tile, so the text-only row is now a
last resort rather than the normal failure mode. Nothing here may raise into the
send path.

Failures used to be invisible: both leaves swallowed their exception and
returned a bare None, so four consecutive editions silently shipped rows with no
thumbnail before anyone noticed. Every failure path now records why, at the leaf
that knows, and _resolve_one prints it with the item id attached.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import requests
from PIL import Image

from config import (
    EE_THUMB_FETCH_MAX_BYTES,
    EE_THUMB_FETCH_TIMEOUT_S,
    EE_THUMB_MAX_WORKERS,
    EE_THUMB_SIZE,
    EE_TILE_DEFAULT,
    EE_TILE_DIR,
)


# Per-thread scratch space for the last leaf failure. The leaves know the http
# status, byte count and content-type; _resolve_one knows the item id and url.
# A thread-local carries the former to the latter without changing any public
# signature, so an injected test fetch() keeps working untouched — it simply
# leaves nothing behind and the caller falls back to a generic reason.
# resolve_ee_thumbnails runs one item per worker thread, so there is no sharing.
_diag = threading.local()


def _set_diag(**kw) -> None:
    _diag.info = kw


def _take_diag() -> dict:
    """Read and clear this thread's last leaf diagnostic."""
    info = getattr(_diag, "info", None)
    _diag.info = None
    return info or {}


def _fmt_diag(**fields) -> str:
    """Render diagnostic fields as key=value pairs, skipping empties."""
    return " ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, ""))


def to_square_thumbnail(raw: bytes, size: int = 80) -> "bytes | None":
    """Center-crop raw image bytes to a square and resize to size×size PNG."""
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        w, h = img.size
        edge = min(w, h)
        left = (w - edge) // 2
        top = (h - edge) // 2
        img = img.crop((left, top, left + edge, top + edge)).resize(
            (size, size), Image.LANCZOS
        )
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:  # noqa: BLE001 — any decode/crop/save failure degrades to None
        _set_diag(stage="decode", reason=type(e).__name__, bytes=len(raw or b""))
        return None


_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _image_headers(url: str) -> "dict[str, str]":
    """Browser-like headers for an image download. Many news hosts (and CDNs
    with hotlink protection) reject a bare requests UA or require a same-origin
    Referer; without these the server-side thumbnail fetch 403s and the row
    drops to the AI fallback even though the article has a real image."""
    from urllib.parse import urlparse

    headers = {
        "User-Agent": _BROWSER_USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        # Full Chrome fingerprint: hosts behind a Cloudflare-style WAF 403
        # datacenter/CI image requests that lack Client-Hints and the
        # image-subresource Fetch-Metadata headers a real browser sends.
        "sec-ch-ua": '"Google Chrome";v="126", "Chromium";v="126", "Not.A/Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    }
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def fetch_remote_thumbnail(url: str) -> "bytes | None":
    """Download an image URL, capped and timed out. None on any failure.

    Records the http status, byte count, content-type and elapsed time via
    _set_diag on every exit. `elapsed` is the field that separates a timeout
    from an instant reset, which is the distinction a bare None destroyed.
    """
    started = time.monotonic()
    status = None
    ctype = None
    try:
        with requests.get(
            url, timeout=EE_THUMB_FETCH_TIMEOUT_S, stream=True, headers=_image_headers(url)
        ) as r:
            # getattr: diagnostics must never be the thing that breaks a download.
            status = getattr(r, "status_code", None)
            headers = getattr(r, "headers", None) or {}
            ctype = (headers.get("Content-Type") or "").split(";")[0] or None
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(chunk_size=8192):
                buf.extend(chunk)
                if len(buf) > EE_THUMB_FETCH_MAX_BYTES:
                    # Silent early return, no exception: invisible before this.
                    _set_diag(
                        stage="fetch", reason="oversize", http=status, ctype=ctype,
                        bytes=len(buf), elapsed=f"{time.monotonic() - started:.2f}s",
                    )
                    return None
            return bytes(buf)
    except Exception as e:  # noqa: BLE001 — any download failure degrades to None
        _set_diag(
            stage="fetch", reason=type(e).__name__, http=status, ctype=ctype,
            bytes=0, elapsed=f"{time.monotonic() - started:.2f}s",
        )
        return None


def _tile_slug(source: str) -> str:
    """Filesystem-safe key for a source name. 'r/toronto' -> 'r-toronto'."""
    out = "".join(ch.lower() if ch.isalnum() else "-" for ch in source.strip())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


@lru_cache(maxsize=None)
def _read_tile(path_str: str) -> "bytes | None":
    try:
        raw = Path(path_str).read_bytes()
        return raw or None
    except Exception:  # noqa: BLE001 — a missing tile falls through to text
        return None


def source_tile(source: str, *, tile_dir: "str | None" = None) -> "bytes | None":
    """Committed per-source tile bytes, falling back to the neutral default.

    Static files on disk: no network, no API, no quota, and nothing to fail at
    send time. Returns None only when both the source tile and the default are
    missing, which is why the text-only row in formatting.py stays reachable.
    """
    base = Path(tile_dir or EE_TILE_DIR)
    for name in (f"{_tile_slug(source)}.png" if source else "", EE_TILE_DEFAULT):
        if not name:
            continue
        raw = _read_tile(str(base / name))
        if raw is not None:
            return raw
    return None


@dataclass
class ThumbAsset:
    cid: str
    data: bytes
    mime: str = "image/png"


def _cache_path(cache_dir: str, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.png"


def _read_valid_cache(path: "Path") -> "bytes | None":
    """Return cached bytes only if the file exists and decodes as a valid image."""
    try:
        raw = path.read_bytes()
        if not raw:
            return None
        Image.open(io.BytesIO(raw)).verify()
        return raw
    except Exception:  # noqa: BLE001
        return None


def _resolve_one(lid, link, cache_dir, fetch) -> "tuple[int, ThumbAsset | None, str]":
    """Resolve one row's thumbnail. Returns (lid, asset, outcome).

    `outcome` is one of cache / article / noimage / fetch_failed / decode_failed
    / error, and feeds the run summary. The noimage and fetch_failed split is the
    load-bearing one: noimage is structural (a Reddit text post or a skip-listed
    podcast has no image to get), fetch_failed is an anomaly worth chasing.
    """
    source = link.get("source", "")
    try:
        url = link.get("link", "") or str(lid)
        path = _cache_path(cache_dir, url)

        cached = _read_valid_cache(path)
        if cached is not None:
            return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=cached), "cache"

        # Resolution chain: the article image (og:image) first, then a static
        # per-source tile. The tile cannot fail the way AI generation did — it is
        # a committed file, so no quota, no safety filter, no latency. ("always
        # show one")
        thumb = None
        outcome = "article"
        image_url = link.get("image")
        if not image_url:
            # No image to fetch at all. Structural for Reddit text posts and for
            # sources in SOURCES_SKIP_OG_IMAGE, and it logged nothing before.
            outcome = "noimage"
            print(
                f"  [ee-thumb] lid={lid} FAIL "
                + _fmt_diag(stage="noimage", reason="empty_image_url", source=source, url=url),
                flush=True,
            )
        else:
            _take_diag()  # clear any stale entry left on this worker thread
            try:
                raw = fetch(image_url)
            except Exception as e:  # noqa: BLE001 — a failed fetch falls back to a tile
                _set_diag(stage="fetch", reason=type(e).__name__)
                raw = None
            if raw is not None:
                thumb = to_square_thumbnail(raw, size=EE_THUMB_SIZE)
            if thumb is None:
                diag = _take_diag()
                stage = diag.pop("stage", "fetch")
                outcome = "decode_failed" if stage == "decode" else "fetch_failed"
                diag.setdefault("reason", "returned_none")
                print(
                    f"  [ee-thumb] lid={lid} FAIL "
                    + _fmt_diag(stage=stage, **diag, source=source, url=image_url),
                    flush=True,
                )

        if thumb is None:
            tile = source_tile(source)
            if tile is None:
                return lid, None, "error"
            tile_thumb = to_square_thumbnail(tile, size=EE_THUMB_SIZE)
            if tile_thumb is None:
                return lid, None, "error"
            # Returns above the cache write below by design. _cache_path keys on
            # the ARTICLE link and _read_valid_cache only checks that bytes
            # decode, never what they depict — so caching a tile would serve it
            # for that article forever, outliving whatever caused the failure.
            return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=tile_thumb), outcome

        # Atomic write: write to a temp file then rename so a crash never leaves
        # a half-written (corrupt/empty) cache file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, thumb)
        finally:
            os.close(fd)
        os.replace(tmp, path)

        return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=thumb), "article"
    except Exception as e:  # noqa: BLE001 — resolution must never raise into the send path
        print(f"  [ee-thumb] resolve failed for item {lid} ({e}); falling back to text.", flush=True)
        return lid, None, "error"


def _emit_run_summary(counts: "dict[str, int]", total: int) -> None:
    """Print the per-run tally and raise a CI warning when tiles were used.

    The tile is designed to sit naturally in the section, so the email itself no
    longer signals that anything failed. This tally is the only signal, which is
    why it is unconditional and why fetch_failed is called out separately from
    the structural noimage count.
    """
    article = counts.get("article", 0) + counts.get("cache", 0)
    tiles = counts.get("noimage", 0) + counts.get("fetch_failed", 0) + counts.get("decode_failed", 0)
    print(
        f"  [ee-thumb] summary: {total} rows · {article} article · {tiles} tile "
        f"({counts.get('noimage', 0)} no-image, {counts.get('fetch_failed', 0)} fetch-failed, "
        f"{counts.get('decode_failed', 0)} decode-failed) · {counts.get('error', 0)} text",
        flush=True,
    )
    if not tiles and not counts.get("error"):
        return
    msg = (
        f"Everything Else: {tiles}/{total} rows fell back to a source tile "
        f"({counts.get('noimage', 0)} no-image, {counts.get('fetch_failed', 0)} fetch-failed, "
        f"{counts.get('decode_failed', 0)} decode-failed, {counts.get('error', 0)} text-only)"
    )
    print(f"::warning title=EE thumbnails::{msg}", flush=True)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(f"- ⚠️ {msg}\n")
        except Exception:  # noqa: BLE001 — a summary write must never break the send
            pass


def resolve_ee_thumbnails(
    items, *, cache_dir, fetch=fetch_remote_thumbnail
) -> "dict[int, ThumbAsset]":
    """Resolve a thumbnail per (id, link). Cache -> og:image -> per-source tile.
    Items that fail every path are omitted (row falls back to text)."""
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    out: "dict[int, ThumbAsset]" = {}
    counts: "dict[str, int]" = {}
    items = list(items)
    with ThreadPoolExecutor(max_workers=EE_THUMB_MAX_WORKERS) as ex:
        futures = [
            ex.submit(_resolve_one, lid, link, cache_dir, fetch)
            for lid, link in items
        ]
        for fut in futures:
            lid, asset, outcome = fut.result()
            counts[outcome] = counts.get(outcome, 0) + 1
            if asset is not None:
                out[lid] = asset
    if items:
        _emit_run_summary(counts, len(items))
    return out
