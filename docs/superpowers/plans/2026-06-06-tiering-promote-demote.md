# Tiering Promote/Demote Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tier (promote/demote) pipeline do what the prompt promises: derive cross-source coverage from real cluster membership instead of an LLM guess, populate `cluster_size`, remove a dead flag and dead code, and decide the fate of the same-protagonist demotion that is currently computed and discarded.

**Architecture:** Triage (`call_triage`) assigns an LLM tier plus per-item `scores`, then `apply_phase2_tier` overwrites every tier with a traction-aware formula (`compute_phase2_tier`). The drift: (a) `cross_source_coverage` is the formula's heaviest input (×3) but is a number the LLM guesses; (b) `cluster_size` is referenced by `monday_dedup_bypass` and the prompt yet never produced; (c) `promotion_to_today_in_the_world` is collected but never read (section routing does the job); (d) the prompt's cross-cluster same-entity demotion is computed in triage then erased by the phase-2 overwrite. Fix by inserting one deterministic `enrich_cluster_metrics` step after triage and before phase-2, deleting the dead flag and dead function, and (optionally, flagged) reinstating entity demotion as a deterministic post-phase-2 pass.

**Tech Stack:** Python 3.9 (runtime; `from __future__ import annotations` already in use), pytest. No new dependencies.

---

## Background

Surfaced by the 2026-06-06 dedup RCA (see [2026-06-06-clustering-miss-backstop.md](2026-06-06-clustering-miss-backstop.md), "Companion plan needed"). Confirmed in code:

- `compute_phase2_tier` ([triage.py:185-211](../../../triage.py)) weights `cross_source_coverage` ×3; it is read from `item["scores"]`, which comes straight from the LLM tool output (`_shape_tool_output`, [triage.py:137](../../../triage.py)).
- `apply_phase2_tier` ([triage.py:251-252](../../../triage.py)) does `item["tier"] = compute_phase2_tier(item)` for every item, discarding the LLM tier and the prompt's entity demotion ([prompts.py:91](../../../prompts.py)).
- `promotion_to_today_in_the_world` is in the schema and shaped onto items ([triage.py:141](../../../triage.py)) but nothing reads it. The Today-in-the-World population is a deterministic score pickoff plus section-routed items ([formatting.py:319-369](../../../formatting.py), see the comment at 356-358: "Triage may also route items directly to Today in the World").
- `monday_dedup_bypass` ([pipeline.py:293-295](../../../pipeline.py)) is never called anywhere in the pipeline, and gates on `cluster_size`, which is never set.

## File Structure

- `triage.py` — add `enrich_cluster_metrics`; remove the `promotion_to_today_in_the_world` schema property and its `_shape_tool_output` line; (Task 5, optional) add `demote_shared_entity_clusters`.
- `newsletter.py` — call `enrich_cluster_metrics` after `call_triage` and before `apply_phase2_tier`; (Task 5) call `demote_shared_entity_clusters` after `apply_phase2_tier`.
- `prompts.py` — drop the `promotion_to_today_in_the_world` bullet and the `cluster_size`-based promotion rule line; soften the cross-cluster-demotion paragraph (the deterministic pass owns it now).
- `pipeline.py` — delete `monday_dedup_bypass` (dead code) OR wire it (Task 4 decision).
- `tests/conftest.py`, `tests/test_integration.py` — drop `promotion_to_today_in_the_world` from fixtures.
- `tests/test_triage.py`, `tests/test_pipeline.py` — new unit tests.

## Before you start

Run: `python -m pytest tests/ -q`
Record the baseline (currently 138 passed). Treat any pre-existing failure as out of scope.

---

### Task 1: Derive `cross_source_coverage` and `cluster_size` from real membership

**Files:**
- Modify: `triage.py` — add `enrich_cluster_metrics` after `apply_phase2_tier` (end of file)
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_triage.py`:

```python
from triage import enrich_cluster_metrics


def test_enrich_sets_coverage_to_distinct_source_count():
    items = [
        {"id": 1, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
        {"id": 2, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
        {"id": 3, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
    ]
    # Three items, two distinct sources -> coverage 2, size 3 (not the LLM's 9).
    links_by_id = {
        1: {"source": "CBC"}, 2: {"source": "CBC"}, 3: {"source": "BBC"},
    }
    enrich_cluster_metrics(items, links_by_id)
    assert [it["cluster_size"] for it in items] == [3, 3, 3]
    assert [it["scores"]["cross_source_coverage"] for it in items] == [2, 2, 2]


def test_enrich_treats_empty_cluster_as_singleton():
    items = [{"id": 5, "cluster_id": "", "scores": {"cross_source_coverage": 4}}]
    enrich_cluster_metrics(items, {5: {"source": "NYT"}})
    assert items[0]["cluster_size"] == 1
    assert items[0]["scores"]["cross_source_coverage"] == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_triage.py -k "enrich" -v`
Expected: FAIL with `ImportError: cannot import name 'enrich_cluster_metrics' from 'triage'`.

- [ ] **Step 3: Implement**

In `triage.py`, append at the end of the file:

```python
def enrich_cluster_metrics(items: list[dict], links_by_id: dict) -> list[dict]:
    """Set each item's cluster_size and cross_source_coverage from real cluster
    membership, replacing the LLM's self-reported cross_source_coverage guess.

    cluster_size = number of items sharing the cluster_id.
    cross_source_coverage = number of DISTINCT sources in the cluster (min 1).
    Items with an empty cluster_id are singletons (size 1, coverage 1).

    Mutates items in place. MUST run after call_triage and before
    apply_phase2_tier, so compute_phase2_tier reads the corrected coverage
    (which it weights x3) instead of the model's estimate.
    """
    by_cluster: dict[str, list[dict]] = {}
    for it in items:
        cid = it.get("cluster_id") or ""
        if not cid:
            it["cluster_size"] = 1
            it.setdefault("scores", {})["cross_source_coverage"] = 1
            continue
        by_cluster.setdefault(cid, []).append(it)
    for members in by_cluster.values():
        size = len(members)
        sources = {
            links_by_id.get(m["id"], {}).get("source", "") for m in members
        }
        sources.discard("")
        coverage = max(len(sources), 1)
        for it in members:
            it["cluster_size"] = size
            it.setdefault("scores", {})["cross_source_coverage"] = coverage
    return items
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_triage.py -k "enrich" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: derive cross_source_coverage and cluster_size from cluster membership

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire `enrich_cluster_metrics` before phase-2 tiering

**Files:**
- Modify: `newsletter.py` — import (line 24) and the triage block (after `call_triage`, before `apply_phase2_tier`)
- Test: `tests/test_smoke.py` (existing; verification)

- [ ] **Step 1: Update the import**

In `newsletter.py`, change line 24 from:

```python
from triage import apply_phase2_tier, call_triage, cap_items
```

to:

```python
from triage import apply_phase2_tier, call_triage, cap_items, enrich_cluster_metrics
```

- [ ] **Step 2: Call enrich between triage and phase-2**

In `newsletter.py`, change the block (lines 54-60) from:

```python
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        with _stage("phase2_tier"):
            apply_phase2_tier(tiered_items, links_by_id)
        print("Phase 2 tier reassignment complete.", flush=True)
```

to:

```python
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        enrich_cluster_metrics(tiered_items, links_by_id)

        with _stage("phase2_tier"):
            apply_phase2_tier(tiered_items, links_by_id)
        print("Phase 2 tier reassignment complete.", flush=True)
```

- [ ] **Step 3: Run the smoke test**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add newsletter.py
git commit -m "feat: enrich cluster metrics before phase-2 tiering

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Remove the dead `promotion_to_today_in_the_world` flag

The flag is never read; Today-in-the-World routing is done by the `section` field plus the score pickoff. Remove it rather than wire a redundant path.

**Files:**
- Modify: `triage.py` — `TRIAGE_TOOL` schema (lines 54, 56) and `_shape_tool_output` (line 141)
- Modify: `prompts.py` — the promotion bullet (line 81) and the promotion-rule wording
- Modify: `tests/conftest.py` (line 53), `tests/test_integration.py` (lines 27, 35, 43)
- Test: existing suite

- [ ] **Step 1: Remove from the schema**

In `triage.py`, delete the property line (54):

```python
                        "promotion_to_today_in_the_world": {"type": "boolean"},
```

and remove `"promotion_to_today_in_the_world"` from the `required` list (line 56), so it reads:

```python
                    "required": ["id", "tier", "section", "cluster_id", "cross_source_coverage", "personal_relevance", "section_fit"],
```

- [ ] **Step 2: Remove from the shaper**

In `triage.py`, delete this line from `_shape_tool_output` (line 141):

```python
            "promotion_to_today_in_the_world": it.get("promotion_to_today_in_the_world", False),
```

- [ ] **Step 3: Remove from the prompt**

In `prompts.py`, delete the bullet (line 81):

```
- promotion_to_today_in_the_world (boolean; true only when cluster_size >= 3 AND no clean section fit)
```

- [ ] **Step 4: Remove from fixtures**

In `tests/conftest.py`, delete line 53:

```python
                "promotion_to_today_in_the_world": it["promotion_to_today_in_the_world"],
```

In `tests/test_integration.py`, delete the three `"promotion_to_today_in_the_world": False,` lines (27, 35, 43).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, baseline minus any tests that asserted on the removed field (there should be none beyond the fixture edits).

- [ ] **Step 6: Commit**

```bash
git add triage.py prompts.py tests/conftest.py tests/test_integration.py
git commit -m "refactor: remove dead promotion_to_today_in_the_world flag

Section routing plus the deterministic score pickoff already populate Today in
the World; the flag was collected but never read.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Resolve `monday_dedup_bypass` dead code

**Decision required (default: delete).** The function is never called and gates on `cluster_size`, which only exists post-`enrich_cluster_metrics` (in the triage stage, not the pre-triage dedup stage where a Monday bypass would run). Two paths:

- **4a (default, YAGNI): delete it.** Remove `monday_dedup_bypass` from `pipeline.py` (lines 293-295) and its tests in `tests/test_pipeline.py` (`test_monday_bypass_*`).
- **4b (only if the Monday "re-admit big clustered stories" behaviour is wanted):** keep it, but it must run after clustering, not in pre-triage dedup. That is a larger change (re-admitting a seen item means re-running it through triage) and should be its own spec. Do not wire it speculatively.

- [ ] **Step 1 (4a): Delete the function and its tests**

In `pipeline.py`, delete lines 293-295 (the `monday_dedup_bypass` def). In `tests/test_pipeline.py`, delete `test_monday_bypass_keeps_items_with_cluster_size_3_plus` and any sibling `test_monday_bypass_*`.

- [ ] **Step 2: Run the suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (baseline minus the deleted Monday tests).

- [ ] **Step 3: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "chore: delete unused monday_dedup_bypass (dead code, cluster_size never produced)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5 (FLAGGED, evaluate before building): Reinstate same-entity demotion deterministically

**This is the risky one. Recommend shipping Tasks 1-4 first, then deciding whether to do this at all.**

The prompt ([prompts.py:91](../../../prompts.py)) tells the LLM to demote the lower-scoring of two clusters that share 2+ protagonists, but `apply_phase2_tier` erases it. A deterministic replacement runs after phase-2.

**Why it's flagged:** reliable protagonist extraction from RSS headlines is hard. Many headlines are Title Case, so "capitalized word = proper noun" over-matches. Falling back to shared significant tokens risks demoting two genuinely distinct stories that share generic words ("AI", "launch", "model"), and a wrong demotion buries a real story. The editorial upside (two same-cast stories not both featured) is modest now that `near_duplicate_ids` already collapses true duplicates.

**If you build it,** the conservative shape:

- Add `demote_shared_entity_clusters(items, clusters, min_shared_entities=2)` to `triage.py`. Extract entities from each cluster's `canonical_headline` using `normalize_text` (from `pipeline`) intersected with a proper-noun heuristic (token appears Capitalized in the headline AND the headline is not entirely Title Case). For each pair of clusters that both contain a tier-1-or-2 item and share `>= min_shared_entities` entities, demote every item in the lower-scoring cluster by one tier (1->2, 2->3; never below 3). Lower-scoring = lower max `_item_score`; ties favour higher `cross_source_coverage`.
- Call it in `newsletter.py` immediately after `apply_phase2_tier`.
- Tests must include a guard that two distinct Tier-1 stories sharing only a generic word ("AI") are NOT demoted, plus a positive case (two clusters sharing two named entities).

Soften the `prompts.py` cross-cluster-demotion paragraph to note the deterministic pass is authoritative (keep the LLM hint or drop it; it no longer drives behaviour).

Do not implement Task 5 without an explicit go-ahead and a calibration example, the same way `near_duplicate_ids` waited for the 2026-06-06 incident.

---

## Self-review

- **Coverage of the four findings:** #2 (coverage = guess) → Task 1+2. #4 (cluster_size never produced) → Task 1 produces it; Task 4 removes the only (dead) consumer. #3 (dead promotion flag) → Task 3. #1 (entity demotion discarded) → Task 5, flagged and gated on a go-ahead.
- **Order matters:** Task 1 must precede phase-2 (Task 2 places it correctly). Task 5, if built, must follow phase-2.
- **Type consistency:** `enrich_cluster_metrics` writes `item["cluster_size"]: int` and `item["scores"]["cross_source_coverage"]: int`, both read by `compute_phase2_tier`/`_item_score` as ints. No signature changes to existing functions.
- **No placeholders:** Tasks 1-4 have complete code and commands. Task 5 is intentionally a design with a stop-gate, not buildable steps, because it needs a calibration example first.
