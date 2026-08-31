# Design Edition Craft-Depth Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is self-contained.** The diagnosis below was established on 2026-08-31 from four shipped weekend editions and a live archive dump. Do not re-derive it. Do not re-read Gmail. Start at Task 1.

**Goal:** Make Tier 1 reachable on weekend design editions, and make prominence depend on the quality of the writing rather than on topic match alone.

---

## Background: why this change exists

On a weekend design edition, the triage tier formula is

```
total = cross_source_coverage + personal_relevance + section_fit_score
Tier 1 if total >= 6, Tier 2 if 3-5, Tier 3 if 1-2, Dropped if <= 0
```

Two of those three dimensions are constants on a design edition:

- `section_fit` is always `good` (+1), because `triage_sections(is_design_edition=True)` returns exactly one section, `"Design & Product"`. An item cannot fit badly into the only section on the menu.
- `cross_source_coverage` is always 1, because design feeds publish original essays and almost never cover the same story. Its schema minimum is 1.

So the ceiling is `1 + 3 + 1 = 5`, against a Tier 1 threshold of 6. **Tier 1 is arithmetically unreachable.** Every featured slot on every weekend edition is filled by the tier-2 promotion loop in `formatting.py`, which ranks on `_item_score`, which on a design edition reduces to `personal_relevance` alone.

`personal_relevance` is scored against `personal-context.md`, which weights career moves, comp benchmarks, design leadership, Claude Code, agent frameworks, and indie-hacker AI income at 3, and explicitly discounts craft ("Principle-level synthesis matters more than tutorials or surface-level case studies"). The result, measured across four Saturday editions (68 slots):

| Source | Slots | Lead | Feature | Brief | Prominent % |
|---|---|---|---|---|---|
| UX Collective | 25 | 1 | 5 | 19 | **24%** |
| Lenny's Newsletter | 16 | 0 | 6 | 10 | 38% |
| NN/g | 15 | 2 | 8 | 5 | **67%** |
| Smashing Magazine | 12 | 1 | 5 | 6 | 50% |

UX Collective takes the most slots and converts the fewest to prominence. A craft essay cannot outrank a career post under a formula whose only live axis is career relevance.

**Already fixed on 2026-08-31 (do not redo):** per-source diversity caps in `formatting.py` (`DESIGN_MAX_FEATURED_PER_SOURCE` etc.), the publish-date pool filter in `archive.py` (`POOL_MAX_PUBLISH_AGE_S`, `POOL_MIN_ITEMS`), and the `doc.cc` feed in `config.py`. This plan is the remaining piece.

---

## The change

On design editions only, replace the dead `cross_source_coverage` axis with a live `craft_depth` axis (0-3):

| Score | Meaning |
|---|---|
| 3 | Original argument with a clear point of view; the author is making a case |
| 2 | Solid practitioner piece; concrete experience or method, lightly argued |
| 1 | Tutorial, listicle, roundup, link post, interview or podcast recap |
| 0 | Promo, jobs board, sponsor content, product or feature announcement |

New ceiling: `3 + 3 + 1 = 7`. Tier 1 at >= 6 becomes reachable and requires genuine quality **and** relevance.

Weekday editions keep `cross_source_coverage` unchanged. It carries real signal there (five outlets covering one story) and the weekday product is working.

**The critical prompt requirement:** `craft_depth` must be scored independently of whether the topic matches Frank's interests. Without an explicit instruction, the model will collapse it into a second `personal_relevance` and nothing changes. State the independence directly and give a worked counter-example.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `triage.py` | Modify | `build_triage_tool(is_design_edition)` emits `craft_depth` instead of `cross_source_coverage` on design editions; `_shape_tool_output` carries it through |
| `prompts.py` | Modify | `build_triage_system_prompt(is_design_edition)` documents the design formula and the craft_depth rubric |
| `formatting.py` | Modify | `_item_score` sums `craft_depth` when present, falling back to `cross_source_coverage` |
| `tests/test_triage.py` | Modify | Tool schema and output shaping, both edition types |
| `tests/test_prompts.py` | Modify | Prompt contains the rubric and the independence instruction on design editions only |
| `tests/test_formatting.py` | Modify | `_item_score` handles both score shapes |

---

## Task 1: Emit craft_depth in the triage tool schema

**Files:** Modify `triage.py` (`build_triage_tool`, around the `cross_source_coverage` property); Test `tests/test_triage.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_design_tool_schema_uses_craft_depth():
    from triage import build_triage_tool
    props = build_triage_tool(True)["input_schema"]["properties"]["items"]["items"]["properties"]
    assert "craft_depth" in props
    assert props["craft_depth"] == {"type": "integer", "minimum": 0, "maximum": 3}
    assert "cross_source_coverage" not in props


def test_weekday_tool_schema_keeps_cross_source_coverage():
    from triage import build_triage_tool
    props = build_triage_tool(False)["input_schema"]["properties"]["items"]["items"]["properties"]
    assert "cross_source_coverage" in props
    assert "craft_depth" not in props


def test_design_tool_requires_craft_depth():
    from triage import build_triage_tool
    req = build_triage_tool(True)["input_schema"]["properties"]["items"]["items"]["required"]
    assert "craft_depth" in req and "cross_source_coverage" not in req
```

- [ ] **Step 2: Implement.** Build the per-item property dict conditionally on `is_design_edition`. Keep every other field identical. `TRIAGE_TOOL` at module level still calls `build_triage_tool()`; leave its default as-is.
- [ ] **Step 3: Run `python3 -m pytest tests/test_triage.py -q`**

## Task 2: Carry craft_depth through output shaping

**Files:** Modify `triage.py` (`_shape_tool_output`); Test `tests/test_triage.py`

- [ ] **Step 1: Write the failing test.** A tool payload carrying `craft_depth: 3` must survive into `items[0]["scores"]["craft_depth"]`. A payload carrying `cross_source_coverage` must still survive unchanged.
- [ ] **Step 2: Implement.** In the `scores` dict, add `craft_depth` when the raw item has it. Do not default it to a number when absent, or weekday items will silently gain a zero axis; use `if "craft_depth" in it` and omit otherwise.
- [ ] **Step 3: Run the triage tests.**

## Task 3: Score craft_depth in the formatter

**Files:** Modify `formatting.py` (`_item_score`); Test `tests/test_formatting.py`

`_item_score` currently reads `cross_source_coverage`. It must sum whichever axis is present so design and weekday items both score correctly.

- [ ] **Step 1: Write the failing tests**

```python
def test_item_score_uses_craft_depth_when_present():
    from formatting import _item_score
    assert _item_score({"craft_depth": 3, "personal_relevance": 2, "section_fit": "good"}) == 6


def test_item_score_falls_back_to_cross_source_coverage():
    from formatting import _item_score
    assert _item_score({"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}) == 5


def test_item_score_prefers_craft_depth_if_both_present():
    from formatting import _item_score
    scores = {"craft_depth": 3, "cross_source_coverage": 1,
              "personal_relevance": 0, "section_fit": "weak"}
    assert _item_score(scores) == 3
```

- [ ] **Step 2: Implement.** `scores.get("craft_depth", scores.get("cross_source_coverage", 0))`.
- [ ] **Step 3: Run `python3 -m pytest tests/test_formatting.py -q`**

**Note:** `_popularity_score` (used by the "In the World" global pickoff) may also read `cross_source_coverage`. On a design edition the pickoff feeds the renamed section. Check it and decide deliberately: popularity should NOT read craft_depth, since craft is not traction. Leave `_popularity_score` on `cross_source_coverage` and let it read 0 on design editions if the key is absent.

## Task 4: Teach the prompt the design formula

**Files:** Modify `prompts.py` (`build_triage_system_prompt`); Test `tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests.** Design prompt contains "craft_depth" and the independence sentence; weekday prompt contains "cross_source_coverage" and not "craft_depth".
- [ ] **Step 2: Implement.** Branch the scoring block on `is_design_edition`. Design version must include:
  - the 0-3 rubric table verbatim from this plan
  - the tier formula restated as `craft_depth + personal_relevance + section_fit_score`
  - this instruction, or equivalent: *"Score craft_depth on the substance of the writing alone. It is independent of whether the topic matches the reader's interests, which is what personal_relevance measures. A rigorously argued essay on a topic the reader does not care about still scores craft_depth 3. A podcast recap about the reader's exact field still scores craft_depth 1."*
- [ ] **Step 3: Run `python3 -m pytest tests/test_prompts.py -q`**

## Task 5: Full suite and a dry run

- [ ] **Step 1:** `python3 -m pytest tests/ -q`. Expect all green except `test_fetch_og_meta_decodes_brotli_encoded_head`, which fails only where the `brotli` package is missing locally. It passes in CI.
- [ ] **Step 2:** Trigger the `newsletter.yml` workflow with `mode: test` and confirm the design edition renders, the featured slots are filled, and at least one item reached genuine Tier 1.
- [ ] **Step 3:** Compare against the baseline in the next section.

---

## Baseline to compare against

Captured 2026-08-31 before any change. The 2026-09-05 Saturday edition ships with the per-source caps, pool freshness filter, and doc.cc feed but WITHOUT craft_depth, so it is the control.

Saturday pool composition after the freshness filter (measured, 2026-08-31):

| Source | Before filter | After filter |
|---|---|---|
| Lenny's Newsletter | 18 | 10 |
| UX Collective | 10 | 10 |
| NN/g | 10 | 3 |
| Smashing Magazine | 7 | 2 |
| **Total** | **45** | **25** |

UX Collective pool share: 22% before, 40% after.

**What success looks like after craft_depth:** at least one item reaching Tier 1 without the promotion loop, and UX Collective's prominence conversion rising from 24% toward the 40-50% range. Its slot count should stay roughly flat or fall slightly; the per-source caps hold volume steady on purpose. **Volume was never the problem. Prominence was.**

**What failure looks like:** craft_depth correlating almost perfectly with personal_relevance across a run. That means the model collapsed the two axes and Task 4's independence instruction needs to be sharper. Print both scores per item during the test run and eyeball the correlation before shipping.

---

## Out of scope

- Link-blog attribution (Sidebar prints its own name on other publishers' articles, and one uxdesign.cc piece shipped Saturday and Sunday under two different bylines because `normalize_url` did not match the two URL forms).
- The stale footer source list in `formatting.py`, which hardcodes the weekday sources on every edition.

Both are real and both are logged. Neither belongs in this change.
