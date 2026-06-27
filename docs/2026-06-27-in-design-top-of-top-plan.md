# In Design "Top of the Top" + Pickoff Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekend "In Design" pickoff a true highlight reel (top, most-talked-about stories, ranked by popularity incl. design-subreddit traction), pin it first, give it its own emoji, stop it double-rendering into section Other Headlines, and diverge the weekday "In the World" pickoff into a genuine "otherwise missed" digest.

**Architecture:** The "global pickoff" already exists in `build_format_input` ([formatting.py:324-374](../formatting.py)) — it skims top tier-1 items into the `Today in the World` section and deletes them from home sections. We (1) fix the leak where pickoff items re-surface in programmatic Other Headlines by rendering the pickoff block first so its IDs seed `used_ids` before any section synthesizes OH, plus a backstop skip; (2) pin the pickoff first; (3) swap the In Design emoji; (4) add a mode-aware design-subreddit traction list so the reddit popularity signal actually fires on weekends; (5) rank the pickoff by a popularity score (coverage + reddit/HN traction) instead of the relevance-equal `_item_score`; (6) diverge the weekday pickoff to pull "doesn't-fit" items.

**Tech Stack:** Python 3, pytest. Files: `formatting.py`, `triage.py`, `config.py`, `newsletter.py`, `tests/test_formatting.py`, `tests/test_triage.py`.

---

## ⚠️ Confirm before executing Phase 4

Phase 4 changes **weekday** editions (5 of 7 days), the highest blast radius. It rests on this mechanical definition of "otherwise missed," which the user should confirm:

> **In the World (weekday) = the top stories, ranked by popularity, whose triage `section_fit` is `weak` or `none`** — i.e. stories that don't cleanly belong to any section card, surfaced first so they aren't missed. (Weekend "In Design" keeps pulling from *all* tier-1 items — the highlight reel.)

If the user wants a different definition (e.g. "items from sections that earned no featured card"), revise Phase 4 only; Phases 1-3 are independent and shippable without it.

---

## File Structure

| File | Responsibility | Phases |
|---|---|---|
| `formatting.py` | Pickoff selection (`build_format_input`), render order + dedup (`parse_and_render_sections`, `_render_today_in_the_world`), emoji (`_global_pickoff_display`), new `_popularity_score` | 1,3,4 |
| `triage.py` | Extract `reddit_bonus`/`hn_bonus` helpers; mode-aware traction (`apply_phase2_tier`, `attach_traction`) | 2,3 |
| `config.py` | `DESIGN_SUBREDDITS` list | 2 |
| `newsletter.py` | Thread `is_design_mode(mode)` into `apply_phase2_tier` and `build_format_input` | 2,4 |
| `tests/test_formatting.py` | Pickoff/render/dedup/emoji/popularity tests | 1,3,4 |
| `tests/test_triage.py` | Bonus-helper + mode-aware traction tests | 2,3 |

---

## Phase 1 — Core: pin pickoff first, kill the double-render, swap emoji

Lowest risk; fixes the reported Figma/Carbon duplication on its own.

### Task 1: Reproduce the double-render with a failing test

**Files:**
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

This mirrors today's bug: an item Claude places in the `Today in the World` block is *also* a tier-1 Design & Product item, so the programmatic Other Headlines re-lists it.

```python
def test_pickoff_item_not_duplicated_in_section_other_headlines():
    # Item #10 is featured in the global pickoff block AND is a tier-1
    # Design & Product item, so OH synthesis would re-list it (the bug).
    text = (
        "## Design & Product\n"
        "**DesignOps shifts [#1]**\nSource: UX Collective\nbody one\n\n"
        "## Today in the World\n"
        "🎨 **Figma goes code-native [#10]:** Config 2026 recap\n"
    )
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),
        _item(10, "Design & Product", tier=1, ccov=2, prel=1, fit="good"),
    ]
    links_by_id = {
        1: {"title": "DesignOps shifts", "source": "UX Collective", "snippet": "x", "link": "https://u/1", "image": ""},
        10: {"title": "Figma goes code-native", "source": "UX Collective", "snippet": "x", "link": "https://u/10", "image": ""},
    }
    html, used_ids = parse_and_render_sections(
        text, links_by_id, {}, tiered_items=tiered_items, is_design_edition=True,
    )
    # The pickoff link for #10 must appear exactly once across the whole email.
    assert html.count('href="https://u/10"') == 1
    assert 10 in used_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/pytest tests/test_formatting.py::test_pickoff_item_not_duplicated_in_section_other_headlines -v`
Expected: FAIL — `assert 2 == 1` (item #10 rendered in both the pickoff and Design & Product Other Headlines).

### Task 2: Render the pickoff block first so its IDs seed `used_ids`

**Files:**
- Modify: `formatting.py` — `parse_and_render_sections` ([formatting.py:804](../formatting.py))

- [ ] **Step 3: Pin the pickoff block first**

In `parse_and_render_sections`, immediately after `blocks = re.split(r"\n## ", text)` (line 804), add a stable reorder that floats the `Today in the World` block to the front. Insert:

```python
    blocks = re.split(r"\n## ", text)

    # Pin the global pickoff (Today in the World / In the World / In Design)
    # to render first. Rendering it before any section runs means its item
    # IDs land in used_ids before render_other_headlines_for_section and
    # build_everything_else synthesize, so a pickoff story can never re-appear
    # as a section's Other Headline. Stable sort keeps every other section in
    # its existing (score-ranked) order.
    def _block_title(b: str) -> str:
        return b.split("\n", 1)[0].replace("## ", "").strip()
    blocks.sort(key=lambda b: 0 if _block_title(b) == TODAY_IN_THE_WORLD else 1)

    html     = ""
```

(Remove the now-duplicated `html = ""` that previously followed the split.)

- [ ] **Step 4: Add a backstop skip in the pickoff renderer**

In `_render_today_in_the_world` ([formatting.py:742](../formatting.py)), skip any item already claimed so the pickoff can never emit a duplicate even if block order changes. Change the render loop head:

```python
    items_html = ""
    for it in items:
        if it["id"] in used_ids:
            continue
        used_ids.add(it["id"])
```

- [ ] **Step 5: Run the failing test — now passes**

Run: `venv/bin/pytest tests/test_formatting.py::test_pickoff_item_not_duplicated_in_section_other_headlines -v`
Expected: PASS

- [ ] **Step 6: Add a first-position assertion test**

```python
def test_pickoff_section_renders_first():
    text = (
        "## Design & Product\n**A [#1]**\nSource: UX Collective\nbody\n\n"
        "## Today in the World\n🎨 **B [#2]:** body two\n"
    )
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),
        _item(2, "Design & Product", tier=1, ccov=2, prel=1, fit="good"),
    ]
    links_by_id = {
        1: {"title": "A", "source": "UX Collective", "snippet": "x", "link": "https://u/1", "image": ""},
        2: {"title": "B", "source": "UX Collective", "snippet": "x", "link": "https://u/2", "image": ""},
    }
    html, _ = parse_and_render_sections(
        text, links_by_id, {}, tiered_items=tiered_items, is_design_edition=True,
    )
    # "In Design" (the pickoff display title) appears before "Design & Product".
    assert html.index("In Design") < html.index("Design &amp; Product") or \
           html.index("In Design") < html.index("Design & Product")
```

- [ ] **Step 7: Run it**

Run: `venv/bin/pytest tests/test_formatting.py::test_pickoff_section_renders_first -v`
Expected: PASS

### Task 3: Swap the In Design emoji to 🖌️

**Files:**
- Modify: `formatting.py` — `_global_pickoff_display` ([formatting.py:489-492](../formatting.py))
- Test: `tests/test_formatting.py`

- [ ] **Step 8: Write the failing test**

```python
def test_in_design_emoji_is_paintbrush():
    from formatting import _global_pickoff_display
    title, emoji = _global_pickoff_display(is_design_edition=True)
    assert title == "In Design"
    assert emoji == "🖌️"
    # Weekday pickoff is unchanged.
    assert _global_pickoff_display(is_design_edition=False) == ("In the World", "🌐")
```

- [ ] **Step 9: Run it — fails** (`assert '🎨' == '🖌️'`)

Run: `venv/bin/pytest tests/test_formatting.py::test_in_design_emoji_is_paintbrush -v`

- [ ] **Step 10: Implement**

```python
def _global_pickoff_display(is_design_edition: bool) -> tuple[str, str]:
    if is_design_edition:
        return ("In Design", "🖌️")
    return ("In the World", "🌐")
```

- [ ] **Step 11: Run it — passes**

Run: `venv/bin/pytest tests/test_formatting.py::test_in_design_emoji_is_paintbrush -v`

- [ ] **Step 12: Run the full formatting + integration suite, then commit**

Run: `venv/bin/pytest tests/test_formatting.py tests/test_integration.py -q`
Expected: all pass.

```bash
git add formatting.py tests/test_formatting.py
git commit -m "fix: pin In Design pickoff first, dedup against section headlines, 🖌️ emoji"
```

---

## Phase 2 — Mode-aware design-subreddit traction

The reddit popularity signal is wired (`compute_phase2_tier`) but searches news subs only, so it never fires on weekend design articles. Make the subreddit list mode-aware.

### Task 4: Add `DESIGN_SUBREDDITS`

**Files:**
- Modify: `config.py` ([config.py:23-31](../config.py))

- [ ] **Step 1: Add the list** directly below `REDDIT_SUBREDDITS`:

```python
# Searched instead of REDDIT_SUBREDDITS on weekend design editions so the
# reddit "most talked about" signal reflects design/product discussion, not
# news. Kept to ~6 subs to stay under Reddit's anonymous ~60 req/min ceiling
# (6 subreddit searches + 1 HN call per item, 5 concurrent workers).
DESIGN_SUBREDDITS = [
    "userexperience",
    "UXDesign",
    "web_design",
    "graphic_design",
    "ProductManagement",
    "Design",
]
```

### Task 5: Thread the edition flag through traction

**Files:**
- Modify: `triage.py` — `_attach_one`, `attach_traction`, `apply_phase2_tier` ([triage.py:258-297](../triage.py))
- Modify: `newsletter.py` ([newsletter.py:62](../newsletter.py))
- Test: `tests/test_triage.py`

- [ ] **Step 2: Write the failing test** (asserts the design list is used when `design_edition=True`)

```python
def test_apply_phase2_tier_uses_design_subreddits_on_design_editions(monkeypatch):
    import triage
    from config import DESIGN_SUBREDDITS
    captured = {}
    def fake_reddit(url, subreddits):
        captured["subs"] = subreddits
        return {"score": 0, "comments": 0, "subreddit_hits": 0}
    monkeypatch.setattr(triage, "fetch_reddit_traction", fake_reddit)
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0})
    items = [{"id": 1, "tier": 1, "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"}}]
    links_by_id = {1: {"link": "https://example.com/a"}}
    triage.apply_phase2_tier(items, links_by_id, design_edition=True)
    assert captured["subs"] == DESIGN_SUBREDDITS
```

- [ ] **Step 3: Run it — fails** (`apply_phase2_tier` takes no `design_edition` kwarg)

Run: `venv/bin/pytest tests/test_triage.py::test_apply_phase2_tier_uses_design_subreddits_on_design_editions -v`

- [ ] **Step 4: Implement the threading.** In `triage.py`:

```python
def _attach_one(item: dict, link: str, subreddits: list) -> None:
    item["reddit"] = fetch_reddit_traction(link, subreddits)
    item["hn"] = fetch_hn_traction(link)


def attach_traction(items: list[dict], links_by_id: dict, subreddits: list = None) -> list[dict]:
    subreddits = subreddits if subreddits is not None else REDDIT_SUBREDDITS
    work = []
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        work.append((item, link))
    if not work:
        return items
    with ThreadPoolExecutor(max_workers=TRACTION_MAX_WORKERS) as executor:
        list(executor.map(lambda pair: _attach_one(pair[0], pair[1], subreddits), work))
    return items


def apply_phase2_tier(items: list[dict], links_by_id: dict, design_edition: bool = False) -> list[dict]:
    from config import DESIGN_SUBREDDITS
    subreddits = DESIGN_SUBREDDITS if design_edition else REDDIT_SUBREDDITS
    try:
        attach_traction(items, links_by_id, subreddits)
    except Exception as e:
        print(f"  Phase 2: attach_traction failed ({e}); keeping Claude tiers.", flush=True)
        return items
    for item in items:
        item["tier"] = compute_phase2_tier(item)
    return items
```

- [ ] **Step 5: Update the caller.** In `newsletter.py:62`:

```python
        with _stage("phase2_tier"):
            apply_phase2_tier(tiered_items, links_by_id, design_edition=is_design_mode(mode))
```

- [ ] **Step 6: Run the triage suite — passes**

Run: `venv/bin/pytest tests/test_triage.py -q`
Expected: all pass (existing `attach_traction`/`apply_phase2_tier` calls use defaults).

- [ ] **Step 7: Commit**

```bash
git add config.py triage.py newsletter.py tests/test_triage.py
git commit -m "feat: search design subreddits for reddit traction on weekend editions"
```

---

## Phase 3 — Rank the pickoff by popularity, not relevance

The pickoff currently ranks by `_item_score` (coverage + relevance, equal weight, no traction). Rank it by a popularity score so "In Design" is genuinely "most talked about / most covered."

### Task 6: Extract shared bonus helpers (DRY)

**Files:**
- Modify: `triage.py` — `compute_phase2_tier` ([triage.py:229-255](../triage.py))
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing test**

```python
def test_reddit_and_hn_bonus_thresholds():
    from triage import reddit_bonus, hn_bonus
    assert reddit_bonus({"score": 1000, "subreddit_hits": 0}) == 2
    assert reddit_bonus({"score": 0, "subreddit_hits": 2}) == 2
    assert reddit_bonus({"score": 200, "subreddit_hits": 1}) == 1
    assert reddit_bonus({"score": 10, "subreddit_hits": 1}) == 0
    assert hn_bonus({"points": 200}) == 1
    assert hn_bonus({"points": 199}) == 0
```

- [ ] **Step 2: Run it — fails** (`ImportError`)

Run: `venv/bin/pytest tests/test_triage.py::test_reddit_and_hn_bonus_thresholds -v`

- [ ] **Step 3: Extract the helpers and reuse them in `compute_phase2_tier`:**

```python
def reddit_bonus(reddit: dict) -> int:
    if reddit.get("score", 0) >= 1000 or reddit.get("subreddit_hits", 0) >= 2:
        return 2
    if reddit.get("score", 0) >= 200:
        return 1
    return 0


def hn_bonus(hn: dict) -> int:
    return 1 if hn.get("points", 0) >= 200 else 0


def compute_phase2_tier(item: dict) -> int:
    scores = item.get("scores", {})
    base = (
        scores.get("cross_source_coverage", 0) * 3
        + scores.get("personal_relevance", 0) * 2
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "none"), 0)
    )
    total = base + reddit_bonus(item.get("reddit", {})) + hn_bonus(item.get("hn", {}))
    if total >= 6:
        return 1
    if total >= 3:
        return 2
    if total >= 1:
        return 3
    return 0
```

- [ ] **Step 4: Run triage suite — passes**

Run: `venv/bin/pytest tests/test_triage.py -q`

### Task 7: Add `_popularity_score` and rank the pickoff by it

**Files:**
- Modify: `formatting.py` — add `_popularity_score`; `build_format_input` pickoff block ([formatting.py:324-374](../formatting.py))
- Test: `tests/test_formatting.py`

- [ ] **Step 5: Write the failing test** — a low-relevance but widely-covered + reddit-hot item must out-rank a high-relevance low-coverage one in the pickoff.

```python
def test_pickoff_ranks_by_popularity_not_relevance():
    # #1: huge personal relevance, no coverage/traction.
    # #2: low relevance, wide coverage + reddit-hot → more "talked about".
    tiered_items = [
        {"id": 1, "section": "Design & Product", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 2, "section": "Tech & AI", "tier": 1, "cluster_id": "c2",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 0, "section_fit": "good"},
         "reddit": {"score": 1500, "subreddit_hits": 3}, "hn": {"points": 300}},
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "s", "image": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=True))
    world = payload["sections"]["Today in the World"]["tier_1"]
    # Both get picked, but #2 (more talked about) must be the hero (position 0).
    assert world[0]["id"] == 2
```

- [ ] **Step 6: Run it — fails** (`build_format_input` has no `is_design_edition` kwarg; ordering is by `_item_score`)

Run: `venv/bin/pytest tests/test_formatting.py::test_pickoff_ranks_by_popularity_not_relevance -v`

- [ ] **Step 7: Add `_popularity_score`** next to `_item_score` ([formatting.py:113](../formatting.py)):

```python
def _popularity_score(item: dict) -> int:
    """Rank the global pickoff by how *talked about* a story is, not how
    personally relevant. Cross-source coverage dominates (x3 — "most
    published"), reddit/HN traction adds the "most discussed" signal, and
    personal relevance is a minor tiebreak (x1)."""
    from triage import reddit_bonus, hn_bonus
    scores = item.get("scores", {})
    return (
        scores.get("cross_source_coverage", 0) * 3
        + reddit_bonus(item.get("reddit", {}))
        + hn_bonus(item.get("hn", {}))
        + scores.get("personal_relevance", 0)
    )
```

- [ ] **Step 8: Use it in the pickoff.** Add `is_design_edition: bool = False` to the `build_format_input` signature ([formatting.py:243](../formatting.py)). At the top of the function build an id→item map so the pickoff can read traction the by_section copies don't carry:

```python
def build_format_input(tiered_items, clusters, links_by_id, suppressed_ids=None, is_design_edition=False):
    item_by_id = {it["id"]: it for it in tiered_items}
```

Then in the pickoff block, replace the `global_pool` sort key (`pair[1]["_score"]`) and the hero/swap logic's reliance on `_score` with `_popularity_score(item_by_id[item["id"]])`. Concretely, change line ~337:

```python
    global_pool.sort(key=lambda pair: _popularity_score(item_by_id[pair[1]["id"]]), reverse=True)
```

Leave the `_has_image` hero-promotion logic untouched (it reads `item["_has_image"]`, still present on the copies).

- [ ] **Step 9: Update the caller.** In `newsletter.py:73`:

```python
            format_input = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids, is_design_edition=is_design_mode(mode))
```

- [ ] **Step 10: Run it — passes; then run the full formatting suite**

Run: `venv/bin/pytest tests/test_formatting.py -q`
Expected: all pass. (Existing pickoff tests use no reddit/hn and coverage-dominant scores, so popularity ordering matches their assertions; if any assert a tie-broken order that changed, update the expected IDs to match `_popularity_score`.)

- [ ] **Step 11: Commit**

```bash
git add formatting.py triage.py newsletter.py tests/test_formatting.py tests/test_triage.py
git commit -m "feat: rank In Design pickoff by popularity (coverage + reddit/HN traction)"
```

---

## Phase 4 — Weekday "In the World" = otherwise missed

**Confirm the definition in the box at the top before starting.** Weekend (`is_design_edition=True`) keeps the all-items highlight-reel pool from Phase 3. Weekday narrows the pool to "doesn't-fit" stories.

### Task 8: Narrow the weekday pickoff pool to weak/no section-fit

**Files:**
- Modify: `formatting.py` — pickoff block in `build_format_input` ([formatting.py:330-338](../formatting.py))
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

```python
def test_weekday_pickoff_pulls_only_misfit_stories():
    # Weekday (is_design_edition=False): only weak/none section_fit items are
    # eligible for "In the World" — the ones that don't land in a section.
    tiered_items = [
        {"id": 1, "section": "Tech & AI", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # great fit → stays in section
        {"id": 2, "section": "Tech & AI", "tier": 1, "cluster_id": "c2",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 0, "section_fit": "none"}},   # no fit → pickoff
        {"id": 3, "section": "US & Global", "tier": 1, "cluster_id": "c3",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 0, "section_fit": "weak"}},   # weak fit → pickoff
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "s", "image": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=False))
    world_ids = {x["id"] for x in payload["sections"]["Today in the World"]["tier_1"]}
    assert world_ids == {2, 3}
    # The good-fit story stays in its home section, not the pickoff.
    assert payload["sections"]["Tech & AI"]["tier_1"][0]["id"] == 1


def test_weekend_pickoff_still_pulls_top_regardless_of_fit():
    # Weekend keeps the highlight-reel behaviour: best item wins even with good fit.
    tiered_items = [
        {"id": 1, "section": "Design & Product", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 2, "section_fit": "good"}},
    ]
    links_by_id = {1: {"title": "t1", "source": "X", "snippet": "s", "image": ""}}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=True))
    world_ids = {x["id"] for x in payload["sections"]["Today in the World"]["tier_1"]}
    assert world_ids == {1}
```

- [ ] **Step 2: Run them — first fails** (weekday currently pulls the top item #1 regardless of fit)

Run: `venv/bin/pytest tests/test_formatting.py::test_weekday_pickoff_pulls_only_misfit_stories -v`

- [ ] **Step 3: Implement the pool filter.** In the pickoff block, where `global_pool` is built ([formatting.py:330-335](../formatting.py)), gate weekday candidates on section fit:

```python
    global_pool = []
    for sec, sec_buckets in by_section.items():
        if sec == TODAY_IN_THE_WORLD:
            continue
        for item in sec_buckets["tier_1"]:
            if not is_design_edition:
                # Weekday "In the World" surfaces only stories that don't land
                # cleanly in a section (weak/no fit) — the otherwise-missed pile.
                fit = item_by_id[item["id"]].get("scores", {}).get("section_fit", "weak")
                if fit not in ("weak", "none"):
                    continue
            global_pool.append((sec, item))
```

(`item_by_id` was added in Phase 3, Step 8.)

- [ ] **Step 4: Run both new tests — pass**

Run: `venv/bin/pytest tests/test_formatting.py::test_weekday_pickoff_pulls_only_misfit_stories tests/test_formatting.py::test_weekend_pickoff_still_pulls_top_regardless_of_fit -v`

- [ ] **Step 5: Run the WHOLE suite and reconcile.** Some existing `build_format_input` tests assumed the weekday pickoff skims top items regardless of fit (e.g. swamp items with `fit="good"`). Under the new rule those good-fit swamp items stay in their sections.

Run: `venv/bin/pytest -q`
Expected: identify any failures whose intent was "swamp the pickoff." Where a test used `fit="good"` swamp items purely to absorb the pickoff, change those swamp items to `fit="none"` so they still get pulled into the pickoff on weekday and the test's actual assertion (per-section caps, image priority, tier-2 fill) holds. Do **not** weaken the assertion being tested — only adjust the swamp setup's `fit`.

- [ ] **Step 6: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: weekday In the World surfaces otherwise-missed (weak/no-fit) stories"
```

---

## Self-Review notes

- **Spec coverage:** double-render fix (P1 T1-2), first-position (P1 T2), emoji (P1 T3), reddit-too signal (P2), most-talked-about ranking (P3), weekday otherwise-missed (P4). All covered.
- **Type consistency:** `reddit_bonus`/`hn_bonus` defined in `triage.py` (P3 T6) and imported by `_popularity_score` (P3 T7) and `compute_phase2_tier`. `is_design_edition` kwarg added to `build_format_input` in P3 T7 and reused in P4. `item_by_id` introduced in P3 T7 Step 8 and reused in P4 T8 Step 3 — P3 must land before P4.
- **Ordering dependency:** Phases are sequential (P3 before P4 for `item_by_id` + signature). P1 and P2 are independent of each other and of P3/P4.
- **Risk flag:** Phase 4 alters weekday editions; gated behind the confirmation box.
