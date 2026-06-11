# Per-section "What this means" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-article "What this means for you" callout with one per-section "What this means" block (2-3 sentences), gated by a `CALLOUT_MODE` toggle so the legacy behavior reverts with a one-line flip.

**Architecture:** The block is generated inside the existing FORMAT call, which already receives every section's full item set across all tiers (featured + Other Headlines). A `CALLOUT_MODE` config flag (`"section"` default, `"article"` legacy) selects both the system prompt (in `call_formatter`) and the parse/render path (in `parse_and_render_sections`). Both behaviors stay fully alive; nothing is deleted.

**Tech Stack:** Python 3, pytest, Anthropic SDK (Claude Sonnet for the FORMAT call).

**Working location:** Work directly on `main` (project preference: no worktrees/branches).

---

## File Structure

- `config.py` — add the `CALLOUT_MODE` flag (module-level constant, env-overridable).
- `prompts.py` — split `CALLOUT_GUIDANCE` into per-article / per-section variants; build both FORMAT system prompts from a shared helper.
- `formatting.py` — `select_format_prompt()` helper + `call_formatter` selection; `_render_callout_html()` + `_extract_section_callout()` helpers; mode branch in `parse_and_render_sections`.
- `tests/test_formatting.py` — update existing callout tests; add per-section, two-hit, zero-hit, label, article-mode, and Today-in-the-World coverage.

---

## Task 1: Add the `CALLOUT_MODE` flag

**Files:**
- Modify: `config.py:9` (next to `TEST_MODE`)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add at the end of `tests/test_formatting.py`:

```python
def test_callout_mode_defaults_to_section():
    import importlib, config
    importlib.reload(config)
    assert config.CALLOUT_MODE == "section"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_formatting.py::test_callout_mode_defaults_to_section -v`
Expected: FAIL with `AttributeError: module 'config' has no attribute 'CALLOUT_MODE'`

- [ ] **Step 3: Add the flag**

In `config.py`, immediately after the `TEST_MODE` line (line 9):

```python
# "What this means" callout mode. "section" renders one per-section block
# collecting every relevant item (featured or Other Headlines); "article"
# restores the legacy one-line-per-featured-story callout. Flip the default
# (or set CALLOUT_MODE=article in the workflow env) to revert with no loss.
CALLOUT_MODE = os.environ.get("CALLOUT_MODE", "section")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_formatting.py::test_callout_mode_defaults_to_section -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_formatting.py
git commit -m "feat: add CALLOUT_MODE flag (section default, article legacy)"
```

---

## Task 2: Split callout guidance and build both FORMAT prompts

**Files:**
- Modify: `prompts.py:27-150` (the `CALLOUT_GUIDANCE` constant and `FORMAT_SYSTEM_PROMPT` f-string)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_per_section_prompt_has_section_callout_rules():
    from prompts import (
        FORMAT_SYSTEM_PROMPT_PER_SECTION,
        FORMAT_SYSTEM_PROMPT_PER_ARTICLE,
    )
    # New per-section prompt: collective block, no "for you", whole-section scope.
    assert "What this means:" in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "What this means for you:" not in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "Other Headlines" in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "at least one" in FORMAT_SYSTEM_PROMPT_PER_SECTION.lower()
    # Legacy per-article prompt keeps the old single-sentence rule.
    assert "What this means for you:" in FORMAT_SYSTEM_PROMPT_PER_ARTICLE
    # Shared structure survives in both.
    for p in (FORMAT_SYSTEM_PROMPT_PER_SECTION, FORMAT_SYSTEM_PROMPT_PER_ARTICLE):
        assert "Layout A" in p
        assert "Featured Layout" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_formatting.py::test_per_section_prompt_has_section_callout_rules -v`
Expected: FAIL with `ImportError: cannot import name 'FORMAT_SYSTEM_PROMPT_PER_SECTION'`

- [ ] **Step 3: Rename the existing guidance constant**

In `prompts.py`, rename `CALLOUT_GUIDANCE` (line 27) to `CALLOUT_GUIDANCE_PER_ARTICLE`. Keep its body byte-for-byte. The line becomes:

```python
CALLOUT_GUIDANCE_PER_ARTICLE = f"""WHAT THIS MEANS FOR YOU LINE. Layout A items only. The bar is high.
```

(everything else in that string is unchanged through its closing `"""`).

- [ ] **Step 4: Add the per-section guidance constant**

Immediately after the `CALLOUT_GUIDANCE_PER_ARTICLE` string closes, add:

```python
CALLOUT_GUIDANCE_PER_SECTION = f"""WHAT THIS MEANS BLOCK. One per section, at the very end of the section. The bar is high.

After writing a section's featured stories, look at EVERY item in that section, the featured stories AND the lower-tier items that become its Other Headlines (you receive all of them with their snippets). Decide which items, if any, clearly hit one of Frank's active concerns below. If you are unsure about an item, it does not count. A weak takeaway is worse than none. There is no quota.

Frank's active concerns (the only basis for relevance):
{PERSONAL_RELEVANCE_BLURB}

Decide how many items in the section clearly hit a concern:
- Zero items hit: write nothing for this section. Skip the block entirely.
- At least one item hits: write exactly one block, as the last thing in the section, in this exact shape:

What this means: <2 to 3 sentences written directly to Frank>

The block collects the section's relevant items wherever they sit:
- One item hits: speak to that one item.
- Two or more items hit: cover each relevant piece in the 2 to 3 sentences, whether it was a featured story or an Other Headline. Name the specific story or fact so Frank knows which item you mean.

Voice rules for this block (these override any generic phrasing instincts):
- 2 to 3 sentences. No more.
- No em dashes. Use a period or a comma.
- No "this matters because", "it's worth noting", "could have implications for", "interestingly", "represents", "in today's".
- No negative parallelism. Avoid "X isn't Y, it's Z" or "not just X, but Y" shapes.
- Name the specific project, asset, or decision when the story supports it: the Leslieville sale, the staff or principal job hunt, the Quite Frankly pipeline, the workout PWA, the pattern library, BoC rate path, GTA condo demand.
- Use real numbers with units when the source supports them. Skip the claim before guessing them.
- Plain second person, in Frank's voice.

Examples (study the specificity gap, then match the strong column):

One item hits (Tech & AI):
Strong: What this means: Anthropic's prompt caching cuts repeated-context cost by 80%, and the Quite Frankly pipeline reads the same personal-context blurb on every run, so wiring caching into the triage call is a near-free token cut.
Weak: What this means: Some of this AI news could be relevant to your projects.

Two items hit (Toronto Housing, one featured + one Other Headline):
Strong: What this means: The Bank of Canada hold keeps buyers waiting for the fall cut, so expect more lookers than offers on the Leslieville unit for now. The Storeys headline on rising GTA condo inventory points the same way, more supply landing into soft demand.
Weak: What this means: Rates and condo supply are both things to watch for your sale.

Zero items hit (US & Global, defense and foreign-policy stories):
Skip. No clear hit on Frank's listed concerns.

Default behavior when uncertain about the section as a whole: skip the block. This block applies to every section including Today in the World, under the same rule."""
```

- [ ] **Step 5: Wrap the FORMAT prompt in a builder and produce both variants**

In `prompts.py`, the `FORMAT_SYSTEM_PROMPT = f"""..."""` block (currently lines 97-150) embeds `{CALLOUT_GUIDANCE}` at line 139. Replace the whole assignment with a builder that takes the guidance as a parameter, then instantiate both prompts plus a back-compat alias. The body of the f-string is unchanged except `{CALLOUT_GUIDANCE}` becomes `{callout_guidance}`:

```python
def _build_format_prompt(callout_guidance: str) -> str:
    return f"""You are the writer for a daily briefing. The selection work has already been done. You will receive a JSON input listing items grouped by section and tier, plus a clusters lookup for stories covered by multiple sources.

Output a single SUBJECT line as the first line:
SUBJECT: <emoji> <headline>

Pick the single most consequential Tier 1 item across all sections as the subject. Rewrite it as a tight headline of at most 70 characters, no quotes, no trailing punctuation. Choose one emoji that captures the topic (legislation ⚖️, tech 💻, housing 🏠, markets 📈, design 🎨, transit 🚇, climate 🌍, world 🌐, AI 🤖).

After SUBJECT, leave one blank line, then write the briefing.

The input "sections" object is keyed by section name. Render each populated section as:

## <section name, exactly as it appears as the JSON key>

The section name must be exactly one of these strings, copied verbatim from the JSON key, with no extra characters, no markdown, no IDs:
- Canada & Toronto
- Toronto Housing
- Tech & AI
- Design & Product
- Finance & Markets
- US & Global
- Today in the World

Section ordering is determined by the input dict key order. Skip a section entirely if it has no items in any tier. Never use a story headline as a section heading.

Each section uses one of two layouts depending on its name.

FEATURED LAYOUT — Today in the World list. Used only for the Today in the World section. Render exactly the 5 items in the input's tier_1 array (in that order). For each item, write:

<emoji> **<short story-phrase that fits this story> [#N]:** One short paragraph (2 to 3 sentences) of body. Use inline markdown links to the item's siblings array when the story has multiple sources — anchor the link on the most relevant noun or concept in the body, formatted as [anchor text](url).

The emoji is per-story, chosen from the story's actual topic (🤖 AI lab, ⚖️ regulation, 📱 product launch, 🏠 housing, 📈 markets, 🌍 climate). The bold micro-header is a phrase drawn from the substance of the story — not a generic summary tag.

LAYOUT A — Featured story. Used for every other section (Canada & Toronto, Toronto Housing, Tech & AI, Design & Product, Finance & Markets, US & Global). For each tier_1 item in those sections, write:

**Original headline text [#N]**
**<short conceptual micro-header for paragraph one.>** Body paragraph one, 2 to 3 sentences.

**<short conceptual micro-header for paragraph two.>** Body paragraph two, 2 to 3 sentences.
Source: <cluster primary_source>

Write exactly 2 body paragraphs per item — no more, no fewer. Each paragraph opens with a short bold micro-header that names a turn in the narrative (setup, scene, cause, exception) — not a summary of the paragraph that follows. Examples of good micro-headers: "Decreasing optimism.", "Threading the needle.", "Why the shift?". If the item has a non-empty siblings array, embed inline markdown links in the body to one or two of the sibling URLs, anchored on a noun or concept that fits. For Finance & Markets and US & Global items, do NOT use inline markdown links in the body, regardless of the siblings array.

{callout_guidance}

Other Headlines and Everything Else are rendered programmatically after you finish. Do not include `### Other Headlines` or `## Everything Else` in your output — anything you write under those headers will be discarded. Your only job is to write the featured tier_1 stories for each section.

CRITICAL RULES YOU MUST FOLLOW:
1. Every input item carries an [#N] ID. You MUST preserve the exact [#N] inside the bold markers of every featured headline. Example: **Headline text [#42]:** for Featured Layout items, or **Headline text [#42]** for Layout A items.
2. Never move an item to a different section than the input assigned. Section is final. Render sections in the order they appear in the input.
3. Never invent items. Use only the IDs provided in the input.
4. For each item, use the cluster's primary_source for the Source line. If the input does not provide a cluster, fall back to the item's own source.
5. Body paragraphs must be separated by exactly one blank line.
6. Inline markdown links must point to URLs that appear in the item's siblings array. Never invent URLs.
"""


FORMAT_SYSTEM_PROMPT_PER_ARTICLE = _build_format_prompt(CALLOUT_GUIDANCE_PER_ARTICLE)
FORMAT_SYSTEM_PROMPT_PER_SECTION = _build_format_prompt(CALLOUT_GUIDANCE_PER_SECTION)
# Back-compat: existing imports/tests reference FORMAT_SYSTEM_PROMPT. Point it
# at the active default so structural assertions keep passing.
FORMAT_SYSTEM_PROMPT = FORMAT_SYSTEM_PROMPT_PER_SECTION
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py::test_per_section_prompt_has_section_callout_rules tests/test_formatting.py -k "format_system or prompt" -v`
Expected: PASS (new test green; existing prompt-structure tests at lines 802-828 still green because the shared body is intact).

- [ ] **Step 7: Commit**

```bash
git add prompts.py tests/test_formatting.py
git commit -m "feat: per-section What this means guidance + dual FORMAT prompts"
```

---

## Task 3: Select the FORMAT prompt by mode in `call_formatter`

**Files:**
- Modify: `formatting.py:30` (import), `formatting.py:419-432` (`call_formatter`)
- Create helper: `formatting.py` `select_format_prompt`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_select_format_prompt_by_mode():
    from formatting import select_format_prompt
    from prompts import (
        FORMAT_SYSTEM_PROMPT_PER_SECTION,
        FORMAT_SYSTEM_PROMPT_PER_ARTICLE,
    )
    assert select_format_prompt("section") is FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert select_format_prompt("article") is FORMAT_SYSTEM_PROMPT_PER_ARTICLE
    # Unknown / None falls back to the configured default ("section").
    assert select_format_prompt(None) is FORMAT_SYSTEM_PROMPT_PER_SECTION
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_formatting.py::test_select_format_prompt_by_mode -v`
Expected: FAIL with `ImportError: cannot import name 'select_format_prompt'`

- [ ] **Step 3: Update imports**

In `formatting.py`, the `from config import (...)` block (line 17) — add `CALLOUT_MODE` to the imported names. In the `from prompts import (...)` block, replace the single `FORMAT_SYSTEM_PROMPT` (line 30) with:

```python
    FORMAT_SYSTEM_PROMPT_PER_ARTICLE,
    FORMAT_SYSTEM_PROMPT_PER_SECTION,
```

- [ ] **Step 4: Add the helper and use it in `call_formatter`**

Add the helper just above `call_formatter` (line 419):

```python
def select_format_prompt(callout_mode=None):
    """Return the FORMAT system prompt for the given callout mode.

    "article" → legacy per-story callout prompt; anything else (including
    None) → the per-section default.
    """
    mode = callout_mode if callout_mode is not None else CALLOUT_MODE
    if mode == "article":
        return FORMAT_SYSTEM_PROMPT_PER_ARTICLE
    return FORMAT_SYSTEM_PROMPT_PER_SECTION
```

Then in `call_formatter`, change the `create(...)` call's `system=` argument (line 429) from `system=FORMAT_SYSTEM_PROMPT,` to:

```python
        system=select_format_prompt(),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py::test_select_format_prompt_by_mode -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: select FORMAT prompt by CALLOUT_MODE in call_formatter"
```

---

## Task 4: Render the per-section block in `parse_and_render_sections`

**Files:**
- Modify: `formatting.py:743` (signature), `formatting.py:767-782` (Today in the World branch), `formatting.py:784-907` (Layout A parse + render)
- Add helpers: `formatting.py` `_render_callout_html`, `_extract_section_callout`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_formatting.py`:

```python
def test_section_mode_single_hit_one_block_at_bottom():
    text = (
        "## Tech & AI\n\n**Big news [#1]**\nBody paragraph.\nSource: CBC\n"
        "**Second story [#2]**\nMore body.\nSource: BBC\n"
        "What this means: One relevant takeaway for you."
    )
    links = {
        1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""},
        2: {"link": "https://b.co", "image": None, "title": "Second story", "snippet": ""},
    }
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    # Exactly one callout block, labelled without "for you".
    assert html.count("What this means:") == 1
    assert "What this means for you:" not in html
    # Block sits after the last story body, not between stories.
    assert html.index("What this means:") > html.index("Second story")


def test_section_mode_zero_hits_no_block():
    text = "## Tech & AI\n\n**Big news [#1]**\nBody paragraph.\nSource: CBC"
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert "What this means" not in html


def test_section_mode_tolerates_legacy_for_you_text():
    text = (
        "## Tech & AI\n\n**Big news [#1]**\nBody.\nSource: CBC\n"
        "What this means for you: legacy phrasing still parses."
    )
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    # Rendered label is normalised to drop "for you".
    assert "What this means:</strong> legacy phrasing" in html
    assert "What this means for you:" not in html


def test_article_mode_keeps_legacy_per_story_callout():
    text = "## Tech & AI\n\n**Big news [#1]**\nBody.\nSource: CBC\nWhat this means for you: do X"
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="article")
    assert "What this means for you:</strong> do X" in html


def test_section_mode_today_in_the_world_block_at_bottom():
    text = (
        "## Today in the World\n\n🌍 **Rates held [#1]:** markets mixed.\n\n"
        "🤖 **AI lab news [#2]:** a model shipped.\n"
        "What this means: The model ship touches the Quite Frankly pipeline."
    )
    links = {
        1: {"link": "https://a.co", "image": None, "title": "Rates held", "snippet": "x"},
        2: {"link": "https://b.co", "image": None, "title": "AI lab news", "snippet": "y"},
    }
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert html.count("What this means:") == 1
    assert html.index("What this means:") > html.index("AI lab news")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_formatting.py -k "section_mode or article_mode" -v`
Expected: FAIL — `parse_and_render_sections() got an unexpected keyword argument 'callout_mode'`.

- [ ] **Step 3: Add the two render helpers**

In `formatting.py`, just above `parse_and_render_sections` (line 743), add:

```python
_CALLOUT_LINE_RE = re.compile(r"^what this means(?: for you)?:\s*(.*)", re.IGNORECASE)


def _render_callout_html(text, palette, label="What this means:"):
    return (
        f'<div style="margin:10px 0 0;padding:12px 14px;background:{palette["callout_bg"]};'
        f'border-left:3px solid {palette["accent"]};font-size:14px;line-height:20px;color:{palette["body"]};'
        f'font-family:Helvetica,Arial,sans-serif">'
        f'<strong style="color:{palette["accent"]}">{label}</strong> {text}</div>'
    )


def _extract_section_callout(lines):
    """Pull a 'What this means[ for you]:' line out of a section's body lines.

    Returns (callout_text, remaining_lines). Tolerates the legacy 'for you'
    phrasing so an in-flight prompt swap never drops the line. Last match wins.
    """
    callout = ""
    remaining = []
    for line in lines:
        m = _CALLOUT_LINE_RE.match(line.strip())
        if m:
            callout = m.group(1).strip()
        else:
            remaining.append(line)
    return callout, remaining
```

- [ ] **Step 4: Add the `callout_mode` parameter and resolve it**

Change the `parse_and_render_sections` signature (line 743) to add `callout_mode=None` as the final parameter:

```python
def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None, is_design_edition=False, palette: dict = LIGHT, oh_copy_by_id=None, oh_collect=None, callout_mode=None):
```

As the first line of the function body, resolve the mode:

```python
    mode = callout_mode if callout_mode is not None else CALLOUT_MODE
```

- [ ] **Step 5: Pre-extract the section callout per section**

Inside the per-section loop, after `title` is computed and the `everything else` skip (around line 765, right before the Today-in-the-World branch at line 767), insert:

```python
        section_callout = ""
        body_lines = lines[1:]
        if mode == "section":
            section_callout, body_lines = _extract_section_callout(body_lines)
```

- [ ] **Step 6: Render the block in the Today in the World branch**

In the Today in the World branch (lines 767-782), change the render call to use `body_lines` instead of `lines[1:]`, and append the callout to `stories_html` before the card is assembled. Replace:

```python
            stories_html = _render_today_in_the_world(lines[1:], links_by_id, used_ids, palette, is_design_edition)
            if not stories_html:
                continue
```

with:

```python
            stories_html = _render_today_in_the_world(body_lines, links_by_id, used_ids, palette, is_design_edition)
            if not stories_html:
                continue
            if mode == "section" and section_callout:
                stories_html += _render_callout_html(section_callout, palette)
```

- [ ] **Step 7: Use `body_lines` in the Layout A parse loop**

In the Layout A path, change the parse loop header (line 788) from `for line in lines[1:]:` to:

```python
        for line in body_lines:
```

- [ ] **Step 8: Replace the per-story callout render with the helper, and append the section block**

The per-story callout render block (lines 893-899) stays for article mode but now uses the helper. Replace it with:

```python
            if s["callout"]:
                stories_html += _render_callout_html(
                    s["callout"], palette, label="What this means for you:"
                )
```

(In `section` mode `s["callout"]` is always empty because the line was pre-extracted, so this never fires.)

Then, after `stories_html += oh_html` (line 907), append the section-level block:

```python
        if mode == "section" and section_callout:
            stories_html += _render_callout_html(section_callout, palette)
```

- [ ] **Step 9: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py -k "section_mode or article_mode" -v`
Expected: PASS (all six new tests).

- [ ] **Step 10: Run the full suite to catch regressions**

Run: `python -m pytest tests/test_formatting.py -v`
Expected: PASS. The legacy fixtures `test_section_card_dark_palette` and the `_FULL_TEXT` builds run in the default `section` mode; their `What this means for you: ...` lines now parse via the tolerant regex and render as one bottom-of-card block. They assert on palette colours, not callout position or label, so they stay green.

- [ ] **Step 11: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: render per-section What this means block, gated by CALLOUT_MODE"
```

---

## Task 5: Update the two existing callout fixtures to assert the new behavior

**Files:**
- Modify: `tests/test_formatting.py:1427-1438` (`test_section_card_dark_palette`)
- Modify: `tests/test_formatting.py:1470-1496` (`_FULL_TEXT` and its two builds)

- [ ] **Step 1: Strengthen `test_section_card_dark_palette`**

The fixture already exercises a callout. Make it assert the new label and that the legacy input still renders. Add these two assertions to the end of `test_section_card_dark_palette` (after line 1438):

```python
    assert "What this means:</strong> do X" in html   # normalised label, bottom block
    assert "What this means for you:" not in html      # "for you" dropped in section mode
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_formatting.py::test_section_card_dark_palette -v`
Expected: PASS

- [ ] **Step 3: Keep `_FULL_TEXT` exercising the callout under the default mode**

`_FULL_TEXT` (line 1470) contains `What this means for you: test it` in the Tech & AI section. Under the default `section` mode this renders as one bottom-of-card block. Add an assertion to `test_full_weekday_build_has_no_dark_only_colours` (after line 1496) confirming the block still renders:

```python
    assert "What this means:</strong> test it" in html
```

- [ ] **Step 4: Run both full-build tests**

Run: `python -m pytest tests/test_formatting.py -k "full_weekend_build or full_weekday_build" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_formatting.py
git commit -m "test: assert per-section callout label in existing fixtures"
```

---

## Task 6: Full regression pass and revert-toggle smoke check

**Files:**
- Test: whole suite

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (no failures).

- [ ] **Step 2: Manually confirm the toggle flips behavior**

Run:

```bash
python -c "
import formatting
text = '## Tech & AI\n\n**Big news [#1]**\nBody.\nSource: CBC\nWhat this means for you: do X'
links = {1: {'link': 'https://a.co', 'image': None, 'title': 'Big news', 'snippet': ''}}
sec, _ = formatting.parse_and_render_sections(text, links, callout_mode='section')
art, _ = formatting.parse_and_render_sections(text, links, callout_mode='article')
print('section label:', 'What this means:</strong>' in sec, '| no for-you:', 'for you' not in sec)
print('article label:', 'What this means for you:</strong>' in art)
"
```

Expected output:
```
section label: True | no for-you: True
article label: True
```

- [ ] **Step 3: Commit any final cleanup (if needed)**

```bash
git add -A
git commit -m "chore: per-section What this means regression pass" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** Trigger per-item/surfaced-per-section (Task 2 guidance + Task 4 zero/one/two-hit tests); high bar (Task 2); bottom placement (Task 4 Steps 6/8 + position asserts); 2-3 sentences and "What this means:" label (Task 2 + Task 4/5 label asserts); Today in the World eligibility (Task 4 Step 6 + TitW test); toggle gating prompt + parse/render + TitW (Tasks 1/3/4); legacy fallback untouched (no task touches `LEGACY_FORMAT_SYSTEM_PROMPT`); `max_tokens` unchanged (no task touches it).
- **Type consistency:** Helper names `select_format_prompt`, `_render_callout_html`, `_extract_section_callout`, variables `mode`/`section_callout`/`body_lines`, and prompt constants `FORMAT_SYSTEM_PROMPT_PER_ARTICLE` / `FORMAT_SYSTEM_PROMPT_PER_SECTION` are used identically across Tasks 2-5.
- **Back-compat:** `FORMAT_SYSTEM_PROMPT` retained as an alias (Task 2 Step 5) so tests at `test_formatting.py:802-828` keep importing it.
