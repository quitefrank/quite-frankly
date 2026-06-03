# Weekend Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render weekend editions (Sat/Sun) in a dark theme that is the inverse of the existing light weekday theme, fixed at send time and resistant to email-client auto-inversion.

**Architecture:** Two module-level palette dicts (`LIGHT`, `DARK`) in `formatting.py`, keyed by semantic role. A `palette` argument is threaded through every render function (default `LIGHT`, so existing callers and weekday output are unchanged). `build_email_html` selects `DARK if is_design_edition else LIGHT` — `is_design_edition` is already `True` for Sat/Sun. Each hardcoded hex is replaced with a palette lookup. The dark build adds `color-scheme: dark` meta hints.

**Tech Stack:** Python 3, pytest. No new dependencies.

**Working branch:** main (project convention: no worktrees/feature branches).

---

## File Structure

- **Modify:** `formatting.py` — add `LIGHT`/`DARK` dicts; thread `palette` through `render_source_line`, `_render_body_markdown`, `render_other_headlines_for_section`, `_render_today_in_the_world`, `parse_and_render_sections`, `build_everything_else`, `build_email_html`.
- **Modify:** `tests/test_formatting.py` — add theme tests.
- No changes to `routing.py`, `newsletter.py`, `config.py` (the `is_design_edition` flag already flows from `newsletter.py:87`).

## Palette key → hex map (reference for all tasks)

| Key | LIGHT | DARK | Used by |
|---|---|---|---|
| `page_bg` | `#f4f4f4` | `#121212` | body + outer table |
| `card_bg` | `#ffffff` | `#1e1e1e` | hero, section, today, everything-else cards |
| `card_border` | `#e6e6e6` | `#2a2a2a` | all card wrappers |
| `header_bg` | `#1f1f1f` | `#ffffff` | header bar |
| `header_text` | `#ffffff` | `#1a1a1a` | header logo text |
| `header_border` | `#222222` | `#e6e6e6` | header bottom border |
| `heading` | `#1a1a1a` | `#f5f5f5` | h1, headlines, headline/today links |
| `body` | `#333333` | `#c8c8c8` | body paragraphs, body links, callout text |
| `meta` | `#999999` | `#7f7f7f` | source line, read-time |
| `meta_label` | `#888888` | `#8a8a8a` | date, "Other Headlines" label |
| `accent` | `#1c7ff2` | `#4d9bff` | section labels, underline color, callout stripe |
| `callout_bg` | `#f0f4ff` | `#16243a` | "What this means for you" box |
| `divider` | `#f0f0f0` | `#333333` | inter-story + Other Headlines hairlines |
| `footer_bg` | `#E9EBF7` | `#1a1c2e` | footer panel |
| `footer_text` | `#79787d` | `#8b8ba3` | footer text |
| `color_scheme` | `light` | `dark` | `<meta>` + body `color-scheme` |

> LIGHT values are the exact current hexes (note: code currently writes some as `#fff`/`#333`; the dicts use the 6-digit form, which renders identically). Weekday output stays visually identical; the light-regression test guards it via light-only markers.

---

### Task 1: Palette dicts + thread `palette` through all signatures + convert `build_email_html` shell

**Files:**
- Modify: `formatting.py` (after the imports near top; and `build_email_html` at ~847-913)
- Modify: `formatting.py` signatures of the 6 render helpers (accept `palette=LIGHT`, unused until later tasks)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
from formatting import LIGHT, DARK, build_email_html


def _weekend_html():
    html, _ = build_email_html("## Tech & AI\n\n**Hello world [#1]**\nBody text.\nSource: CBC",
                               {1: {"link": "https://x.co", "image": None, "title": "Hello world", "snippet": ""}},
                               is_design_edition=True)
    return html


def _weekday_html():
    html, _ = build_email_html("## Tech & AI\n\n**Hello world [#1]**\nBody text.\nSource: CBC",
                               {1: {"link": "https://x.co", "image": None, "title": "Hello world", "snippet": ""}},
                               is_design_edition=False)
    return html


def test_palettes_have_identical_keys():
    assert set(LIGHT) == set(DARK)


def test_weekend_shell_is_dark():
    html = _weekend_html()
    assert "#121212" in html                       # dark page bg
    assert 'background:#ffffff' in html             # inverted white header bar
    assert 'name="color-scheme" content="dark"' in html
    assert 'content="dark"' in html
    assert "color-scheme:dark" in html.replace(" ", "")


def test_weekday_shell_is_light():
    html = _weekday_html()
    assert "#f4f4f4" in html                        # light page bg
    assert "#121212" not in html
    assert 'name="color-scheme" content="light"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py::test_weekend_shell_is_dark -v`
Expected: FAIL — `ImportError: cannot import name 'LIGHT'` (or AssertionError).

- [ ] **Step 3: Add palette dicts**

Insert near the top of `formatting.py`, after the existing imports and before the first function:

```python
# ── Colour themes ───────────────────────────────────────────────────────────
# LIGHT = current weekday palette (values identical to prior hardcoded hexes).
# DARK  = weekend palette, the inverse. build_email_html picks one per edition.
LIGHT = {
    "page_bg": "#f4f4f4",
    "card_bg": "#ffffff",
    "card_border": "#e6e6e6",
    "header_bg": "#1f1f1f",
    "header_text": "#ffffff",
    "header_border": "#222222",
    "heading": "#1a1a1a",
    "body": "#333333",
    "meta": "#999999",
    "meta_label": "#888888",
    "accent": "#1c7ff2",
    "callout_bg": "#f0f4ff",
    "divider": "#f0f0f0",
    "footer_bg": "#E9EBF7",
    "footer_text": "#79787d",
    "color_scheme": "light",
}
DARK = {
    "page_bg": "#121212",
    "card_bg": "#1e1e1e",
    "card_border": "#2a2a2a",
    "header_bg": "#ffffff",
    "header_text": "#1a1a1a",
    "header_border": "#e6e6e6",
    "heading": "#f5f5f5",
    "body": "#c8c8c8",
    "meta": "#7f7f7f",
    "meta_label": "#8a8a8a",
    "accent": "#4d9bff",
    "callout_bg": "#16243a",
    "divider": "#333333",
    "footer_bg": "#1a1c2e",
    "footer_text": "#8b8ba3",
    "color_scheme": "dark",
}
```

- [ ] **Step 4: Add `palette=LIGHT` to the 6 helper signatures**

Change each signature (bodies untouched in this task):

```python
def render_source_line(primary_source: str, also_in: list[str], article_link: str | None, palette: dict = LIGHT) -> str:
def _render_body_markdown(text: str, palette: dict = LIGHT) -> str:
def render_other_headlines_for_section(section, tiered_items, links_by_id, used_ids, palette: dict = LIGHT):
def _render_today_in_the_world(lines: list[str], links_by_id: dict, used_ids: set, palette: dict = LIGHT) -> str:
def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None, is_design_edition=False, palette: dict = LIGHT):
def build_everything_else(links_by_id, used_ids, clusters_by_item_id=None, tiered_items=None, palette: dict = LIGHT):
```

- [ ] **Step 5: Convert `build_email_html` to select and thread the palette + dark shell**

In `build_email_html`, immediately after `today_long`/`short_date` are computed (~line 852), add:

```python
    c = DARK if is_design_edition else LIGHT
```

Update the two render calls to pass the palette:

```python
    sections_html, used_ids = parse_and_render_sections(
        claude_response, links_by_id, clusters_by_item_id,
        tiered_items=tiered_items, suppressed_ids=suppressed_ids,
        is_design_edition=is_design_edition, palette=c,
    )
    everything_else_html    = build_everything_else(
        links_by_id, used_ids, clusters_by_item_id, tiered_items=tiered_items, palette=c,
    )
```

Replace the HTML shell (the `html = f"""..."""` block, lines ~872-911) with this palette-driven version:

```python
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="{c['color_scheme']}">
<meta name="supported-color-schemes" content="{c['color_scheme']}"></head>
<body style="margin:0;padding:0;background:{c['page_bg']};color-scheme:{c['color_scheme']}">
<table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;background:{c['page_bg']}">
<tr><td style="padding:20px 10px">
<div style="max-width:670px;margin:0 auto">

  <div style="margin-bottom:10px;border-radius:15px;overflow:hidden;border:1px solid {c['card_border']};font-family:Helvetica,Arial,sans-serif">
    <div style="padding:16px 20px;border-bottom:1px solid {c['header_border']};background:{c['header_bg']};">
      <table border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;padding-right:10px;">
            <img src="https://quitefrank.co/wp-content/uploads/2021/03/favicon.svg" width="28" height="28" style="display:block;border-radius:50%;" alt="Quite Frankly">
          </td>
          <td style="vertical-align:middle;">
            <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:{c['header_text']};font-family:Helvetica,Arial,sans-serif">Quite Frankly</p>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:20px 20px 22px;background:{c['card_bg']};">
      <h1 style="margin:0 0 6px;font-size:26px;font-weight:700;color:{c['heading']};line-height:1.2;font-family:Helvetica,Arial,sans-serif">Here's what matters today.</h1>
      <p style="margin:0;font-size:13px;color:{c['meta_label']};font-family:Helvetica,Arial,sans-serif">{today_long}</p>
    </div>
  </div>

  {sections_html}
  {everything_else_html}

  <div style="margin-top:10px;border-radius:15px;overflow:hidden;background:{c['footer_bg']};font-family:Helvetica,Arial,sans-serif">
    <div style="padding:15px;font-size:12px;color:{c['footer_text']};text-align:center;line-height:20px">
      Generated daily by Quite Frankly &nbsp;·&nbsp; Sources: CBC, Globe and Mail, TechCrunch, UX Collective, BBC, Smashing Magazine, Yahoo Finance, Globe &amp; Mail Finance, r/toronto<br>
      <span style="font-size:11px">Quite Frankly &nbsp;·&nbsp; Toronto, Ontario</span>
    </div>
  </div>

</div>
</td></tr></table>
</body></html>"""
```

- [ ] **Step 6: Run the new tests**

Run: `venv/bin/pytest tests/test_formatting.py -k "palette or shell" -v`
Expected: `test_palettes_have_identical_keys`, `test_weekend_shell_is_dark`, `test_weekday_shell_is_light` PASS.

- [ ] **Step 7: Run full suite (nothing else should break)**

Run: `venv/bin/pytest -q`
Expected: all pass (helpers still default to LIGHT, so unconverted bodies are unchanged).

- [ ] **Step 8: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: add LIGHT/DARK palettes and dark shell for weekend editions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Convert `render_source_line` and `_render_body_markdown`

**Files:**
- Modify: `formatting.py` (`render_source_line` ~375-380, `_render_body_markdown` ~424-431)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
from formatting import render_source_line, _render_body_markdown


def test_source_line_uses_palette_accent():
    light = render_source_line("CBC", [], "https://x.co", palette=LIGHT)
    dark = render_source_line("CBC", [], "https://x.co", palette=DARK)
    assert "#1c7ff2" in light
    assert "#4d9bff" in dark
    assert "#1c7ff2" not in dark


def test_body_markdown_link_uses_palette():
    dark = _render_body_markdown("see [docs](https://x.co)", palette=DARK)
    assert "#c8c8c8" in dark          # body link colour
    assert "#4d9bff" in dark          # underline accent
    assert "#1c7ff2" not in dark
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k "source_line_uses or body_markdown_link" -v`
Expected: FAIL — dark output still contains `#1c7ff2`.

- [ ] **Step 3: Convert the bodies**

In `render_source_line`, replace the return block:

```python
    if article_link:
        return (
            f'{img}<a href="{article_link}" '
            f'style="color:{palette["accent"]};text-decoration:none;vertical-align:middle;font-size:12px;">{label}</a>'
        )
    return f'{img}<span style="vertical-align:middle;font-size:12px;color:{palette["meta"]};">{label}</span>'
```

In `_render_body_markdown`, replace the link substitution:

```python
    text = _MARKDOWN_LINK_RE.sub(
        lambda m: (
            f'<a href="{m.group(2)}" '
            f'style="color:{palette["body"]};text-decoration:underline;text-decoration-color:{palette["accent"]};">{m.group(1)}</a>'
        ),
        text,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k "source_line or body_markdown" -v`
Expected: PASS (including the pre-existing `render_source_line` tests, which use default LIGHT).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: palette-drive source line and body markdown links

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Convert `_render_today_in_the_world` and `render_other_headlines_for_section`

**Files:**
- Modify: `formatting.py` (`_render_today_in_the_world` ~551-561; `render_other_headlines_for_section` ~481-496)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
from formatting import _render_today_in_the_world, render_other_headlines_for_section


def test_today_in_world_dark_palette():
    links = {1: {"link": "https://x.co", "image": None, "title": "T"}}
    html = _render_today_in_the_world(["🌍 **Header [#1]:** body"], links, set(), palette=DARK)
    assert "#f5f5f5" in html       # heading-coloured link
    assert "#4d9bff" in html       # underline accent
    assert "#c8c8c8" in html       # body paragraph
    assert "#1c7ff2" not in html


def test_other_headlines_dark_palette():
    items = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {}}]
    links = {1: {"link": "https://x.co", "title": "One two three four five six", "snippet": "A sentence."}}
    html = render_other_headlines_for_section("Tech & AI", items, links, set(), palette=DARK)
    assert "#c8c8c8" in html       # link + item body
    assert "#4d9bff" in html       # underline accent
    assert "#8a8a8a" in html       # "Other Headlines" label
    assert "#333333" in html       # divider (dark)
    assert "#1c7ff2" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k "today_in_world_dark or other_headlines_dark" -v`
Expected: FAIL — dark markers absent / light markers present.

- [ ] **Step 3: Convert `_render_today_in_the_world`**

Replace the link/body block (~549-562):

```python
        if href:
            bold = (
                f'<a href="{href}" style="color:{palette["heading"]};text-decoration:underline;text-decoration-color:{palette["accent"]};">'
                f'<strong>{bold_inner}</strong></a>'
            )
        else:
            bold = f'<strong>{bold_inner}</strong>'
        rendered_body = _render_body_markdown(it["body"], palette)
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:{palette["body"]};'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{it["emoji"]}</span>'
            f'{bold} {rendered_body}</p>'
        )
```

- [ ] **Step 4: Convert `render_other_headlines_for_section`**

Replace the linked-part, item, and wrapper blocks (~479-497):

```python
        linked_part = (
            f'<a href="{l["link"]}" '
            f'style="color:{palette["body"]};font-weight:400;text-decoration:underline;text-decoration-color:{palette["accent"]};">'
            f"{link_words}</a>"
            if l.get("link") else link_words
        )
        summary = _first_sentence(l.get("snippet", ""))
        body = f"{linked_part}: {summary}" if summary else linked_part
        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:{palette["body"]};'
            f'font-family:Helvetica,Arial,sans-serif">{body}</li>'
        )

    return (
        f'<div style="margin-top:16px;padding-top:14px;border-top:1px solid {palette["divider"]};">'
        f'<p style="margin:0 0 8px;font-size:12px;font-weight:700;color:{palette["meta_label"]};'
        f'font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.08em">Other Headlines</p>'
        f'<ul style="margin:0;padding-left:20px">{items_html}</ul>'
        "</div>"
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k "today_in_world or other_headlines" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: palette-drive today-in-world and other-headlines blocks

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Convert `parse_and_render_sections` (section cards + today card wrapper)

**Files:**
- Modify: `formatting.py` (`parse_and_render_sections` body ~591-735)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
from formatting import parse_and_render_sections


def test_section_card_dark_palette():
    text = "## Tech & AI\n\n**Big news [#1]**\nThe body paragraph.\nSource: CBC\nWhat this means for you: do X"
    links = {1: {"link": "https://x.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, palette=DARK)
    assert "background:#1e1e1e" in html      # card bg
    assert "1px solid #2a2a2a" in html       # card border
    assert "#f5f5f5" in html                 # headline
    assert "#c8c8c8" in html                 # body + callout text
    assert "background:#16243a" in html      # callout bg
    assert "#4d9bff" in html                 # accent label + callout stripe
    assert "#1c7ff2" not in html
    assert "#ffffff" not in html             # no light card bg leaked in section


def test_section_card_light_unchanged():
    text = "## Tech & AI\n\n**Big news [#1]**\nThe body paragraph.\nSource: CBC"
    links = {1: {"link": "https://x.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links)  # default LIGHT
    assert "background:#fff" in html
    assert "#1c7ff2" in html
    assert "#121212" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k "section_card_dark" -v`
Expected: FAIL — dark markers absent.

- [ ] **Step 3: Compute helper palette + convert the today-card wrapper**

At the top of `parse_and_render_sections`, the `palette` arg is already in the signature (Task 1). No extra computation needed — use `palette` directly.

Replace the today-in-world card wrapper (~593-605) — pass palette into the inner call and drive the wrapper colours:

```python
            stories_html = _render_today_in_the_world(lines[1:], links_by_id, used_ids, palette)
            if not stories_html:
                continue
            html += (
                f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
                f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
                f'\n  <div style="padding:15px 15px 0">'
                f'\n    <p style="color:{palette["accent"]};margin:0 0 12px;font-size:13px;font-weight:700;'
                f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{display_emoji} {display_title}</p>'
                f'\n  </div>'
                f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
                f'\n</div>'
            )
            continue
```

- [ ] **Step 4: Convert the per-story render loop**

Replace the divider, headline, body, source, and callout blocks (~652-716):

```python
            border       = "" if i == len(stories) - 1 else f"border-bottom:1px solid {palette['divider']};padding-bottom:16px;margin-bottom:16px;"
```

```python
            if s["headline"]:
                headline_inner = (
                    f'<a href="{article_link}" style="color:{palette["heading"]};text-decoration:none;">{s["headline"]}</a>'
                    if article_link else s["headline"]
                )
                stories_html += (
                    f'<p style="margin:0 0 8px;font-size:24px;font-weight:700;color:{palette["heading"]};'
                    f'line-height:26px;font-family:Helvetica,Arial,sans-serif">{headline_inner}</p>'
                )

            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs[:FEATURED_STORY_PARAGRAPH_CAP]:
                    rendered = _render_body_markdown(p, palette)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:{palette["body"]};'
                        f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
                    )
```

```python
            if primary_source:
                stories_html += (
                    f'<p style="margin:0 0 10px;font-size:12px;color:{palette["meta"]};'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'{render_source_line(primary_source, also_in, article_link, palette)}</p>'
                )

            if s["callout"]:
                stories_html += (
                    f'<div style="margin:10px 0 0;padding:12px 14px;background:{palette["callout_bg"]};'
                    f'border-left:3px solid {palette["accent"]};font-size:14px;line-height:20px;color:{palette["body"]};'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'<strong style="color:{palette["accent"]}">What this means for you:</strong> {s["callout"]}</div>'
                )
```

- [ ] **Step 5: Pass palette into the Other Headlines call + convert the section card wrapper**

Replace the OH call (~720) and the final section wrapper (~726-735):

```python
        oh_html = render_other_headlines_for_section(title, tiered_items, links_by_id, used_ids, palette)
        stories_html += oh_html

        if not stories_html:
            continue

        html += (
            f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
            f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
            f'\n  <div style="padding:15px 15px 0">'
            f'\n    <p style="color:{palette["accent"]};margin:0 0 12px;font-size:13px;font-weight:700;'
            f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
            f'\n  </div>'
            f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
            f'\n</div>'
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k "section_card" -v`
Expected: PASS (both dark and light-unchanged).

- [ ] **Step 7: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: palette-drive section cards and today card

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Convert `build_everything_else`

**Files:**
- Modify: `formatting.py` (`build_everything_else` body ~811-835)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
from formatting import build_everything_else


def test_everything_else_dark_palette():
    links = {1: {"link": "https://x.co", "title": "One two three four five", "source": "CBC", "image": None}}
    items = [{"id": 1, "tier": 3, "scores": {}}]
    html = build_everything_else(links, set(), tiered_items=items, palette=DARK)
    assert "background:#1e1e1e" in html      # card bg
    assert "1px solid #2a2a2a" in html       # card border
    assert "#c8c8c8" in html                 # item text + link
    assert "#4d9bff" in html                 # accent (label + underline)
    assert "#1c7ff2" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py -k "everything_else_dark" -v`
Expected: FAIL.

- [ ] **Step 3: Convert the body**

Replace the linked-part, item, and wrapper blocks (~811-835):

```python
        linked_part = (
            f'<a href="{l["link"]}" style="color:{palette["body"]};'
            f'text-decoration:underline;text-decoration-color:{palette["accent"]};">'
            f'{link_words}</a>'
            if l["link"] else link_words
        )
        full_line = f"{linked_part} {remaining}" if remaining else linked_part
        emoji = pick_everything_else_emoji(l.get("title", ""), l.get("source", ""), used_emojis)
        used_emojis.add(emoji)
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:{palette["body"]};'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{emoji}</span>'
            f'{full_line}</p>'
        )

    return (
        f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
        f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
        f'\n  <div style="padding:15px 15px 0">'
        f'\n    <p style="color:{palette["accent"]};margin:0 0 14px;font-size:13px;font-weight:700;'
        f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        f'\n  </div>'
        f'\n  <div style="padding:0 15px 15px">{items_html}</div>'
        f'\n</div>'
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_formatting.py -k "everything_else" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: palette-drive Everything Else card

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full-build guard — dark build has no light-only colours; weekday build unchanged

**Files:**
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing/guard test**

```python
LIGHT_ONLY_MARKERS = ["#f4f4f4", "#1c7ff2", "#f0f4ff", "#E9EBF7", "#79787d", "#f0f0f0"]
DARK_ONLY_MARKERS = ["#121212", "#4d9bff", "#1e1e1e", "#16243a", "#1a1c2e"]

_FULL_TEXT = (
    "## Today in the World\n\n🌍 **Rates held [#1]:** markets mixed.\n\n"
    "## Tech & AI\n\n**Big news [#2]**\nBody paragraph here.\nSource: CBC\n"
    "What this means for you: test it"
)
_FULL_LINKS = {
    1: {"link": "https://a.co", "image": None, "title": "Rates held", "snippet": "x"},
    2: {"link": "https://b.co", "image": None, "title": "Big news", "snippet": "y"},
}


def test_full_weekend_build_has_no_light_only_colours():
    html, _ = build_email_html(_FULL_TEXT, _FULL_LINKS, is_design_edition=True)
    for m in LIGHT_ONLY_MARKERS:
        assert m not in html, f"light-only colour {m} leaked into dark build"
    for m in DARK_ONLY_MARKERS:
        assert m in html


def test_full_weekday_build_has_no_dark_only_colours():
    html, _ = build_email_html(_FULL_TEXT, _FULL_LINKS, is_design_edition=False)
    for m in DARK_ONLY_MARKERS:
        assert m not in html, f"dark-only colour {m} leaked into light build"
    for m in LIGHT_ONLY_MARKERS:
        assert m in html
```

- [ ] **Step 2: Run the guard tests**

Run: `venv/bin/pytest tests/test_formatting.py -k "no_light_only or no_dark_only" -v`
Expected: PASS. If any FAIL, a hex in the named function was missed — grep `formatting.py` for the leaked marker and convert it to the matching palette key, then re-run.

- [ ] **Step 3: Run the entire suite**

Run: `venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 4: Visual confirmation (manual)**

Run a render and open it:

```bash
venv/bin/python -c "from formatting import build_email_html; \
h,_=build_email_html(open('/dev/stdin').read(), {1:{'link':'https://a.co','image':None,'title':'Rates held','snippet':'x'}}, is_design_edition=True); \
open('tmp/weekend-render.html','w').write(h)" <<< "## Tech & AI

**Big news [#1]**
Body paragraph.
Source: CBC
What this means for you: test"
open tmp/weekend-render.html
```

Expected: dark page, white header bar with dark logo, dark cards, bright-blue accents.

- [ ] **Step 5: Commit**

```bash
git add tests/test_formatting.py
git commit -m "test: guard weekend dark build against light-colour leakage

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Trigger by `is_design_edition` (Sat/Sun) → Task 1 (`build_email_html` selection). ✓
- Palette object threaded through all 7 functions → Tasks 1–5. ✓
- Exact palette values → key map table + per-task code. ✓
- Header inversion (white bg, dark text) → Task 1 shell. ✓
- Brighter `#4d9bff` accent on dark → all conversion tasks. ✓
- Anti-inversion `color-scheme` meta → Task 1 shell. ✓
- Light output unchanged → default `palette=LIGHT` + light-regression tests (Tasks 4, 6). ✓
- Tests (light guard, dark markers, routing) → Tasks 1–6. Routing is covered indirectly: `is_design_edition` drives selection and is already asserted in `tests/test_routing.py`; the dark build is exercised via `is_design_edition=True`. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full replacement code. ✓

**Type/name consistency:** `palette` arg name and the 16 keys (`page_bg`, `card_bg`, `card_border`, `header_bg`, `header_text`, `header_border`, `heading`, `body`, `meta`, `meta_label`, `accent`, `callout_bg`, `divider`, `footer_bg`, `footer_text`, `color_scheme`) are identical across `LIGHT`, `DARK`, and every lookup. ✓

**Note on `#ffffff`:** Not a usable light-only marker because the dark header bar is `#ffffff`. The guard test uses `#f4f4f4` (light page) and `#1e1e1e` (dark card) instead, which are unambiguous.
