"""Thumbnail acquisition for the Everything Else section.

Every external step (download, generate, decode) degrades to None on failure;
callers treat None as "no thumbnail" and fall back to a text-only row. Nothing
here may raise into the send path.
"""
from __future__ import annotations

import hashlib
import io
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import requests
from PIL import Image

from config import (
    EE_IMAGE_PROMPT_TEMPLATE,
    EE_THUMB_FETCH_MAX_BYTES,
    EE_THUMB_FETCH_TIMEOUT_S,
    EE_THUMB_MAX_WORKERS,
    EE_THUMB_SIZE,
    GEMINI_IMAGE_MODEL,
)


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
    except Exception:  # noqa: BLE001 — any decode/crop/save failure degrades to None
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
    }
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def fetch_remote_thumbnail(url: str) -> "bytes | None":
    """Download an image URL, capped and timed out. None on any failure."""
    try:
        with requests.get(
            url, timeout=EE_THUMB_FETCH_TIMEOUT_S, stream=True, headers=_image_headers(url)
        ) as r:
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(chunk_size=8192):
                buf.extend(chunk)
                if len(buf) > EE_THUMB_FETCH_MAX_BYTES:
                    return None
            return bytes(buf)
    except Exception:  # noqa: BLE001 — any download failure degrades to None
        return None


def generate_thumbnail(title: str, snippet: str, *, api_key: "str | None" = None) -> "bytes | None":
    """Generate an editorial illustration via Gemini. None on any failure,
    including a missing GEMINI_API_KEY (logged no-op, never a crash)."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        print("  [ee-thumb] GEMINI_API_KEY missing; skipping AI image.", flush=True)
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        prompt = EE_IMAGE_PROMPT_TEMPLATE.format(title=title, snippet=snippet or "")
        resp = client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for part in resp.candidates[0].content.parts:
            data = getattr(getattr(part, "inline_data", None), "data", None)
            if data:
                return data
        return None
    except Exception as e:  # noqa: BLE001 — generation must never break the send
        print(f"  [ee-thumb] generation failed ({e}); falling back to text.", flush=True)
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


def _resolve_one(lid, link, cache_dir, fetch, gen) -> "tuple[int, ThumbAsset | None]":
    try:
        url = link.get("link", "") or str(lid)
        path = _cache_path(cache_dir, url)

        cached = _read_valid_cache(path)
        if cached is not None:
            return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=cached)

        # Resolution chain: article image (og:image) first, AI generation only as
        # a fallback when the article image is absent, undownloadable, or corrupt.
        # Each source is isolated so one failing falls through to the next rather
        # than dropping the row to text. ("always show one")
        thumb = None
        image_url = link.get("image")
        if image_url:
            try:
                raw = fetch(image_url)
            except Exception:  # noqa: BLE001 — a failed fetch falls back to gen
                raw = None
            if raw is not None:
                thumb = to_square_thumbnail(raw, size=EE_THUMB_SIZE)
        if thumb is None:
            try:
                raw = gen(link.get("title", ""), link.get("snippet", ""))
            except Exception:  # noqa: BLE001 — generation must never break the send
                raw = None
            if raw is not None:
                thumb = to_square_thumbnail(raw, size=EE_THUMB_SIZE)
        if thumb is None:
            return lid, None

        # Atomic write: write to a temp file then rename so a crash never leaves
        # a half-written (corrupt/empty) cache file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            os.write(fd, thumb)
        finally:
            os.close(fd)
        os.replace(tmp, path)

        return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=thumb)
    except Exception as e:  # noqa: BLE001 — resolution must never raise into the send path
        print(f"  [ee-thumb] resolve failed for item {lid} ({e}); falling back to text.", flush=True)
        return lid, None


def resolve_ee_thumbnails(
    items, *, cache_dir, fetch=fetch_remote_thumbnail, gen=generate_thumbnail
) -> "dict[int, ThumbAsset]":
    """Resolve a thumbnail per (id, link). Cache -> og:image -> AI generate.
    Items that fail every path are omitted (row falls back to text)."""
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    out: "dict[int, ThumbAsset]" = {}
    with ThreadPoolExecutor(max_workers=EE_THUMB_MAX_WORKERS) as ex:
        futures = [
            ex.submit(_resolve_one, lid, link, cache_dir, fetch, gen)
            for lid, link in items
        ]
        for fut in futures:
            lid, asset = fut.result()
            if asset is not None:
                out[lid] = asset
    return out
