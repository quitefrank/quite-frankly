# Duplicate Article Suppression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a clustered story appear exactly once in the newsletter, so a story that triage groups into one cluster can never show up as both a featured story and a catch-all bullet.

**Architecture:** The bug is a state-sharing gap. `build_format_input` collapses duplicate cluster members out of the formatter input, but the programmatic Other Headlines and Everything Else blocks render from the full uncollapsed `tiered_items` list and only skip ids already in `used_ids` (which holds rendered-as-featured ids). A collapsed-away sibling is in neither, so the catch-all renderers pick it back up. The fix computes one `suppressed_ids` set from triage's clusters and threads it through both the formatter input collapse and the catch-all renderers (by seeding `used_ids`), so every surface honors the same suppression decision.

**Tech Stack:** Python 3.11, pytest. No new dependencies.

---

## Background

Confirmed against `comparison/2026-05-21.json`: triage correctly placed four articles about the Raúl Castro indictment into one cluster, `cuba_raul_castro_charges` (ids 57, 83, 85, 76). One was featured in US & Global; the other three leaked into Other Headlines and Everything Else. Clustering (detection) worked. This is purely a suppression gap, labelled F2 below. The F1 detection backstop is deliberately deferred (see the Deferred section at the end).

## File Structure

- `formatting.py` — add `suppressed_cluster_ids`; convert the per-section collapse in `build_format_input` to a global collapse; seed `used_ids` in `parse_and_render_sections`; add a `suppressed_ids` parameter to `build_email_html`. Delete the now-dead `_collapse_by_cluster_within_section`.
- `newsletter.py` — compute the suppressed set once after triage and pass it to `build_format_input` and `build_email_html`.
- `tests/test_formatting.py` — new unit and end-to-end tests.

No new files. `render_other_headlines_for_section` and `build_everything_else` need no change: both already skip ids in `used_ids`, so seeding `used_ids` upstream is enough.

## Before you start

Establish a green baseline so any pre-existing failure is not mistaken for a regression.

Run: `python -m pytest tests/ -q`
Record the result. If a test is already failing on `main`, note it and treat it as out of scope for this plan.

---

### Task 1: Add `suppressed_cluster_ids`

**Files:**
- Modify: `formatting.py` (add a function after `_item_score`, ending at line 56)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Add the import. In `tests/test_formatting.py`, change the import block (lines 3-9) to include `suppressed_cluster_ids`:

```python
from formatting import (
    build_everything_else,
    build_format_input,
    parse_and_render_sections,
    render_other_headlines_for_section,
    render_source_line,
    suppressed_cluster_ids,
)
```

Append these two tests to the end of `tests/test_formatting.py`:

```python
def test_suppressed_cluster_ids_keeps_highest_scored_representative():
    # Four feed items, one underlying story, one cluster (the real
    # cuba_raul_castro_charges case). One item survives as the
    # representative; the other three ids are suppressed.
    items = [
        _item(57, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(83, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(85, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(76, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
    ]
    for it in items:
        it["cluster_id"] = "cuba_raul_castro_charges"
    # All four tie at score 5; the lowest id (57) wins the tiebreak and
    # survives, so the other three are suppressed.
    assert suppressed_cluster_ids(items) == {83, 85, 76}


def test_suppressed_cluster_ids_ignores_singletons_and_empty_clusters():
    # _item gives each item a unique cluster_id (cl_<id>), so items 1 and 2
    # are singleton clusters. Items 3 and 4 carry an explicit empty
    # cluster_id ("no cluster known"). Nothing is suppressed.
    items = [
        _item(1, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(3, "Tech & AI", tier=2),
        _item(4, "Tech & AI", tier=2),
    ]
    items[2]["cluster_id"] = ""
    items[3]["cluster_id"] = ""
    assert suppressed_cluster_ids(items) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_formatting.py::test_suppressed_cluster_ids_keeps_highest_scored_representative tests/test_formatting.py::test_suppressed_cluster_ids_ignores_singletons_and_empty_clusters -v`
Expected: FAIL with `ImportError: cannot import name 'suppressed_cluster_ids' from 'formatting'`.

- [ ] **Step 3: Implement `suppressed_cluster_ids`**

In `formatting.py`, insert this function immediately after `_item_score` (which ends at line 56), before `_collapse_by_cluster_within_section`:

```python
def suppressed_cluster_ids(tiered_items: list[dict]) -> set[int]:
    """Return the ids of non-representative cluster members.

    For each non-empty cluster_id with 2+ members, the highest-scored item
    is the representative; every other member's id is returned. The
    newsletter must show a cluster exactly once, so these ids are
    suppressed from every surface: featured stories, Other Headlines, and
    Everything Else. Scope is global: a cluster whose members span two
    sections still collapses to a single representative.

    Ties on _item_score are broken by lowest id so the result is
    deterministic. Items with an empty cluster_id are never suppressed -
    an empty cluster_id is triage's "no cluster known" signal.
    """
    by_cluster: dict[str, list[dict]] = {}
    for item in tiered_items:
        cid = item.get("cluster_id") or ""
        if not cid:
            continue
        by_cluster.setdefault(cid, []).append(item)

    suppressed: set[int] = set()
    for members in by_cluster.values():
        if len(members) < 2:
            continue
        rep = max(
            members,
            key=lambda it: (_item_score(it.get("scores", {})), -it["id"]),
        )
        for item in members:
            if item["id"] != rep["id"]:
                suppressed.add(item["id"])
    return suppressed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py::test_suppressed_cluster_ids_keeps_highest_scored_representative tests/test_formatting.py::test_suppressed_cluster_ids_ignores_singletons_and_empty_clusters -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: add suppressed_cluster_ids to pick one representative per cluster

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Make the collapse in `build_format_input` global

**Files:**
- Modify: `formatting.py` — `build_format_input` signature (line 82) and the collapse block (lines 105-109); delete `_collapse_by_cluster_within_section` (lines 59-79)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`:

```python
def test_build_format_input_collapses_cluster_across_sections():
    # Triage clustered the same story under two different sections. The
    # global collapse keeps only the highest-scored member, so the
    # cross-section duplicate never reaches the formatter.
    tiered_items = [
        _item(10, "US & Global", tier=1, ccov=4, prel=1, fit="good"),        # score 6
        _item(11, "Finance & Markets", tier=1, ccov=3, prel=0, fit="good"),  # score 4
    ]
    for it in tiered_items:
        it["cluster_id"] = "trump_iran_attack"
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "Reuters", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    surviving = [
        it["id"]
        for sec in payload["sections"].values()
        for bucket in sec.values()
        for it in bucket
    ]
    assert surviving == [10]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_formatting.py::test_build_format_input_collapses_cluster_across_sections -v`
Expected: FAIL. The current per-`(section, cluster_id)` collapse keeps one item per section, so both ids 10 and 11 survive and `surviving` has two entries.

- [ ] **Step 3: Implement the global collapse**

In `formatting.py`, change the `build_format_input` signature (line 82) from:

```python
def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict]) -> str:
```

to:

```python
def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict], suppressed_ids: set[int] | None = None) -> str:
```

Replace the collapse block (lines 105-109), which currently reads:

```python
    # Within-section cluster collapse: triage clusters the same underlying
    # story into multiple feed items; without this, a single story can occupy
    # several featured slots in one section. Keep the highest-scored per
    # (section, cluster_id). Items with empty cluster_id pass through.
    tiered_items = _collapse_by_cluster_within_section(tiered_items)
```

with:

```python
    # Global cluster collapse: triage clusters the same underlying story into
    # multiple feed items. Drop every non-representative cluster member so a
    # single story occupies at most one slot anywhere in the briefing. The
    # cluster_members map above was built from the uncollapsed list, so a
    # surviving story still links to every sibling's URL.
    if suppressed_ids is None:
        suppressed_ids = suppressed_cluster_ids(tiered_items)
    tiered_items = [it for it in tiered_items if it["id"] not in suppressed_ids]
```

Delete the now-unused function `_collapse_by_cluster_within_section` entirely (lines 59-79, including its docstring). It has no callers outside `build_format_input` and is not imported by any test.

- [ ] **Step 4: Run the new test and the existing collapse tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py -k "collapse or cluster" -v`
Expected: PASS. `test_build_format_input_collapses_cluster_across_sections` passes, and the existing `test_build_format_input_collapses_same_cluster_within_section` and `test_build_format_input_does_not_collapse_items_with_empty_cluster_id` still pass (a same-section cluster is a subset of the global behavior; empty cluster_ids are still never suppressed).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "refactor: collapse clusters globally in build_format_input

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Suppress collapsed siblings from Other Headlines and Everything Else

This is the load-bearing fix for the confirmed bug.

**Files:**
- Modify: `formatting.py` — `parse_and_render_sections` (signature line 627, body lines 628-630); `build_email_html` (signature line 885, call site lines 901-903)
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_formatting.py`:

```python
def test_suppressed_cluster_sibling_absent_from_rendered_html():
    # The real cuba_raul_castro_charges case: four articles, one cluster.
    # The representative is featured; the other three must not reappear in
    # Other Headlines or Everything Else.
    tiered_items = [
        _item(57, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(83, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(85, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(76, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
    ]
    for it in tiered_items:
        it["cluster_id"] = "cuba_raul_castro_charges"
    links_by_id = {
        57: {"title": "US charges Raul Castro over plane downing",
             "link": "https://bbc.com/57", "image": "", "source": "BBC",
             "snippet": "The indictment names the former leader."},
        83: {"title": "Cuba's Raul Castro indicted over 1996 downing",
             "link": "https://npr.org/83", "image": "", "source": "NPR World",
             "snippet": "A grand jury returned the indictment."},
        85: {"title": "US grand jury indicts Raul Castro",
             "link": "https://npr.org/85", "image": "", "source": "NPR World",
             "snippet": "The charges relate to the 1996 shootdown."},
        76: {"title": "News of indictment slow to reach Cubans",
             "link": "https://nyt.com/76", "image": "", "source": "NYT",
             "snippet": "Cubans waiting for a breakthrough."},
    }
    suppressed = suppressed_cluster_ids(tiered_items)  # {83, 85, 76}
    formatter_output = (
        "SUBJECT: 🌐 Castro charged\n\n"
        "## US & Global\n"
        "**US charges Raul Castro over plane downing [#57]**\n"
        "**The indictment.** A federal court has charged the former leader.\n\n"
        "**The backdrop.** Two civilian planes were shot down in 1996.\n\n"
        "**What is alleged.** Prosecutors tie the order to the chain of command.\n"
        "Source: BBC\n"
    )
    cluster_info = {"primary_source": "BBC", "also_in": ["NPR World", "NYT"]}
    html, _ = build_email_html(
        formatter_output, links_by_id,
        clusters_by_item_id={i: cluster_info for i in (57, 83, 85, 76)},
        tiered_items=tiered_items,
        suppressed_ids=suppressed,
    )
    assert "bbc.com/57" in html        # representative is featured
    assert "npr.org/83" not in html    # suppressed siblings never reappear
    assert "npr.org/85" not in html
    assert "nyt.com/76" not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_formatting.py::test_suppressed_cluster_sibling_absent_from_rendered_html -v`
Expected: FAIL with `TypeError: build_email_html() got an unexpected keyword argument 'suppressed_ids'`. (Once the parameter exists but is not yet threaded, the failure mode would instead be the `npr.org/83` assertion, because the sibling leaks into Other Headlines. Either failure confirms the bug is unfixed.)

- [ ] **Step 3: Thread `suppressed_ids` into the renderers**

In `formatting.py`, change the `parse_and_render_sections` signature (line 627) from:

```python
def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None):
```

to:

```python
def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None):
```

Then change its opening lines (628-630) from:

```python
    clusters_by_item_id = clusters_by_item_id or {}
    tiered_items = tiered_items or []
    used_ids = set()
```

to:

```python
    clusters_by_item_id = clusters_by_item_id or {}
    tiered_items = tiered_items or []
    # Seed used_ids with suppressed cluster members so the programmatic
    # Other Headlines and Everything Else blocks can never re-surface a
    # duplicate that the formatter input already collapsed away. Both
    # render_other_headlines_for_section and build_everything_else skip
    # ids found in used_ids.
    used_ids = set(suppressed_ids or ())
```

Next, change the `build_email_html` signature (line 885) from:

```python
def build_email_html(claude_response, links_by_id, clusters_by_item_id=None, tiered_items=None):
```

to:

```python
def build_email_html(claude_response, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None):
```

Then change its call to `parse_and_render_sections` (lines 901-903) from:

```python
    sections_html, used_ids = parse_and_render_sections(
        claude_response, links_by_id, clusters_by_item_id, tiered_items=tiered_items
    )
```

to:

```python
    sections_html, used_ids = parse_and_render_sections(
        claude_response, links_by_id, clusters_by_item_id,
        tiered_items=tiered_items, suppressed_ids=suppressed_ids,
    )
```

No change is needed to `build_everything_else`: it receives the `used_ids` returned by `parse_and_render_sections`, which now already contains the suppressed ids.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_formatting.py::test_suppressed_cluster_sibling_absent_from_rendered_html -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "fix: suppress collapsed cluster siblings from Other Headlines and Everything Else

A clustered story could be featured once and then reappear as a catch-all
bullet because the catch-all renderers worked off the uncollapsed item
list. Seed used_ids with the suppressed-cluster-member set so every
surface honors one suppression decision.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Wire the suppression set through `newsletter.py`

**Files:**
- Modify: `newsletter.py` — import (line 33), `main` locals (lines 55-56), the triage/format block (lines 61-66), the `build_email_html` call (line 83)
- Test: `tests/test_smoke.py` (existing; no new test, used as the verification)

- [ ] **Step 1: Update the import**

In `newsletter.py`, change line 33 from:

```python
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email
```

to:

```python
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email, suppressed_cluster_ids
```

- [ ] **Step 2: Initialise the suppressed set alongside the other triage locals**

In `newsletter.py`, change lines 55-56 from:

```python
    clusters_by_item_id = {}
    tiered_items = []
```

to:

```python
    clusters_by_item_id = {}
    tiered_items = []
    suppressed_ids: set[int] = set()
```

- [ ] **Step 3: Compute the suppressed set after triage and pass it to `build_format_input`**

In `newsletter.py`, change the triage and format block (lines 61-66) from:

```python
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        with _stage("format"):
            format_input = build_format_input(tiered_items, clusters, links_by_id)
            format_raw = call_formatter(format_input)
```

to:

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

- [ ] **Step 4: Pass the suppressed set to `build_email_html`**

In `newsletter.py`, change line 83 from:

```python
        html, subject = build_email_html(format_raw, links_by_id, clusters_by_item_id, tiered_items=tiered_items)
```

to:

```python
        html, subject = build_email_html(format_raw, links_by_id, clusters_by_item_id, tiered_items=tiered_items, suppressed_ids=suppressed_ids)
```

The legacy fallback path leaves `suppressed_ids` as the empty set, so a triage failure renders exactly as before.

- [ ] **Step 5: Run the smoke test to verify the pipeline still runs end to end**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS (2 passed). `test_main_runs_through_two_passes` exercises `main()` with a fake Anthropic client.

- [ ] **Step 6: Commit**

```bash
git add newsletter.py
git commit -m "feat: thread cluster suppression through the newsletter pipeline

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Guard against over-suppression and run the full suite

**Files:**
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the regression-guard test**

Append to `tests/test_formatting.py`:

```python
def test_distinct_clusters_are_never_suppressed():
    # Two items in the same section but different stories (distinct
    # cluster_ids, supplied by the _item helper as cl_1 and cl_2). Neither
    # is a duplicate, so neither is suppressed and both survive into the
    # formatter input. This guards against the global collapse over-reaching.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),
    ]
    assert suppressed_cluster_ids(tiered_items) == set()
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "TechCrunch", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    surviving = {
        it["id"]
        for sec in payload["sections"].values()
        for bucket in sec.values()
        for it in bucket
    }
    assert surviving == {1, 2}
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `python -m pytest tests/test_formatting.py::test_distinct_clusters_are_never_suppressed -v`
Expected: PASS. (This test describes behavior already correct after Tasks 1-2; it exists as a permanent guard, so it should pass immediately.)

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, with the same baseline count from "Before you start" plus the 5 tests added by this plan. No regressions.

- [ ] **Step 4: Commit**

```bash
git add tests/test_formatting.py
git commit -m "test: guard against over-suppression of distinct clusters

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Deferred: the F1 clustering-miss backstop

The earlier design discussion recommended a hybrid: this suppression fix (F2) plus a deterministic near-duplicate detector (F1) for the case where triage assigns two articles about one story *different* cluster_ids.

F1 is deliberately not in this plan. The May 21 evidence (`comparison/2026-05-21.json`) shows triage clustered all four Castro articles correctly and kept two genuinely different Cuba stories out of that cluster. Detection worked. Building a fuzzy headline-similarity merge now would be speculative (YAGNI), and the agent evaluation flagged its real downside: a wrong merge silently drops a real story.

If a clustering miss ever produces a visible duplicate, that incident gives a concrete example to calibrate against. The backstop would then be a function that runs after triage, computes headline token-set similarity plus shared-entity overlap with conservative thresholds, and contributes additional ids to the same `suppressed_ids` set this plan introduces. Because the suppression plumbing is now global, F1 would need no further rendering changes.

## Self-review

- **Spec coverage:** F2 (suppression gap) is fully covered by Tasks 1-5. F1 (detection gap) is explicitly deferred with rationale above.
- **Type consistency:** `suppressed_cluster_ids` returns `set[int]` everywhere. `suppressed_ids` is `set[int] | None` on `build_format_input`, `parse_and_render_sections`, and `build_email_html`, and a concrete `set[int]` in `newsletter.py`. `used_ids` stays a `set[int]`.
- **No placeholders:** every step has the exact code and exact command.
