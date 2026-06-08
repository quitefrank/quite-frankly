"""Thumbnail acquisition for the Everything Else section.

Every external step (download, generate, decode) degrades to None on failure;
callers treat None as "no thumbnail" and fall back to a text-only row. Nothing
here may raise into the send path.
"""
from __future__ import annotations

import io

from PIL import Image


def to_square_thumbnail(raw: bytes, size: int = 80) -> "bytes | None":
    """Center-crop raw image bytes to a square and resize to size×size PNG."""
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001 — any decode failure degrades to None
        return None
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
