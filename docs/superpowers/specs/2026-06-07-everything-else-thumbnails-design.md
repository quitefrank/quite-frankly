# Everything Else thumbnails + AI fallback images — Design

**Date:** 2026-06-07
**Status:** Approved (pending spec review)
**Scope:** The global **Everything Else** card only. Other Headlines is explicitly out of scope and must render exactly as it does today.

## Problem / goal

Everything Else rows are currently emoji + one linked sentence. Add an **80×80 thumbnail** to the left of each row (8px corner radius, matching the existing inline article images and the Luma reference email), and lengthen each blurb to **two sentences** so the text fills the height the thumbnail now sets. Every row should have a thumbnail: use the article's `og:image` when present, and **AI-generate** an editorial illustration when it is not.

Non-goals: changing Other Headlines, changing featured-story rendering, changing any section other than Everything Else.

## User-facing result

A rendered Everything Else card where each item is a two-column row:

```
┌──────────────────────────────────────────────┐
│ 📋 EVERYTHING ELSE                            │
│ [80x80] 🏠 Subject link two-sentence blurb    │
│  img      that fills the row height...        │
│ [80x80] 🤖 Subject link two-sentence blurb... │
└──────────────────────────────────────────────┘
```

If a row's image can't be resolved (no `og:image`, generation fails, key missing, download fails), that row silently falls back to **today's layout** (emoji + text, full width, no thumbnail). The send never breaks on an image problem.

## Decisions (settled in brainstorming)

| Decision | Choice |
|---|---|
| Sections affected | Everything Else only |
| Thumbnail size / radius | 80×80, `border-radius:8px` |
| Emoji | Kept, inline with the blurb (thumbnail is additional, not a replacement) |
| Blurb length | Everything Else → 2 sentences; Other Headlines → 1 sentence (unchanged) |
| Imageless fallback | AI-generate per article |
| Image provider | Google AI Studio / Gemini API, key `GEMINI_API_KEY` (same var Plately uses: `process.env.GEMINI_API_KEY`) |
| Image style | Flat editorial/abstract illustration, deliberately **not** photoreal (content-integrity guardrail for real news) |
| Caching | Generated + downloaded thumbnails cached on disk, keyed by article-URL hash |
| Embedding | Inline `multipart/related` CID attachments in the email (no external hosting) |
| Degradation | Any image failure → text-only row; pipeline must never fail the send |

## Architecture

### New module: `images.py`

Owns all thumbnail acquisition and processing. Pure, injectable, no import-time side effects.

- `fetch_remote_thumbnail(url: str) -> bytes | None`
  Download an `og:image` URL (short timeout, byte cap), return raw bytes or `None` on any failure.
- `generate_thumbnail(title: str, snippet: str) -> bytes | None`
  Call the Gemini image model (via `google-genai`, key from `GEMINI_API_KEY`) with the editorial-style prompt built from `title`/`snippet`. Return raw image bytes or `None` on any failure (missing key, API error, safety block).
- `to_square_thumbnail(raw: bytes, size: int = 80) -> bytes | None`
  Pillow: center-crop to square, resize to `size`×`size`, re-encode (PNG). `None` on decode failure.
- `resolve_ee_thumbnails(items, *, cache_dir, fetch=fetch_remote_thumbnail, gen=generate_thumbnail) -> dict[int, ThumbAsset]`
  Orchestrator. For each `(id, link)` in `items`:
  1. Cache hit on `sha256(link.url)` → load bytes, done.
  2. Else if `link["image"]` present → `fetch` it.
  3. Else → `gen(title, snippet)`.
  4. `to_square_thumbnail` the bytes; write to cache; build a `ThumbAsset`.
  5. Any step returning `None` → omit this id from the result dict (row falls back to text).
  Runs fetches/generations concurrently with a `ThreadPoolExecutor`, mirroring `enrich_from_og_metadata` in [pipeline.py](pipeline.py).

`ThumbAsset` = `{cid: str, data: bytes, mime: str}`. `cid` is a stable token, e.g. `ee-<id>@quitefrankly`.

### Rendering: `build_everything_else` ([formatting.py](formatting.py))

Add an optional `images_by_id: dict[int, str] | None = None` parameter mapping item id → CID.

- For an item **with** a CID: render the two-column email-safe table — `<td width=80>` holding `<img src="cid:..." width=80 height=80 style="...border-radius:8px">`, `<td valign=top>` holding the existing emoji span + blurb line.
- For an item **without** a CID: render exactly today's single `<p>` row.
- Section wrapper (card, padding, `📋 Everything Else` header) is unchanged.

When `images_by_id` is `None` (offline tests), every row renders text-only — identical to current behavior.

### Copy: two-sentence Everything Else, one-sentence Other Headlines

The batched `write_subject_blurbs(oh_items + ee_items)` call in `build_email_html` ([formatting.py](formatting.py#L1141)) stays a single API call. Thread a per-item length target:

- `write_subject_blurbs` payload gains a `sentences` field per item (1 or 2).
- Callers tag EE items with `sentences=2`, OH items with `sentences=1`.
- `SUBJECT_BLURB_SYSTEM_PROMPT` ([prompts.py](prompts.py#L153)) is updated: the `blurb` field honors the per-item `sentences` count (1 sentence ≈ 18–35 words as today; 2 sentences ≈ up to ~55 words), still subject-first, still bound by every existing voice rule (no em dashes, banned phrases, facts only from title/snippet).

Other Headlines blurbs stay one sentence, so the out-of-scope section is visually unchanged.

### Email assembly: inline CID images

`build_email_html` currently returns an HTML string. It will return **`(html, inline_images)`** where `inline_images` is a `list[ThumbAsset]` for exactly the CIDs referenced in the rendered Everything Else. Resolution happens inside `build_email_html`, after `ee_items` is selected, via an injected `thumbnail_resolver` (default `None` → no thumbnails, mirroring the `blurb_writer=None` pattern).

`send_email` ([formatting.py](formatting.py#L1204)) changes from `MIMEMultipart("alternative")` to `multipart/related`:

- Root `MIMEMultipart("related")`.
- First part: the HTML (wrapped in `multipart/alternative` for correctness).
- One `MIMEImage` per `ThumbAsset`, with `Content-ID: <cid>` and `Content-Disposition: inline`.

The MIME object construction is extracted into a testable helper `build_email_message(html, subject, inline_images) -> EmailMessage/MIMEMultipart`, so tests assert structure without sending.

`newsletter.py` is updated to unpack `(html, inline_images)` from `build_email_html` and pass both to `send_email`.

## Data flow

```
ee_items selected (≤7)
   │
   ├─ write_subject_blurbs(oh+ee, per-item sentences)   → blurbs
   │
   └─ thumbnail_resolver(ee_items)                       → {id: ThumbAsset}
         cache → og:image fetch → AI generate → square-crop
   │
build_everything_else(..., images_by_id={id: cid})       → EE html
   │
build_email_html                                         → (html, [ThumbAsset])
   │
send_email(html, subject, inline_images)                 → multipart/related send
```

## Config / deps / env

- `requirements.txt`: add `google-genai` and `Pillow`.
- `config.py`: `EE_THUMB_SIZE = 80`, thumbnail cache dir path, Gemini model id (pinned at build time against the installed SDK), Gemini timeout + max workers, and the editorial-style prompt template.
- Env: `GEMINI_API_KEY`. **Build task:** add it to the GitHub Actions workflow secrets, since the pipeline runs in CI.

## Error handling

Every external step degrades to `None`, and `None` removes the row's thumbnail (text-only fallback). No exception from image work may propagate to the send path. Logged with a one-line `print` like the existing og-meta and blurb paths. Missing `GEMINI_API_KEY` is a logged no-op, not a crash.

## Testing

Offline, no network or keys (inject fakes, mirroring `blurb_writer=None`):

- **Render — with image:** resolver supplies a CID for an id → that EE row is a two-column table with `<img src="cid:...">`.
- **Render — fallback:** resolver omits an id → that row is today's single `<p>`, no `<td>`/`<img>`.
- **Assets surfaced:** `build_email_html` returns `inline_images` whose CIDs exactly match those referenced in the HTML.
- **MIME structure:** `build_email_message` produces `multipart/related` with one inline `MIMEImage` per asset, each with a matching `Content-ID`.
- **Square crop:** `to_square_thumbnail` of a non-square test image yields an 80×80 image.
- **Cache reuse:** second `resolve_ee_thumbnails` for the same URL does not call the generator/fetcher again.
- **Copy targeting:** `write_subject_blurbs` payload carries `sentences=2` for EE items and `sentences=1` for OH items.
- **Total-failure path:** resolver returns `{}` → Everything Else renders exactly as it does today (regression guard).

## Open build-time confirmations

1. Exact Gemini image model ID (verified against the installed `google-genai` SDK — likely `imagen-4` or `gemini-2.5-flash-image`).
2. Adding `GEMINI_API_KEY` to GitHub Actions secrets.
