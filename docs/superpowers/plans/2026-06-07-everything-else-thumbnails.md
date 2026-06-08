# Everything Else Thumbnails + AI Fallback Images — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an 80×80 thumbnail and two-sentence blurb to each Everything Else row, sourcing the image from the article's `og:image` or, when absent, an AI-generated editorial illustration (Google AI Studio / Gemini), embedded inline via CID.

**Architecture:** A new `images.py` module owns all thumbnail acquisition (download / generate / crop / disk-cache) behind injectable callables. `build_everything_else` gains an `images_by_id` param for two-column rendering. `build_email_html` returns `(html, subject, inline_images)`; `send_email` sends `multipart/related` with CID image parts. Copy length is targeted per item (Everything Else = 2 sentences, Other Headlines = 1) through the existing single batched blurb call.

**Tech Stack:** Python 3, `requests`, `Pillow` (new), `google-genai` (new), `pytest`, Gmail SMTP, GitHub Actions.

**Spec:** [docs/superpowers/specs/2026-06-07-everything-else-thumbnails-design.md](../specs/2026-06-07-everything-else-thumbnails-design.md)

**Conventions:** Work directly on `main` (no worktrees/branches for this project). Run tests with `venv/bin/pytest`. Image/network work must never raise into the send path — every external step degrades to `None`.

---

### Task 1: Add dependencies and verify the Gemini image model

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add the two new runtime deps**

Append to `requirements.txt`:

```
Pillow>=10.0.0
google-genai>=0.3.0
```

- [ ] **Step 2: Install them into the venv**

Run: `venv/bin/pip install -r requirements.txt`
Expected: Pillow and google-genai install successfully.

- [ ] **Step 3: Verify imports resolve**

Run: `venv/bin/python -c "import PIL, google.genai; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Verify the image model is reachable (build-time confirmation #1)**

Run (requires `GEMINI_API_KEY` in env):
```bash
GEMINI_API_KEY=$GEMINI_API_KEY venv/bin/python - <<'PY'
from google import genai
from google.genai import types
import os
c = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
r = c.models.generate_content(
    model="gemini-2.5-flash-image",
    contents="A flat editorial illustration of a city skyline, muted palette, no text.",
    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
)
parts = r.candidates[0].content.parts
got = [p for p in parts if getattr(p, "inline_data", None) and p.inline_data.data]
print("image bytes:", len(got[0].inline_data.data) if got else 0)
PY
```
Expected: prints a non-zero byte count. If the model id or `response_modalities` shape errors, adjust to the working value and record it; that value becomes `GEMINI_IMAGE_MODEL` in Task 2.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt
git commit -m "build: add Pillow and google-genai for Everything Else thumbnails"
```

---

### Task 2: Add config constants

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Append the thumbnail config block**

Add to `config.py` (end of file):

```python
# --- Everything Else thumbnails ---
EE_THUMB_SIZE = 80                     # rendered thumbnail edge, px
EE_THUMB_RADIUS = 8                    # CSS border-radius, px
EE_THUMB_CACHE_DIR = "tmp/ee_thumb_cache"
EE_THUMB_FETCH_TIMEOUT_S = 4.0         # download an og:image
EE_THUMB_FETCH_MAX_BYTES = 5_000_000   # cap a downloaded image at 5 MB
EE_THUMB_MAX_WORKERS = 6               # concurrent resolves

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"  # confirmed in Task 1
GEMINI_IMAGE_TIMEOUT_S = 20.0

# Editorial, deliberately non-photoreal so an AI image never reads as a real
# news photo. {title}/{snippet} are filled per item.
EE_IMAGE_PROMPT_TEMPLATE = (
    "Create a flat, minimal editorial illustration representing this news item. "
    "Use a calm, muted palette and simple geometric shapes. Absolutely no text, "
    "no logos, no real faces, no photorealism. Square composition.\n\n"
    "Headline: {title}\nContext: {snippet}"
)
```

- [ ] **Step 2: Verify it imports**

Run: `venv/bin/python -c "import config; print(config.GEMINI_IMAGE_MODEL, config.EE_THUMB_SIZE)"`
Expected: prints `gemini-2.5-flash-image 80`.

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat: add Everything Else thumbnail config constants"
```

---

### Task 3: `to_square_thumbnail` — crop + resize

**Files:**
- Create: `images.py`
- Test: `tests/test_images.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_images.py`:

```python
import io
from PIL import Image

from images import to_square_thumbnail


def _png(width, height, color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def test_to_square_thumbnail_resizes_nonsquare_to_80x80():
    out = to_square_thumbnail(_png(200, 100), size=80)
    assert out is not None
    img = Image.open(io.BytesIO(out))
    assert img.size == (80, 80)


def test_to_square_thumbnail_returns_none_on_garbage():
    assert to_square_thumbnail(b"not an image", size=80) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_images.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'images'`.

- [ ] **Step 3: Write minimal implementation**

Create `images.py`:

```python
"""Thumbnail acquisition for the Everything Else section.

Every external step (download, generate, decode) degrades to None on failure;
callers treat None as "no thumbnail" and fall back to a text-only row. Nothing
here may raise into the send path.
"""
from __future__ import annotations

import io

from PIL import Image


def to_square_thumbnail(raw: bytes, size: int = 80) -> bytes | None:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_images.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add images.py tests/test_images.py
git commit -m "feat: add to_square_thumbnail image cropping"
```

---

### Task 4: `fetch_remote_thumbnail` — download an og:image

**Files:**
- Modify: `images.py`
- Test: `tests/test_images.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_images.py`:

```python
import images as images_mod


class _FakeResp:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status_code = status

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_remote_thumbnail_returns_bytes(monkeypatch):
    monkeypatch.setattr(
        images_mod.requests, "get",
        lambda *a, **k: _FakeResp([b"ab", b"cd"]),
    )
    assert images_mod.fetch_remote_thumbnail("http://x/y.jpg") == b"abcd"


def test_fetch_remote_thumbnail_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(images_mod.requests, "get", boom)
    assert images_mod.fetch_remote_thumbnail("http://x/y.jpg") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_images.py -k fetch_remote -v`
Expected: FAIL with `AttributeError: module 'images' has no attribute 'requests'` / `fetch_remote_thumbnail`.

- [ ] **Step 3: Write minimal implementation**

Add to `images.py` (imports at top, function below `to_square_thumbnail`):

```python
import requests

from config import EE_THUMB_FETCH_MAX_BYTES, EE_THUMB_FETCH_TIMEOUT_S


def fetch_remote_thumbnail(url: str) -> bytes | None:
    """Download an image URL, capped and timed out. None on any failure."""
    try:
        with requests.get(url, timeout=EE_THUMB_FETCH_TIMEOUT_S, stream=True) as r:
            r.raise_for_status()
            buf = bytearray()
            for chunk in r.iter_content(chunk_size=8192):
                buf.extend(chunk)
                if len(buf) > EE_THUMB_FETCH_MAX_BYTES:
                    return None
            return bytes(buf)
    except Exception:  # noqa: BLE001 — any download failure degrades to None
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_images.py -k fetch_remote -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add images.py tests/test_images.py
git commit -m "feat: add fetch_remote_thumbnail download"
```

---

### Task 5: `generate_thumbnail` — Gemini, with missing-key no-op

**Files:**
- Modify: `images.py`
- Test: `tests/test_images.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_images.py`:

```python
def test_generate_thumbnail_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert images_mod.generate_thumbnail("Headline", "snippet") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_images.py -k generate_thumbnail -v`
Expected: FAIL with `AttributeError: ... 'generate_thumbnail'`.

- [ ] **Step 3: Write minimal implementation**

Add to `images.py`:

```python
import os

from config import EE_IMAGE_PROMPT_TEMPLATE, GEMINI_IMAGE_MODEL


def generate_thumbnail(title: str, snippet: str, *, api_key: str | None = None) -> bytes | None:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_images.py -k generate_thumbnail -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add images.py tests/test_images.py
git commit -m "feat: add generate_thumbnail via Gemini with missing-key no-op"
```

---

### Task 6: `resolve_ee_thumbnails` — orchestrator + disk cache + ThumbAsset

**Files:**
- Modify: `images.py`
- Test: `tests/test_images.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_images.py`:

```python
def test_resolve_prefers_og_image_then_caches(tmp_path):
    calls = {"fetch": 0, "gen": 0}

    def fake_fetch(url):
        calls["fetch"] += 1
        return _png(120, 120)

    def fake_gen(title, snippet):
        calls["gen"] += 1
        return _png(120, 120)

    items = [(1, {"link": "http://a/1", "image": "http://a/og.jpg",
                  "title": "T1", "snippet": "s1"})]

    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out) == {1}
    assert out[1].cid == "ee-1@quitefrankly"
    assert out[1].mime == "image/png"
    assert calls == {"fetch": 1, "gen": 0}

    # Second call hits the disk cache — no fetch, no gen.
    out2 = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out2) == {1}
    assert calls == {"fetch": 1, "gen": 0}


def test_resolve_generates_when_no_og_image(tmp_path):
    def fake_fetch(url):
        raise AssertionError("should not fetch")

    def fake_gen(title, snippet):
        return _png(64, 64)

    items = [(2, {"link": "http://a/2", "image": "",
                  "title": "T2", "snippet": "s2"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out) == {2}


def test_resolve_omits_item_on_total_failure(tmp_path):
    items = [(3, {"link": "http://a/3", "image": "", "title": "T3", "snippet": ""})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path),
        fetch=lambda u: None, gen=lambda t, s: None,
    )
    assert out == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_images.py -k resolve -v`
Expected: FAIL with `AttributeError: ... 'resolve_ee_thumbnails'`.

- [ ] **Step 3: Write minimal implementation**

Add to `images.py`:

```python
import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from config import EE_THUMB_MAX_WORKERS, EE_THUMB_SIZE


@dataclass
class ThumbAsset:
    cid: str
    data: bytes
    mime: str = "image/png"


def _cache_path(cache_dir: str, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.png"


def _resolve_one(lid, link, cache_dir, fetch, gen) -> tuple[int, ThumbAsset | None]:
    url = link.get("link", "") or str(lid)
    path = _cache_path(cache_dir, url)
    if path.exists():
        return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=path.read_bytes())

    raw = fetch(link["image"]) if link.get("image") else gen(
        link.get("title", ""), link.get("snippet", "")
    )
    if raw is None:
        return lid, None
    thumb = to_square_thumbnail(raw, size=EE_THUMB_SIZE)
    if thumb is None:
        return lid, None
    path.write_bytes(thumb)
    return lid, ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=thumb)


def resolve_ee_thumbnails(
    items, *, cache_dir, fetch=fetch_remote_thumbnail, gen=generate_thumbnail
) -> dict[int, ThumbAsset]:
    """Resolve a thumbnail per (id, link). Cache → og:image → AI generate.
    Items that fail every path are omitted (row falls back to text)."""
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    out: dict[int, ThumbAsset] = {}
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_images.py -k resolve -v`
Expected: PASS (all three).

- [ ] **Step 5: Run the whole images suite**

Run: `venv/bin/pytest tests/test_images.py -v`
Expected: PASS (all tests).

- [ ] **Step 6: Commit**

```bash
git add images.py tests/test_images.py
git commit -m "feat: add resolve_ee_thumbnails orchestrator with disk cache"
```

---

### Task 7: Two-sentence copy targeting (Everything Else = 2, Other Headlines = 1)

**Files:**
- Modify: `prompts.py:153-172` (`SUBJECT_BLURB_SYSTEM_PROMPT`)
- Modify: `formatting.py` (`write_subject_blurbs`, and the call in `build_email_html`)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`:

```python
def test_write_subject_blurbs_payload_tags_sentence_targets(monkeypatch):
    import formatting

    captured = {}

    class _FakeMsg:
        content = [type("B", (), {"text": "[]"})()]

    class _FakeMessages:
        def create(self, **kwargs):
            captured["user"] = kwargs["messages"][0]["content"]
            return _FakeMsg()

    class _FakeClient:
        messages = _FakeMessages()

    items = [(10, {"title": "A", "snippet": "", "source": "x"}),
             (11, {"title": "B", "snippet": "", "source": "y"})]
    formatting.write_subject_blurbs(
        items, sentences_by_id={10: 2, 11: 1}, client=_FakeClient()
    )

    import json
    payload = json.loads(captured["user"])
    by_id = {o["id"]: o["sentences"] for o in payload}
    assert by_id == {10: 2, 11: 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k sentence_targets -v`
Expected: FAIL (`write_subject_blurbs` has no `sentences_by_id` param / payload lacks `sentences`).

- [ ] **Step 3: Update `write_subject_blurbs`**

In `formatting.py`, change the signature and payload of `write_subject_blurbs`:

```python
def write_subject_blurbs(items, sentences_by_id=None, client=None):
```

and build the payload with a per-item sentence target:

```python
    sentences_by_id = sentences_by_id or {}
    payload = [
        {
            "id": lid,
            "title": l.get("title", ""),
            "snippet": l.get("snippet", ""),
            "source": l.get("source", ""),
            "sentences": sentences_by_id.get(lid, 1),
        }
        for lid, l in items
    ]
```

- [ ] **Step 4: Update the call site in `build_email_html`**

In `formatting.py`, replace the batched call (currently `blurb_copy = blurb_writer(oh_items + ee_items)`):

```python
        sentences_by_id = {lid: 1 for lid, _ in oh_items}
        sentences_by_id.update({lid: 2 for lid, _ in ee_items})
        blurb_copy = blurb_writer(oh_items + ee_items, sentences_by_id=sentences_by_id)
```

- [ ] **Step 5: Update the system prompt**

In `prompts.py`, edit `SUBJECT_BLURB_SYSTEM_PROMPT`. Change the input description line to note the new field and make `blurb` honor it. Replace the line that begins `You receive a JSON array of news items, each with:` with:

```
You receive a JSON array of news items, each with: id, title, snippet (may be empty), source, and sentences (1 or 2 — how many sentences the blurb must be).
```

and replace the `- blurb:` bullet (line ~160) with:

```
- blurb: written in exactly the number of sentences given by the item's `sentences` field. It begins with the exact subject string and carries the single most specific fact the source supports. For sentences=1, write one sentence of 18 to 35 words. For sentences=2, write two sentences totalling up to 55 words: the first states what happened, the second adds the most relevant supporting detail.
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `venv/bin/pytest tests/test_formatting.py -k sentence_targets -v`
Expected: PASS.

- [ ] **Step 7: Run the full formatting suite (regression)**

Run: `venv/bin/pytest tests/test_formatting.py -v`
Expected: PASS. If any existing test calls `write_subject_blurbs(items)` positionally, it still works (new arg is optional).

- [ ] **Step 8: Commit**

```bash
git add prompts.py formatting.py tests/test_formatting.py
git commit -m "feat: target two-sentence blurbs for Everything Else, one for Other Headlines"
```

---

### Task 8: Two-column rendering in `build_everything_else`

**Files:**
- Modify: `formatting.py` (`build_everything_else`, ~line 1062)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`:

```python
def test_build_everything_else_renders_thumbnail_when_cid_present():
    from formatting import build_everything_else, LIGHT

    links = {
        1: {"title": "Alpha story here now", "link": "http://a/1",
            "source": "Src", "scores": {}, "image": ""},
    }
    # Make item 1 selectable as an Everything Else pick.
    tiered = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {"composite": 5}}]
    html = build_everything_else(
        links, used_ids=set(), tiered_items=tiered, palette=LIGHT,
        images_by_id={1: "ee-1@quitefrankly"},
    )
    assert 'src="cid:ee-1@quitefrankly"' in html
    assert "border-radius:8px" in html


def test_build_everything_else_text_only_without_cid():
    from formatting import build_everything_else, LIGHT

    links = {
        1: {"title": "Alpha story here now", "link": "http://a/1",
            "source": "Src", "scores": {}, "image": ""},
    }
    tiered = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {"composite": 5}}]
    html = build_everything_else(links, used_ids=set(), tiered_items=tiered, palette=LIGHT)
    assert "cid:" not in html
    assert "<img" not in html
```

> Note: confirm the `tiered_items` shape your `_select_everything_else` expects by reading [formatting.py](formatting.py) around `_select_everything_else`; adjust the fixture keys if needed so item 1 is actually selected.

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k everything_else_renders_thumbnail -v`
Expected: FAIL (`build_everything_else` has no `images_by_id`; no `cid:` in output).

- [ ] **Step 3: Implement the two-column row**

In `formatting.py`, change the `build_everything_else` signature to accept `images_by_id`:

```python
def build_everything_else(links_by_id, used_ids, clusters_by_item_id=None,
                          tiered_items=None, palette: dict = LIGHT, copy_by_id=None,
                          images_by_id=None):
```

Inside the item loop, replace the current per-item `items_html +=` block with a branch on whether a CID exists:

```python
    images_by_id = images_by_id or {}
    ...
    for lid, l in top:
        emoji = pick_everything_else_emoji(l.get("title", ""), l.get("source", ""), used_emojis)
        used_emojis.add(emoji)
        line = _everything_else_line(l, copy_by_id.get(lid), palette)
        cid = images_by_id.get(lid)
        if cid:
            items_html += (
                f'<table cellpadding="0" cellspacing="0" border="0" '
                f'style="width:100%;margin:0 0 14px"><tr>'
                f'<td valign="top" style="width:80px;padding-right:12px">'
                f'<img src="cid:{cid}" width="80" height="80" alt="" '
                f'style="display:block;width:80px;height:80px;object-fit:cover;'
                f'border-radius:8px"></td>'
                f'<td valign="top">'
                f'<p style="margin:0;line-height:22px;font-size:15px;color:{palette["body"]};'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<span style="margin-right:6px">{emoji}</span>{line}</p>'
                f'</td></tr></table>'
            )
        else:
            items_html += (
                f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:{palette["body"]};'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<span style="margin-right:6px">{emoji}</span>{line}</p>'
            )
```

(The card wrapper / `📋 Everything Else` header below the loop is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k "everything_else_renders_thumbnail or text_only_without_cid" -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: render Everything Else rows with optional CID thumbnail"
```

---

### Task 9: `multipart/related` email with inline CID images

**Files:**
- Modify: `formatting.py` (add `MIMEImage` import; refactor `send_email`, ~line 1204)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`:

```python
def test_build_email_message_has_related_image_parts():
    from formatting import build_email_message
    from images import ThumbAsset

    assets = [ThumbAsset(cid="ee-1@quitefrankly", data=b"\x89PNG-bytes")]
    msg = build_email_message("<html><img src='cid:ee-1@quitefrankly'></html>",
                              "Subject", assets)

    assert msg.get_content_type() == "multipart/related"
    image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(image_parts) == 1
    assert image_parts[0]["Content-ID"] == "<ee-1@quitefrankly>"


def test_build_email_message_no_images_is_plain_html():
    from formatting import build_email_message
    msg = build_email_message("<html>hi</html>", "Subject", [])
    assert "text/html" in [p.get_content_type() for p in msg.walk()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k build_email_message -v`
Expected: FAIL (`build_email_message` does not exist).

- [ ] **Step 3: Implement `build_email_message` and rewire `send_email`**

In `formatting.py`, add the import near the other MIME imports:

```python
from email.mime.image import MIMEImage
```

Add a builder and refactor `send_email` to use it:

```python
def build_email_message(html, subject, inline_images=None):
    """Build a multipart/related message: HTML plus inline CID images."""
    inline_images = inline_images or []
    root = MIMEMultipart("related")
    root["Subject"] = subject
    root["From"] = f"Quite Frankly <{SENDER}>"
    root["To"] = RECIPIENT

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    root.attach(alt)

    for asset in inline_images:
        subtype = asset.mime.split("/", 1)[-1] if "/" in asset.mime else "png"
        img = MIMEImage(asset.data, _subtype=subtype)
        img.add_header("Content-ID", f"<{asset.cid}>")
        img.add_header("Content-Disposition", "inline")
        root.attach(img)

    return root


def send_email(html, subject, inline_images=None):
    gmail_user = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    msg = build_email_message(html, subject, inline_images)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())
    print(f"Sent: {subject}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k build_email_message -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: send Everything Else thumbnails as inline CID images"
```

---

### Task 10: Wire thumbnail resolution into `build_email_html`

**Files:**
- Modify: `formatting.py` (`build_email_html`, line 1108; return tuple)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`. Reuse whatever minimal `claude_response` / `links_by_id` an existing `build_email_html` test in this file uses (copy its setup), then assert the new return arity and asset surfacing:

```python
def test_build_email_html_returns_inline_images(monkeypatch):
    from formatting import build_email_html
    from images import ThumbAsset

    # Minimal inputs — copy the fixture an existing build_email_html test uses.
    claude_response, links_by_id, tiered = _minimal_build_email_inputs()  # helper below

    def fake_resolver(ee_items, *, cache_dir):
        return {lid: ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=b"x")
                for lid, _ in ee_items}

    html, subject, inline_images = build_email_html(
        claude_response, links_by_id, tiered_items=tiered,
        thumbnail_resolver=fake_resolver,
    )
    cids_in_html = {a.cid for a in inline_images if f"cid:{a.cid}" in html}
    assert cids_in_html == {a.cid for a in inline_images}
    assert isinstance(subject, str)
```

> Add a small `_minimal_build_email_inputs()` helper at the top of the test file that returns a `claude_response` string with one Everything-Else-eligible item, its `links_by_id`, and `tiered_items` — model it on the existing `build_email_html` test setup already in `tests/test_formatting.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k returns_inline_images -v`
Expected: FAIL (`build_email_html` takes no `thumbnail_resolver` and returns 2 values).

- [ ] **Step 3: Update `build_email_html`**

Change the signature (line 1108) to add the resolver:

```python
def build_email_html(claude_response, links_by_id, clusters_by_item_id=None,
                     tiered_items=None, suppressed_ids=None, is_design_edition=False,
                     blurb_writer=None, thumbnail_resolver=None):
```

After `ee_items = _select_everything_else(...)` (line 1134), resolve thumbnails:

```python
    from config import EE_THUMB_CACHE_DIR
    ee_images = {}
    inline_images = []
    if thumbnail_resolver is not None and ee_items:
        assets = thumbnail_resolver(ee_items, cache_dir=EE_THUMB_CACHE_DIR)
        ee_images = {lid: a.cid for lid, a in assets.items()}
        inline_images = list(assets.values())
```

Pass `images_by_id=ee_images` into the `build_everything_else(...)` call (line 1151):

```python
    everything_else_html = build_everything_else(
        links_by_id, used_ids, clusters_by_item_id, tiered_items=tiered_items,
        palette=c, copy_by_id=ee_copy, images_by_id=ee_images,
    )
```

Find the function's `return html, subject` (near the end of `build_email_html`) and change it to:

```python
    return html, subject, inline_images
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/pytest tests/test_formatting.py -k returns_inline_images -v`
Expected: PASS.

- [ ] **Step 5: Fix any existing `build_email_html` callers in tests**

Run: `venv/bin/pytest tests/test_formatting.py -v`
Expected: Some existing tests may unpack `html, subject = build_email_html(...)`. Update each to `html, subject, _ = build_email_html(...)`. Re-run until green.

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: resolve and surface Everything Else thumbnails from build_email_html"
```

---

### Task 11: Wire the real resolver and unpacking in `newsletter.py`

**Files:**
- Modify: `newsletter.py:25,89-97`

- [ ] **Step 1: Update the import**

On `newsletter.py:25`, add `resolve_ee_thumbnails` from `images`:

```python
from images import resolve_ee_thumbnails
```

- [ ] **Step 2: Pass the resolver and unpack three values**

Replace the `build_email_html(...)` call (lines 89-93) and the `send_email` call (line 97):

```python
        html, subject, inline_images = build_email_html(
            claude_response, links_by_id, clusters,
            tiered_items=tiered_items, suppressed_ids=suppressed_ids,
            is_design_edition=is_design_mode(mode),
            blurb_writer=write_subject_blurbs,
            thumbnail_resolver=resolve_ee_thumbnails,
        )
    with _stage("send_email"):
        send_email(html, subject, inline_images)
```

> Match the exact positional args already present on lines 89-93 — copy them; only add the two new keyword args and the third unpacked value.

- [ ] **Step 3: Verify the module imports and the full suite passes**

Run: `venv/bin/python -c "import newsletter; print('ok')" && venv/bin/pytest -q`
Expected: prints `ok`, then the full test suite passes.

- [ ] **Step 4: Commit**

```bash
git add newsletter.py
git commit -m "feat: wire Everything Else thumbnail resolver into the send pipeline"
```

---

### Task 12: Add `GEMINI_API_KEY` to CI (build-time confirmation #2)

**Files:**
- Modify: `.github/workflows/*.yml` (the workflow that runs `newsletter.py`)

- [ ] **Step 1: Find the workflow that runs the pipeline**

Run: `grep -rln "newsletter.py\|ANTHROPIC_API_KEY\|GMAIL_APP_PASSWORD" .github/workflows/`
Expected: one workflow file. Open it.

- [ ] **Step 2: Add the secret to the run step's env**

In the step that runs the pipeline (alongside `ANTHROPIC_API_KEY` / `GMAIL_*`), add:

```yaml
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
```

- [ ] **Step 3: Add the repo secret (manual, outside the code)**

Run: `gh secret set GEMINI_API_KEY` (paste the AI Studio key when prompted), or add it in GitHub repo Settings → Secrets and variables → Actions. Confirm with: `gh secret list | grep GEMINI_API_KEY`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows
git commit -m "ci: pass GEMINI_API_KEY to the newsletter pipeline"
```

---

### Task 13: End-to-end dry run

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 2: Generate one real email HTML locally and eyeball it**

Use the project's existing local/dry-run entry point (check `README.md` / `CUTOVER.md` for the dry-run command). With `GEMINI_API_KEY` exported, run a single pipeline pass that writes the HTML to `tmp/` (do not send), open it, and confirm: Everything Else rows show 80×80 rounded thumbnails, two-sentence blurbs, emoji intact; Other Headlines unchanged; imageless items (if any) degrade cleanly to text rows.

- [ ] **Step 3: Confirm the thumbnail cache populated**

Run: `ls tmp/ee_thumb_cache/ | head`
Expected: one `.png` per resolved item; a second run reuses them (no regeneration).

---

## Notes for the implementer

- **Never let image work raise into the send.** Every external call already returns `None` on failure; keep it that way.
- **Offline tests inject fakes** (`thumbnail_resolver`, `blurb_writer`, `fetch`, `gen`) — no network or API keys in the test suite, mirroring the existing `blurb_writer=None` pattern.
- **Cache dir** is `tmp/ee_thumb_cache` (under the existing gitignored `tmp/`). Confirm `tmp/` is gitignored; if not, add `tmp/ee_thumb_cache/` to `.gitignore`.
- **Other Headlines is out of scope** — its one-sentence blurbs and bulleted rendering must be unchanged after Task 7. The full-suite regression run in Task 7 Step 7 guards this.
