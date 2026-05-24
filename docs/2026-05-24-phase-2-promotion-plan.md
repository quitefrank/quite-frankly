# Phase 2 promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the Phase 1.5 shadow scoring (`compute_phase2_tier` + Reddit/HN traction) into the production tier-assignment path. Retire the shadow comparison logs and the Sunday digest. After this lands, Reddit and HN traction influence what stories get featured in the daily newsletter.

**Architecture:** Move the existing scoring helpers from `comparison.py` into `triage.py`. Add one new orchestrator function `apply_phase2_tier(items, links_by_id)` that calls `attach_traction` then `compute_phase2_tier` per item, with a single try/except that falls back to Claude's tiers on whole-call failure. Wire it into `newsletter.py` between the triage and format passes. Delete the shadow scoring block, the Sunday digest block, and the now-orphaned `comparison.py`.

**Tech Stack:** Python 3, pytest. No new dependencies. No new APIs (Reddit + HN already in use in shadow).

**Spec:** [`docs/2026-05-24-phase-2-promotion-spec.md`](2026-05-24-phase-2-promotion-spec.md)

---

## File Structure

| File | Change | Responsibility |
| --- | --- | --- |
| `triage.py` | Modify (append) | Receives the moved scoring helpers (`compute_phase2_tier`, `attach_traction`, `_attach_one`, `SECTION_FIT_SCORE`, `TRACTION_MAX_WORKERS`). Hosts the new `apply_phase2_tier`. |
| `comparison.py` | Delete | All contents moved or retired. |
| `newsletter.py` | Modify | Insert `apply_phase2_tier` call after triage. Delete the post-send shadow block and the Sunday weekly-digest block. Update imports. |
| `tests/test_triage.py` | Create | New file. Holds the moved `compute_phase2_tier` tests plus new `apply_phase2_tier` tests. |
| `tests/test_comparison.py` | Delete | All tests either move to `test_triage.py` (the four `compute_phase2_tier` tests) or are retired with the shadow layer. |
| `tests/test_smoke.py` | Modify | Drop the `write_comparison_log` and `summarize_week` monkeypatches; add a stub for the new traction calls so the smoke test doesn't hit the network. |
| `tests/test_integration.py` | Modify | Add an end-to-end test that mocks Reddit + HN and verifies Phase 2 tiers reach `build_format_input`. |

No new directories. `comparison/` (the data folder with historical JSON) is left on disk untouched.

---

## Task 1: Move scoring helpers from `comparison.py` to `triage.py`

This is a pure move. Behavior unchanged, tests still pass after import updates.

**Files:**
- Modify: `triage.py` (append after line 164)
- Modify: `comparison.py` (remove lines 19-89 and the `traction` import; leave `shadow_score` and the comparison/digest functions for now, but they need their imports updated to point at `triage`)
- Modify: `tests/test_comparison.py` (update imports of moved symbols)

- [ ] **Step 1: Append moved helpers to `triage.py`**

Open `triage.py` and add this block at the end of the file (after `build_triage_user_message`):

```python


# ---- Phase 2 traction-aware tier scoring ----

from concurrent.futures import ThreadPoolExecutor

from config import REDDIT_SUBREDDITS
from traction import fetch_hn_traction, fetch_reddit_traction


# Reddit's anonymous rate limit is ~60 req/min. With 7 subreddits per item +
# 1 HN call, 5 concurrent workers keeps burst rate under that ceiling.
TRACTION_MAX_WORKERS = 5


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}


def compute_phase2_tier(item: dict) -> int:
    scores = item.get("scores", {})
    base = (
        scores.get("cross_source_coverage", 0) * 3
        + scores.get("personal_relevance", 0) * 2
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "none"), 0)
    )

    reddit = item.get("reddit", {})
    if reddit.get("score", 0) >= 1000 or reddit.get("subreddit_hits", 0) >= 2:
        reddit_bonus = 2
    elif reddit.get("score", 0) >= 200:
        reddit_bonus = 1
    else:
        reddit_bonus = 0

    hn = item.get("hn", {})
    hn_bonus = 1 if hn.get("points", 0) >= 200 else 0

    total = base + reddit_bonus + hn_bonus
    if total >= 6:
        return 1
    if total >= 3:
        return 2
    if total >= 1:
        return 3
    return 0


def _attach_one(item: dict, link: str) -> None:
    item["reddit"] = fetch_reddit_traction(link, REDDIT_SUBREDDITS)
    item["hn"] = fetch_hn_traction(link)


def attach_traction(items: list[dict], links_by_id: dict) -> list[dict]:
    """Attach Reddit + HN traction to each item, in parallel across items.

    Each worker handles one item's full traction (7 subreddit searches + 1 HN
    query, ~800ms total). With TRACTION_MAX_WORKERS=5 the burst rate to
    Reddit stays under the anonymous 60 req/min ceiling.
    """
    work = []
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        work.append((item, link))
    if not work:
        return items
    with ThreadPoolExecutor(max_workers=TRACTION_MAX_WORKERS) as executor:
        list(executor.map(lambda pair: _attach_one(*pair), work))
    return items
```

- [ ] **Step 2: Remove the moved symbols from `comparison.py`**

Open `comparison.py`. Delete:
- The `from concurrent.futures import ThreadPoolExecutor` line.
- The `from config import REDDIT_SUBREDDITS` line.
- The `from traction import fetch_hn_traction, fetch_reddit_traction` line.
- `TRACTION_MAX_WORKERS` (the constant + its preceding comment).
- `SECTION_FIT_SCORE` (the constant).
- `compute_phase2_tier` (the function).
- `_attach_one` (the function).
- `attach_traction` (the function).

Leave `shadow_score`, `_delta_entry`, `build_comparison_log`, `write_comparison_log`, `summarize_week`, `build_weekly_digest_html` and their imports in place — they're deleted in Task 5.

Update `shadow_score` to import from triage. Find this function:

```python
def shadow_score(items: list[dict], links_by_id: dict) -> list[dict]:
    enriched = attach_traction([dict(i) for i in items], links_by_id)
    for item in enriched:
        item["tier"] = compute_phase2_tier(item)
    return enriched
```

Add at the top of `comparison.py` (after the remaining imports):

```python
from triage import attach_traction, compute_phase2_tier
```

- [ ] **Step 3: Update test imports in `tests/test_comparison.py`**

Change the existing import block at the top:

```python
from comparison import (
    build_comparison_log,
    build_weekly_digest_html,
    compute_phase2_tier,
    shadow_score,
    summarize_week,
    write_comparison_log,
)
```

to:

```python
from comparison import (
    build_comparison_log,
    build_weekly_digest_html,
    shadow_score,
    summarize_week,
    write_comparison_log,
)
from triage import compute_phase2_tier
```

Also update the two `monkeypatch.setattr` calls that target `comparison.fetch_reddit_traction` and `comparison.fetch_hn_traction` (lines 92-93 and 109-110): change `"comparison.fetch_reddit_traction"` to `"triage.fetch_reddit_traction"` and `"comparison.fetch_hn_traction"` to `"triage.fetch_hn_traction"`.

- [ ] **Step 4: Run the test suite**

Run: `pytest -q`
Expected: PASS (all previously-passing tests still pass; the move is behavior-preserving).

- [ ] **Step 5: Commit**

```bash
git add triage.py comparison.py tests/test_comparison.py
git commit -m "refactor: move Phase 2 scoring helpers from comparison.py to triage.py"
```

---

## Task 2: TDD `apply_phase2_tier` — happy path

**Files:**
- Create: `tests/test_triage.py`
- Modify: `triage.py` (append `apply_phase2_tier`)

- [ ] **Step 1: Write the failing test**

Create `tests/test_triage.py` with this content:

```python
import triage
from triage import apply_phase2_tier


def test_apply_phase2_tier_recomputes_using_traction(monkeypatch):
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 5000, "comments": 800, "subreddit_hits": 3})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})

    items = [{
        "id": 0,
        "tier": 3,
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
    }]
    links_by_id = {0: {"link": "https://example.com/x"}}

    result = apply_phase2_tier(items, links_by_id)
    assert result[0]["tier"] == 1
    assert items[0]["tier"] == 1  # in-place overwrite, unlike shadow_score


def test_apply_phase2_tier_recomputes_without_traction(monkeypatch):
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 0, "comments": 0, "subreddit_hits": 0})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})

    items = [{
        "id": 7,
        "tier": 2,
        "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"},
    }]
    links_by_id = {7: {"link": "https://example.com/y"}}

    result = apply_phase2_tier(items, links_by_id)
    # 2*3 + 2*2 + 1 = 11 → tier 1 even with no traction
    assert result[0]["tier"] == 1
```

- [ ] **Step 2: Run the test to verify failure**

Run: `pytest tests/test_triage.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_phase2_tier' from 'triage'`.

- [ ] **Step 3: Implement `apply_phase2_tier` (happy path only)**

Append to `triage.py` after the `attach_traction` function added in Task 1:

```python


def apply_phase2_tier(items: list[dict], links_by_id: dict) -> list[dict]:
    """Overwrite each item's tier using the Phase 2 traction-aware formula.

    Mutates items in place (in contrast to the deep-copy `shadow_score` used
    while traction lived in shadow). Returns the same list.
    """
    attach_traction(items, links_by_id)
    for item in items:
        item["tier"] = compute_phase2_tier(item)
    return items
```

- [ ] **Step 4: Run the test to verify pass**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (both tests green).

- [ ] **Step 5: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: apply_phase2_tier overwrites Claude tier with traction-aware formula"
```

---

## Task 3: TDD `apply_phase2_tier` — fallback on `attach_traction` failure

**Files:**
- Modify: `tests/test_triage.py` (add fallback test)
- Modify: `triage.py` (wrap `attach_traction` call in try/except)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_triage.py`:

```python
def test_apply_phase2_tier_falls_back_when_attach_traction_raises(monkeypatch, capsys):
    def boom(items, links_by_id):
        raise RuntimeError("Reddit blew up")

    monkeypatch.setattr(triage, "attach_traction", boom)

    items = [
        {"id": 0, "tier": 1, "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 1, "tier": 3, "scores": {"cross_source_coverage": 0, "personal_relevance": 1, "section_fit": "weak"}},
    ]
    links_by_id = {0: {"link": "https://a"}, 1: {"link": "https://b"}}

    result = apply_phase2_tier(items, links_by_id)

    assert result[0]["tier"] == 1  # Claude's tier preserved
    assert result[1]["tier"] == 3  # Claude's tier preserved
    out = capsys.readouterr().out
    assert "attach_traction failed" in out or "Reddit blew up" in out
```

- [ ] **Step 2: Run the test to verify failure**

Run: `pytest tests/test_triage.py::test_apply_phase2_tier_falls_back_when_attach_traction_raises -v`
Expected: FAIL with `RuntimeError: Reddit blew up` (the exception propagates out of `apply_phase2_tier`).

- [ ] **Step 3: Add the try/except in `apply_phase2_tier`**

Edit `triage.py`. Replace the `apply_phase2_tier` body with:

```python
def apply_phase2_tier(items: list[dict], links_by_id: dict) -> list[dict]:
    """Overwrite each item's tier using the Phase 2 traction-aware formula.

    Mutates items in place. If the Reddit/HN fetch raises (network outage,
    library error), log and return items unchanged so the email still ships
    with Claude's original tier assignments.
    """
    try:
        attach_traction(items, links_by_id)
    except Exception as e:
        print(f"  Phase 2: attach_traction failed ({e}); keeping Claude tiers.", flush=True)
        return items
    for item in items:
        item["tier"] = compute_phase2_tier(item)
    return items
```

- [ ] **Step 4: Run the full triage test file to verify**

Run: `pytest tests/test_triage.py -v`
Expected: PASS (all three tests green).

- [ ] **Step 5: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: apply_phase2_tier falls back to Claude tiers when traction fetch fails"
```

---

## Task 4: Cutover in `newsletter.py`

This is the single visible behavior change: Phase 2 tiers now ship in the live email.

**Files:**
- Modify: `newsletter.py` (lines 22-28, 65-72, 93-134)

- [ ] **Step 1: Update imports**

In `newsletter.py`, delete the entire `from comparison import (...)` block (lines 22-28):

```python
from comparison import (
    build_comparison_log,
    build_weekly_digest_html,
    shadow_score,
    summarize_week,
    write_comparison_log,
)
```

The lines should be removed completely (no replacement; leave a single blank line if needed for readability).

Then update the existing `from triage import` line (line 32):

```python
from triage import call_triage, cap_items
```

to add `apply_phase2_tier`:

```python
from triage import apply_phase2_tier, call_triage, cap_items
```

- [ ] **Step 2: Insert the `apply_phase2_tier` call after triage**

In `newsletter.py`, find the block (lines 62-72):

```python
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        suppressed_ids = suppressed_cluster_ids(tiered_items)
        if suppressed_ids:
            print(f"Cluster suppression: hiding {len(suppressed_ids)} duplicate item(s)", flush=True)

        with _stage("format"):
            format_input = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids)
            format_raw = call_formatter(format_input)
```

Add a new `_stage` block for traction-aware scoring immediately after the triage stage and before cluster suppression:

```python
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        with _stage("phase2_tier"):
            apply_phase2_tier(tiered_items, links_by_id)
        print("Phase 2 tier reassignment complete.", flush=True)

        suppressed_ids = suppressed_cluster_ids(tiered_items)
        if suppressed_ids:
            print(f"Cluster suppression: hiding {len(suppressed_ids)} duplicate item(s)", flush=True)

        with _stage("format"):
            format_input = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids)
            format_raw = call_formatter(format_input)
```

- [ ] **Step 3: Delete the post-send shadow scoring block**

In `newsletter.py`, delete lines 93-118 (the entire `if tiered_items and TEST_MODE:` / `elif tiered_items:` / `else:` block that runs shadow scoring). The block to delete starts with:

```python
    if tiered_items and TEST_MODE:
        print("Skipping shadow scoring (test mode).", flush=True)
    elif tiered_items:
        print("Running Phase 1.5 shadow scoring...", flush=True)
```

and ends with:

```python
    else:
        print("Skipping shadow scoring (no triage output).")
```

Delete the whole block.

- [ ] **Step 4: Delete the Sunday weekly-digest block**

In `newsletter.py`, delete lines 120-134 (the `if mode == Mode.SUNDAY_VISUAL:` block that sends the weekly digest). The block to delete starts with:

```python
    if mode == Mode.SUNDAY_VISUAL:
        print("Sending weekly Phase 2 shadow digest...")
```

and ends with:

```python
        except Exception as e:
            print(f"Weekly digest failed: {e}")
```

Delete the whole block.

- [ ] **Step 5: Remove now-unused imports**

`Path` from `pathlib` and `timedelta` from `datetime` were only used by the deleted blocks. Check the remaining `newsletter.py` for any other references:

Run: `grep -n "Path\|timedelta" newsletter.py`

If `Path` is no longer used anywhere, remove `from pathlib import Path` (line 7). If `timedelta` is no longer used, change `from datetime import datetime, timedelta` (line 6) to `from datetime import datetime`.

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: tests that exercise the shadow block in `newsletter.main` (smoke test) will fail because they monkeypatch `write_comparison_log` and `summarize_week` on the `newsletter` module — those names no longer exist there. That's expected and gets fixed in Task 6.

If any other test fails for unrelated reasons, stop and investigate before continuing.

- [ ] **Step 7: Commit**

```bash
git add newsletter.py
git commit -m "feat: Phase 2 tiers ship in production; retire shadow scoring and Sunday digest"
```

---

## Task 5: Delete `comparison.py` and its tests

**Files:**
- Delete: `comparison.py`
- Delete: `tests/test_comparison.py`

- [ ] **Step 1: Verify nothing imports `comparison` anymore**

Run: `grep -rn "import comparison\|from comparison" --include="*.py" .`
Expected output: empty (no matches). If there are matches in production code, stop and resolve them before continuing. Matches inside test files are acceptable if the test file is also being deleted in this task.

- [ ] **Step 2: Delete the files**

Run:

```bash
git rm comparison.py tests/test_comparison.py
```

- [ ] **Step 3: Confirm removal**

Run: `ls comparison.py tests/test_comparison.py 2>&1`
Expected: `No such file or directory` for both.

- [ ] **Step 4: Run the test suite**

Run: `pytest -q`
Expected: smoke test still fails (Task 6 fixes it); no other failures. The `compute_phase2_tier` tests from the deleted `test_comparison.py` are now covered by `test_triage.py` Tasks 2 and 3.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: delete comparison.py after Phase 2 cutover"
```

---

## Task 6: Update `tests/test_smoke.py` for the new pipeline

The smoke test currently monkeypatches `newsletter.write_comparison_log` and `newsletter.summarize_week`, which no longer exist. It also needs to stub out the new Reddit/HN calls so the smoke test stays offline.

**Files:**
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Rewrite the smoke test**

Replace the body of `test_main_runs_through_two_passes` (everything below the function signature) with:

```python
    fake_items = [
        {"title": "Toronto council debates housing supply", "link": "https://example.com/1", "snippet": "", "image": "", "source": "CBC"},
        {"title": "Bank of Canada holds rates steady", "link": "https://example.com/2", "snippet": "", "image": "", "source": "Yahoo Finance"},
    ]

    monkeypatch.setattr("formatting.send_email", lambda html, subject: None)
    monkeypatch.setattr("pipeline.fetch_all_feeds", lambda feeds: fake_items)
    monkeypatch.setattr("pipeline.deduplicate", lambda items: items)

    # Patch the imports newsletter.py has already done at module load time.
    import newsletter
    import triage
    monkeypatch.setattr(newsletter, "fetch_all_feeds", lambda feeds: fake_items)
    monkeypatch.setattr(newsletter, "deduplicate", lambda items: items)
    monkeypatch.setattr(newsletter, "send_email", lambda html, subject: None)
    # Keep the smoke test offline: stub the live Reddit/HN calls that the
    # new Phase 2 path runs between triage and format.
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 0, "comments": 0, "subreddit_hits": 0})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})
    newsletter.main()
```

- [ ] **Step 2: Run the smoke test**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: update smoke test for Phase 2 pipeline (no comparison stubs, offline traction)"
```

---

## Task 7: Integration test — Phase 2 tiers reach `build_format_input`

Verify the end-to-end wiring: a high-traction item that Claude tiered 3 should reach the formatter with tier 1.

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Inspect the existing integration test file**

Run: `head -30 tests/test_integration.py`
Read enough to understand the existing fixtures and helper functions before writing the new test.

- [ ] **Step 2: Add the new test**

`build_format_input` returns a JSON string with shape `{"sections": {<section>: {"tier_1": [...], "tier_2": [...], "tier_3": [...]}, ...}, "clusters": {...}}`. The test parses that and confirms id=42 lands in *some* `tier_1` bucket (it may land in Tech & AI's tier_1 or get promoted into Today in the World's tier_1 by the global pickoff — either is correct).

Append to `tests/test_integration.py`:

```python
import json


def test_phase2_traction_promotes_borderline_item_into_format_input(monkeypatch):
    """An item Claude tiered as 3 with strong Reddit traction should reach the
    format pass at tier 1 after apply_phase2_tier rewrites it."""
    import triage
    from triage import apply_phase2_tier
    from formatting import build_format_input

    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 5000, "comments": 800, "subreddit_hits": 3})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 250, "comments": 10})

    tiered_items = [{
        "id": 42,
        "tier": 3,
        "section": "Tech & AI",
        "cluster_id": "",
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
        "promotion_to_today_in_the_world": False,
    }]
    links_by_id = {42: {"link": "https://example.com/sleeper", "title": "Sleeper story", "source": "TechCrunch", "image": ""}}
    clusters: dict = {}
    suppressed_ids: set = set()

    apply_phase2_tier(tiered_items, links_by_id)
    assert tiered_items[0]["tier"] == 1

    format_input_json = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids)
    parsed = json.loads(format_input_json)

    ids_in_tier_1: set[int] = set()
    ids_in_tier_2_or_3: set[int] = set()
    for section_buckets in parsed["sections"].values():
        for item in section_buckets.get("tier_1", []):
            ids_in_tier_1.add(item["id"])
        for bucket_name in ("tier_2", "tier_3"):
            for item in section_buckets.get(bucket_name, []):
                ids_in_tier_2_or_3.add(item["id"])

    assert 42 in ids_in_tier_1, "Phase 2 promotion didn't reach the format input as tier 1"
    assert 42 not in ids_in_tier_2_or_3, "Item appears in both tier 1 and a lower tier"
```

- [ ] **Step 3: Run the integration test**

Run: `pytest tests/test_integration.py::test_phase2_traction_promotes_borderline_item_into_format_input -v`
Expected: PASS.

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests green).

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: Phase 2 traction promotes borderline item into format input at correct tier"
```

---

## Task 8: Final verification

**Files:** None.

- [ ] **Step 1: Run the full test suite one more time**

Run: `pytest -q`
Expected: PASS (everything green).

- [ ] **Step 2: Verify no leftover comparison references**

Run: `grep -rn "comparison\|shadow_score\|write_comparison_log\|summarize_week\|build_weekly_digest_html" --include="*.py" .`
Expected: zero matches in production code. Matches inside the `comparison/` data directory (JSON files) or in `docs/` are fine.

- [ ] **Step 3: Verify the staging path with a TEST_MODE dry run**

This step does NOT send an email. It runs `newsletter.main()` against live data with `TEST_MODE=1` (which short-circuits the SMTP send inside `formatting.send_email`).

Run: `TEST_MODE=1 python newsletter.py 2>&1 | tail -40`

Expected output includes:
- `[triage] start` / `[triage] done in Xs`
- `[phase2_tier] start` / `[phase2_tier] done in Xs` (this is the new stage; expect ~20-40s)
- `Phase 2 tier reassignment complete.`
- `[format] start` / `[format] done in Xs`
- No mention of "shadow scoring", "comparison log", or "weekly digest".
- No tracebacks.

If `[phase2_tier]` takes more than 60s on a normal run, that's a regression worth investigating before merging.

- [ ] **Step 4: Confirm `comparison/` historical data is untouched**

Run: `ls comparison/ | wc -l && git status comparison/`
Expected: the count is the same as before this task started; `git status comparison/` reports no changes.

- [ ] **Step 5: No commit needed**

Verification only. The previous task commits are the deliverable.
