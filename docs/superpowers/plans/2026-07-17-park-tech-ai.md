# Park Tech & AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Tech & AI section from every newsletter edition behind a single `TECH_AI_ENABLED = False` flag, leaving all its wiring in place so re-enabling is one boolean.

**Architecture:** Add one flag to `config.py`. Gate two things off it: (1) the four tech feeds are excluded from the composed `FEEDS_WEEKDAY` list, and (2) "Tech & AI" is dropped from the triage section menu so triage can't route a stray item into a feed-less section. Everything else (SECTION_MAP, favicons, emoji, prompt scaffolding, HN snippet-strip) is left inert. All changes are TDD.

**Tech Stack:** Python 3.11, pytest. Files: `config.py`, `prompts.py`, `tests/test_config.py` (new), `tests/test_prompts.py`.

**Spec:** `docs/superpowers/specs/2026-07-17-park-tech-ai-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `config.py` | Modify | Add `TECH_AI_ENABLED`; factor `FEEDS_WEEKDAY` through `_weekday_feeds(tech_enabled)` so the tech feeds are conditionally included |
| `prompts.py` | Modify | `triage_sections()` drops "Tech & AI" when the flag is off; fix the now-stale comment |
| `tests/test_config.py` | Create | Assert feed composition honors the flag in both states |
| `tests/test_prompts.py` | Modify | Assert triage menu drops Tech & AI when parked; both-gates-compose case |

---

## Task 1: Add the flag and gate the feeds

**Files:**
- Modify: `config.py:7-9` (flag) and `config.py:46-104` (feed composition)
- Test: `tests/test_config.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import config
from config import _weekday_feeds, FEEDS_WEEKDAY

TECH_SOURCES = {"TechCrunch", "Hacker News", "Simon Willison", "Stratechery"}


def test_tech_feeds_excluded_when_parked():
    feeds = _weekday_feeds(tech_enabled=False)
    sources = {f["source"] for f in feeds}
    assert not (sources & TECH_SOURCES), "no tech source should be fetched when parked"
    # Non-tech weekday feeds survive untouched.
    assert "CBC" in sources
    assert "BBC" in sources
    assert "NYT The Daily" in sources


def test_tech_feeds_restored_when_enabled():
    feeds = _weekday_feeds(tech_enabled=True)
    sources = {f["source"] for f in feeds}
    assert TECH_SOURCES <= sources, "flipping the flag restores every tech feed"


def test_exported_feeds_reflect_default_flag():
    # FEEDS_WEEKDAY is composed once at import from the module-level flag.
    exported = {f["source"] for f in FEEDS_WEEKDAY}
    if config.TECH_AI_ENABLED:
        assert TECH_SOURCES <= exported
    else:
        assert not (exported & TECH_SOURCES)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name '_weekday_feeds' from 'config'`.

- [ ] **Step 3: Add the flag**

In `config.py`, after line 9 (`TEST_MODE = ...`), add:

```python

# --- Parked sections ---
# Tech & AI parked 2026-07-17: Frank gets more comprehensive tech/AI coverage
# from another newsletter. Everything below (feeds, SECTION_MAP rows, favicons,
# emoji, prompt scaffolding) is left in place, inert. To restore the section,
# flip this to True — no other change is required.
TECH_AI_ENABLED = False
```

- [ ] **Step 4: Factor the feed list through a composition helper**

In `config.py`, replace the `FEEDS_WEEKDAY = [ ... ]` literal (lines 46-87) so the tech
block becomes a named list and the weekday list is composed by a helper. Replace lines
46-104 with:

```python
_TECH_AI_FEEDS = [
    {"url": "https://feeds.feedburner.com/TechCrunch",                                                   "source": "TechCrunch"},
    {"url": "https://hnrss.org/frontpage",                                                               "source": "Hacker News"},
    {"url": "https://simonwillison.net/atom/everything/",                                                "source": "Simon Willison"},
    {"url": "https://stratechery.com/feed/",                                                             "source": "Stratechery"},
]

_WEEKDAY_FEEDS_CANADA_TORONTO = [
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                               "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",             "source": "Globe & Mail"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                            "source": "r/toronto"},
    {"url": "https://www.blogto.com/rss/articles.xml",                                                   "source": "BlogTO"},
    {"url": "https://www.thestar.com/feeds/rss/news.xml",                                                "source": "Toronto Star"},
    {"url": "https://nationalpost.com/feed",                                                             "source": "National Post"},
    {"url": "https://www.nationalnewswatch.com/feed/",                                                   "source": "National Newswatch"},
    {"url": "https://www.canadaland.com/feed/",                                                          "source": "Canadaland"},
]

_WEEKDAY_FEEDS_HOUSING = [
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                        "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                      "source": "r/canadahousing"},
    {"url": "https://storeys.com/feed/",                                                                 "source": "Storeys"},
    {"url": "https://betterdwelling.com/feed/",                                                          "source": "BetterDwelling"},
    {"url": "https://www.moneysense.ca/category/columns/real-estate/feed/",                              "source": "MoneySense Real Estate"},
]

_WEEKDAY_FEEDS_FINANCE = [
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US",  "source": "Yahoo Finance"},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                                               "source": "WSJ"},
    {"url": "https://www.moneysense.ca/feed/",                                                           "source": "MoneySense"},
]

_WEEKDAY_FEEDS_US_GLOBAL = [
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                               "source": "BBC"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",                                 "source": "NYT"},
    {"url": "https://www.economist.com/international/rss.xml",                                           "source": "Economist"},
    {"url": "https://feeds.npr.org/1004/rss.xml",                                                        "source": "NPR World"},
    {"url": "https://api.axios.com/feed/",                                                               "source": "Axios"},
]

_WEEKDAY_FEEDS_PODCASTS = [
    {"url": "https://rss.art19.com/the-daily",                                                           "source": "NYT The Daily"},
    {"url": "https://feeds.megaphone.fm/VMP5705694065",                                                  "source": "Today Explained"},
    {"url": "https://www.cbc.ca/podcasting/includes/frontburner.xml",                                    "source": "CBC Frontburner"},
    {"url": "https://podcastfeeds.nbcnews.com/HL4TzgYC",                                                 "source": "NBC Meet the Press"},
]


def _weekday_feeds(tech_enabled: bool) -> list[dict]:
    """Compose the weekday feed set. Tech & AI is included only when enabled;
    it is parked by default (see TECH_AI_ENABLED). Keeping _TECH_AI_FEEDS
    defined and splicing it here makes re-enabling a one-flag change."""
    feeds = []
    feeds += _WEEKDAY_FEEDS_CANADA_TORONTO
    feeds += _WEEKDAY_FEEDS_HOUSING
    if tech_enabled:
        feeds += _TECH_AI_FEEDS
    feeds += _WEEKDAY_FEEDS_FINANCE
    feeds += _WEEKDAY_FEEDS_US_GLOBAL
    feeds += _WEEKDAY_FEEDS_PODCASTS
    return feeds


FEEDS_WEEKDAY = _weekday_feeds(TECH_AI_ENABLED)

FEEDS_SATURDAY_STRATEGIC = [
    {"url": "https://uxdesign.cc/feed",                  "source": "UX Collective"},
    {"url": "https://www.smashingmagazine.com/feed/",    "source": "Smashing Magazine"},
    {"url": "https://www.nngroup.com/feed/rss/",         "source": "NN/g"},
    {"url": "https://www.lennysnewsletter.com/feed",     "source": "Lenny's Newsletter"},
]

FEEDS_SUNDAY_VISUAL = [
    {"url": "https://design-milk.com/feed",              "source": "Design Milk"},
    {"url": "https://www.itsnicethat.com/articles.rss",  "source": "It's Nice That"},
    {"url": "https://tympanus.net/codrops/feed/",        "source": "Codrops"},
    {"url": "https://sidebar.io/feed.xml",               "source": "Sidebar"},
    {"url": "https://trendland.com/feed/",               "source": "Trendland"},
]

FEEDS = FEEDS_WEEKDAY  # back-compat alias
```

Note: the previous `FEEDS = FEEDS_WEEKDAY` alias (old line 104) is preserved. The section
comments that used to head each block (`# Canada & Toronto`, etc.) now name the sublists.

- [ ] **Step 5: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (all three tests).

- [ ] **Step 6: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: park Tech & AI feeds behind TECH_AI_ENABLED flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Drop Tech & AI from the triage menu

Without this, triage's JSON-schema enum still offers "Tech & AI", so a stray non-tech item
could be routed into a section that now has no feeds — the exact thin-section failure the
`design_allowed` gate was built to prevent.

**Files:**
- Modify: `prompts.py:126-129` (`triage_sections`) and its import block near `prompts.py:3`
- Test: `tests/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_prompts.py`:

```python
def test_triage_sections_drops_tech_ai_when_parked(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", False)
    weekend = triage_sections(design_allowed=True)
    weekday = triage_sections(design_allowed=False)
    assert "Tech & AI" not in weekend
    assert "Tech & AI" not in weekday
    # Design gate still composes on top of the tech gate.
    assert "Design & Product" in weekend
    assert "Design & Product" not in weekday


def test_triage_sections_restores_tech_ai_when_enabled(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", True)
    assert "Tech & AI" in triage_sections(design_allowed=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_prompts.py::test_triage_sections_drops_tech_ai_when_parked -v`
Expected: FAIL — `assert "Tech & AI" not in weekend` (it's still in the list).

- [ ] **Step 3: Import config into prompts**

At the top of `prompts.py`, alongside the existing imports (near line 3, `from pathlib import Path`), add:

```python
import config
```

- [ ] **Step 4: Gate the section list**

Replace `triage_sections` (`prompts.py:126-129`):

```python
def triage_sections(design_allowed: bool = True) -> list[str]:
    sections = list(TRIAGE_SECTIONS)
    if not config.TECH_AI_ENABLED:
        sections = [s for s in sections if s != "Tech & AI"]
    if not design_allowed:
        sections = [s for s in sections if s != "Design & Product"]
    return sections
```

Reading `config.TECH_AI_ENABLED` at call time (not importing the bare value) is what lets
the `monkeypatch.setattr(config, "TECH_AI_ENABLED", ...)` in the tests take effect.

- [ ] **Step 5: Fix the now-stale comment**

The comment at `prompts.py:112-114` and the existing test comment at
`tests/test_prompts.py:47-50` both claim weekday design items "fall back to Tech & AI."
With Tech & AI parked, that is no longer true. Update the `prompts.py` comment
(lines 112-114, immediately above `TRIAGE_SECTIONS`) to:

```python
# TRIAGE_SECTIONS is the full menu. triage_sections() filters it: Tech & AI is
# dropped whenever the section is parked (config.TECH_AI_ENABLED is False), and
# Design & Product is dropped on weekday editions (design_allowed False) so a
# reclassified weekday source can't spawn a thin one-item design section — it
# falls back to its feed-origin section instead.
```

And update the comment in `tests/test_prompts.py:47-50` (inside
`test_triage_sections_gates_design_by_weekday`) to drop the "forces such items back to
Tech & AI" clause:

```python
    # Design & Product is the weekend edition's signature. On weekday editions
    # its feeds aren't fetched, so the only way an item lands there is the LLM
    # reclassifying a weekday source (Simon Willison writing about writing, say).
    # Dropping it from the weekday menu forces such items to their feed-origin
    # section instead.
```

- [ ] **Step 6: Run the full prompts suite**

Run: `venv/bin/python -m pytest tests/test_prompts.py -v`
Expected: PASS. In particular the pre-existing `test_triage_sections_gates_design_by_weekday`
still passes: its assertion `[s for s in weekend if s != "Design & Product"] == weekday`
holds because the tech gate removes "Tech & AI" from both `weekend` and `weekday` equally.

- [ ] **Step 7: Commit**

```bash
git add prompts.py tests/test_prompts.py
git commit -m "feat: drop Tech & AI from triage menu when parked

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Full-suite regression and parked-edition smoke check

**Files:** none modified — verification only.

- [ ] **Step 1: Run the entire test suite**

Run: `venv/bin/python -m pytest -q`
Expected: PASS, no regressions. Pay attention to `test_routing.py` (feed routing) and
`test_triage.py` (menu enum) — both consume the changed config/prompt surfaces.

- [ ] **Step 2: Confirm no tech source survives a weekday build**

Run:
```bash
venv/bin/python -c "
from routing import get_mode, get_feeds_for_mode
from datetime import date
tech = {'TechCrunch','Hacker News','Simon Willison','Stratechery'}
for d in [date(2026,7,20), date(2026,7,21)]:  # Mon catchup, Tue daily
    srcs = {f['source'] for f in get_feeds_for_mode(get_mode(d))}
    assert not (srcs & tech), d
    print(d, 'OK — no tech feeds')
"
```
Expected: two `OK — no tech feeds` lines.

- [ ] **Step 3: Confirm the triage tool enum omits Tech & AI**

Run:
```bash
venv/bin/python -c "
from prompts import triage_sections
print('weekend menu:', triage_sections(design_allowed=True))
assert 'Tech & AI' not in triage_sections(design_allowed=True)
print('OK — Tech & AI parked out of triage menu')
"
```
Expected: menu printed without "Tech & AI", then the OK line.

- [ ] **Step 4: Final commit if any doc/tracking updates are pending**

No code changes expected in this task. If the plan checkboxes are tracked in-repo, commit them:
```bash
git add -A
git commit -m "chore: verify Tech & AI parking (full suite green)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>" || echo "nothing to commit"
```

---

## Self-Review Notes

- **Spec coverage:** flag (Task 1 Step 3), feed gate (Task 1 Step 4), triage-menu gate
  (Task 2), inert residue left untouched (no task — deliberate), reversibility
  (`_weekday_feeds(True)` test + `test_triage_sections_restores_tech_ai_when_enabled`),
  HN snippet-strip left as-is (no task — inert). All covered.
- **No placeholders:** every code step shows full code.
- **Type consistency:** `_weekday_feeds(tech_enabled: bool)` and `config.TECH_AI_ENABLED`
  used identically across tasks; `triage_sections(design_allowed: bool)` signature unchanged.
- **Not gated (intentional):** `SECTION_MAP`, `SECTION_EMOJIS`, `SOURCE_FAVICONS`,
  `SECTION_ORDER`, format-prompt strings, `pipeline.py` HN strip — all inert with no tech
  feed, per spec.
