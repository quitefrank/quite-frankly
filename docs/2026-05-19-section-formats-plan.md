# Section Formats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Today in the World" featured section (top-5 across all categories), introduce image-prioritized featured picking, demote tier-1 overflow into per-section Other Headlines, add inline source links in non-Finance non-US/Global featured bodies, and add a "From the Front Page"-style longform fallback layout for any section that resolves to one featured story.

**Architecture:** Selection logic in `build_format_input` runs three passes — global top-5 pickoff for Today in the World, per-section featured fill with image priority, then per-section Other Headlines including tier-1 overflow. Formatter prompt gains two new layouts (Today in the World list, From the Front Page longform) and an inline-source-link rule. Renderer parses two new layout markers and converts markdown links in body text to HTML.

**Tech Stack:** Python 3.11, anthropic, pytest. No new dependencies.

**Reference:** Format names "Today in the World", "From the Front Page", and "In the Know" are layout references derived from Superhuman's daily newsletter. Section names in our newsletter remain unchanged except for Worth Knowing → Today in the World.

---

## Behavior Summary

| Section | Cap | Layout | Inline source links |
|---|---|---|---|
| Today in the World | 5 (global) | hero image + 5 emoji-led items | yes |
| Canada & Toronto | 2 | standard 2-featured + Other Headlines | yes |
| Toronto Housing | 2 | standard 2-featured + Other Headlines | yes |
| Tech & AI | 2 | standard 2-featured + Other Headlines | yes |
| Design & Product | 2 | standard 2-featured + Other Headlines | yes |
| Finance & Markets | 1 | From the Front Page longform + Other Headlines | no |
| US & Global | 1 | From the Front Page longform + Other Headlines | no |
| Everything Else | 7 | unchanged | n/a |

**Today in the World layout.** Hero image from the highest-ranked top-5 item that has an image. The hero item is duplicated as the first list entry. Each of the 5 items renders as `<emoji> <bold micro-header>:` followed by a 1-paragraph body with inline source links. The micro-header is a punchy phrase drawn from the story, not a generic summary tag.

**Standard 2-featured layout** (current rendering, two new behavior tweaks). Each featured story shows an image, a 2-paragraph body, source line, and the optional "what this means for you" callout. Behavior tweaks:
1. Tier-1 candidates sort by `(has_image desc, score desc)` instead of pure score order.
2. Tier-1 items beyond the section cap demote into Other Headlines rather than dropping straight to Everything Else.

**From the Front Page longform.** A single featured story rendered with hero image and 3–4 short paragraphs, each opening with a bolded conceptual micro-header that names a turn in the story (setup, scene, cause, exception). Source line and callout follow. Triggered any time a section's featured cap resolves to one article. Finance & Markets and US & Global always trigger this (cap = 1).

**Inline source links.** When a story's cluster has multiple sources, the Claude formatter is instructed to embed inline markdown hyperlinks in the body, anchored on the most relevant noun or concept, pointing to each sibling source's URL. Renderer converts markdown links to HTML. Rule does not apply to Finance & Markets or US & Global sections.

**Everything Else.** Unchanged.

---

## Open Assumptions

These are decisions I made when the spec didn't pin them down. Confirm before execution begins, or note overrides.

1. **Section concentration in Today in the World.** Pure top-5 by composite score. If 5 of the 5 happen to come from the same home section, accept the concentration.
2. **Image-priority sort.** `(has_image desc, score desc)`. A lower-scored item with an image beats a higher-scored item without. Override would be a "score-within-tolerance" rule, which adds complexity.
3. **No image among Today in the World top-5.** Fall through to render the section with no hero image (still 5 emoji-led items). The "must have image" promotion rule applies only when there is at least one image-bearing tier-1 item in the global candidate pool.
4. **Today in the World hero duplication.** The hero item appears both as the hero image+caption and as the first of the 5 list items. (Alternative: hero stands alone above the list with no duplicated item.)
5. **`promotion_to_worth_knowing` field rename.** Rename to `promotion_to_today_in_the_world` for consistency. The field is currently unused downstream, so the rename is safe.

---

## File Structure

Files modified, no new files:

- `config.py` — section name rename
- `prompts.py` — TRIAGE enum rename, FORMAT_SYSTEM_PROMPT rewrite, LEGACY_FORMAT_SYSTEM_PROMPT touch-up
- `triage.py` — TRIAGE_TOOL enum rename, field rename
- `formatting.py` — `build_format_input` gains global pickoff, image priority, cluster URL plumbing. `render_other_headlines_for_section` includes tier-1 overflow. `parse_and_render_sections` parses two new layouts. Body rendering converts markdown links to HTML.
- `tests/test_formatting.py` — existing tests updated for the rename and new behaviors; new tests for image priority, global pickoff, overflow demotion, Today in the World parsing, From the Front Page parsing, inline link rendering.
- `tests/test_triage.py` — section enum rename only.

---

## Task Sequence

Phase A: Rename (Task 1)
Phase B: Selection logic (Tasks 2–4)
Phase C: Inline link plumbing (Tasks 5–6)
Phase D: Layouts (Tasks 7–9)
Phase E: Integration sweep (Task 10)

Each task ends with a commit. After Phase A the suite still passes with the rename applied. After Phase B the JSON payload Claude receives carries the new selection. After Phase C the JSON has per-item sibling URLs. After Phase D renderers handle both new layouts and markdown links. Phase E verifies the end-to-end output.

All commands assume CWD `/Users/quitefrank/Claude/Personal/projects/quite-frankly/.worktrees/section-formats`.

---

### Task 1: Rename Worth Knowing → Today in the World

Mechanical rename across all files that reference the section. The triage tool's `promotion_to_worth_knowing` field also gets renamed.

**Files:**
- Modify: `config.py:87-141, 153-162, 213-218`
- Modify: `formatting.py:20-28`
- Modify: `prompts.py:37, 74, 93, 130`
- Modify: `triage.py:37-53`
- Modify: `tests/test_formatting.py:302-315`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_today_in_the_world_replaces_worth_knowing_in_section_order():
    from formatting import SECTION_ORDER
    assert "Today in the World" in SECTION_ORDER
    assert "Worth Knowing" not in SECTION_ORDER


def test_today_in_the_world_replaces_worth_knowing_in_section_map():
    from config import SECTION_MAP
    assert "Today in the World" in SECTION_MAP.values()
    assert "Worth Knowing" not in SECTION_MAP.values()


def test_today_in_the_world_has_an_emoji():
    from config import SECTION_EMOJIS
    assert "Today in the World" in SECTION_EMOJIS
    assert "Worth Knowing" not in SECTION_EMOJIS
```

Replace the existing `test_worth_knowing_section_renders` (line 302–315) with:

```python
def test_today_in_the_world_section_renders():
    text = """## Today in the World

**Big global story [#5]**
Body paragraph one.

Body paragraph two.
Source: NYT
"""
    links_by_id = {5: {"link": "https://example.com/5", "image": "", "title": "Big global story"}}
    clusters_by_item_id = {5: {"primary_source": "NYT", "also_in": ["BBC"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    assert "Today in the World" in html
    assert "NYT, BBC" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_formatting.py::test_today_in_the_world_replaces_worth_knowing_in_section_order -v`
Expected: FAIL with `assert "Today in the World" in SECTION_ORDER`.

- [ ] **Step 3: Apply the rename across source files**

In `config.py`:
- Replace the four `"Worth Knowing"` values in `SECTION_MAP` (lines 137–140) with `"Today in the World"`.
- Replace `"Worth Knowing":    "🎧",` in `SECTION_EMOJIS` (line 160) with `"Today in the World": "🌐",`.
- Update the `# Worth Knowing (podcasts)` comments at lines 63, 136, and 213 to `# Today in the World (podcasts)`.

In `formatting.py`:
- Replace `"Worth Knowing",` on line 27 of `SECTION_ORDER` with `"Today in the World",`.

In `prompts.py`:
- In `TRIAGE_SYSTEM_PROMPT` (line 37), replace `"Worth Knowing"` in the section enum with `"Today in the World"`.
- In `FORMAT_SYSTEM_PROMPT` (line 74), replace `- Worth Knowing` in the section list with `- Today in the World`.
- In `FORMAT_SYSTEM_PROMPT` (line 93), replace `For Worth Knowing, render every item as a full Tier 1 story...` with `For Today in the World, render every item as a full Tier 1 story...` (this whole instruction block gets rewritten in Task 7; for now just rename).
- In `LEGACY_FORMAT_SYSTEM_PROMPT` (line 130), no Worth Knowing reference is currently present in the listed sections; verify and skip.

In `triage.py`:
- Replace `"Worth Knowing",` in the section enum (line 44) with `"Today in the World",`.
- Rename `promotion_to_worth_knowing` to `promotion_to_today_in_the_world` in the schema (line 51) and the required array (line 53).
- Rename the corresponding key in `_shape_tool_output` (line 138).

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `python3 -m pytest tests/ -q`
Expected: PASS (72 tests originally; with the 3 new + 1 replaced, the count should be 74).

- [ ] **Step 5: Commit**

```bash
git add config.py formatting.py prompts.py triage.py tests/test_formatting.py
git commit -m "refactor: rename Worth Knowing section to Today in the World"
```

---

### Task 2: Add image priority to per-section featured picking

Score-sorted tier-1 candidates currently use a single score key. Sort key becomes `(has_image desc, score desc)`. Items with images surface above items without; ties break by composite score. Each scored item gets an `image` boolean derived from `links_by_id[id]["image"]`.

**Files:**
- Modify: `formatting.py:50-92`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_build_format_input_prioritises_images_within_tier_1():
    # Section has 3 tier_1 candidates, cap=2.
    # Top scorer has no image (score 7); next has image (score 5); third has image (score 4).
    # Expected: items with images surface first, sorted by score within the image group.
    # Picks: id=2 (image, 5), id=3 (image, 4). The score-7 no-image item drops out.
    tiered_items = [
        _item(1, "Toronto Housing", tier=1, ccov=3, prel=3, fit="good"),  # score 7
        _item(2, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(3, "Toronto Housing", tier=1, ccov=2, prel=1, fit="good"),  # score 4
    ]
    links_by_id = {
        1: {"title": "t1", "source": "BetterDwelling", "snippet": "x", "image": ""},
        2: {"title": "t2", "source": "BetterDwelling", "snippet": "x", "image": "https://img/2.jpg"},
        3: {"title": "t3", "source": "BetterDwelling", "snippet": "x", "image": "https://img/3.jpg"},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 2
    # Items with images come first, sorted by score within that group.
    assert [x["id"] for x in housing["tier_1"]] == [2, 3]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_formatting.py::test_build_format_input_prioritises_images_within_tier_1 -v`
Expected: FAIL — current code sorts by score only, so the score-7 no-image item would be picked.

- [ ] **Step 3: Modify `build_format_input` to use the new sort key**

In `formatting.py`, edit lines 62–74 inside `build_format_input`:

Replace the bucket-building block:

```python
        link = links_by_id.get(item["id"], {})
        by_section[section][bucket].append({
            "id": item["id"],
            "title": link.get("title", ""),
            "snippet": link.get("snippet", ""),
            "source": link.get("source", ""),
            "cluster_id": item.get("cluster_id"),
            "_score": _item_score(item.get("scores", {})),
        })

    for section_buckets in by_section.values():
        for bucket in section_buckets.values():
            bucket.sort(key=lambda x: x["_score"], reverse=True)
```

With:

```python
        link = links_by_id.get(item["id"], {})
        by_section[section][bucket].append({
            "id": item["id"],
            "title": link.get("title", ""),
            "snippet": link.get("snippet", ""),
            "source": link.get("source", ""),
            "cluster_id": item.get("cluster_id"),
            "_score": _item_score(item.get("scores", {})),
            "_has_image": bool(link.get("image")),
        })

    # Tier 1 buckets sort by (has_image desc, score desc) so image-bearing
    # stories surface before image-less ones within the same tier. Tier 2 and
    # Tier 3 buckets keep pure score ordering — image priority only matters
    # for the featured slot.
    for section_buckets in by_section.values():
        for bucket_name, bucket in section_buckets.items():
            if bucket_name == "tier_1":
                bucket.sort(key=lambda x: (x["_has_image"], x["_score"]), reverse=True)
            else:
                bucket.sort(key=lambda x: x["_score"], reverse=True)
```

Then strip `_has_image` alongside `_score` in the cleanup block at lines 104–107:

```python
    for section_buckets in sorted_sections.values():
        for bucket in section_buckets.values():
            for item in bucket:
                item.pop("_score", None)
                item.pop("_has_image", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS. The new test passes, and `test_build_format_input_caps_tier_1_at_two_per_section` still passes because all its items have the same (missing) image field and score ordering breaks the tie.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: prioritise image-bearing items for featured slots"
```

---

### Task 3: Demote tier-1 overflow into Other Headlines

`render_other_headlines_for_section` today filters to `tier == 2`. Change it to include tier-1 items in the section that are not in `used_ids` (i.e., were truncated out of the featured bucket). Sort order within Other Headlines: tier ascending then composite score descending, so tier-1 overflow surfaces above tier-2 items.

**Files:**
- Modify: `formatting.py:239-288`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_other_headlines_includes_tier_1_overflow_above_tier_2():
    # Section has 3 tier_1 items; cap=2 means 1 demotes to Other Headlines.
    # The demoted tier_1 should appear in Other Headlines AHEAD of a lower-scored tier_2.
    tiered_items = [
        {"id": 1, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},  # score 7
        {"id": 2, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},  # score 6
        {"id": 3, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},  # score 5 (overflow)
        {"id": 4, "section": "Toronto Housing", "tier": 2,
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},  # score 4
    ]
    links_by_id = {
        n: {"link": f"https://example.com/{n}", "title": f"Story {n}",
            "snippet": "First sentence.", "source": "Storeys", "image": ""}
        for n in range(1, 5)
    }
    used_ids = {1, 2}  # featured slots took the top two tier_1
    html = render_other_headlines_for_section("Toronto Housing", tiered_items, links_by_id, used_ids)
    # Tier-1 overflow id=3 must appear; tier-2 id=4 must appear; id=3 must come first.
    pos_3 = html.find("Story 3")
    pos_4 = html.find("Story 4")
    assert pos_3 >= 0 and pos_4 >= 0, "Both overflow and tier-2 must render"
    assert pos_3 < pos_4, "Tier-1 overflow should surface above tier-2"
    assert used_ids == {1, 2, 3, 4}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_formatting.py::test_other_headlines_includes_tier_1_overflow_above_tier_2 -v`
Expected: FAIL — tier-1 overflow does not appear today.

- [ ] **Step 3: Modify `render_other_headlines_for_section` to include tier-1 overflow**

In `formatting.py`, replace lines 246–260 (the candidate-collection and sort block):

```python
    candidates = []
    for it in tiered_items or []:
        if it.get("section") != section:
            continue
        if it.get("tier") != 2:
            continue
        if it["id"] in used_ids:
            continue
        if it["id"] not in links_by_id:
            continue
        candidates.append((-_item_score(it.get("scores", {})), it["id"]))

    candidates.sort()
    picked = [lid for _neg_score, lid in candidates[:MAX_OTHER_HEADLINES_PER_SECTION]]
```

With:

```python
    candidates = []
    for it in tiered_items or []:
        if it.get("section") != section:
            continue
        tier = it.get("tier")
        if tier not in (1, 2):
            continue
        if it["id"] in used_ids:
            continue
        if it["id"] not in links_by_id:
            continue
        # Sort tier 1 before tier 2, then by composite score desc.
        candidates.append((tier, -_item_score(it.get("scores", {})), it["id"]))

    candidates.sort()
    picked = [lid for _tier, _neg_score, lid in candidates[:MAX_OTHER_HEADLINES_PER_SECTION]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS. Re-check the existing `test_render_other_headlines_for_section_caps_at_three_and_skips_used_ids` and `test_render_other_headlines_for_section_skips_items_already_in_used_ids` still pass — they only use tier-2 items in their inputs, so the new tier-1 inclusion logic is a no-op for them.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: demote tier-1 featured-cap overflow into Other Headlines"
```

---

### Task 4: Global top-5 pickoff into Today in the World

Before per-section caps run, lift the top 5 tier-1 items across all non-Today-in-the-World sections by composite score, move them into the Today in the World tier-1 bucket, and remove them from their home sections. The hero (position 0) is the highest-scored among the 5 that has an image; if none of the 5 have an image, look at lower-scored tier-1 candidates and swap one in to keep the cap at 5 with a usable hero. If no image-bearing tier-1 candidate exists at all, accept the top-5-by-score with no hero swap (the renderer drops the hero image gracefully).

**Files:**
- Modify: `formatting.py:33-92`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_today_in_the_world_pulls_global_top_five():
    # Five sections, three tier_1 items each. Today in the World should
    # get the top 5 globally by composite score and they should NOT appear
    # in their home sections' tier_1.
    tiered_items = [
        # Tech & AI: scores 9, 7, 6
        _item(101, "Tech & AI", tier=1, ccov=4, prel=3, fit="good"),  # 8
        _item(102, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),  # 6
        _item(103, "Tech & AI", tier=1, ccov=2, prel=2, fit="good"),  # 5
        # Toronto Housing: scores 9, 5, 4
        _item(201, "Toronto Housing", tier=1, ccov=4, prel=3, fit="good"),  # 8
        _item(202, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # 5
        _item(203, "Toronto Housing", tier=1, ccov=2, prel=1, fit="good"),  # 4
        # Finance & Markets: score 7
        _item(301, "Finance & Markets", tier=1, ccov=3, prel=3, fit="good"),  # 7
        # US & Global: score 8
        _item(401, "US & Global", tier=1, ccov=4, prel=3, fit="good"),  # 8
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "x", "image": f"https://img/{i['id']}.jpg"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    titw = payload["sections"]["Today in the World"]
    # Top 5 by composite score: 101 (8), 201 (8), 401 (8), 301 (7), 102 (6)
    assert {x["id"] for x in titw["tier_1"]} == {101, 201, 401, 301, 102}
    # Picked items must not reappear in their home sections.
    assert 101 not in {x["id"] for x in payload["sections"]["Tech & AI"]["tier_1"]}
    assert 201 not in {x["id"] for x in payload["sections"]["Toronto Housing"]["tier_1"]}
    assert 301 not in {x["id"] for x in payload["sections"]["Finance & Markets"]["tier_1"]}
    assert 401 not in {x["id"] for x in payload["sections"]["US & Global"]["tier_1"]}


def test_today_in_the_world_hero_is_highest_scored_with_image():
    # Top scorer has no image; second-top has an image. Hero must be the second.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=4, prel=3, fit="good"),  # 8, no image
        _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),  # 6, with image
        _item(3, "Tech & AI", tier=1, ccov=2, prel=2, fit="good"),  # 5, with image
    ]
    links_by_id = {
        1: {"title": "t1", "source": "X", "snippet": "x", "image": ""},
        2: {"title": "t2", "source": "X", "snippet": "x", "image": "https://img/2.jpg"},
        3: {"title": "t3", "source": "X", "snippet": "x", "image": "https://img/3.jpg"},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    titw = payload["sections"]["Today in the World"]
    # All three picked (top 5 but only 3 candidates).
    assert {x["id"] for x in titw["tier_1"]} == {1, 2, 3}
    # Position 0 (hero) must be id=2 (highest-scored with image).
    assert titw["tier_1"][0]["id"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_formatting.py::test_today_in_the_world_pulls_global_top_five tests/test_formatting.py::test_today_in_the_world_hero_is_highest_scored_with_image -v`
Expected: FAIL — no global pickoff exists yet.

- [ ] **Step 3: Add the global pickoff in `build_format_input`**

In `formatting.py`, add a constant near the top of the file (above `_item_score`):

```python
TODAY_IN_THE_WORLD = "Today in the World"
TODAY_IN_THE_WORLD_CAP = 5
```

Update `SECTION_FEATURED_CAPS` to reflect that Today in the World does not participate in per-section featured filling (it gets filled by global pickoff):

```python
SECTION_FEATURED_CAPS = {
    "Finance & Markets": 1,
    "US & Global": 1,
    # Today in the World is populated by the global pickoff; per-section
    # filling is skipped for it (cap=0 here means "don't fill from this
    # section's own items").
    TODAY_IN_THE_WORLD: 0,
}
```

After the bucket-building loop in `build_format_input` and BEFORE the per-section cap loop (insert between lines 75 and 81), add:

```python
    # Global pickoff: pull the top TODAY_IN_THE_WORLD_CAP tier-1 items
    # across every section EXCEPT Today in the World itself, move them into
    # the Today in the World tier_1 bucket, and delete them from their home
    # sections. Hero (position 0) is the highest-scored picked item that has
    # an image; if none of the picks have images, look for an image-bearing
    # tier-1 candidate beyond the picks and swap one in.
    global_pool = []
    for sec, sec_buckets in by_section.items():
        if sec == TODAY_IN_THE_WORLD:
            continue
        for item in sec_buckets["tier_1"]:
            global_pool.append((sec, item))
    global_pool.sort(key=lambda pair: (pair[1]["_has_image"], pair[1]["_score"]), reverse=True)
    # The sort above mixes has_image into the key, which is fine for hero
    # selection but we want the top 5 by SCORE regardless of image. Re-sort
    # by pure score first to pick the 5, then promote a hero among them.
    global_pool.sort(key=lambda pair: pair[1]["_score"], reverse=True)
    picked = global_pool[:TODAY_IN_THE_WORLD_CAP]

    # Hero promotion: if any picked item has an image, move the
    # highest-scored image-bearer to position 0. If none has an image,
    # try to swap in a lower-scored image-bearer from the remaining pool.
    if picked:
        hero_idx_in_picked = next(
            (i for i, (_, item) in enumerate(picked) if item["_has_image"]),
            None,
        )
        if hero_idx_in_picked is None:
            swap_idx = next(
                (i for i, (_, item) in enumerate(global_pool[TODAY_IN_THE_WORLD_CAP:], start=TODAY_IN_THE_WORLD_CAP)
                 if item["_has_image"]),
                None,
            )
            if swap_idx is not None:
                # Replace the lowest-scored pick with the image-bearer.
                picked[-1] = global_pool[swap_idx]
                hero_idx_in_picked = len(picked) - 1
        if hero_idx_in_picked is not None and hero_idx_in_picked != 0:
            picked[0], picked[hero_idx_in_picked] = picked[hero_idx_in_picked], picked[0]

    # Move picks into Today in the World, delete from home sections.
    picked_ids = {item["id"] for _, item in picked}
    for sec, _ in picked:
        by_section[sec]["tier_1"] = [
            it for it in by_section[sec]["tier_1"] if it["id"] not in picked_ids
        ]
    by_section[TODAY_IN_THE_WORLD]["tier_1"] = [item for _, item in picked]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS. Existing tests may need updates if they assumed the old behavior — specifically `test_section_order_is_by_max_score_descending` should still pass because Today in the World will now have the top global scores and naturally sort first.

If existing tests fail because they expected specific items to remain in non-TitW sections, update those tests to account for the global pickoff. The pickoff is now a documented behavior.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: global top-5 pickoff feeds Today in the World"
```

---

### Task 5: Build per-cluster sibling URL list

For each multi-source cluster, build a list of `{source, url}` for every cluster member. Embed the sibling list in each tier-1 item's JSON payload so the Claude formatter can reference URLs when emitting inline source links. Skip the sibling list for Finance & Markets and US & Global items (no inline links rule).

**Files:**
- Modify: `formatting.py:50-112`
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_build_format_input_embeds_sibling_urls_for_multi_source_clusters():
    tiered_items = [
        {"id": 50, "section": "Tech & AI", "tier": 1, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 51, "section": "Tech & AI", "tier": 2, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 1, "section_fit": "good"}},
        {"id": 52, "section": "Tech & AI", "tier": 3, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 0, "section_fit": "good"}},
    ]
    links_by_id = {
        50: {"title": "Primary headline", "source": "TechCrunch",
             "snippet": "x", "link": "https://tc.example/50", "image": ""},
        51: {"title": "Same story diff angle", "source": "The Verge",
             "snippet": "x", "link": "https://verge.example/51", "image": ""},
        52: {"title": "Wire copy", "source": "Reuters",
             "snippet": "x", "link": "https://reut.example/52", "image": ""},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    tech = payload["sections"]["Tech & AI"]["tier_1"]
    assert len(tech) == 1
    siblings = tech[0]["siblings"]
    # Siblings exclude the primary item itself.
    sources_with_urls = {(s["source"], s["url"]) for s in siblings}
    assert ("The Verge", "https://verge.example/51") in sources_with_urls
    assert ("Reuters", "https://reut.example/52") in sources_with_urls
    assert ("TechCrunch", "https://tc.example/50") not in sources_with_urls


def test_build_format_input_omits_siblings_for_finance_and_us_global():
    tiered_items = [
        {"id": 60, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 61, "section": "Finance & Markets", "tier": 2, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"}},
    ]
    links_by_id = {
        60: {"title": "FOMC", "source": "WSJ", "snippet": "x",
             "link": "https://wsj.example/60", "image": ""},
        61: {"title": "FOMC angle", "source": "Yahoo Finance", "snippet": "x",
             "link": "https://yf.example/61", "image": ""},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    fm = payload["sections"]["Finance & Markets"]["tier_1"][0]
    assert fm.get("siblings", []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_formatting.py::test_build_format_input_embeds_sibling_urls_for_multi_source_clusters tests/test_formatting.py::test_build_format_input_omits_siblings_for_finance_and_us_global -v`
Expected: FAIL — `siblings` key is not produced today.

- [ ] **Step 3: Add sibling URL computation in `build_format_input`**

In `formatting.py`, add a constant near the top of the file (alongside `TODAY_IN_THE_WORLD`):

```python
SECTIONS_WITHOUT_INLINE_LINKS = {"Finance & Markets", "US & Global"}
```

After bucketing but before sorting (just after the bucket-building loop ends around line 71), insert sibling computation. Build a `cluster_members` map first, then inject `siblings` into each item:

```python
    # Build {cluster_id: [{"source": ..., "url": ...}, ...]} from all items
    # (including those that won't render featured) so we don't lose
    # cross-source visibility when the cluster spans tiers.
    cluster_members: dict[str, list[dict]] = {}
    for item in tiered_items:
        cid = item.get("cluster_id")
        if not cid:
            continue
        link = links_by_id.get(item["id"], {})
        url = link.get("link", "")
        source = link.get("source", "")
        if not url or not source:
            continue
        cluster_members.setdefault(cid, []).append({
            "id": item["id"],
            "source": source,
            "url": url,
        })

    # Attach siblings to each featured-eligible item (tier_1 items in
    # sections that allow inline links). The sibling list excludes the item
    # itself and is empty for Finance & Markets / US & Global.
    for section, buckets in by_section.items():
        if section in SECTIONS_WITHOUT_INLINE_LINKS:
            for item in buckets["tier_1"] + buckets["tier_2"] + buckets["tier_3"]:
                item["siblings"] = []
            continue
        for item in buckets["tier_1"] + buckets["tier_2"] + buckets["tier_3"]:
            cid = item.get("cluster_id")
            members = cluster_members.get(cid, [])
            item["siblings"] = [
                {"source": m["source"], "url": m["url"]}
                for m in members
                if m["id"] != item["id"]
            ]
```

Place this block AFTER the existing bucket-building (which currently ends with the `bucket.sort(...)` loops) and BEFORE the global pickoff added in Task 4. The siblings field then flows through pickoff naturally.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: thread per-cluster sibling URLs into formatter input"
```

---

### Task 6: Convert markdown links to HTML in body rendering

Body paragraphs from the Claude formatter may contain markdown link syntax `[text](url)`. The renderer currently passes body text through as plain HTML, so the brackets would render as literal text. Add a converter that turns markdown links into `<a href="url">text</a>` with the same style as the source line.

**Files:**
- Modify: `formatting.py:389-396` (the body paragraph render block inside `parse_and_render_sections`)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_body_paragraphs_render_markdown_links_as_html():
    text = """## Tech & AI

**Multi-source story [#200]**
Claude says [The Verge](https://verge.example/x) covered this first.

Source: TechCrunch
"""
    links_by_id = {200: {"link": "https://tc.example/200", "image": "",
                         "title": "Multi-source story"}}
    clusters_by_item_id = {200: {"primary_source": "TechCrunch",
                                 "also_in": ["The Verge"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    # Markdown link survives as a real anchor tag.
    assert '<a href="https://verge.example/x"' in html
    assert ">The Verge</a>" in html
    # Raw markdown brackets must not leak through.
    assert "[The Verge]" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_formatting.py::test_body_paragraphs_render_markdown_links_as_html -v`
Expected: FAIL — raw markdown text appears in HTML output.

- [ ] **Step 3: Add the converter and apply it during body rendering**

In `formatting.py`, add a module-level helper near `_first_sentence`:

```python
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _render_body_markdown_links(text: str) -> str:
    """Convert [label](url) markdown links to <a href> with the inline link style."""
    return _MARKDOWN_LINK_RE.sub(
        lambda m: (
            f'<a href="{m.group(2)}" '
            f'style="color:#1c7ff2;text-decoration:underline;">{m.group(1)}</a>'
        ),
        text,
    )
```

In `parse_and_render_sections`, replace the body paragraph render loop (lines 389–395):

```python
            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs:
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                        f'font-family:Helvetica,Arial,sans-serif">{p}</p>'
                    )
```

With:

```python
            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs:
                    rendered = _render_body_markdown_links(p)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                        f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: render markdown links in story body as HTML anchors"
```

---

### Task 7: Rewrite FORMAT_SYSTEM_PROMPT for the new layouts

Update the formatter prompt to describe:
- Today in the World layout: emoji + bolded micro-header + colon + 1-paragraph body for each of the 5 items, with inline source links.
- Standard 2-featured layout: unchanged structure.
- From the Front Page longform: triggered when a section has exactly 1 tier-1 item; render 3–4 short paragraphs, each opening with a bolded conceptual micro-header.
- Inline source link rule: when an item has a `siblings` array of one or more entries, embed inline markdown links to those URLs in the body. No inline links for Finance & Markets or US & Global items (those will have empty siblings arrays).

**Files:**
- Modify: `prompts.py:54-101`
- Test: `tests/test_formatting.py` (structural prompt-content test only)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_format_prompt_describes_today_in_the_world_layout():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Layout description must mention the emoji-led item structure for TitW.
    assert "Today in the World" in FORMAT_SYSTEM_PROMPT
    assert "emoji" in FORMAT_SYSTEM_PROMPT.lower()
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()


def test_format_prompt_describes_from_the_front_page_fallback():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Single-featured section fallback must be documented.
    assert "single featured story" in FORMAT_SYSTEM_PROMPT.lower()
    assert "3 to 4" in FORMAT_SYSTEM_PROMPT or "three to four" in FORMAT_SYSTEM_PROMPT.lower()


def test_format_prompt_describes_inline_source_links_rule():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Inline link rule and the Finance/US & Global exclusion must both be stated.
    assert "siblings" in FORMAT_SYSTEM_PROMPT.lower()
    assert "Finance & Markets" in FORMAT_SYSTEM_PROMPT
    assert "US & Global" in FORMAT_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_formatting.py::test_format_prompt_describes_today_in_the_world_layout tests/test_formatting.py::test_format_prompt_describes_from_the_front_page_fallback tests/test_formatting.py::test_format_prompt_describes_inline_source_links_rule -v`
Expected: FAIL — current prompt doesn't mention these.

- [ ] **Step 3: Rewrite `FORMAT_SYSTEM_PROMPT`**

In `prompts.py`, replace the existing `FORMAT_SYSTEM_PROMPT` (lines 54–101) with:

```python
FORMAT_SYSTEM_PROMPT = """You are the writer for a daily briefing. The selection work has already been done. You will receive a JSON input listing items grouped by section and tier, plus a clusters lookup for stories covered by multiple sources.

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

Each section uses one of three layouts depending on its name and how many tier_1 items it has.

LAYOUT A — Today in the World list. Used only for the Today in the World section. Render exactly the 5 items in the input's tier_1 array (in that order). For each item, write:

<emoji> **<short story-phrase that fits this story> [#N]:** One short paragraph (2 to 3 sentences) of body. Use inline markdown links to the item's siblings array when the story has multiple sources — anchor the link on the most relevant noun or concept in the body, formatted as [anchor text](url).

The emoji is per-story, chosen from the story's actual topic (🤖 AI lab, ⚖️ regulation, 📱 product launch, 🏠 housing, 📈 markets, 🌍 climate). The bold micro-header is a phrase drawn from the substance of the story — not a generic summary tag.

LAYOUT B — Standard featured. Used for Canada & Toronto, Toronto Housing, Tech & AI, and Design & Product when the tier_1 array has 2 items. For each of the 2 tier_1 items, write:

**Original headline text [#N]**
Body paragraph one, 3 to 4 sentences.

Body paragraph two, 3 to 4 sentences.
Source: <cluster primary_source>

If the item has a non-empty siblings array, embed inline markdown links in the body to one or two of the sibling URLs, anchored on a noun or concept that fits.

LAYOUT C — From the Front Page longform. Used when a section's tier_1 array has exactly 1 item. This always applies to Finance & Markets and US & Global, and applies to other sections only when their tier_1 happens to resolve to a single featured story. Render the single featured story as:

**Original headline text [#N]**
**<short conceptual micro-header for paragraph one.>** Body paragraph one, 2 to 3 sentences.

**<short conceptual micro-header for paragraph two.>** Body paragraph two, 2 to 3 sentences.

**<short conceptual micro-header for paragraph three.>** Body paragraph three, 2 to 3 sentences.

**<short conceptual micro-header for paragraph four if warranted.>** Body paragraph four, 2 to 3 sentences.
Source: <cluster primary_source>

Three paragraphs is the default; a fourth is acceptable when the story genuinely has a fourth turn. Each bolded micro-header names a turn in the narrative (setup, scene, cause, exception) — not a summary of the paragraph that follows. Examples: "Decreasing optimism.", "Threading the needle.", "Why the shift?". For Finance & Markets and US & Global items, do NOT use inline markdown links in the body, regardless of the siblings array.

After each featured story under Layouts B and C, if and only if the item is genuinely relevant to Frank's work as a product designer, his Leslieville condo, his investments, his freelance work, or his life in Toronto, add a single What this means for you line:
What this means for you: <one specific sentence written directly to Frank, starting with You or with the subject of the insight, never starting with his name>

If there is no clear personal relevance, skip the line entirely. The What this means for you line does not apply to Layout A items.

Other Headlines and Everything Else are rendered programmatically after you finish. Do not include `### Other Headlines` or `## Everything Else` in your output — anything you write under those headers will be discarded. Your only job is to write the featured tier_1 stories for each section.

CRITICAL RULES YOU MUST FOLLOW:
1. Every input item carries an [#N] ID. You MUST preserve the exact [#N] inside the bold markers of every featured headline (Layouts A, B, C). Example: **Headline text [#42]:** for Layout A or **Headline text [#42]** for Layouts B and C.
2. Never move an item to a different section than the input assigned. Section is final. Render sections in the order they appear in the input.
3. Never invent items. Use only the IDs provided in the input.
4. For each item, use the cluster's primary_source for the Source line. If the input does not provide a cluster, fall back to the item's own source.
5. Body paragraphs must be separated by exactly one blank line.
6. Inline markdown links must point to URLs that appear in the item's siblings array. Never invent URLs.
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add prompts.py tests/test_formatting.py
git commit -m "feat: format prompt covers Today in the World and longform layouts"
```

---

### Task 8: Render Today in the World layout

Parse and render the Layout A markers (`<emoji> **<micro-header> [#N]:** body`). Hero image: the first item (position 0 in the section's input order) shows its image full-width above the list. The same item also renders as the first list entry. Items 2–5 render without per-item images, just emoji + bold + body. Source line and "what this means for you" do not apply to TitW.

**Files:**
- Modify: `formatting.py:291-439` (`parse_and_render_sections`)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_today_in_the_world_layout_renders_hero_and_emoji_items():
    text = """## Today in the World

🤖 **Odyssey ships two world models [#10]:** The AI lab released [Agora-1](https://odyssey.example/agora) for multiplayer simulation and Starchild-1 for audio.

🏠 **Toronto rents drop again [#11]:** Average asking rent slid 4 percent for the third consecutive month.

⚖️ **Privacy bill passes committee [#12]:** Auto-delete defaults move closer to law.

📈 **Markets rally on rate cut [#13]:** S&P closed up 1.2 percent after the Fed signaled easing.

🚇 **TTC subway extension funded [#14]:** Federal commitment closes the funding gap.
"""
    links_by_id = {
        10: {"link": "https://odyssey.example/news", "image": "https://img/10.jpg",
             "title": "Odyssey ships two world models"},
        11: {"link": "https://rent.example/", "image": "", "title": "Toronto rents drop"},
        12: {"link": "https://privacy.example/", "image": "", "title": "Privacy bill"},
        13: {"link": "https://markets.example/", "image": "", "title": "Markets rally"},
        14: {"link": "https://ttc.example/", "image": "", "title": "TTC funded"},
    }
    html, used_ids = parse_and_render_sections(text, links_by_id, {}, tiered_items=[])
    # Hero image from item 10 appears once.
    assert html.count('src="https://img/10.jpg"') == 1
    # All 5 emoji + bold headers render.
    assert "🤖" in html and "🏠" in html and "⚖️" in html and "📈" in html and "🚇" in html
    # Inline markdown link in item 10's body becomes an anchor.
    assert '<a href="https://odyssey.example/agora"' in html
    # All 5 IDs are tracked as used.
    assert {10, 11, 12, 13, 14}.issubset(used_ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_formatting.py::test_today_in_the_world_layout_renders_hero_and_emoji_items -v`
Expected: FAIL — current parser only handles `**Headline [#N]**` (no emoji prefix or trailing colon).

- [ ] **Step 3: Add Layout A parsing and rendering**

In `formatting.py`, add a module-level regex and helper near `ID_TAG_RE`:

```python
# Layout A item: <emoji> **<micro-header> [#N]:** <body>
# Emoji is any sequence of non-space, non-asterisk characters before the
# first ** marker on the line.
LAYOUT_A_ITEM_RE = re.compile(
    r"^(?P<emoji>\S+)\s+\*\*(?P<header>.+?)\s*\[#(?P<id>\d+)\]:\*\*\s*(?P<body>.*)$"
)


def _is_today_in_the_world_section(title: str) -> bool:
    return title.strip() == "Today in the World"
```

Inside `parse_and_render_sections`, at the top of the section-block loop (just after the `emoji = SECTION_EMOJIS.get(title, "")` line), branch on the section name:

```python
        if _is_today_in_the_world_section(title):
            stories_html = _render_today_in_the_world(lines[1:], links_by_id, used_ids)
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

Add the renderer helper function at module level in `formatting.py`:

```python
def _render_today_in_the_world(lines: list[str], links_by_id: dict, used_ids: set) -> str:
    """Render the Today in the World list (Layout A) from Claude output lines.

    Hero image comes from the first item that has one. The hero image renders
    once at the top of the list and the hero item also appears as the first
    list entry. Each item is `<emoji> **<header> [#N]:** body`.
    """
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = LAYOUT_A_ITEM_RE.match(line)
        if not m:
            continue
        item_id = int(m.group("id"))
        items.append({
            "emoji": m.group("emoji"),
            "header": m.group("header").strip(),
            "id": item_id,
            "body": m.group("body").strip(),
        })

    if not items:
        return ""

    hero_image_html = ""
    for it in items:
        link = links_by_id.get(it["id"], {})
        if link.get("image"):
            img = link["image"]
            href = link.get("link", "")
            img_tag = (
                f'<img src="{img}" alt="{it["header"]}" '
                f'style="width:100%;max-width:640px;height:200px;object-fit:cover;'
                f'display:block;margin:0 0 12px;border-radius:8px">'
            )
            hero_image_html = (
                f'<a href="{href}" style="text-decoration:none;display:block">{img_tag}</a>'
                if href else img_tag
            )
            break

    items_html = ""
    for it in items:
        used_ids.add(it["id"])
        link = links_by_id.get(it["id"], {})
        href = link.get("link", "")
        bold_inner = f'{it["header"]}:'
        if href:
            bold = (
                f'<a href="{href}" style="color:#1a1a1a;text-decoration:none;">'
                f'<strong>{bold_inner}</strong></a>'
            )
        else:
            bold = f'<strong>{bold_inner}</strong>'
        rendered_body = _render_body_markdown_links(it["body"])
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{it["emoji"]}</span>'
            f'{bold} {rendered_body}</p>'
        )

    return hero_image_html + items_html
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: render Today in the World layout with hero and emoji items"
```

---

### Task 9: Render From the Front Page longform layout

When a section's parsed content has exactly one `**Headline [#N]**` followed by multiple `**<short cap>.** paragraph` blocks, render as longform: hero image, then each paragraph with its bolded micro-header inline at the start. Source line and "what this means for you" still render below.

Detection: inside the existing per-section parsing loop, after `stories` has been collected, check whether the single story's body looks like longform (multiple `**...**` bold openers at the start of separate paragraphs). If yes, route through `_render_from_the_front_page` instead of the standard renderer.

**Files:**
- Modify: `formatting.py:291-439` (`parse_and_render_sections`)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_formatting.py`:

```python
def test_from_the_front_page_longform_renders_micro_headers():
    text = """## Finance & Markets

**Fed signals rate cut by year end [#300]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back to one.

**Threading the needle.** Powell framed the move as data-dependent without naming a trigger.

**What it means.** Mortgage rates likely tick down through Q4.

Source: WSJ
"""
    links_by_id = {300: {"link": "https://wsj.example/300", "image": "https://img/300.jpg",
                         "title": "Fed signals rate cut"}}
    clusters_by_item_id = {300: {"primary_source": "WSJ", "also_in": []}}
    html, used_ids = parse_and_render_sections(text, links_by_id, clusters_by_item_id, tiered_items=[])
    # Three paragraph micro-headers render as bold inside the paragraph.
    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    assert "<strong>What it means.</strong>" in html
    # Hero image rendered.
    assert 'src="https://img/300.jpg"' in html
    # Source line still rendered.
    assert "WSJ" in html
    # ID tracked.
    assert 300 in used_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_formatting.py::test_from_the_front_page_longform_renders_micro_headers -v`
Expected: FAIL — current renderer treats the inner `**...**` markers as malformed text.

- [ ] **Step 3: Add longform detection and rendering**

In `formatting.py`, add a module-level regex near `LAYOUT_A_ITEM_RE`:

```python
# Layout C paragraph opener: a body paragraph starts with **<short cap>.** or **<short cap>?**
LAYOUT_C_PARAGRAPH_RE = re.compile(r"^\*\*(?P<header>[^*]+)\*\*\s*(?P<rest>.*)$")


def _looks_like_longform(body_lines: list[str]) -> bool:
    """Body is longform if 2+ of its paragraphs start with **<short cap>.**"""
    joined = "\n".join(body_lines)
    paragraphs = [p.strip() for p in re.split(r"\n\n+", joined) if p.strip()]
    return sum(1 for p in paragraphs if LAYOUT_C_PARAGRAPH_RE.match(p)) >= 2
```

Inside `parse_and_render_sections`, after the `stories` list is finalized for a section and before the standard `stories_html` rendering loop, add a longform branch:

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

Add the renderer helper at module level:

```python
def _render_from_the_front_page(story: dict, links_by_id: dict,
                                 clusters_by_item_id: dict, used_ids: set) -> str:
    """Render a single featured story as longform: hero image, headline,
    micro-headered paragraphs, source line, optional callout."""
    headline_for_lookup = story["headline"]
    if story.get("id") is not None:
        headline_for_lookup = f"{story['headline']} [#{story['id']}]"
    article_data = find_article_data(headline_for_lookup, links_by_id)
    article_link = article_data["link"]
    article_image = article_data["image"]
    if article_data["id"] is not None:
        used_ids.add(article_data["id"])

    out = '<div>'

    if article_image:
        img_tag = (
            f'<img src="{article_image}" alt="{story["headline"]}" '
            f'style="width:100%;max-width:640px;height:200px;object-fit:cover;'
            f'display:block;margin:0 0 12px;border-radius:8px">'
        )
        out += (
            f'<a href="{article_link}" style="text-decoration:none;display:block">{img_tag}</a>'
            if article_link else img_tag
        )

    if story["headline"]:
        headline_inner = (
            f'<a href="{article_link}" style="color:#1a1a1a;text-decoration:none;">{story["headline"]}</a>'
            if article_link else story["headline"]
        )
        out += (
            f'<p style="margin:0 0 8px;font-size:24px;font-weight:700;color:#1a1a1a;'
            f'line-height:26px;font-family:Helvetica,Arial,sans-serif">{headline_inner}</p>'
        )

    paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(story["body"])) if p.strip()]
    for p in paragraphs:
        m = LAYOUT_C_PARAGRAPH_RE.match(p)
        if m:
            header = m.group("header").strip()
            rest = _render_body_markdown_links(m.group("rest").strip())
            out += (
                f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<strong>{header}</strong> {rest}</p>'
            )
        else:
            rendered = _render_body_markdown_links(p)
            out += (
                f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
            )

    cluster = clusters_by_item_id.get(article_data["id"]) if article_data["id"] is not None else None
    if cluster:
        primary_source = cluster.get("primary_source") or story["source"]
        also_in = cluster.get("also_in") or []
    else:
        primary_source = story["source"]
        also_in = []

    if primary_source:
        out += (
            f'<p style="margin:0 0 10px;font-size:12px;color:#999;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'{render_source_line(primary_source, also_in, article_link)}</p>'
        )

    if story.get("callout"):
        out += (
            f'<div style="margin:10px 0 0;padding:12px 14px;background:#f0f4ff;'
            f'border-left:3px solid #1c7ff2;font-size:14px;line-height:20px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<strong style="color:#1c7ff2">What this means for you:</strong> {story["callout"]}</div>'
        )

    out += '</div>'
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_formatting.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: render From the Front Page longform for single-featured sections"
```

---

### Task 10: Integration sweep and visual check

Run the full suite. Construct a synthetic end-to-end Claude response covering every layout, render to HTML, and write it to a tmp file. Have Frank open it in a browser to confirm the visual outcome before merging.

**Files:**
- Test: `tests/test_formatting.py`
- Output: `tmp/sample-newsletter-{timestamp}.html`

- [ ] **Step 1: Add an integration test that exercises all three layouts**

Add to `tests/test_formatting.py`:

```python
def test_end_to_end_renders_all_three_layouts(tmp_path):
    """Synthetic Claude response covering Today in the World, standard featured,
    and From the Front Page longform. Smoke test only — verifies all three
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
Body paragraph one with [a link](https://example.com/x).

Body paragraph two.
Source: TechCrunch

**Second featured story [#21]**
Body paragraph one.

Body paragraph two.
Source: Hacker News

## US & Global

**Fed signals rate cut by year end [#30]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back.

**Threading the needle.** Powell framed the move as data-dependent.

**What it means.** Mortgage rates likely tick down through Q4.

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
    assert "Today in the World" in html
    assert "Tech & AI" in html
    assert "US & Global" in html
    assert "Odyssey ships world models" in subject
    # Layout-specific markers
    assert '<img src="https://img/10.jpg"' in html  # TitW hero
    assert "🤖" in html and "🚇" in html             # TitW emojis
    assert '<a href="https://example.com/x"' in html  # inline link in Tech & AI body
    assert "<strong>Decreasing optimism.</strong>" in html  # longform micro-header

    # Write the rendered HTML to a tmp file so Frank can open it visually.
    out = tmp_path / "sample-newsletter.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nSample newsletter rendered to: {out}")
```

- [ ] **Step 2: Run the full suite**

Run: `python3 -m pytest tests/ -q -s`
Expected: PASS for everything, including the new integration test. The `-s` flag surfaces the print so the tmp path appears in output.

- [ ] **Step 3: Render a sample for manual visual review**

Run the integration test in isolation with `-s` and copy the generated HTML to a stable location:

```bash
python3 -m pytest tests/test_formatting.py::test_end_to_end_renders_all_three_layouts -s 2>&1 | tee /tmp/sample-output.log
mkdir -p tmp
cp $(grep -oE '/[^ ]+sample-newsletter.html' /tmp/sample-output.log | head -1) tmp/sample-newsletter.html
open tmp/sample-newsletter.html
```

Frank inspects the rendered output. If anything looks wrong (broken hero image, mis-bolded micro-header, missing emoji, source line not anchored), document the fix and add a corresponding regression test before patching.

- [ ] **Step 4: Final commit**

```bash
git add tests/test_formatting.py
git commit -m "test: end-to-end integration covering all three section layouts"
```

---

## Post-Plan Review Checklist

After all tasks complete, before opening a PR:

- [ ] Full suite green: `python3 -m pytest tests/ -q`
- [ ] No references to "Worth Knowing" remain: `grep -rn "Worth Knowing" --include="*.py"` returns nothing
- [ ] No references to `promotion_to_worth_knowing` remain: `grep -rn "promotion_to_worth_knowing" --include="*.py"` returns nothing
- [ ] Sample HTML opens cleanly in Gmail render preview (drag the file onto the Gmail compose window in a test draft)
- [ ] Real run (with `MODE=test python3 newsletter.py`) produces output that matches the layout expectations

---

## Notes on the Visual Pass

The standard featured layout (Layout B) is unchanged in rendering. Today in the World and From the Front Page are the visually new pieces. Pay close attention to:

- **Today in the World hero.** The hero image plus the same item appearing again as the first list entry. If this feels redundant in the visual, the alternative is to render the hero as a tall card with the headline overlaid, and the list of 5 sits below as items 1–5 with no image. Decide after seeing the first sample.
- **Layout A micro-headers.** Whether the emoji + bolded micro-header reads naturally with the body that follows. The micro-header is meant to be a phrase the story already contains, not a generic tag.
- **Layout C micro-headers.** Whether they read as "turns in the story" or as paragraph summaries. The latter is wrong. Frank's reference: Superhuman's "Decreasing optimism.", "Threading the needle.", "Why the shift?".
- **Inline source links in Layout B body.** Whether they land on the right noun and feel like reading, not like footnotes inline.
