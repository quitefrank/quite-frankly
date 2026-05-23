# Everything Else: emoji prefix + bold link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle every Everything Else item with a per-article emoji prefix and a bolded version of the existing first-words link, while keeping content, ranking, source-to-section mapping, and the 7-item cap unchanged.

**Architecture:** Two data structures in `config.py` (keyword regex → emoji, source name → emoji). One helper `pick_everything_else_emoji(title, source)` in `formatting.py` with deterministic resolution: keyword regex first, source-name lookup second, `📰` safety net last. Rewrite of `build_everything_else` to emit `<p>` paragraphs with an emoji `<span>` and a `<strong>`-wrapped first-words link, replacing the current `<ul>/<li>` structure.

**Tech Stack:** Python 3, pytest. No new dependencies. No new LLM calls.

**Spec:** [`docs/2026-05-23-everything-else-emoji-spec.md`](2026-05-23-everything-else-emoji-spec.md)

---

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `config.py` | Modify (append) | Two new module-level constants: keyword pattern list and source-name map. |
| `formatting.py` | Modify | Add `pick_everything_else_emoji` helper; rewrite `build_everything_else` (lines 837-894) to use `<p>` + emoji + `<strong>`. |
| `tests/test_formatting.py` | Modify | Update one existing `<li`-count assertion; add tests for the new helper and the new render structure. |

No new files. No moves. No renames.

---

## Task 1: Seed the keyword + source emoji maps in `config.py`

**Files:**
- Modify: `config.py` (append after `SECTION_EMOJIS` — currently ends at line 162)

- [ ] **Step 1: Add the two constants after SECTION_EMOJIS**

Open `config.py`, find the `SECTION_EMOJIS = { ... }` block (lines 153-162), and append directly after it:

```python
# Per-item emoji selection for Everything Else.
# Resolution order in formatting.pick_everything_else_emoji:
#   1. First case-insensitive keyword regex match (declared order wins).
#   2. Exact source-name lookup below.
#   3. Newspaper safety net (📰) — only fires if a feed source is added
#      without being added to EVERYTHING_ELSE_SOURCE_EMOJIS.
EVERYTHING_ELSE_KEYWORD_EMOJIS = [
    # AI / tech firms
    (r"\b(openai|anthropic|gpt|claude|gemini|llm|chatgpt|copilot)\b", "🤖"),
    (r"\b(apple|iphone|ipad|mac|airpods)\b", "🍎"),
    (r"\b(google|alphabet|android|pixel)\b", "🔎"),
    (r"\b(meta|facebook|instagram|whatsapp|threads)\b", "📱"),
    (r"\b(microsoft|azure|xbox|windows)\b", "🪟"),
    (r"\b(amazon|aws|prime)\b", "📦"),
    (r"\b(tesla|musk|spacex|x corp|twitter)\b", "🚀"),

    # Housing / real estate
    (r"\b(rent|condo|landlord|mortgage|housing|real estate|listing|airbnb)\b", "🏠"),

    # Markets / finance
    (r"\b(fed|inflation|interest rate|tsx|s&p|nasdaq|dow|recession|bond|yield)\b", "📈"),
    (r"\b(crypto|bitcoin|ethereum|stablecoin)\b", "🪙"),
    (r"\b(layoff|firing|severance|hiring freeze)\b", "📉"),

    # Politics
    (r"\b(trump|biden|harris|white house|congress|senate|gop|democrat|republican)\b", "🇺🇸"),
    (r"\b(ottawa|trudeau|carney|liberal|conservative|ndp|poilievre|parliament)\b", "🇨🇦"),
    (r"\b(election|vote|ballot|poll|polling|riding)\b", "🗳️"),

    # Toronto / Ontario
    (r"\b(toronto|ontario|ttc|tdsb|leslieville|scarborough|mississauga)\b", "🏙️"),

    # World / environment
    (r"\b(climate|emissions|wildfire|hurricane|flood|heatwave)\b", "🌍"),
    (r"\b(war|ukraine|gaza|israel|hamas|nato)\b", "🕊️"),

    # Work / labour
    (r"\b(strike|union|labour|labor|walkout)\b", "👷"),

    # Culture
    (r"\b(film|movie|netflix|hollywood|streaming|series|hbo)\b", "🎬"),
    (r"\b(nba|nhl|nfl|mlb|raptors|leafs|blue jays|formula 1|world cup|olympics)\b", "🏆"),
    (r"\b(restaurant|chef|menu|michelin)\b", "🍽️"),

    # Design / product
    (r"\b(design|ux|figma|product|prototype|interaction)\b", "🎨"),
]

EVERYTHING_ELSE_SOURCE_EMOJIS = {
    # Canada & Toronto
    "CBC":                "🇨🇦",
    "Globe & Mail":       "🇨🇦",
    "r/toronto":          "🏙️",
    "BlogTO":             "🏙️",
    "Toronto Star":       "🏙️",
    "National Post":      "🇨🇦",
    "National Newswatch": "🇨🇦",
    "Canadaland":         "🇨🇦",

    # Toronto Housing
    "Globe & Mail Finance":   "🏠",
    "r/canadahousing":        "🏠",
    "Storeys":                "🏠",
    "BetterDwelling":         "🏠",
    "MoneySense Real Estate": "🏠",

    # Tech & AI
    "TechCrunch":     "💻",
    "Hacker News":    "💻",
    "Simon Willison": "🤖",
    "Stratechery":    "💻",

    # Finance & Markets
    "Yahoo Finance": "📈",
    "WSJ":           "📈",
    "MoneySense":    "💰",

    # US & Global
    "BBC":       "🌍",
    "NYT":       "🇺🇸",
    "Economist": "🌍",
    "NPR World": "🌍",
    "Axios":     "🇺🇸",

    # Design & Product
    "UX Collective":      "🎨",
    "Smashing Magazine":  "🎨",
    "NN/g":               "🎨",
    "Lenny's Newsletter": "📊",
    "Design Milk":        "🎨",
    "Hypebeast":          "👟",
    "Codrops":            "🎨",
    "Sidebar":            "🎨",
    "Trendland":          "🎨",

    # Today in the World (podcasts)
    "NYT The Daily":      "🎙️",
    "Today Explained":    "🎙️",
    "CBC Frontburner":    "🎙️",
    "NBC Meet the Press": "🎙️",
}
```

- [ ] **Step 2: Confirm config.py still imports cleanly**

Run: `python -c "import config; print(len(config.EVERYTHING_ELSE_KEYWORD_EMOJIS), len(config.EVERYTHING_ELSE_SOURCE_EMOJIS))"`
Expected: `23 38` (or matching numbers if you tuned the seeds).

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "config: seed Everything Else keyword + source emoji maps"
```

---

## Task 2: Add failing tests for `pick_everything_else_emoji`

**Files:**
- Modify: `tests/test_formatting.py` (append new tests near the end of the file)

- [ ] **Step 1: Add helper to the import list at the top of `tests/test_formatting.py`**

Find the existing `from formatting import (...)` block at the top of the file. Add `pick_everything_else_emoji` to the imported names, keeping alphabetical order if the existing block uses it.

Example final import block (your existing entries plus the new name):

```python
from formatting import (
    build_email_html,
    build_everything_else,
    build_format_input,
    parse_and_render_sections,
    pick_everything_else_emoji,
    render_other_headlines_for_section,
    render_source_line,
    suppressed_cluster_ids,
)
```

- [ ] **Step 2: Append the new test block to the bottom of `tests/test_formatting.py`**

```python
def test_pick_everything_else_emoji_keyword_match_wins_over_source():
    # Title contains an AI-vendor keyword; source map says 📈 for WSJ,
    # but the keyword regex must win because it comes first in resolution.
    assert pick_everything_else_emoji("OpenAI raises Series F", "WSJ") == "🤖"


def test_pick_everything_else_emoji_source_used_when_no_keyword_match():
    # Title has no mapped keyword; source map kicks in.
    assert pick_everything_else_emoji("Quiet Monday at the market", "WSJ") == "📈"


def test_pick_everything_else_emoji_safety_net_when_neither_matches():
    # Unmapped source, unmapped keyword set → 📰 safety net.
    assert pick_everything_else_emoji("A poem about clouds", "Unknown Source") == "📰"


def test_pick_everything_else_emoji_is_case_insensitive():
    assert pick_everything_else_emoji("OPENAI hires research lead", "WSJ") == "🤖"
    assert pick_everything_else_emoji("OpEnAi releases benchmark", "WSJ") == "🤖"


def test_pick_everything_else_emoji_respects_word_boundaries():
    # "capitalism" must not match the \b(apple|...)\b rule via substring.
    # Source "WSJ" still resolves to 📈 via the source map.
    assert pick_everything_else_emoji("Capitalism and its critics", "WSJ") == "📈"


def test_pick_everything_else_emoji_empty_title_falls_through_to_source():
    assert pick_everything_else_emoji("", "WSJ") == "📈"
    assert pick_everything_else_emoji(None, "WSJ") == "📈"


def test_pick_everything_else_emoji_first_keyword_in_declared_order_wins():
    # Title mentions both "apple" (🍎) and "google" (🔎). The keyword list
    # declares apple before google, so apple wins.
    assert pick_everything_else_emoji("Apple and Google announce partnership", "WSJ") == "🍎"
```

- [ ] **Step 3: Run the new tests to confirm they all fail (helper not yet defined)**

Run: `pytest tests/test_formatting.py -k pick_everything_else_emoji -v`
Expected: All seven tests FAIL with `ImportError` on the new symbol, or `AttributeError` once the import is added. (If you see a collection-level error, that's the import failing — that counts as the expected failure for TDD.)

- [ ] **Step 4: Commit the failing tests**

```bash
git add tests/test_formatting.py
git commit -m "test: failing tests for pick_everything_else_emoji"
```

---

## Task 3: Implement `pick_everything_else_emoji` in `formatting.py`

**Files:**
- Modify: `formatting.py` (add new helper above `build_everything_else`, which currently starts at line 837)

- [ ] **Step 1: Make sure the `re` and the new config constants are importable**

`formatting.py` already imports `re` at the top of the file. Confirm by opening the file — if `re` is not imported, add `import re` near the other stdlib imports.

For the config constants, find the existing `from config import ...` block. Add the two new names:

```python
from config import (
    # ... existing imports preserved ...
    EVERYTHING_ELSE_KEYWORD_EMOJIS,
    EVERYTHING_ELSE_SOURCE_EMOJIS,
)
```

If `formatting.py` uses `import config` rather than `from config import ...`, leave the import line alone and reference the constants as `config.EVERYTHING_ELSE_KEYWORD_EMOJIS` / `config.EVERYTHING_ELSE_SOURCE_EMOJIS` inside the helper. Mirror whichever pattern the file already uses.

- [ ] **Step 2: Insert the helper directly above `def build_everything_else(...)`**

```python
def pick_everything_else_emoji(title: str, source: str) -> str:
    """Pick the per-item emoji for an Everything Else entry.

    Resolution order:
      1. First case-insensitive keyword match in EVERYTHING_ELSE_KEYWORD_EMOJIS.
      2. Exact match in EVERYTHING_ELSE_SOURCE_EMOJIS.
      3. Newspaper safety net (📰) — only reached if a new source slipped
         into the feed without being added to the source map.
    """
    text = (title or "").lower()
    for pattern, emoji in EVERYTHING_ELSE_KEYWORD_EMOJIS:
        if re.search(pattern, text):
            return emoji
    if source in EVERYTHING_ELSE_SOURCE_EMOJIS:
        return EVERYTHING_ELSE_SOURCE_EMOJIS[source]
    return "📰"
```

If using the `import config` style, swap the bare constant names for `config.EVERYTHING_ELSE_KEYWORD_EMOJIS` and `config.EVERYTHING_ELSE_SOURCE_EMOJIS`.

- [ ] **Step 3: Run the helper tests to confirm they pass**

Run: `pytest tests/test_formatting.py -k pick_everything_else_emoji -v`
Expected: All 7 tests PASS.

- [ ] **Step 4: Commit**

```bash
git add formatting.py
git commit -m "feat: pick_everything_else_emoji helper for per-item emoji selection"
```

---

## Task 4: Update existing Everything Else HTML test to fail against the old `<li>` structure

**Files:**
- Modify: `tests/test_formatting.py` (around line 392 inside `test_build_everything_else_caps_at_seven_globally`)

- [ ] **Step 1: Replace the `<li`-count assertion with a `<p style`-count assertion + emoji presence check**

Find this in `tests/test_formatting.py` (line 392 today):

```python
    html = build_everything_else(links_by_id, used_ids, {}, tiered_items=tiered_items)
    assert html.count("<li") == 7
    # The two tier_1 overflows must appear (highest priority).
    assert "Headline 0" in html
    assert "Headline 1" in html
```

Replace it with:

```python
    html = build_everything_else(links_by_id, used_ids, {}, tiered_items=tiered_items)
    # New structure: <p> per item, no <ul>/<li>. Each item carries an emoji span
    # and a <strong>-wrapped first-words link.
    assert "<ul" not in html
    assert "<li" not in html
    assert html.count("<p style=\"margin:0 0 14px") == 7
    assert html.count("<strong>") == 7
    # Every item uses source "CBC" → 🇨🇦 via EVERYTHING_ELSE_SOURCE_EMOJIS.
    # Titles are "Headline {i}", which match no keyword regex, so source wins.
    # The section header text "Everything Else" carries no 🇨🇦, so exactly 7.
    assert html.count("🇨🇦") == 7
    # The two tier_1 overflows must appear (highest priority).
    assert "Headline 0" in html
    assert "Headline 1" in html
```

- [ ] **Step 2: Run the updated test to confirm it now FAILS**

Run: `pytest tests/test_formatting.py::test_build_everything_else_caps_at_seven_globally -v`
Expected: FAIL — the current `build_everything_else` still emits `<li>` and no `<strong>`, so the new assertions don't hold.

- [ ] **Step 3: Confirm the empty-state test still passes**

Run: `pytest tests/test_formatting.py::test_build_everything_else_returns_empty_when_no_unused_items -v`
Expected: PASS (it asserts `html == ""`; we're keeping the empty-string return for the no-items case).

- [ ] **Step 4: Commit the failing test update**

```bash
git add tests/test_formatting.py
git commit -m "test: assert new <p>/strong/emoji structure for Everything Else"
```

---

## Task 5: Rewrite `build_everything_else` to emit the new HTML

**Files:**
- Modify: `formatting.py` (current lines 837-894 — the body of `build_everything_else`)

- [ ] **Step 1: Replace the `items_html` build and the surrounding container with the new `<p>`-based structure**

The current implementation (lines 869-894 in `formatting.py`) is:

```python
    items_html = ""
    for _tier, _neg_score, _lid, l in top:
        words = l["title"].split(" ")
        link_words = " ".join(words[:4])
        remaining = " ".join(words[4:])
        linked_part = (
            f'<a href="{l["link"]}" style="color:#333;font-weight:400;'
            f'text-decoration:underline;text-decoration-color:#1c7ff2;">{link_words}</a>'
            if l["link"] else link_words
        )
        full_line = f"{linked_part} {remaining}" if remaining else linked_part
        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">{full_line}</li>'
        )

    return (
        '\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
        'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
        '\n  <div style="padding:15px 15px 0">'
        '\n    <p style="color:#1c7ff2;margin:0 0 4px;font-size:13px;font-weight:700;'
        'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        '\n  </div>'
        f'\n  <div style="padding:0 15px 15px"><ul style="margin:0;padding-left:20px">{items_html}</ul></div>'
        '\n</div>'
    )
```

Replace the entire block above with:

```python
    items_html = ""
    for _tier, _neg_score, _lid, l in top:
        words = l["title"].split(" ")
        link_words = " ".join(words[:4])
        remaining = " ".join(words[4:])
        linked_part = (
            f'<a href="{l["link"]}" style="color:#333;font-weight:700;'
            f'text-decoration:underline;text-decoration-color:#1c7ff2;">'
            f'<strong>{link_words}</strong></a>'
            if l["link"] else f'<strong>{link_words}</strong>'
        )
        full_line = f"{linked_part} {remaining}" if remaining else linked_part
        emoji = pick_everything_else_emoji(l.get("title", ""), l.get("source", ""))
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{emoji}</span>'
            f'{full_line}</p>'
        )

    return (
        '\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
        'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
        '\n  <div style="padding:15px 15px 0">'
        '\n    <p style="color:#1c7ff2;margin:0 0 4px;font-size:13px;font-weight:700;'
        'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        '\n  </div>'
        f'\n  <div style="padding:0 15px 15px">{items_html}</div>'
        '\n</div>'
    )
```

Two changes vs. the old code, beyond moving from `<li>` to `<p>`:
1. The link's `font-weight` flips from `400` to `700`, and the inner text is wrapped in `<strong>`. Both bolding signals are kept (`font-weight:700` plus `<strong>`) so that email clients which strip semantic tags still render the link bold.
2. The wrapping `<ul style="margin:0;padding-left:20px">{items_html}</ul>` is gone — `<p>` items now sit directly under the card's inner `<div>`.

- [ ] **Step 2: Run the previously-failing test to confirm it now passes**

Run: `pytest tests/test_formatting.py::test_build_everything_else_caps_at_seven_globally -v`
Expected: PASS.

- [ ] **Step 3: Run the full formatting test file**

Run: `pytest tests/test_formatting.py -v`
Expected: All tests PASS. Pay particular attention to any test that asserts on `build_email_html` output (which calls `build_everything_else` internally) — they should still pass because the card container, section header, and item content remain.

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: All tests PASS (formatting plus pipeline plus prompts plus smoke plus triage plus traction plus routing plus comparison).

- [ ] **Step 5: Commit**

```bash
git add formatting.py
git commit -m "feat: per-item emoji + bold link prefix in Everything Else"
```

---

## Task 6: Manual visual spot-check (optional but recommended)

**Files:**
- Use: `tmp/agent-scratch/` (scratch dir for any temp HTML — do not commit)

- [ ] **Step 1: Generate a fixture-based render to eyeball the new HTML**

If a smoke fixture already exists for a sample newsletter, run it. Otherwise, write a one-off script in `tmp/agent-scratch/render_smoke.py`:

```python
# tmp/agent-scratch/render_smoke.py — throwaway preview script
from formatting import build_everything_else

links_by_id = {
    0: {"id": 0, "title": "OpenAI ships GPT-5 alongside revised pricing", "link": "https://example.com/0", "image": "", "source": "WSJ"},
    1: {"id": 1, "title": "Toronto condo listings rise as rates settle",     "link": "https://example.com/1", "image": "", "source": "Storeys"},
    2: {"id": 2, "title": "Carney unveils housing accelerator",              "link": "https://example.com/2", "image": "", "source": "CBC"},
    3: {"id": 3, "title": "TTC plans Eglinton service changes",              "link": "https://example.com/3", "image": "", "source": "BlogTO"},
    4: {"id": 4, "title": "Bitcoin tops sixty thousand again",               "link": "https://example.com/4", "image": "", "source": "Yahoo Finance"},
    5: {"id": 5, "title": "Climate report flags Lake Ontario warming",       "link": "https://example.com/5", "image": "", "source": "BBC"},
    6: {"id": 6, "title": "Codrops feature: scroll-driven animations",       "link": "https://example.com/6", "image": "", "source": "Codrops"},
}
tiered = [{"id": i, "tier": 3, "section": "Tech & AI",
           "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}}
          for i in range(7)]

html = build_everything_else(links_by_id, used_ids=set(), clusters_by_item_id={}, tiered_items=tiered)
import pathlib
out = pathlib.Path("tmp/agent-scratch/everything_else_preview.html")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"<!doctype html><html><body>{html}</body></html>")
print(out)
```

Run: `python tmp/agent-scratch/render_smoke.py`
Open the file path it prints in a browser. Confirm: no bullets, an emoji at the start of each item, the first-4-words link is bold/underlined/blue-underline, the rest of the headline is plain.

- [ ] **Step 2: Discard the scratch script**

No commit. `tmp/agent-scratch/` is for transient previews per the global preferences.

---

## Done definition

- `pytest -q` passes.
- The Everything Else block in a generated newsletter renders with one emoji per item, a bolded first-words link, and no bullets.
- The Today in the World section is byte-identical to its pre-change output.
- `config.py` carries the two new maps; future tuning happens there.

## Out of scope (do not touch)

- `_render_today_in_the_world` and any other section renderer.
- `FORMAT_SYSTEM_PROMPT`, `LEGACY_FORMAT_SYSTEM_PROMPT`, or any prompt.
- `MAX_EVERYTHING_ELSE`, the ranking logic, the cluster suppression logic.
- `SECTION_EMOJIS` (the section-header emoji map).
- The "📋 Everything Else" section header itself.
