# Unified Featured Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire Layouts B and C; rename the existing "Today in the World" layout to "Featured Layout"; introduce a single unified "Layout A" used by every other section (Canada & Toronto, Toronto Housing, Tech & AI, Design & Product, Finance & Markets, US & Global). Layout A has two body paragraphs per story, each opened with a bold micro-header.

**Architecture:** The current renderer already produces identical HTML for Layout B and Layout C body content (both render `**Cap.** body` as `<strong>Cap.</strong> body` inside a `<p>` element with identical styling). The only true visual differences live in (a) inter-story borders for multi-story sections, and (b) the special-case branch in `parse_and_render_sections` that calls `_render_from_the_front_page` when a section has exactly one story. We collapse to one featured-story renderer path, enforce a 2-paragraph cap at the renderer level (defense in depth against prompt drift), and rewrite the prompt so Claude always asks for 2 bold-micro-header paragraphs per story. Layout A in the prompt is the unified contract; Featured Layout in the prompt is the renamed Today in the World list.

**Tech Stack:** Python 3.12, `re` module for parsing, no new dependencies. Tests use `pytest`.

---

## File Structure

Files touched in this plan:

- **Modify** `formatting.py`
  - Remove `LAYOUT_C_PARAGRAPH_RE` (line ~334), `_looks_like_longform()` (lines ~337-341), and `_render_from_the_front_page()` (lines ~576-654).
  - In `parse_and_render_sections()`, delete the single-story longform branch (lines ~740-760) so the multi-story default path is the only featured renderer.
  - In that same default path (lines ~762-848), cap the per-story paragraph count at 2 before rendering.

- **Modify** `prompts.py`
  - Rewrite the layout section of `FORMAT_SYSTEM_PROMPT` (lines ~80-115): replace the Layout A/B/C trio with Featured Layout + new Layout A.
  - Update CRITICAL RULES (line ~120) to reference Featured Layout and Layout A instead of A/B/C.
  - `LEGACY_FORMAT_SYSTEM_PROMPT` is untouched — it's a fallback used when triage fails, and its simpler 2-paragraph format already renders cleanly through the unified path.

- **Modify** `tests/test_formatting.py`
  - Update `test_format_prompt_describes_today_in_the_world_layout` (line ~721) — the prompt-naming check.
  - Replace `test_format_prompt_describes_from_the_front_page_fallback` (line ~729) with a Layout A 2-paragraph contract check.
  - Rename and update `test_from_the_front_page_longform_renders_micro_headers` (line ~744) to test the unified renderer's 2-paragraph cap.
  - Rename `test_end_to_end_renders_all_three_layouts` to `test_end_to_end_renders_both_layouts` (line ~772); update its synthesized Claude response to use 2 paragraphs.
  - Update `test_end_to_end_pipeline_from_build_format_input_to_html` (line ~843): synthesize 2 paragraphs instead of 3 in the Finance & Markets block.

No new files. No new dependencies.

---

## Branching and Commits

This project's memory says **work directly on `main`; no feature branches, no worktrees**. Each task ends with a commit on `main`.

---

### Task 1: Cap featured-story body paragraphs at 2 in the renderer

**Why first:** This is the load-bearing behavior change. Adding it first means the rest of the plan (removing the longform branch, deleting dead code, rewriting the prompt) just simplifies code that's already producing the right output.

**Files:**
- Modify: `formatting.py` (default rendering path inside `parse_and_render_sections`, around lines 798-806)
- Modify: `tests/test_formatting.py` (add new test)

- [ ] **Step 1: Add a failing test for the 2-paragraph cap**

Append this test to `tests/test_formatting.py` (place it near the other parse_and_render_sections tests, just before `test_from_the_front_page_longform_renders_micro_headers`):

```python
def test_featured_story_caps_body_paragraphs_at_two():
    """Renderer caps featured-story body paragraphs at 2 even if Claude emits more."""
    text = """## Toronto Housing

**Stronger protection has arrived [#100]**
**Enhanced safeguards.** Ontario has new protections for pre-construction buyers.

**Market confidence building.** These protections restore trust in the new home market.

**Economic ripple effects.** A more secure marketplace boosts construction activity.
Source: Storeys

**Hidden townhouse hits the market [#101]**
**Exclusive enclave.** A rare Annex townhouse appeared on MLS.

**Understated luxury.** The community values privacy over flash.

**Market positioning.** At $2M, it targets discreet buyers.
Source: BlogTO
"""
    links_by_id = {
        100: {"link": "https://storeys.example/100", "image": "", "title": "Stronger protection"},
        101: {"link": "https://blogto.example/101", "image": "", "title": "Hidden townhouse"},
    }
    html, _ = parse_and_render_sections(text, links_by_id, {}, tiered_items=[])

    # First two paragraphs of story 100 render.
    assert "<strong>Enhanced safeguards.</strong>" in html
    assert "<strong>Market confidence building.</strong>" in html
    # Third paragraph of story 100 must NOT render.
    assert "<strong>Economic ripple effects.</strong>" not in html
    assert "Economic ripple effects" not in html

    # First two paragraphs of story 101 render.
    assert "<strong>Exclusive enclave.</strong>" in html
    assert "<strong>Understated luxury.</strong>" in html
    # Third paragraph of story 101 must NOT render.
    assert "<strong>Market positioning.</strong>" not in html
    assert "Market positioning" not in html
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `pytest tests/test_formatting.py::test_featured_story_caps_body_paragraphs_at_two -v`

Expected: FAIL. Each of the third-paragraph "must NOT render" assertions will fail because the current renderer emits all paragraphs.

- [ ] **Step 3: Add the cap in the default rendering loop**

In `formatting.py`, find the default rendering block inside `parse_and_render_sections` (around lines 799-806). The current code:

```python
            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs:
                    rendered = _render_body_markdown(p)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                        f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
                    )
```

Replace with:

```python
            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs[:FEATURED_STORY_PARAGRAPH_CAP]:
                    rendered = _render_body_markdown(p)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                        f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
                    )
```

Add this constant near the other section caps at the top of `formatting.py` (just after `MAX_OTHER_HEADLINES_PER_SECTION` on line 56):

```python
FEATURED_STORY_PARAGRAPH_CAP = 2
```

- [ ] **Step 4: Run the new test, verify it passes**

Run: `pytest tests/test_formatting.py::test_featured_story_caps_body_paragraphs_at_two -v`

Expected: PASS.

- [ ] **Step 5: Run the full test suite, expect three existing tests to fail**

Run: `pytest tests/test_formatting.py -v`

Expected failures (these will be updated in Task 4, do not fix yet):
- `test_from_the_front_page_longform_renders_micro_headers` — asserts `<strong>What it means.</strong>` is in HTML, but the third paragraph is now capped out.
- `test_end_to_end_renders_all_three_layouts` — asserts `<strong>Decreasing optimism.</strong>` is in HTML; this is the FIRST paragraph and should still render. But this test's synthesized response includes three paragraphs for the Finance & Markets section, so the third (`<strong>What it means.</strong>`, though not asserted, may surface elsewhere). Verify which assertion fails and continue.
- `test_end_to_end_pipeline_from_build_format_input_to_html` — asserts `<strong>Conclusion.</strong>` (third paragraph) is in HTML. This will fail.

Note the exact failing assertions, then proceed.

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: cap featured-story body paragraphs at 2

Defense-in-depth cap at the renderer so Claude's paragraph count
drift cannot inflate featured stories past the intended 2-paragraph
shape. Existing longform tests still pass through Layout C's
renderer for now; they will be updated in a follow-up task."
```

---

### Task 2: Remove the single-story longform branch from `parse_and_render_sections`

**Why:** The branch at lines 740-760 routes single-story sections to `_render_from_the_front_page`. With the 2-paragraph cap in Task 1 applied uniformly, the default multi-story path produces byte-identical HTML for single-story sections. The branch is no longer load-bearing.

**Files:**
- Modify: `formatting.py` (delete the longform branch in `parse_and_render_sections`)
- Modify: `tests/test_formatting.py` (add a regression test confirming single-story sections still render correctly via the default path)

- [ ] **Step 1: Add a regression test for single-story sections**

Append to `tests/test_formatting.py`, just after `test_featured_story_caps_body_paragraphs_at_two`:

```python
def test_single_story_section_renders_micro_headers_via_default_path():
    """Sections with exactly one story still render bold micro-headers on
    each paragraph after the longform branch is removed."""
    text = """## Finance & Markets

**Fed signals rate cut [#200]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back to one.

**Threading the needle.** Powell framed the move as data-dependent.
Source: WSJ
"""
    links_by_id = {200: {"link": "https://wsj.example/200", "image": "https://img/200.jpg",
                         "title": "Fed signals rate cut"}}
    clusters_by_item_id = {200: {"primary_source": "WSJ", "also_in": []}}
    html, used_ids = parse_and_render_sections(text, links_by_id, clusters_by_item_id, tiered_items=[])

    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    # Hero image rendered.
    assert 'src="https://img/200.jpg"' in html
    # Source line rendered.
    assert "WSJ" in html
    # ID tracked.
    assert 200 in used_ids
```

- [ ] **Step 2: Run the new test, verify it passes (the longform branch still produces this output)**

Run: `pytest tests/test_formatting.py::test_single_story_section_renders_micro_headers_via_default_path -v`

Expected: PASS. This test currently passes through `_render_from_the_front_page`. We are about to make it pass through the default path with identical output.

- [ ] **Step 3: Delete the longform branch in `parse_and_render_sections`**

In `formatting.py`, find this block in `parse_and_render_sections` (lines ~740-760):

```python
        # From the Front Page longform: exactly one featured story whose
        # body uses **<header>.** paragraph openers.
        if len(stories) == 1 and _looks_like_longform(stories[0]["body"]):
            stories_html = _render_from_the_front_page(
                stories[0], links_by_id, clusters_by_item_id, used_ids
            )
            oh_html = render_other_headlines_for_section(title, tiered_items, links_by_id, used_ids)
            stories_html += oh_html
            if not stories_html:
                continue
            html += (
                f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
                f'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
                f'\n  <div style="padding:15px 15px 0">'
                f'\n    <p style="color:#1c7ff2;margin:0 0 12px;font-size:13px;font-weight:700;'
                f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
                f'\n  </div>'
                f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
                f'\n</div>'
            )
            continue
```

Delete the entire block. The next line of code (`stories_html = ""` starting the default path) will follow immediately after the `if current_story: stories.append(current_story)` block above.

- [ ] **Step 4: Re-run the regression test, verify it still passes**

Run: `pytest tests/test_formatting.py::test_single_story_section_renders_micro_headers_via_default_path -v`

Expected: PASS. This proves the default path produces equivalent output for single-story sections.

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/test_formatting.py -v`

Expected: same three failures from Task 1 step 5 are still failing (longform-specific assertions on third paragraphs). All other tests pass.

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "refactor: drop single-story longform branch; unified path handles it

The default multi-story rendering loop produces identical HTML for
single-story sections once paragraphs are capped at 2. The longform
branch and its inter-story-borderless wrapper are no longer needed."
```

---

### Task 3: Delete dead code (`_render_from_the_front_page`, `_looks_like_longform`, `LAYOUT_C_PARAGRAPH_RE`)

**Why:** After Task 2, these symbols have no callers. Removing them eliminates the only place in the code that still refers to "Layout C" / "longform" naming.

**Files:**
- Modify: `formatting.py`

- [ ] **Step 1: Confirm no remaining callers**

Run from the project root:

```bash
grep -n "_render_from_the_front_page\|_looks_like_longform\|LAYOUT_C_PARAGRAPH_RE" formatting.py prompts.py newsletter.py pipeline.py triage.py
```

Expected: only the definitions themselves match (all inside `formatting.py`). No usage outside the file.

Also check the tests:

```bash
grep -n "_render_from_the_front_page\|_looks_like_longform\|LAYOUT_C_PARAGRAPH_RE" tests/
```

Expected: no matches. Tests address the rendering through `parse_and_render_sections`, not the helpers directly.

- [ ] **Step 2: Delete `_render_from_the_front_page`**

In `formatting.py`, delete the function `_render_from_the_front_page` and its docstring (currently around lines 576-654).

- [ ] **Step 3: Delete `_looks_like_longform`**

In `formatting.py`, delete the function `_looks_like_longform` and its docstring (currently around lines 337-341).

- [ ] **Step 4: Delete `LAYOUT_C_PARAGRAPH_RE`**

In `formatting.py`, delete the line:

```python
LAYOUT_C_PARAGRAPH_RE = re.compile(r"^\*\*(?P<header>[^*]+)\*\*\s*(?P<rest>.*)$")
```

…along with its `# Layout C paragraph opener:` comment block (currently around lines 332-334).

- [ ] **Step 5: Run the full test suite**

Run: `pytest tests/test_formatting.py -v`

Expected: same three pre-existing test failures from Task 1 step 5 still failing. No new failures. No `NameError` or `AttributeError`.

- [ ] **Step 6: Commit**

```bash
git add formatting.py
git commit -m "chore: remove unused Layout C helpers and regex

_render_from_the_front_page, _looks_like_longform, and
LAYOUT_C_PARAGRAPH_RE all became unused once the longform branch
was removed in the previous commit."
```

---

### Task 4: Update existing tests to match the new layout shape

**Why:** Three tests still assert behavior from the retired 3-paragraph longform shape. Update them to match the 2-paragraph cap and the unified renderer.

**Files:**
- Modify: `tests/test_formatting.py`

- [ ] **Step 1: Rename and update `test_from_the_front_page_longform_renders_micro_headers`**

In `tests/test_formatting.py`, find the test at line ~744. Replace the entire test with:

```python
def test_featured_story_renders_micro_headers():
    """Featured-story body paragraphs that open with **Cap.** render as
    <strong>Cap.</strong> inline."""
    text = """## Finance & Markets

**Fed signals rate cut by year end [#300]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back to one.

**Threading the needle.** Powell framed the move as data-dependent without naming a trigger.

Source: WSJ
"""
    links_by_id = {300: {"link": "https://wsj.example/300", "image": "https://img/300.jpg",
                         "title": "Fed signals rate cut"}}
    clusters_by_item_id = {300: {"primary_source": "WSJ", "also_in": []}}
    html, used_ids = parse_and_render_sections(text, links_by_id, clusters_by_item_id, tiered_items=[])
    # Two paragraph micro-headers render as bold inside the paragraph.
    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    # Hero image rendered.
    assert 'src="https://img/300.jpg"' in html
    # Source line still rendered.
    assert "WSJ" in html
    # ID tracked.
    assert 300 in used_ids
```

- [ ] **Step 2: Rename and update `test_end_to_end_renders_all_three_layouts`**

Find the test at line ~772. Change its name and its synthesized Claude response so the Finance/Global section uses 2 paragraphs instead of 3. Replace the test with:

```python
def test_end_to_end_renders_both_layouts(tmp_path):
    """Synthetic Claude response covering Featured Layout (Today in the
    World) and Layout A (every other section). Smoke test — verifies all
    section blocks render without error and produce non-empty HTML."""
    from formatting import build_email_html
    response = """SUBJECT: 🤖 Odyssey ships world models

## Today in the World

🤖 **Odyssey ships two world models [#10]:** The AI lab released [Agora-1](https://odyssey.example/agora) and Starchild-1.

🏠 **Toronto rents drop again [#11]:** Asking rent fell 4 percent for the third month.

⚖️ **Privacy bill passes committee [#12]:** Auto-delete defaults move closer to law.

📈 **Markets rally on rate cut [#13]:** S&P up 1.2 percent on Fed signal.

🚇 **TTC subway extension funded [#14]:** Federal commitment closes the gap.

## Tech & AI

**Two big AI announcements today [#20]**
**Setup.** Body paragraph one with [a link](https://example.com/x).

**Stakes.** Body paragraph two.
Source: TechCrunch

**Second featured story [#21]**
**Opening.** Body paragraph one.

**Implication.** Body paragraph two.
Source: Hacker News

## US & Global

**Fed signals rate cut by year end [#30]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back.

**Threading the needle.** Powell framed the move as data-dependent.
Source: WSJ
"""
    links_by_id = {
        10: {"link": "https://odyssey.example/news", "image": "https://img/10.jpg", "title": "Odyssey"},
        11: {"link": "https://rent.example/", "image": "", "title": "Rents"},
        12: {"link": "https://privacy.example/", "image": "", "title": "Privacy bill"},
        13: {"link": "https://markets.example/", "image": "", "title": "Markets"},
        14: {"link": "https://ttc.example/", "image": "", "title": "TTC"},
        20: {"link": "https://tc.example/20", "image": "https://img/20.jpg", "title": "AI announcements"},
        21: {"link": "https://hn.example/21", "image": "", "title": "Second story"},
        30: {"link": "https://wsj.example/30", "image": "https://img/30.jpg", "title": "Fed cut"},
    }
    html, subject = build_email_html(response, links_by_id, {}, tiered_items=[])
    assert "In the World" in html
    assert "Tech & AI" in html
    assert "US & Global" in html
    assert "Odyssey ships world models" in subject
    # Featured Layout markers
    assert '<img src="https://img/10.jpg"' in html  # Featured Layout hero
    assert "🤖" in html and "🚇" in html             # Featured Layout emojis
    # Layout A markers
    assert '<a href="https://example.com/x"' in html  # inline link in Tech & AI body
    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    assert "<strong>Setup.</strong>" in html
    assert "<strong>Stakes.</strong>" in html

    # Write the rendered HTML to a tmp file so Frank can open it visually.
    out = tmp_path / "sample-newsletter.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nSample newsletter rendered to: {out}")
```

- [ ] **Step 3: Update `test_end_to_end_pipeline_from_build_format_input_to_html`**

Find the test at line ~843. Two changes:

(a) In the comment block before the synthesized response (around line 856-857), change:

```python
    #   - Finance & Markets has 1 item (left after pickoff lifts the highest
    #     scorer), Layout C territory.
```

to:

```python
    #   - Finance & Markets has 1 item (left after pickoff lifts the highest
    #     scorer), which renders through the unified Layout A path.
```

(b) In the synthesized response (around lines 947-956), change the Finance & Markets block from three paragraphs to two:

```python
## Finance & Markets

**{fm_tier1[0]['title']} [#{fm_tier1[0]['id']}]**
**Setup.** First paragraph of body.

**Turn.** Second paragraph of body.

Source: Yahoo Finance
```

(c) Update the comment around line 923 from:

```python
    # Cap=1 means longform layout will trigger. Siblings should be empty (Finance & Markets is excluded).
```

to:

```python
    # Cap=1 means the section has a single Layout A story. Siblings should be empty (Finance & Markets is excluded).
```

(d) Update the comment block around line 977-982 from:

```python
    # Layout A emoji items render.
    assert "🌐" in html
    # Layout C micro-header markers render as bold inside paragraphs.
    assert "<strong>Setup.</strong>" in html
    assert "<strong>Turn.</strong>" in html
    assert "<strong>Conclusion.</strong>" in html
```

to:

```python
    # Featured Layout emoji items render.
    assert "🌐" in html
    # Layout A micro-header markers render as bold inside paragraphs.
    assert "<strong>Setup.</strong>" in html
    assert "<strong>Turn.</strong>" in html
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest tests/test_formatting.py -v`

Expected: all tests pass except the two prompt-content tests that haven't been updated yet:
- `test_format_prompt_describes_today_in_the_world_layout` — still passes (its assertions are loose enough to survive the prompt rewrite, but verify).
- `test_format_prompt_describes_from_the_front_page_fallback` — will fail once the prompt is rewritten in Task 5. Currently still passes.

If any other test fails, stop and investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add tests/test_formatting.py
git commit -m "test: update featured-layout tests to expect 2 capped paragraphs

Renames longform-specific tests and trims their synthesized Claude
output from 3 paragraphs to 2 to match the new unified Layout A."
```

---

### Task 5: Rewrite the formatter prompt — retire Layouts B and C, rename old Layout A to Featured Layout, define new Layout A

**Why:** The prompt is the upstream control. Until it's rewritten, Claude will keep emitting the old layout shapes (which the renderer would gracefully cap, but at the cost of paragraphs Claude wrote being thrown away). This task brings the prompt in line with the renderer.

**Files:**
- Modify: `prompts.py`
- Modify: `tests/test_formatting.py` (two prompt-content tests)

- [ ] **Step 1: Update the prompt-content tests first (failing test)**

In `tests/test_formatting.py`, replace `test_format_prompt_describes_today_in_the_world_layout` at line ~721:

```python
def test_format_prompt_describes_featured_layout():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Featured Layout is the renamed Today in the World list layout.
    assert "Featured Layout" in FORMAT_SYSTEM_PROMPT
    assert "Today in the World" in FORMAT_SYSTEM_PROMPT
    assert "emoji" in FORMAT_SYSTEM_PROMPT.lower()
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()
```

Replace `test_format_prompt_describes_from_the_front_page_fallback` at line ~729 with:

```python
def test_format_prompt_describes_layout_a_for_other_sections():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Layout A is the unified featured-story format for every non-Today section.
    assert "Layout A" in FORMAT_SYSTEM_PROMPT
    # Layout A requires exactly 2 body paragraphs.
    assert "2 body paragraphs" in FORMAT_SYSTEM_PROMPT or "two body paragraphs" in FORMAT_SYSTEM_PROMPT.lower()
    # Each paragraph opens with a bold micro-header.
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()
    # Layouts B and C are no longer mentioned.
    assert "Layout B" not in FORMAT_SYSTEM_PROMPT
    assert "Layout C" not in FORMAT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run the prompt tests, verify they fail**

Run: `pytest tests/test_formatting.py::test_format_prompt_describes_featured_layout tests/test_formatting.py::test_format_prompt_describes_layout_a_for_other_sections -v`

Expected: both FAIL.
- `test_format_prompt_describes_featured_layout` fails because the prompt does not yet contain the string "Featured Layout".
- `test_format_prompt_describes_layout_a_for_other_sections` fails because the prompt still says "Layout B" and "Layout C", and doesn't yet require exactly 2 paragraphs.

- [ ] **Step 3: Rewrite the layout descriptions in `FORMAT_SYSTEM_PROMPT`**

In `prompts.py`, find the block in `FORMAT_SYSTEM_PROMPT` that runs from line ~80 ("Each section uses one of three layouts...") through line ~115 ("...does not apply to Layout A items.").

Replace that entire block with:

```
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

After each Layout A item, if and only if the item is genuinely relevant to Frank's work as a product designer, his Leslieville condo, his investments, his freelance work, or his life in Toronto, add a single What this means for you line:
What this means for you: <one specific sentence written directly to Frank, starting with You or with the subject of the insight, never starting with his name>

If there is no clear personal relevance, skip the line entirely. The What this means for you line does not apply to Featured Layout items.
```

- [ ] **Step 4: Update the CRITICAL RULES reference to old layout names**

In `prompts.py`, find the CRITICAL RULES block (line ~119-126). Change rule 1 from:

```
1. Every input item carries an [#N] ID. You MUST preserve the exact [#N] inside the bold markers of every featured headline (Layouts A, B, C). Example: **Headline text [#42]:** for Layout A or **Headline text [#42]** for Layouts B and C.
```

to:

```
1. Every input item carries an [#N] ID. You MUST preserve the exact [#N] inside the bold markers of every featured headline. Example: **Headline text [#42]:** for Featured Layout items, or **Headline text [#42]** for Layout A items.
```

- [ ] **Step 5: Run the prompt tests, verify they pass**

Run: `pytest tests/test_formatting.py::test_format_prompt_describes_featured_layout tests/test_formatting.py::test_format_prompt_describes_layout_a_for_other_sections -v`

Expected: both PASS.

- [ ] **Step 6: Run the full test suite**

Run: `pytest tests/test_formatting.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add prompts.py tests/test_formatting.py
git commit -m "feat: unify Layouts B and C into Layout A with 2 bold-cap paragraphs

The formatter prompt now describes two layouts:
- Featured Layout: the Today in the World list (renamed from Layout A)
- Layout A: every other section, 2 paragraphs each with a bold
  micro-header opener.

Aligns the prompt contract with the renderer's 2-paragraph cap and
the unified rendering path. Previously, Claude was free to drift
into the 3-4 paragraph longform shape in any single-item section,
which is what produced the Toronto Housing rendering issue."
```

---

### Task 6: Visual smoke test

**Why:** Verify the rendered email looks right end-to-end before declaring done. Tests cover assertions but not the visual gestalt.

**Files:** None modified. Generates HTML to inspect.

- [ ] **Step 1: Run the end-to-end visual test**

Run: `pytest tests/test_formatting.py::test_end_to_end_renders_both_layouts -v -s`

Expected: PASS. The `-s` flag surfaces the test's `print` line announcing where the rendered HTML was written.

- [ ] **Step 2: Open the generated HTML**

The test writes the rendered email to a temp path. Open it in a browser to verify:
- The Today in the World / In the World section appears with hero image and emoji-led list (Featured Layout).
- Tech & AI shows two stories, each with a 24px headline + 2 paragraphs prefixed with bold micro-headers + source line + inter-story border.
- US & Global shows one story with 2 paragraphs prefixed with bold micro-headers + source line.

- [ ] **Step 3: Confirm no third-paragraph bleed**

In the generated HTML, search for any of the cap-style strings that should NOT appear (`<strong>What it means.</strong>`, `<strong>Conclusion.</strong>`, etc.). Expected: zero matches.

- [ ] **Step 4: Confirm done**

If the visual looks right, the plan is complete. No commit at this step — Task 5 already committed the final state.

---

## Self-Review Notes

- Spec coverage:
  - Retire Layouts B and C → Tasks 2, 3, 5.
  - Rename old Layout A to "Featured Layout" → Task 5.
  - New Layout A: 2 bold-micro-header paragraphs, applied to every non-featured section → Tasks 1, 5.
  - Per-section story count stays as it is today → no changes to `SECTION_FEATURED_CAPS` (default 2, Finance & Markets and US & Global at 1). Confirmed.
- No placeholders; every step shows the actual code to type or the exact assertion to add.
- Renderer-side cap at 2 (Task 1) and prompt-side ask for exactly 2 (Task 5) form defense in depth against future LLM drift.
- Tasks are ordered to keep the test suite as green as possible at every commit boundary. Tasks 1-3 leave three known failing tests that are explicitly slated for repair in Task 4.
