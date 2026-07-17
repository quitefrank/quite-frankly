# Park the Tech & AI Section

**Date:** 2026-07-17
**Status:** Approved, ready for implementation planning
**Ships independently of:** the design weekly-archive spec (`2026-07-17-design-weekly-archive-design.md`)

## Goal

Remove the Tech & AI section from every edition of the newsletter. Frank has another
newsletter that covers tech and AI more comprehensively. Park the section so it produces
no items and renders nowhere, while keeping all its wiring in the codebase so re-enabling
it later is a single boolean flip.

Non-goal: deleting the tech feeds, section mappings, favicons, or prompt scaffolding.
Everything stays in the tree, inert.

## Background

Tech & AI has no dedicated machinery. It is a generic section distinguished only by:

- Four feeds in `FEEDS_WEEKDAY` (`config.py:64-68`): TechCrunch, Hacker News, Simon
  Willison, Stratechery.
- Four `SECTION_MAP` entries (`config.py:125-128`).
- A `SECTION_EMOJIS` row (`config.py:175`) and `SOURCE_FAVICONS` rows (`config.py:256`,
  `config.py:310`).
- Its name in `TRIAGE_SECTIONS` (`prompts.py:118`), `SECTION_ORDER` (`formatting.py:84`),
  and several format-prompt strings (`prompts.py:186, 202, 266, 281`).

Two facts make parking clean:

1. `deduplicate` → triage → render is driven entirely by which items exist. If no feed
   produces a Tech & AI item, no such item flows through the pipeline.
2. The format prompt already instructs the model to "Skip a section entirely if it has no
   items" (`prompts.py:281`). An empty Tech & AI section therefore never renders, even
   with its name still present in prompt text.

The HN snippet-stripping special-case (`pipeline.py:246-247`) only fires for
`source == "Hacker News"` and is inert once that feed stops being fetched. It stays as-is.

### The one subtlety: the triage menu

The comment at `prompts.py:112-114` notes that on weekdays, dropping Design & Product from
the triage menu lets design-flavored items "fall back to their feed-origin section (Tech &
AI)." This is descriptive prose, not a hard-coded default — nothing routes to a literal
"Tech & AI" string as a fallback. But it means Tech & AI currently acts as an informal
catch-all in the triage enum. If we leave "Tech & AI" in `TRIAGE_SECTIONS` after removing
its feeds, triage could route a stray non-tech item (e.g. a Simon-Willison-adjacent story
arriving via another feed) into a section with no feeds behind it, producing exactly the
thin one-item section the design gate was built to prevent. So parking must also drop
"Tech & AI" from the triage menu.

## Design

Add one flag to `config.py`:

```python
# --- Parked sections ---
# Tech & AI parked 2026-07-17: Frank gets better tech/AI coverage from another
# newsletter. Everything below (feeds, SECTION_MAP rows, favicons, emoji, prompt
# scaffolding) is left in place, inert. To restore the section: flip this to True.
TECH_AI_ENABLED = False
```

Then gate exactly two things off it:

### 1. Feeds — stop fetching tech sources

`FEEDS_WEEKDAY` (`config.py:46-102`) is the fetched set for Monday-catchup and weekday-daily
modes. The four Tech & AI feed dicts (`config.py:64-68`) must not be fetched when the flag
is False.

Keep the four dicts defined in the file (so re-enabling is trivial), but build the exported
`FEEDS_WEEKDAY` conditionally. Concretely: define the tech feeds as a named local list
(`_TECH_AI_FEEDS`), then compose `FEEDS_WEEKDAY` including them only when `TECH_AI_ENABLED`.

The weekend feed sets (`FEEDS_SATURDAY_STRATEGIC`, `FEEDS_SUNDAY_VISUAL`) never contained
tech feeds and are untouched.

### 2. Triage menu — remove the catch-all

`TRIAGE_SECTIONS` (`prompts.py:115-123`) and `triage_sections()` (`prompts.py:126-129`) must
exclude "Tech & AI" when the flag is False, the same shape as the existing `design_allowed`
filter. `triage_sections()` becomes the single place both filters compose:

```python
def triage_sections(design_allowed: bool = True) -> list[str]:
    sections = list(TRIAGE_SECTIONS)
    if not TECH_AI_ENABLED:
        sections = [s for s in sections if s != "Tech & AI"]
    if not design_allowed:
        sections = [s for s in sections if s != "Design & Product"]
    return sections
```

Import `TECH_AI_ENABLED` into `prompts.py` from `config`.

### What is deliberately NOT gated

- `SECTION_MAP`, `SECTION_EMOJIS`, `SOURCE_FAVICONS` rows: inert with no feeds; left in place.
- `SECTION_ORDER` in `formatting.py`: ordering a section that never has items is harmless.
- Format-prompt strings naming Tech & AI (`prompts.py:186, 202, 266, 281`): the model is
  already told to skip empty sections, so these are inert residue. Leaving them keeps the
  re-enable a one-line flip with no prompt edits.
- HN snippet-strip in `pipeline.py`: inert without the HN feed.

## Testing

- `get_feeds_for_mode(WEEKDAY_DAILY)` and `(MONDAY_CATCHUP)` return no feed whose source is
  in the four tech sources, when `TECH_AI_ENABLED` is False.
- `triage_sections(design_allowed=True)` excludes "Tech & AI" when the flag is False.
- `triage_sections(design_allowed=False)` excludes both "Tech & AI" and "Design & Product".
- A regression asserting that flipping the flag True restores tech feeds and the triage
  entry (parametrize on the flag, or monkeypatch it), proving the park is reversible.
- Weekend modes' feed sets are unchanged by the flag.

## Re-enabling later

Set `TECH_AI_ENABLED = True`. No other change required. Feeds resume, triage accepts the
section again, prompts and rendering already know it.
