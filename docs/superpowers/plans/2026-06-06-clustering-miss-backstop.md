# Clustering-Miss Dedup Backstop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop two articles about the same story (different URLs, differently-worded headlines, sometimes different sections) from both appearing in the newsletter, by (1) giving triage the snippet so it can cluster on content, and (2) adding a deterministic content-similarity backstop that recovers clustering misses.

**Architecture:** Today there are exactly two dedup signals: exact-URL match (`pipeline.deduplicate` / within-batch) and the LLM's `cluster_id`. The URL match can't catch cross-publisher reposts, and the LLM clusterer is fed *title only* — never the snippet, the URL, or the embedded video. So a story covered by two outlets slips through. Fix in two moves: feed the snippet into the triage message and nudge the prompt to cluster on shared protagonists/events; then add `near_duplicate_ids`, a deterministic pass that re-detects same-story pairs from content and contributes their ids to the **existing** `suppressed_ids` set, requiring no rendering changes.

**Tech Stack:** Python 3.11, pytest. No new dependencies (stdlib `re` only).

---

## Background

The 2026-05-22 plan fixed the *suppression* gap (F2): a clustered story leaking into Other Headlines / Everything Else. It explicitly **deferred** the *detection* backstop (F1) with this note:

> "If a clustering miss ever produces a visible duplicate, that incident gives a concrete example to calibrate against. The backstop would then be a function that runs after triage, computes headline token-set similarity plus shared-entity overlap with conservative thresholds, and contributes additional ids to the same `suppressed_ids` set this plan introduces. Because the suppression plumbing is now global, F1 would need no further rendering changes."

The 2026-06-06 design edition is that incident: two articles about Bryce Ratner and Keith Lee building a no-code fitness app (both embedding the same YouTube video) appeared as separate stories — one in Design & Product, one as a standalone "no-code fitness app success" item. Triage gave them different `cluster_id`s because it only ever saw their (differently-worded) titles. This plan builds the deferred F1 backstop, now calibrated against a real case.

## File Structure

- `prompts.py` — add a clustering instruction to `TRIAGE_SYSTEM_PROMPT` telling the model to use the snippet and cluster on shared people/company/product/event.
- `triage.py` — `build_triage_user_message`: append a truncated snippet to each headline line.
- `pipeline.py` — add three pure text-dedup primitives (`youtube_id`, `canonical_key`, `normalize_text`) next to the existing dedup code.
- `formatting.py` — add `near_duplicate_ids` next to `suppressed_cluster_ids`; it reuses `_item_score` and imports the three primitives from `pipeline`.
- `newsletter.py` — union `near_duplicate_ids(...)` into the `suppressed_ids` computed after triage.
- `tests/test_triage.py`, `tests/test_pipeline.py`, `tests/test_formatting.py` — unit tests per task.

No new files. No new dependencies. No rendering changes (the backstop feeds the `suppressed_ids` plumbing the 2026-05-22 plan already threaded through every surface).

## Before you start

Establish a green baseline so any pre-existing failure is not mistaken for a regression.

Run: `python -m pytest tests/ -q`
Record the result. If a test already fails on `main`, note it and treat it as out of scope.

---

### Task 1: Feed the snippet into the triage message

**Files:**
- Modify: `triage.py` — `build_triage_user_message` (lines 168-172)
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_triage.py`:

```python
from triage import build_triage_user_message


def test_triage_message_includes_snippet():
    items = [{
        "id": 7, "title": "Codex goals explained", "source": "IAI",
        "section_label": "Design & Product",
        "snippet": "Bryce Ratner shows how Keith Lee built a no-code fitness app.",
    }]
    msg = build_triage_user_message(items)
    assert "[#7]" in msg
    assert "Bryce Ratner" in msg          # snippet now reaches the model
    assert "no-code fitness app" in msg


def test_triage_message_omits_separator_when_snippet_empty():
    items = [{
        "id": 8, "title": "Just a title", "source": "CBC",
        "section_label": "Canada & Toronto", "snippet": "",
    }]
    msg = build_triage_user_message(items)
    assert "[#8]" in msg
    assert " — " not in msg                # no dangling separator
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_triage.py::test_triage_message_includes_snippet tests/test_triage.py::test_triage_message_omits_separator_when_snippet_empty -v`
Expected: `test_triage_message_includes_snippet` FAILS (`assert "Bryce Ratner" in msg` — the snippet is not in the message today).

- [ ] **Step 3: Implement**

In `triage.py`, replace `build_triage_user_message` (lines 168-172):

```python
def build_triage_user_message(items: list[dict]) -> str:
    lines = []
    for i in items:
        lines.append(f"[#{i['id']}] [{i.get('section_label', '?')}] {i['title']} | Source: {i['source']}")
    return "Here are today's headlines. Call emit_triage with one entry per item:\n\n" + "\n".join(lines)
```

with:

```python
def build_triage_user_message(items: list[dict]) -> str:
    lines = []
    for i in items:
        snippet = (i.get("snippet") or "").strip()
        # The snippet is the only place differently-worded headlines about
        # the same story share vocabulary (the same people, company, event),
        # so it's what lets triage cluster cross-publisher duplicates. Cap at
        # 200 chars to keep the prompt tractable across ~120 items.
        snippet_part = f" — {snippet[:200]}" if snippet else ""
        lines.append(
            f"[#{i['id']}] [{i.get('section_label', '?')}] {i['title']} "
            f"| Source: {i['source']}{snippet_part}"
        )
    return "Here are today's headlines. Call emit_triage with one entry per item:\n\n" + "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_triage.py -k "triage_message" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: pass snippet into the triage message so clustering sees content

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Tell the prompt to cluster on shared protagonists/events

**Files:**
- Modify: `prompts.py` — `TRIAGE_SYSTEM_PROMPT` (the clustering instruction near line 69 / the `cluster_id` bullet near line 78)
- Test: none (prompt text; verified end-to-end by the smoke test and the Task 5 calibration)

- [ ] **Step 1: Add the clustering guidance**

In `prompts.py`, inside `TRIAGE_SYSTEM_PROMPT`, immediately after the line:

```
Your job: score each item, group items into clusters when multiple sources cover the same story, and assign each item to a section.
```

insert:

```
Each headline may be followed by " — " and a snippet. Use BOTH the title and the snippet to detect duplicates. Two items are the same story, and MUST get the same cluster_id, when they share the same primary people, company, product, or event, even if the headlines are worded differently or sit in different sections. When you are unsure whether two items are the same story, prefer giving them the same cluster_id.
```

- [ ] **Step 2: Verify the prompt still builds and the smoke test passes**

Run: `python -m pytest tests/test_smoke.py tests/test_prompts.py -q`
Expected: PASS (no import-time errors from `prompts.py`; smoke test still runs `main()` end to end).

- [ ] **Step 3: Commit**

```bash
git add prompts.py
git commit -m "feat: instruct triage to cluster on shared people/company/event using snippets

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add the text-dedup primitives

**Files:**
- Modify: `pipeline.py` — add `youtube_id`, `canonical_key`, `normalize_text` after `monday_dedup_bypass` (end of file)
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
from pipeline import youtube_id, canonical_key, normalize_text


def test_youtube_id_extracts_from_watch_and_short_forms():
    assert youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("see https://youtu.be/dQw4w9WgXcQ now") == "dQw4w9WgXcQ"
    assert youtube_id("https://example.com/article") == ""
    assert youtube_id("") == ""


def test_canonical_key_keys_off_shared_youtube_video():
    a = {"link": "https://siteA.com/post", "snippet": "watch https://youtu.be/dQw4w9WgXcQ"}
    b = {"link": "https://youtube.com/watch?v=dQw4w9WgXcQ", "snippet": ""}
    c = {"link": "https://siteC.com/other", "snippet": "no video here"}
    assert canonical_key(a) == canonical_key(b) == "yt:dQw4w9WgXcQ"
    assert canonical_key(c) == ""


def test_normalize_text_drops_stopwords_and_short_tokens():
    tokens = normalize_text("How Keith Lee built a no-code Fitness App")
    assert "keith" in tokens and "fitness" in tokens and "built" in tokens
    assert "how" not in tokens and "a" not in tokens   # stopword + 1-char
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -k "youtube or canonical or normalize_text" -v`
Expected: FAIL with `ImportError: cannot import name 'youtube_id' from 'pipeline'`.

- [ ] **Step 3: Implement the primitives**

In `pipeline.py`, append at the end of the file:

```python
# ---- Content-similarity primitives for the clustering-miss backstop ----

_YOUTUBE_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?v=|embed/|shorts/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})'
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "are", "its", "it", "this", "that", "as", "at", "by", "from", "how", "why",
    "what", "new", "up", "out", "his", "her", "she", "he", "they", "you", "your",
    "i", "we", "s", "was", "were", "has", "have", "will",
})


def youtube_id(text: str) -> str:
    """Return an 11-char YouTube video id found in text, or '' if none."""
    m = _YOUTUBE_RE.search(text or "")
    return m.group(1) if m else ""


def canonical_key(item: dict) -> str:
    """A high-confidence same-story key, or '' if none can be derived.

    Keys off a shared YouTube video id found in the item's link or snippet.
    Two items with the same non-empty key are the same story with near
    certainty. (When article-body fetching lands, og:url / rel=canonical and
    body-embedded video ids can feed in here too.)
    """
    vid = youtube_id(item.get("link", "")) or youtube_id(item.get("snippet", ""))
    return f"yt:{vid}" if vid else ""


def normalize_text(text: str) -> frozenset:
    """Lowercased significant-token set for fuzzy story matching.

    Drops stopwords and tokens of 2 chars or fewer so similarity reflects the
    proper nouns and content words that identify a story (people, companies,
    products), not boilerplate.
    """
    return frozenset(
        t for t in _TOKEN_RE.findall((text or "").lower())
        if t not in _STOPWORDS and len(t) > 2
    )
```

(`re` is already imported at the top of `pipeline.py`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -k "youtube or canonical or normalize_text" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "feat: add youtube_id, canonical_key, normalize_text dedup primitives

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Add the `near_duplicate_ids` backstop

**Files:**
- Modify: `formatting.py` — add `near_duplicate_ids` immediately after `suppressed_cluster_ids` (ends line 147); add `from pipeline import canonical_key, normalize_text` to the imports
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Write the failing tests**

Add `near_duplicate_ids` to the `from formatting import (...)` block at the top of `tests/test_formatting.py`. Then append:

```python
def test_near_duplicate_ids_catches_same_story_different_clusters():
    # The 2026-06-06 incident: two articles, different sources, different
    # (LLM-assigned) cluster_ids, different sections, headlines worded
    # differently — but both about Ratner + Lee building a no-code fitness
    # app. The snippet vocabulary overlaps enough to merge them.
    a = _item(7, "Design & Product", tier=1, ccov=1, prel=2, fit="good")   # score 4
    b = _item(8, "Tech & AI", tier=2, ccov=1, prel=1, fit="good")          # score 3
    links_by_id = {
        7: {"title": "IAI Codex goals explained for product teams",
            "link": "https://iai.com/codex",
            "snippet": "Bryce Ratner walks through how Keith Lee built a no-code fitness app."},
        8: {"title": "How she built a fitness app with no code",
            "link": "https://maker.com/keith-lee",
            "snippet": "Keith Lee built her no-code fitness app, profiled by Bryce Ratner."},
    }
    # Higher-scored item (7) survives; 8 is suppressed.
    assert near_duplicate_ids([a, b], links_by_id) == {8}


def test_near_duplicate_ids_catches_shared_video_even_with_thin_text():
    # Canonical-key path: same embedded YouTube id, almost no shared words.
    a = _item(1, "Design & Product", tier=1, ccov=2, prel=1, fit="good")   # score 4
    b = _item(2, "Tech & AI", tier=2, ccov=1, prel=0, fit="weak")          # score 1
    links_by_id = {
        1: {"title": "Profile of a builder", "link": "https://a.com/x",
            "snippet": "full story at https://youtu.be/dQw4w9WgXcQ"},
        2: {"title": "Totally different framing", "link": "https://b.com/y",
            "snippet": "watch https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    }
    assert near_duplicate_ids([a, b], links_by_id) == {2}


def test_near_duplicate_ids_leaves_distinct_stories_alone():
    a = _item(1, "Tech & AI", tier=1, ccov=3, prel=2, fit="good")
    b = _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good")
    links_by_id = {
        1: {"title": "Anthropic ships prompt caching", "link": "https://x.com/1",
            "snippet": "Anthropic cut token costs on repeated context."},
        2: {"title": "Bank of Canada holds rates", "link": "https://y.com/2",
            "snippet": "The central bank kept its policy rate unchanged."},
    }
    assert near_duplicate_ids([a, b], links_by_id) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_formatting.py -k "near_duplicate" -v`
Expected: FAIL with `ImportError: cannot import name 'near_duplicate_ids' from 'formatting'`.

- [ ] **Step 3: Implement**

In `formatting.py`, add to the imports near the top (alongside the existing `from pipeline import ...` if present, otherwise as a new line):

```python
from pipeline import canonical_key, normalize_text
```

Then insert this function immediately after `suppressed_cluster_ids` (which ends at line 147):

```python
def near_duplicate_ids(
    tiered_items: list[dict],
    links_by_id: dict[int, dict],
    overlap_threshold: float = 0.5,   # calibrated against the 2026-06-06 incident (Task 6)
    min_shared_tokens: int = 3,
) -> set[int]:
    """Deterministic backstop for clustering misses (the deferred F1 detector).

    suppressed_cluster_ids keys off cluster_id, so it can't catch two articles
    about one story that triage gave DIFFERENT cluster_ids (different URLs,
    differently-worded headlines, sometimes different sections). This pass
    re-detects them from content and returns the ids to hide, contributing to
    the same suppressed_ids set every surface already honors.

    Two items are near-duplicates when EITHER:
      - they share a non-empty canonical key (e.g. the same embedded YouTube
        video), or
      - their combined title+snippet token sets share at least
        min_shared_tokens significant tokens AND their overlap coefficient
        (shared / size of the smaller set) is >= overlap_threshold.

    Overlap coefficient, not Jaccard: a featured story carries a long headline
    plus snippet while its duplicate may be a short headline, so the union is
    lopsided and Jaccard understates a real match.

    Within each near-duplicate group the highest-scored item survives (ties to
    lowest id, matching suppressed_cluster_ids); the rest are returned.
    Conservative by design: a wrong merge silently drops a real story, so the
    thresholds favour precision over recall.
    """
    ids = [it["id"] for it in tiered_items]
    text: dict[int, frozenset] = {}
    keys: dict[int, str] = {}
    for it in tiered_items:
        src = links_by_id.get(it["id"], {})
        text[it["id"]] = normalize_text(f"{src.get('title', '')} {src.get('snippet', '')}")
        keys[it["id"]] = canonical_key(src)

    parent = {i: i for i in ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    n = len(ids)
    for a_idx in range(n):
        for b_idx in range(a_idx + 1, n):
            a, b = ids[a_idx], ids[b_idx]
            ka, kb = keys[a], keys[b]
            if ka and ka == kb:
                union(a, b)
                continue
            shared = text[a] & text[b]
            if len(shared) < min_shared_tokens:
                continue
            smaller = min(len(text[a]), len(text[b]))
            if smaller and len(shared) / smaller >= overlap_threshold:
                union(a, b)

    groups: dict[int, list[dict]] = {}
    for it in tiered_items:
        groups.setdefault(find(it["id"]), []).append(it)

    suppressed: set[int] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        rep = max(
            members,
            key=lambda it: (_item_score(it.get("scores", {})), -it["id"]),
        )
        for it in members:
            if it["id"] != rep["id"]:
                suppressed.add(it["id"])
    return suppressed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_formatting.py -k "near_duplicate" -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "feat: add near_duplicate_ids backstop for clustering misses

Recovers two articles about one story that triage gave different cluster_ids,
via shared canonical key (e.g. same YouTube video) or title+snippet
similarity. Contributes to the existing suppressed_ids plumbing.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Wire the backstop into the pipeline

**Files:**
- Modify: `newsletter.py` — import (line 25) and the `suppressed_ids` computation (line 62)
- Test: `tests/test_smoke.py` (existing; used as verification)

- [ ] **Step 1: Update the import**

In `newsletter.py`, change line 25 from:

```python
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email, suppressed_cluster_ids, write_subject_blurbs
```

to:

```python
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email, suppressed_cluster_ids, near_duplicate_ids, write_subject_blurbs
```

- [ ] **Step 2: Union the backstop into the suppressed set**

In `newsletter.py`, change line 62 from:

```python
        suppressed_ids = suppressed_cluster_ids(tiered_items)
```

to:

```python
        suppressed_ids = (
            suppressed_cluster_ids(tiered_items)
            | near_duplicate_ids(tiered_items, links_by_id)
        )
```

The representative tiebreak is identical in both functions (`(_item_score, -id)`), so they never disagree on which item survives; the union only ever adds ids the LLM clusterer missed.

- [ ] **Step 3: Run the smoke test**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS (the pipeline still runs end to end with the fake Anthropic client).

- [ ] **Step 4: Commit**

```bash
git add newsletter.py
git commit -m "feat: union near_duplicate_ids into pipeline suppression

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Calibrate against the real incident and run the full suite — DONE 2026-06-06

This is the verification gate. The thresholds in Task 4 are conservative defaults; confirm they actually catch the 2026-06-06 case and don't over-merge.

**Resolution.** The two items were the same Lenny's "How I AI" episode (YouTube `EJKwI4m0fZg`, confirmed embedded in both pages), surfaced as two RSS entries:
- `lennysnewsletter.com/p/how-i-ai-codex-goals-explained-and` — "🎙️ How I AI: Codex Goals explained & Claude Opus 4.8 review & Building an iPhone app with zero technical skills" (Design & Product, featured)
- `lennysnewsletter.com/p/building-an-iphone-app-with-zero` — "Building an iPhone app with zero technical skills | Bryce Rattner Keithley" (In Design list)

The titles share "building an iphone app with zero technical skills". Overlap coefficient is 0.667 title-only, but the worst realistic shape (segment carries its fitness-app description, episode carries title only) is exactly 0.5, so the 0.6 default would miss it. Lowered `overlap_threshold` to **0.5**; `min_shared_tokens=3` holds precision. Test `test_near_duplicate_ids_catches_2026_06_06_lennys_incident` added and passing; full suite 138 passed. The durable fix is the canonical-key path (both share `EJKwI4m0fZg`) once article-body fetch lands — see Deferred.

**Files:**
- Test: `tests/test_formatting.py`

- [ ] **Step 1: Slot the real titles/snippets into a calibration test**

Obtain the two real items from the 2026-06-06 edition (title, link, snippet for each). Append a test to `tests/test_formatting.py` using the **real** strings:

```python
def test_near_duplicate_ids_catches_2026_06_06_ratner_lee_incident():
    a = _item(<real_id_a>, "Design & Product", tier=1, ccov=1, prel=2, fit="good")
    b = _item(<real_id_b>, "Tech & AI", tier=2, ccov=1, prel=1, fit="good")
    links_by_id = {
        <real_id_a>: {"title": "<real title A>", "link": "<real url A>",
                      "snippet": "<real snippet A>"},
        <real_id_b>: {"title": "<real title B>", "link": "<real url B>",
                      "snippet": "<real snippet B>"},
    }
    suppressed = near_duplicate_ids([a, b], links_by_id)
    assert len(suppressed) == 1   # exactly one of the two survives
```

- [ ] **Step 2: Run it; tune only if it fails**

Run: `python -m pytest tests/test_formatting.py::test_near_duplicate_ids_catches_2026_06_06_ratner_lee_incident -v`
Expected: PASS. If it FAILS (the real snippets share fewer tokens than the reconstruction), lower `overlap_threshold` toward 0.5 or `min_shared_tokens` to 2 in `near_duplicate_ids` — but re-run `test_near_duplicate_ids_leaves_distinct_stories_alone` after any change to confirm distinct stories are still left alone. Do not loosen past the point where that guard fails.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS, baseline count from "Before you start" plus the tests added here. No regressions.

- [ ] **Step 4: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "test: calibrate near_duplicate_ids against the 2026-06-06 incident

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Deferred / future work

- **Article-body fetch for the video signal.** The strongest dedup signal (a shared embedded video) lives in the article HTML body, which the pipeline never fetches (only 16KB of `<head>` for og:image). When body fetching is added, `canonical_key` should read body-embedded YouTube ids, `og:url`, and `<link rel="canonical">` — the function is already structured for it.
- **Sibling cross-linking for backstop merges.** `near_duplicate_ids` hides the duplicate but does not union `cluster_id`, so the surviving story won't list the dropped one in its "also in" sources. Hidden-but-not-cross-linked is strictly better than a visible duplicate; unioning `cluster_id` is a future polish.

## Companion plan needed: tiering promote/demote drift (separate subsystem)

Out of scope here, but surfaced by the same RCA and worth its own plan:
1. `apply_phase2_tier` (`triage.py:251-252`) overwrites every tier with the traction formula, **discarding the LLM's cross-cluster same-entity demotion** the prompt promises (`prompts.py:91`). The only entity-level tier dedup never ships.
2. `cross_source_coverage` is weighted ×3 in `compute_phase2_tier` but is a self-reported LLM guess; it should be derived from actual cluster size post-clustering.
3. `promotion_to_today_in_the_world` is collected (`triage.py:141`) but never read — the Today-in-the-World pickoff is a separate deterministic top-N. Dead field.
4. `cluster_size` is gated on by `monday_dedup_bypass` (`pipeline.py:295`) and the prompt's promotion rule, but the triage schema never returns it, so it's always 0.

## Self-review

- **Spec coverage:** Frank's action-plan step 1 (feed the deduper the missing signals) = Tasks 1-2. Step 2 (deterministic dedup pass) = Tasks 3-5. Regression test = Task 6. Tiering review = Companion-plan section. All covered.
- **Type consistency:** `youtube_id`/`canonical_key` return `str`; `normalize_text` returns `frozenset`; `near_duplicate_ids` returns `set[int]`, unioned with `suppressed_cluster_ids`'s `set[int]`. Representative tiebreak `(_item_score, -id)` matches `suppressed_cluster_ids` exactly.
- **No placeholders:** every code step shows complete code, except Task 6 which intentionally requires the real article strings (the calibration input) and marks them `<real_*>`.
