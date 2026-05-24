# Phase 2 promotion: traction-aware tier scoring in production

**Date:** 2026-05-24
**Scope:** Promote the existing Phase 1.5 shadow scoring to production. Reddit and HN traction now influence the live newsletter's tier assignments. Shadow comparison logs and the Sunday digest are retired.

## Goal

Replace the Claude triage pass's tier verdict with the Phase 2 formula already running in shadow. Claude still scores each item on the three existing dimensions (cross_source_coverage, personal_relevance, section_fit), but the final tier (1, 2, 3, or 0) is now assigned by `compute_phase2_tier()`, which folds Reddit and HN traction into the math.

The intent: stop relying solely on Frank's ~30 RSS feeds as the denominator for "is this a big story." Use Reddit (r/news, r/worldnews, r/canada, r/toronto, r/technology, r/canadahousing) and HN as an independent crowd-size signal that can promote sleeper stories Frank's feed list under-covered, and avoid over-featuring bubble stories that happen to repeat across his feed mix.

## Out of scope

- No changes to the triage prompt or what Claude scores.
- No changes to cluster suppression, Today in the World logic, or section layouts.
- No new feeds, subreddits, or signals beyond what Phase 1.5 already collects.
- No changes to the `comparison/` directory's existing JSON files (kept as historical record).
- No edits to the format pass, build_format_input, or HTML rendering.

## Pipeline change

Today's order (after the redesign):

```
fetch → dedup → assign_ids → triage (Claude) → format (Claude) → build_html → send_email
                                                                                    ↓
                                                              shadow_score (Reddit+HN) → comparison log
                                                              [Sunday only] weekly digest email
```

New order:

```
fetch → dedup → assign_ids → triage (Claude) → attach_traction (Reddit+HN)
                                                       ↓
                                              apply_phase2_tier
                                                       ↓
                                              format (Claude) → build_html → send_email
```

The Reddit and HN fetch moves from post-send to pre-format. The format pass receives items whose `tier` field reflects Phase 2 scoring, so featured-slot selection and section ordering downstream all use the new tiers without further code changes.

Expected latency impact: roughly +30 seconds on the daily run (today ~1m30s, after ~2m). Acceptable because the run is GitHub-Actions-scheduled at 5am Toronto and not user-visible.

## Tier formula (unchanged from shadow)

Reused verbatim from [`comparison.py:31-57`](../comparison.py#L31-L57):

```
base = cross_source_coverage * 3
     + personal_relevance * 2
     + SECTION_FIT_SCORE[section_fit]     # good=1, weak=0, none=-1

reddit_bonus = 2 if reddit.score >= 1000 or reddit.subreddit_hits >= 2
             = 1 if reddit.score >= 200
             = 0 otherwise

hn_bonus = 1 if hn.points >= 200 else 0

total = base + reddit_bonus + hn_bonus

tier = 1 if total >= 6
     = 2 if total >= 3
     = 3 if total >= 1
     = 0 otherwise
```

## Fallback

`compute_phase2_tier` already reads traction via `.get(..., 0)`, so an item with missing or empty `reddit`/`hn` keys produces a defined tier (just without the bonuses). That covers the common case of "this URL isn't on Reddit or HN" — no special handling needed, the formula just doesn't get a bump.

The only real failure mode is `attach_traction` raising before any items get traction (network outage, Reddit blocking the IP, library error). Handle that at the orchestrator level: catch the exception, log a warning, and skip the Phase 2 tier recomputation entirely. The newsletter ships with Claude's original tier assignments. Behavior in that case matches today's Phase 1.

No per-item fallback. If an individual subreddit query fails inside `attach_traction`, the existing worker handles it (returns empty data for that source), the Phase 2 formula still runs for that item, and the item simply doesn't get the corresponding bonus.

## Code organization

- Move `compute_phase2_tier`, `attach_traction`, `_attach_one`, and `SECTION_FIT_SCORE` from [`comparison.py`](../comparison.py) into [`triage.py`](../triage.py). They are now production triage logic.
- Add a new function `apply_phase2_tier(items, links_by_id)` in `triage.py` that calls `attach_traction` followed by `compute_phase2_tier` per item, overwriting `item["tier"]`. If `attach_traction` raises, log and return the items list unchanged (Claude's tiers preserved). Caller in `newsletter.py` uses the returned list as input to `build_format_input`.
- Delete from [`comparison.py`](../comparison.py): `shadow_score`, `_delta_entry`, `build_comparison_log`, `write_comparison_log`, `summarize_week`, `build_weekly_digest_html`, `TRACTION_MAX_WORKERS` (if not still referenced from triage.py after the move; otherwise keep there), and the module's imports of `REDDIT_SUBREDDITS` and `traction` (move with the functions).
- After all helpers move out, [`comparison.py`](../comparison.py) becomes either empty (delete the file) or holds only constants no longer used (delete those too). Default: delete the file.
- Delete from [`newsletter.py`](../newsletter.py): the shadow-scoring block (lines 93-118) and the Sunday weekly-digest block (lines 120-134). Add a single call to `apply_phase2_tier(tiered_items, links_by_id)` after the triage call and before `build_format_input`. Update the import block: remove `comparison` imports, add the new triage exports.

## Test changes

Delete shadow-mode tests in `tests/` covering:
- `shadow_score`
- `build_comparison_log` (and its delta-entry behavior)
- `write_comparison_log`
- `summarize_week`
- `build_weekly_digest_html`
- the Sunday-only digest send branch in newsletter.main

Keep and adapt the existing unit tests for `compute_phase2_tier` and `attach_traction`. Update their imports to reflect the move into `triage.py`.

Add new tests for `apply_phase2_tier`:
1. All items have traction → every item's tier is recomputed via the Phase 2 formula.
2. One item has empty `reddit` and empty `hn` → that item still gets a Phase 2 tier, just with no traction bonus applied. (Verifies that "URL not on Reddit/HN" is not treated as a failure.)
3. `attach_traction` raises → `apply_phase2_tier` catches it, logs, returns items with Claude's tiers intact.
4. End-to-end pipeline test: mocked Reddit and HN responses, verify the format input received by the format pass has Phase 2 tiers, not Claude's.

## Failure modes and risks

| Risk | Mitigation |
|---|---|
| Reddit rate-limits during the run | Per-item fallback to Claude's tier. Email ships. Logged for review. |
| HN Algolia is down | Per-item fallback. HN missing alone doesn't trigger fallback unless Reddit also missing for that item. |
| One subreddit returns malformed JSON | `attach_traction` already isolates per-item failures via the worker pool. Item gets an empty reddit dict and falls back. |
| Phase 2 produces a visibly worse newsletter | Single `git revert` of the cutover commit restores Phase 1. No schema changes, no migrations. |
| Phase 2 demotes a Frank-relevant story because it didn't trend on Reddit/HN | Accepted risk. The whole point of the formula is to weigh traction. If this is a persistent pattern after a week, revisit the formula thresholds or the personal_relevance weight. |
| Latency creep makes the run miss the 5am window | Reddit and HN fetches are already known to take ~30s in shadow mode. The run still completes inside the GitHub Actions free-tier window. If something does regress, the per-stage timing logs (`_stage` context manager) will surface it. |

## What this does not change

- Triage prompt and what Claude scores. Frank can still tune those independently.
- Section assignment. Phase 2 only affects tier, not which section a story lands in.
- Today in the World selection logic (`promotion_to_today_in_the_world` flag stays on Claude's output).
- Cluster suppression. The set of suppressed sibling IDs is computed before tier reassignment and depends on cluster membership, not tier.
- Featured-slot caps, image-bearing prioritization, or Other Headlines / Everything Else routing. All downstream of tier and unaffected by how tier was computed.

## Rollback plan

If Phase 2 ships and the resulting newsletters look worse over 2-3 days:

1. `git revert` the cutover commit.
2. The shadow layer was deleted, so reverting restores it. The next day's run resumes writing comparison logs.
3. No data cleanup needed. The `comparison/` directory was never modified by the cutover.

The cutover should land as a single coherent commit (or a small commit series under a single PR if split for review). Reverting one or two commits is the recovery path.

## Roadmap impact

After this ships, the roadmap entry for Phase 2 in [`docs/2026-05-15-newsletter-redesign-spec.md`](2026-05-15-newsletter-redesign-spec.md) is satisfied. Phase 3 (Google Trends, reader feedback, deeper relevance modeling) stays in the backlog with no new dependency on Phase 2 internals.
