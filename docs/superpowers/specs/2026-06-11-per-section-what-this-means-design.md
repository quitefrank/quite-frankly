# Per-section "What this means" — Design

**Date:** 2026-06-11
**Status:** Approved, ready for implementation plan

## Problem

The "What this means for you" callout is generated per featured Layout A story
as a single sentence. One sentence per article gives little depth, and tying it
to individual featured stories misses relevance that lives in the Other
Headlines of a section. Frank wants a per-section block of 2-3 sentences,
labelled "What this means" (dropping "for you"), that surfaces the relevant
takeaways for a section wherever they sit.

## Goal

Replace the per-article callout with one per-section "What this means" block:

- **Trigger is per-item, surfaced per-section.** If at least one article in the
  section — featured *or* Other Headlines — clearly hits one of Frank's active
  concerns, the block appears. Zero hits in the section means no block.
- **Covers every relevant item.** One hit: speak to that item. Two or more hits:
  cover each relevant piece in the 2-3 sentences, regardless of whether it was
  featured or an Other Headline.
- **High per-item bar stays.** An item only "counts" when it clearly hits a
  listed concern. A weak takeaway is worse than none.
- **Placement:** bottom of the section card, after featured stories and Other
  Headlines.
- **Length:** 2-3 sentences.
- **Label:** "What this means:" (no "for you").
- **Today in the World:** eligible under the same rule (block only if ≥1 item
  there hits a concern).

## Approach

Generate the block inside the existing FORMAT call (`call_formatter`). That call
already receives every section's full item set across all tiers — tier_1
(featured), tier_2, and tier_3 (which become Other Headlines) — each with title,
snippet, and source (see `build_format_input`, formatting.py:283-291). The model
already sees the Other Headlines material; it simply does not write it out. So it
can weigh featured + OH by relevance with no pipeline restructuring and no extra
API call.

Rejected alternative: a dedicated synthesis pass after assembly. It would see the
final polished OH prose but costs an extra API call per edition plus plumbing to
feed rendered sections back in. The relevance judgment works fine from raw
title+snippet, so the extra call is not worth it.

## Feature toggle (revert safety)

A flag keeps both behaviors fully alive so the new version can be trialed across
several editions and reverted with a one-line flip, losing none of the work
layered on top in the meantime.

`config.py`, alongside `TEST_MODE`:

```python
# "section" = new per-section block; "article" = legacy one-line-per-story.
# Flip the default (or set CALLOUT_MODE=article in the workflow env) to revert.
CALLOUT_MODE = os.environ.get("CALLOUT_MODE", "section")
```

- Default ships as `"section"` (new behavior live immediately).
- `"article"` reproduces today's output exactly — nothing is deleted.

The flag gates three things:

1. **Prompt** (`prompts.py`): keep today's guidance as
   `CALLOUT_GUIDANCE_PER_ARTICLE`; add `CALLOUT_GUIDANCE_PER_SECTION`. A
   `_build_format_prompt(guidance)` helper produces
   `FORMAT_SYSTEM_PROMPT_PER_ARTICLE` and `FORMAT_SYSTEM_PROMPT_PER_SECTION`.
   `call_formatter` selects by `CALLOUT_MODE`.
2. **Parse/render** (`formatting.py`, `parse_and_render_sections`): `"article"`
   keeps the per-story attach + render-under-story path untouched; `"section"`
   captures one section-level callout and renders it at the bottom of the card.
3. **Today in the World**: the bottom-of-card block appears only in `"section"`
   mode.

## Components

### 1. Prompt rewrite (`prompts.py`)

- Keep current `CALLOUT_GUIDANCE` content as `CALLOUT_GUIDANCE_PER_ARTICLE`.
- Add `CALLOUT_GUIDANCE_PER_SECTION` with per-section instructions:
  - After writing a section's featured stories, scan every item in that section
    across all tiers (featured + the lower-tier items that become Other
    Headlines).
  - Identify items that clearly hit one of Frank's active concerns; per-item bar
    stays high.
  - Zero hits → emit nothing for the section.
  - One or more hits → emit exactly one line at the end of the section:
    `What this means: <2-3 sentences>`. One hit speaks to that item; multiple
    hits cover each relevant piece (featured or OH), naming the entity/fact.
  - All existing voice rules carry over: no em dashes, banned phrases, real
    numbers with units, plain second person, name the specific project/asset.
  - Reframe the examples from single-item to section-level (a one-hit example and
    a two-hit example).
  - Same rule applies to Today in the World.
- `_build_format_prompt(guidance)` returns the full FORMAT system prompt with the
  given guidance interpolated. Produce both
  `FORMAT_SYSTEM_PROMPT_PER_ARTICLE` and `FORMAT_SYSTEM_PROMPT_PER_SECTION`.

### 2. Formatter call (`formatting.py`, `call_formatter`)

Select the system prompt by `CALLOUT_MODE` (`"article"` →
`FORMAT_SYSTEM_PROMPT_PER_ARTICLE`, else `FORMAT_SYSTEM_PROMPT_PER_SECTION`).

### 3. Parse + render (`formatting.py`, `parse_and_render_sections`)

- Add a helper `_extract_section_callout(lines)` that pulls a
  `^what this means(?: for you)?:` line out of a section's body lines and returns
  `(callout, remaining_lines)`. The regex tolerates the legacy "for you" form.
- **`"section"` mode:**
  - Layout A sections: capture one section-level callout (do not attach to a
    story); after `stories_html += oh_html`, append one callout `div` at the
    bottom of the card body, label `What this means:`, holding the 2-3 sentences.
    Reuse the existing callout styling (callout_bg box, accent left border).
  - Today in the World: extract the callout from the section lines before
    `_render_today_in_the_world`, then append the same bottom-of-card block to
    that card.
  - Remove the per-story callout render under each story.
- **`"article"` mode:** unchanged from today — `What this means for you:` attaches
  to the current/last story and renders under it.

### 4. Tests (`tests/test_formatting.py`)

- Update the two existing callout tests (≈ lines 1428, 1473).
- Add coverage for `"section"` mode: one block per section, bottom-of-card
  placement, `What this means:` label without "for you", a two-hit synthesis
  case, and a zero-hit section rendering no block.
- Add a test that `"article"` mode still renders the legacy per-story callout.

## Out of scope

- `LEGACY_FORMAT_SYSTEM_PROMPT` (prompts.py:186) keeps its per-story
  "What this means for you" line. It is the deprecated single-pass fallback; leave
  it untouched.
- `max_tokens=4000` on `call_formatter` is unchanged. Consolidating per-story
  lines into one per-section block does not increase total output materially.
