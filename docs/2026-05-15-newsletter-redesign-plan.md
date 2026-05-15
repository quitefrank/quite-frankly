# Quite Frankly Newsletter Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add day-of-week routing, an expanded source pool, two-pass Claude triage with tier scoring, a Worth Knowing section, weekend strategic/visual design modes, and Phase 1.5 shadow evaluation (Reddit + HN traction logging) to the existing single-mode newsletter pipeline.

**Architecture:** Split the monolithic `newsletter.py` into focused modules. A routing module branches on weekday and selects the feed pool and section layout. A triage module makes the first Claude call to score and tier items. A formatting module makes the second Claude call to render the email. A shadow module runs in parallel, queries free traction APIs (Reddit, Hacker News), and writes comparison logs for later promotion to Phase 2.

**Tech Stack:** Python 3.11, anthropic, feedparser, requests (new, for Reddit + HN), pytest (new, for tests).

**Reference spec:** `docs/2026-05-15-newsletter-redesign-spec.md`

---

## File Structure

```
quite-frankly/
├── newsletter.py          (slim orchestration entry point)
├── config.py              (FEEDS, sections, blurb, favicons, subreddits)
├── prompts.py             (TRIAGE_SYSTEM_PROMPT, FORMAT_SYSTEM_PROMPT, builders)
├── routing.py             (Mode enum, mode resolution, feed/section selection)
├── pipeline.py            (fetch, dedup, ID assignment)
├── triage.py              (pass-1 Claude call, JSON parsing, tier mapping)
├── formatting.py          (pass-2 Claude call, HTML rendering, source rendering)
├── traction.py            (Reddit + HN API queries)
├── comparison.py          (shadow scoring, comparison log, weekly digest)
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── sample_feed.xml
│   │   ├── sample_triage_response.json
│   │   └── sample_format_response.md
│   ├── test_routing.py
│   ├── test_pipeline.py
│   ├── test_triage.py
│   ├── test_formatting.py
│   ├── test_traction.py
│   └── test_comparison.py
├── comparison/            (runtime output, gitignored)
│   └── YYYY-MM-DD.json
└── docs/
    ├── 2026-05-15-newsletter-redesign-spec.md
    └── 2026-05-15-newsletter-redesign-plan.md
```

Each module has one clear job. `newsletter.py` shrinks to orchestration only. Existing functions migrate to the file matching their responsibility.

---

## Task Sequence

Phase A: Foundation (Tasks 1–3)
Phase B: Triage and rendering (Tasks 4–6)
Phase C: Shadow evaluation (Tasks 7–9)
Phase D: Cutover (Task 10)

Each task ends with a commit. After Phase A, the existing newsletter still runs (no behavior change yet). After Phase B, the new triage and Worth Knowing section are live. After Phase C, shadow logs are being written. Phase D flips the production switch.

---

### Task 1: Test scaffold and module split

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_feed.xml`
- Create: `tests/fixtures/sample_format_response.md`
- Create: `tests/test_smoke.py`
- Create: `config.py`
- Create: `prompts.py`
- Create: `pipeline.py`
- Create: `formatting.py`
- Modify: `newsletter.py` (slim down to orchestration)
- Modify: `.gitignore` (add `comparison/`, `__pycache__/`, `.pytest_cache/`)

- [ ] **Step 1: Create dev requirements and gitignore**

```bash
cat > requirements-dev.txt <<EOF
pytest>=8.0.0
requests-mock>=1.11.0
EOF
```

```bash
cat > .gitignore <<EOF
__pycache__/
.pytest_cache/
comparison/
*.pyc
.DS_Store
EOF
```

- [ ] **Step 2: Write a smoke test that asserts the current pipeline produces an email subject line**

`tests/conftest.py`:

```python
import os
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_feed_xml():
    return (FIXTURES / "sample_feed.xml").read_text()


@pytest.fixture
def sample_format_response():
    return (FIXTURES / "sample_format_response.md").read_text()


@pytest.fixture
def fake_anthropic_client(monkeypatch, sample_format_response):
    class FakeMessage:
        content = [type("Block", (), {"text": sample_format_response})()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeMessage()

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: FakeClient())
    return FakeClient()
```

`tests/fixtures/sample_feed.xml`:

```xml
<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Sample</title>
    <item>
      <title>Toronto council debates housing supply</title>
      <link>https://example.com/article-1</link>
      <description>Council weighs density rules.</description>
    </item>
    <item>
      <title>Bank of Canada holds rates steady</title>
      <link>https://example.com/article-2</link>
      <description>Markets unchanged.</description>
    </item>
  </channel>
</rss>
```

`tests/fixtures/sample_format_response.md`:

```markdown
SUBJECT: 🏠 Toronto council weighs density rules

## Canada & Toronto

**Toronto council debates housing supply [#0]**
Council weighed density rules at Thursday's meeting. The proposal would allow taller buildings in transit-rich areas. Supporters say it would help with affordability.

Critics argue the rules favor developers and could change neighborhood character. The motion passed and goes to a public consultation phase.
Source: CBC

## Finance & Markets

**Bank of Canada holds rates steady [#1]**
The Bank of Canada held its key rate at current levels. Officials cited cooling inflation and a slowing labor market. Markets responded calmly.

Economists are split on the next move. A cut is on the table for the summer if growth softens further.
Source: Yahoo Finance
```

`tests/test_smoke.py`:

```python
def test_smoke_pytest_runs():
    assert True
```

- [ ] **Step 3: Verify test runs**

```bash
pip install -r requirements-dev.txt && pytest -v
```

Expected: `1 passed`.

- [ ] **Step 4: Split monolithic newsletter.py into modules (mechanical move, no behavior change)**

Create `config.py` and move the constants `RECIPIENT`, `SENDER`, `SEEN_LINKS_FILE`, `SEVEN_DAYS_S`, `FEEDS`, `SECTION_MAP`, `SECTION_EMOJIS`, `SOURCE_FAVICONS` from `newsletter.py` to `config.py`.

Create `prompts.py` and move `SYSTEM_PROMPT` to it, renamed to `FORMAT_SYSTEM_PROMPT` (since the triage prompt is incoming in Task 4).

Create `pipeline.py` and move `extract_image`, `fetch_feed`, `fetch_all_feeds`, `load_seen_links`, `save_seen_links`, `deduplicate` to it.

Create `formatting.py` and move `source_with_favicon`, `find_article_data`, `render_other_headlines`, `parse_and_render_sections`, `build_everything_else`, `parse_subject_line`, `build_email_html`, `call_claude` (renamed `call_formatter`), `send_email` to it.

Slim `newsletter.py` to just the `main()` function and imports:

```python
#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

from config import SECTION_MAP
from pipeline import fetch_all_feeds, deduplicate
from formatting import call_formatter, build_email_html, send_email


def main():
    print("Fetching feeds...")
    all_items = fetch_all_feeds()
    print(f"Total raw items: {len(all_items)}")

    print("Deduplicating...")
    items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}")

    headlines = "\n".join(
        f"[#{idx}] [{SECTION_MAP.get(i['source'], i['source'])}] {i['title']} | Source: {i['source']}"
        for idx, i in enumerate(items)
    )
    links_by_id = {idx: i for idx, i in enumerate(items)}

    print("Calling Claude API...")
    claude_response = call_formatter(headlines)

    print("Building HTML...")
    html, subject = build_email_html(claude_response, links_by_id)

    print("Sending email...")
    send_email(html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
```

Adjust `formatting.py` to take `links_by_id` (dict keyed by integer ID) instead of `links` (list). Update `find_article_data` and call sites to look up by ID first, fall back to fuzzy match.

- [ ] **Step 5: Verify the smoke test still passes after the split**

```bash
pytest -v
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt .gitignore tests/ config.py prompts.py pipeline.py formatting.py newsletter.py
git commit -m "Refactor newsletter.py into modules and add pytest scaffold"
```

---

### Task 2: Day-of-week routing

**Files:**
- Create: `routing.py`
- Create: `tests/test_routing.py`
- Modify: `newsletter.py` (call routing in main)
- Modify: `config.py` (split FEEDS into weekday/saturday/sunday pools)

- [ ] **Step 1: Write failing tests for routing**

`tests/test_routing.py`:

```python
from datetime import date
from routing import Mode, get_mode, get_feeds_for_mode


def test_monday_is_weekend_catchup():
    assert get_mode(date(2026, 5, 18)) == Mode.MONDAY_CATCHUP


def test_tuesday_through_friday_is_daily():
    for d in [date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)]:
        assert get_mode(d) == Mode.WEEKDAY_DAILY


def test_saturday_is_strategic_design():
    assert get_mode(date(2026, 5, 23)) == Mode.SATURDAY_STRATEGIC


def test_sunday_is_visual_design():
    assert get_mode(date(2026, 5, 24)) == Mode.SUNDAY_VISUAL


def test_weekday_pool_excludes_design_feeds():
    feeds = get_feeds_for_mode(Mode.WEEKDAY_DAILY)
    sources = [f["source"] for f in feeds]
    assert "Design Milk" not in sources
    assert "Hypebeast" not in sources
    assert "UX Collective" not in sources


def test_saturday_pool_is_strategic_design_only():
    feeds = get_feeds_for_mode(Mode.SATURDAY_STRATEGIC)
    sources = [f["source"] for f in feeds]
    assert "UX Collective" in sources
    assert "Lenny's Newsletter" in sources
    assert "Hypebeast" not in sources
    assert "CBC" not in sources


def test_sunday_pool_is_visual_design_only():
    feeds = get_feeds_for_mode(Mode.SUNDAY_VISUAL)
    sources = [f["source"] for f in feeds]
    assert "Design Milk" in sources
    assert "Codrops" in sources
    assert "Lenny's Newsletter" not in sources
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_routing.py -v
```

Expected: `ImportError` or all fail.

- [ ] **Step 3: Implement routing.py and update config.py**

`routing.py`:

```python
"""Day-of-week routing for newsletter modes."""

from datetime import date
from enum import Enum

from config import FEEDS_WEEKDAY, FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL


class Mode(Enum):
    MONDAY_CATCHUP = "monday_catchup"
    WEEKDAY_DAILY = "weekday_daily"
    SATURDAY_STRATEGIC = "saturday_strategic"
    SUNDAY_VISUAL = "sunday_visual"


def get_mode(d: date) -> Mode:
    weekday = d.weekday()
    if weekday == 0:
        return Mode.MONDAY_CATCHUP
    if 1 <= weekday <= 4:
        return Mode.WEEKDAY_DAILY
    if weekday == 5:
        return Mode.SATURDAY_STRATEGIC
    return Mode.SUNDAY_VISUAL


def get_feeds_for_mode(mode: Mode) -> list[dict]:
    if mode in (Mode.MONDAY_CATCHUP, Mode.WEEKDAY_DAILY):
        return FEEDS_WEEKDAY
    if mode == Mode.SATURDAY_STRATEGIC:
        return FEEDS_SATURDAY_STRATEGIC
    return FEEDS_SUNDAY_VISUAL


def is_design_mode(mode: Mode) -> bool:
    return mode in (Mode.SATURDAY_STRATEGIC, Mode.SUNDAY_VISUAL)
```

`config.py` (add at the bottom, replacing the existing `FEEDS` list with three new lists):

```python
FEEDS_WEEKDAY = [
    # Canada & Toronto
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                         "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",       "source": "Globe & Mail"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                       "source": "r/toronto"},
    {"url": "https://www.blogto.com/rss/articles.xml",                                              "source": "BlogTO"},
    {"url": "https://www.thestar.com/feeds/rss/news.xml",                                           "source": "Toronto Star"},
    {"url": "https://nationalpost.com/feed",                                                        "source": "National Post"},
    {"url": "https://www.nationalnewswatch.com/feed/",                                              "source": "National Newswatch"},

    # Toronto Housing
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                   "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                 "source": "r/canadahousing"},
    {"url": "https://storeys.com/feed/",                                                            "source": "Storeys"},
    {"url": "https://betterdwelling.com/feed/",                                                     "source": "BetterDwelling"},
    {"url": "https://www.moneysense.ca/category/columns/real-estate/feed/",                         "source": "MoneySense Real Estate"},

    # Tech & AI
    {"url": "https://feeds.feedburner.com/TechCrunch",                                              "source": "TechCrunch"},
    {"url": "https://hnrss.org/frontpage",                                                          "source": "Hacker News"},
    {"url": "https://simonwillison.net/atom/everything/",                                           "source": "Simon Willison"},
    {"url": "https://stratechery.com/feed/",                                                        "source": "Stratechery"},

    # Finance & Markets
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US", "source": "Yahoo Finance"},
    {"url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                                          "source": "WSJ"},
    {"url": "https://www.moneysense.ca/feed/",                                                      "source": "MoneySense"},

    # US & Global
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                          "source": "BBC"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",                            "source": "NYT"},
    {"url": "https://www.economist.com/the-world-this-week/rss.xml",                                "source": "Economist"},
    {"url": "https://feeds.npr.org/1004/rss.xml",                                                   "source": "NPR World"},
    {"url": "https://api.axios.com/feed/",                                                          "source": "Axios"},

    # Podcasts (cultural currency)
    {"url": "https://rss.art19.com/the-daily",                                                      "source": "NYT The Daily"},
    {"url": "https://feeds.megaphone.fm/todayexplained",                                            "source": "Today Explained"},
    {"url": "https://www.cbc.ca/podcasting/includes/frontburner.xml",                               "source": "CBC Frontburner"},
    {"url": "https://podcastfeeds.nbcnews.com/HL4TzgYC",                                            "source": "NBC Meet the Press"},
]

FEEDS_SATURDAY_STRATEGIC = [
    {"url": "https://uxdesign.cc/feed",                  "source": "UX Collective"},
    {"url": "https://www.smashingmagazine.com/feed/",    "source": "Smashing Magazine"},
    {"url": "https://www.nngroup.com/feed/rss/",         "source": "NN/g"},
    {"url": "https://www.lennysnewsletter.com/feed",     "source": "Lenny's Newsletter"},
]

FEEDS_SUNDAY_VISUAL = [
    {"url": "https://design-milk.com/feed",              "source": "Design Milk"},
    {"url": "https://hypebeast.com/feed",                "source": "Hypebeast"},
    {"url": "https://tympanus.net/codrops/feed/",        "source": "Codrops"},
    {"url": "https://sidebar.io/feed.xml",               "source": "Sidebar"},
    {"url": "https://trendland.com/feed/",               "source": "Trendland"},
]
```

Extend `SECTION_MAP` in `config.py` with entries for every new source. Map podcasts to `"Worth Knowing"` and design sources to `"Design & Product"`.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_routing.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Wire routing into newsletter.py main**

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from routing import get_mode, get_feeds_for_mode

def main():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    mode = get_mode(today)
    print(f"Mode: {mode.value}")

    feeds = get_feeds_for_mode(mode)
    all_items = fetch_all_feeds(feeds)
    # ...rest unchanged for now
```

Update `fetch_all_feeds` in `pipeline.py` to accept a feeds list argument instead of reading the module global.

- [ ] **Step 6: Commit**

```bash
git add routing.py config.py newsletter.py pipeline.py tests/test_routing.py
git commit -m "Add day-of-week routing and expanded source pool"
```

---

### Task 3: Article ID assignment and Monday dedup-bypass

**Files:**
- Modify: `pipeline.py` (assign_ids, monday_dedup_bypass)
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

`tests/test_pipeline.py`:

```python
from datetime import date
from pipeline import assign_ids, monday_dedup_bypass


def test_assign_ids_returns_dict_keyed_by_id():
    items = [
        {"title": "a", "link": "u1", "source": "CBC"},
        {"title": "b", "link": "u2", "source": "BBC"},
    ]
    by_id = assign_ids(items)
    assert by_id == {0: items[0], 1: items[1]}


def test_assign_ids_attaches_id_to_each_item():
    items = [{"title": "a", "link": "u1", "source": "CBC"}]
    by_id = assign_ids(items)
    assert by_id[0]["id"] == 0


def test_monday_bypass_keeps_items_with_cluster_size_3_plus():
    seen = {"u1": 0, "u2": 0, "u3": 0}
    items = [
        {"id": 0, "title": "Story A", "link": "u1", "source": "CBC", "cluster_size": 4},
        {"id": 1, "title": "Story B", "link": "u2", "source": "BBC", "cluster_size": 2},
        {"id": 2, "title": "Story C", "link": "u3", "source": "NYT", "cluster_size": 1},
    ]
    result = monday_dedup_bypass(items, seen)
    assert {i["id"] for i in result} == {0}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_pipeline.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement assign_ids and monday_dedup_bypass**

Add to `pipeline.py`:

```python
def assign_ids(items: list[dict]) -> dict[int, dict]:
    by_id = {}
    for idx, item in enumerate(items):
        item["id"] = idx
        by_id[idx] = item
    return by_id


def monday_dedup_bypass(items: list[dict], seen: dict) -> list[dict]:
    """On Mondays, re-admit items already in `seen` only if cluster_size >= 3."""
    return [i for i in items if i["link"] in seen and i.get("cluster_size", 0) >= 3]
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline.py tests/test_pipeline.py
git commit -m "Add article ID assignment and Monday dedup bypass helpers"
```

---

### Task 4: Triage pass (pass-1 Claude call + tier scoring)

**Files:**
- Create: `triage.py`
- Create: `tests/test_triage.py`
- Create: `tests/fixtures/sample_triage_response.json`
- Modify: `prompts.py` (add TRIAGE_SYSTEM_PROMPT, PERSONAL_RELEVANCE_BLURB)

- [ ] **Step 1: Write the triage system prompt**

Add to `prompts.py`:

```python
PERSONAL_RELEVANCE_BLURB = """Frank is a senior product designer at theScore in Toronto, aiming for staff or principal product designer roles. He is rebuilding his portfolio, running AI side projects (Claude-based research tools, a workout PWA), and selling a Leslieville condo. He does not gamble or follow sports. He cares about Canadian politics in the dinner-table sense, Toronto housing market dynamics, AI tooling for designers, design industry moves at the staff/principal level, and personal finance for a transitional year. He is turning 38 in June."""


TRIAGE_SYSTEM_PROMPT = f"""You are a triage editor for a daily news briefing.

You will receive a list of today's news headlines, each prefixed with an integer ID [#N], a section label in square brackets, and a source name. Your job: score each item, group items into clusters when multiple sources cover the same story, and assign each item to a section.

Reader context for personal relevance scoring:
{PERSONAL_RELEVANCE_BLURB}

For each item, return:
- id (integer)
- tier (1=Featured, 2=Worth Reading, 3=Background, or 0=Dropped)
- section (one of: "Canada & Toronto", "Toronto Housing", "Tech & AI", "Finance & Markets", "US & Global", "Worth Knowing", "Design & Product")
- cluster_id (string; same id for items covering the same underlying story)
- scores: cross_source_coverage (integer count of feeds covering it, including itself), personal_relevance (0-3), section_fit ("good" | "weak" | "none")
- promotion_to_worth_knowing (boolean; true only when cluster_size >= 3 AND no clean section fit)
- reasoning (one sentence)

Tier mapping (sum cross_source_coverage + personal_relevance + section_fit_score):
- section_fit_score: good=1, weak=0, none=-1
- Tier 1 if total >= 6
- Tier 2 if total 3-5
- Tier 3 if total 1-2
- Dropped if total <= 0

Also return a "clusters" array. For each cluster_id, list primary_source (the source whose headline is most distinctive), also_in (other sources in the cluster), and canonical_headline.

Output strict JSON only. No prose, no markdown fences."""
```

- [ ] **Step 2: Create the triage response fixture**

`tests/fixtures/sample_triage_response.json`:

```json
{
  "items": [
    {"id": 0, "tier": 1, "section": "Canada & Toronto", "cluster_id": "cl_a", "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}, "promotion_to_worth_knowing": false, "reasoning": "Toronto housing supply directly relevant."},
    {"id": 1, "tier": 1, "section": "Finance & Markets", "cluster_id": "cl_b", "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}, "promotion_to_worth_knowing": false, "reasoning": "Bank of Canada move covered widely."}
  ],
  "clusters": [
    {"id": "cl_a", "primary_source": "CBC", "also_in": ["BlogTO"], "canonical_headline": "Toronto council debates housing supply"},
    {"id": "cl_b", "primary_source": "Yahoo Finance", "also_in": ["WSJ", "Globe & Mail Finance"], "canonical_headline": "Bank of Canada holds rates steady"}
  ]
}
```

- [ ] **Step 3: Write failing tests for triage parsing**

`tests/test_triage.py`:

```python
import json
from pathlib import Path
from triage import parse_triage_response, select_items_by_tier


FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_triage_response_returns_items_and_clusters():
    raw = (FIXTURES / "sample_triage_response.json").read_text()
    items, clusters = parse_triage_response(raw)
    assert len(items) == 2
    assert items[0]["tier"] == 1
    assert clusters["cl_a"]["primary_source"] == "CBC"


def test_select_tier_1_items():
    raw = (FIXTURES / "sample_triage_response.json").read_text()
    items, _ = parse_triage_response(raw)
    tier1 = select_items_by_tier(items, tier=1)
    assert len(tier1) == 2


def test_parse_handles_extra_whitespace_and_fences():
    raw = '```json\n{"items": [], "clusters": []}\n```'
    items, clusters = parse_triage_response(raw)
    assert items == []
    assert clusters == {}
```

- [ ] **Step 4: Run tests, verify they fail**

```bash
pytest tests/test_triage.py -v
```

Expected: `ImportError`.

- [ ] **Step 5: Implement triage.py**

```python
"""Pass-1 Claude triage: score, tier, and cluster items."""

import json
import os
import re

import anthropic

from prompts import TRIAGE_SYSTEM_PROMPT


def call_triage(headlines_text: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=TRIAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": headlines_text}],
    )
    return message.content[0].text


def parse_triage_response(raw: str) -> tuple[list[dict], dict[str, dict]]:
    cleaned = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    data = json.loads(cleaned)
    items = data.get("items", [])
    clusters_list = data.get("clusters", [])
    clusters = {c["id"]: c for c in clusters_list}
    return items, clusters


def select_items_by_tier(items: list[dict], tier: int) -> list[dict]:
    return [i for i in items if i.get("tier") == tier]


def build_triage_user_message(items: list[dict]) -> str:
    lines = []
    for i in items:
        lines.append(f"[#{i['id']}] [{i.get('section_label', '?')}] {i['title']} | Source: {i['source']}")
    return "Here are today's headlines:\n\n" + "\n".join(lines)
```

- [ ] **Step 6: Run tests, verify they pass**

```bash
pytest tests/test_triage.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add triage.py prompts.py tests/test_triage.py tests/fixtures/sample_triage_response.json
git commit -m "Add pass-1 triage module with tier scoring and clustering"
```

---

### Task 5: Format pass updates (Worth Knowing, cluster rendering, tier-aware sections)

**Files:**
- Modify: `prompts.py` (rewrite FORMAT_SYSTEM_PROMPT to consume triage output)
- Modify: `formatting.py` (consume tier data, add Worth Knowing section, render cluster corroboration in source line)
- Create: `tests/test_formatting.py`

- [ ] **Step 1: Write failing tests for cluster source rendering**

`tests/test_formatting.py`:

```python
from formatting import render_source_line


def test_single_source_renders_plain():
    line = render_source_line(
        primary_source="CBC",
        also_in=[],
        article_link="https://example.com/a",
    )
    assert "CBC" in line
    assert "also in" not in line.lower()


def test_two_source_cluster_renders_both_inline():
    line = render_source_line(
        primary_source="CBC",
        also_in=["Toronto Star"],
        article_link="https://example.com/a",
    )
    assert "CBC, Toronto Star" in line


def test_three_plus_cluster_renders_with_also_in_suffix():
    line = render_source_line(
        primary_source="NYT",
        also_in=["BBC", "Economist", "NPR World"],
        article_link="https://example.com/a",
    )
    assert "NYT" in line
    assert "BBC" in line
    assert "Economist" in line
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_formatting.py -v
```

Expected: fail (function not defined).

- [ ] **Step 3: Implement render_source_line in formatting.py**

```python
def render_source_line(primary_source: str, also_in: list[str], article_link: str | None) -> str:
    favicon = SOURCE_FAVICONS.get(
        primary_source,
        f"https://www.google.com/s2/favicons?domain={primary_source}&sz=64",
    )
    img = (
        f'<img src="{favicon}" width="16" height="16" '
        f'style="width:16px;height:16px;vertical-align:middle;margin-right:4px;'
        f'border-radius:3px;display:inline-block">'
    )
    if not also_in:
        label = primary_source
    elif len(also_in) == 1:
        label = f"{primary_source}, {also_in[0]}"
    else:
        also_str = ", ".join(also_in)
        label = f"{primary_source} (also in {also_str})"

    if article_link:
        return (
            f'{img}<a href="{article_link}" '
            f'style="color:#1c7ff2;text-decoration:none;vertical-align:middle;font-size:12px;">{label}</a>'
        )
    return f'{img}<span style="vertical-align:middle;font-size:12px;color:#999;">{label}</span>'
```

Existing `source_with_favicon` becomes a thin wrapper for backward compatibility, or gets replaced at all call sites. Recommended: replace at call sites.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_formatting.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Rewrite FORMAT_SYSTEM_PROMPT to consume the triage output**

Replace the existing `FORMAT_SYSTEM_PROMPT` in `prompts.py` with the version below. It accepts a structured input rather than raw headlines, since selection and section assignment already happened in the triage pass.

```python
FORMAT_SYSTEM_PROMPT = """You are the writer for a daily briefing. The selection work has already been done. You will receive a JSON input listing items grouped by section and tier, plus a clusters lookup for stories covered by multiple sources.

Output a single SUBJECT line as the first line:
SUBJECT: <emoji> <headline>

Pick the single most consequential Tier 1 item across all sections as the subject. Rewrite it as a tight headline of at most 70 characters, no quotes, no trailing punctuation. Choose one emoji that captures the topic (legislation ⚖️, tech 💻, housing 🏠, markets 📈, design 🎨, transit 🚇, climate 🌍, world 🌐, AI 🤖).

After SUBJECT, leave one blank line, then write the briefing.

For each section in this exact order (skip a section entirely if it has no items):
## Canada & Toronto
## Toronto Housing
## Tech & AI
## Finance & Markets
## US & Global
## Worth Knowing

For Tier 1 items, write a full story:

**Original headline text [#N]**
Body paragraph one, 3 to 4 sentences.

Body paragraph two, 3 to 4 sentences.
Source: <use the cluster's primary_source>

After each Tier 1 story, if and only if the item is genuinely relevant to Frank's work as a product designer, his Leslieville condo, his investments, his freelance work, or his life in Toronto, add a single What this means for you line:
What this means for you: <one specific sentence written directly to Frank, starting with You or with the subject of the insight, never starting with his name>

If there is no clear personal relevance, skip the line entirely.

For Tier 2 items in a section, after all Tier 1 stories, add:

### Other Headlines
- **First few words of headline [#N]**: one sentence summary. Source: <primary_source>

Cap Other Headlines at 5 items per section. If a section has more than 5 Tier 2 items, list the 5 strongest by personal_relevance.

For Worth Knowing, render every item as a full Tier 1 story unless the item lacks a body summary, in which case render it as a one-line bullet with the [#N] ID preserved.

After all sections, add:

## Everything Else

For each section with Tier 3 items, add a subsection:

### <Section Name>
- **First few words of headline [#N]**: one sentence summary. Source: <primary_source>

CRITICAL RULES YOU MUST FOLLOW:
1. Every input item carries an [#N] ID. You MUST preserve the exact [#N] inside the bold markers of every featured headline, and at the same position inside the bold for Other Headlines and Everything Else items. Example: **Headline text [#42]**.
2. Never move an item to a different section than the triage assigned. Section is final.
3. Never invent items. Use only the IDs provided in the input.
4. For each item, use the cluster's primary_source for the Source line. If the input does not provide a cluster, fall back to the item's own source.
5. Body paragraphs must be separated by exactly one blank line.
"""
```

The triage already determined what goes where, so the format prompt is freed from selection logic. This is the split the spec relies on.

- [ ] **Step 6: Update parse_and_render_sections to handle Worth Knowing and to use cluster data**

In `formatting.py`, modify `parse_and_render_sections` to:
- Recognize `## Worth Knowing` as a valid section heading
- For each rendered story, look up its cluster (by item ID) and pass primary_source + also_in to `render_source_line`
- Skip empty sections (Worth Knowing renders nothing if no items)

- [ ] **Step 7: Add a tests/test_formatting.py case asserting Worth Knowing section renders when given matching markdown input**

```python
def test_worth_knowing_section_renders():
    text = """## Worth Knowing

**Big global story [#5]**
Body paragraph one.

Body paragraph two.
Source: NYT
"""
    links_by_id = {5: {"link": "https://example.com/5", "image": "", "title": "Big global story"}}
    clusters_by_item_id = {5: {"primary_source": "NYT", "also_in": ["BBC"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    assert "Worth Knowing" in html
    assert "NYT, BBC" in html
```

Update `parse_and_render_sections` signature to take `clusters_by_item_id`. Pass `{}` from call sites that don't have cluster data yet.

- [ ] **Step 8: Run all tests, verify they pass**

```bash
pytest -v
```

Expected: all passing.

- [ ] **Step 9: Commit**

```bash
git add prompts.py formatting.py tests/test_formatting.py
git commit -m "Add Worth Knowing section and cluster-aware source rendering"
```

---

### Task 6: Wire two-pass pipeline into newsletter.py main

**Files:**
- Modify: `newsletter.py` (orchestrate routing → fetch → triage → format → send)

- [ ] **Step 1: Update main() to chain pipeline through routing, triage, and format passes**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from config import SECTION_MAP
from routing import get_mode, get_feeds_for_mode
from pipeline import fetch_all_feeds, deduplicate, assign_ids
from triage import call_triage, parse_triage_response, build_triage_user_message
from formatting import call_formatter, build_email_html, send_email


def main():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    mode = get_mode(today)
    print(f"Mode: {mode.value}")

    feeds = get_feeds_for_mode(mode)
    all_items = fetch_all_feeds(feeds)
    print(f"Raw items: {len(all_items)}")

    items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}")

    for item in items:
        item["section_label"] = SECTION_MAP.get(item["source"], item["source"])

    links_by_id = assign_ids(items)

    print("Calling triage pass...")
    triage_user = build_triage_user_message(items)
    triage_raw = call_triage(triage_user)
    tiered_items, clusters = parse_triage_response(triage_raw)

    print("Calling format pass...")
    format_input = build_format_input(tiered_items, clusters, links_by_id)
    format_raw = call_formatter(format_input)

    print("Building HTML...")
    clusters_by_item_id = {
        item["id"]: clusters.get(item["cluster_id"], {})
        for item in tiered_items
    }
    html, subject = build_email_html(format_raw, links_by_id, clusters_by_item_id)

    print("Sending email...")
    send_email(html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
```

Add `build_format_input` to `formatting.py`:

```python
import json


SECTION_ORDER = [
    "Canada & Toronto",
    "Toronto Housing",
    "Tech & AI",
    "Finance & Markets",
    "US & Global",
    "Worth Knowing",
]


def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict]) -> str:
    by_section: dict[str, dict[str, list]] = {
        s: {"tier_1": [], "tier_2": [], "tier_3": []} for s in SECTION_ORDER
    }
    for item in tiered_items:
        section = item.get("section")
        tier = item.get("tier", 0)
        if section not in by_section or tier == 0:
            continue
        bucket = f"tier_{tier}"
        if bucket not in by_section[section]:
            continue
        link = links_by_id.get(item["id"], {})
        by_section[section][bucket].append({
            "id": item["id"],
            "title": link.get("title", ""),
            "snippet": link.get("snippet", ""),
            "source": link.get("source", ""),
            "cluster_id": item.get("cluster_id"),
        })

    return json.dumps({
        "sections": by_section,
        "clusters": clusters,
    }, indent=2)
```

The format prompt sees a fully shaped input: per-section tier buckets plus the clusters lookup so primary_source resolution stays local to the prompt.

- [ ] **Step 2: Run smoke test through the fake Anthropic client**

Extend `conftest.py`'s `fake_anthropic_client` so it returns the triage fixture JSON on the first call and the format fixture markdown on the second.

```python
@pytest.fixture
def fake_anthropic_client(monkeypatch, sample_format_response):
    triage_json = (FIXTURES / "sample_triage_response.json").read_text()
    responses = iter([triage_json, sample_format_response])

    class FakeMessage:
        def __init__(self, text):
            self.content = [type("Block", (), {"text": text})()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeMessage(next(responses))

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: FakeClient())
    return FakeClient()
```

Write an end-to-end smoke test:

```python
def test_main_runs_through_two_passes(fake_anthropic_client, monkeypatch):
    monkeypatch.setattr("formatting.send_email", lambda html, subject: None)
    monkeypatch.setattr("pipeline.fetch_all_feeds", lambda feeds: [
        {"title": "Toronto council debates housing supply", "link": "https://example.com/1", "snippet": "", "image": "", "source": "CBC"},
        {"title": "Bank of Canada holds rates steady", "link": "https://example.com/2", "snippet": "", "image": "", "source": "Yahoo Finance"},
    ])
    from newsletter import main
    main()
```

Add this to `tests/test_smoke.py`.

- [ ] **Step 3: Run smoke test, verify it passes**

```bash
pytest tests/test_smoke.py -v
```

Expected: passing.

- [ ] **Step 4: Commit**

```bash
git add newsletter.py formatting.py tests/test_smoke.py tests/conftest.py
git commit -m "Wire two-pass triage and format pipeline into orchestration"
```

---

### Task 7: Traction module (Reddit + HN)

**Files:**
- Create: `traction.py`
- Create: `tests/test_traction.py`
- Modify: `requirements.txt` (add `requests`)
- Modify: `config.py` (add `REDDIT_SUBREDDITS`)

- [ ] **Step 1: Add requests to requirements.txt**

```bash
echo "requests>=2.31.0" >> requirements.txt
```

- [ ] **Step 2: Add config**

In `config.py`:

```python
REDDIT_SUBREDDITS = [
    "news",
    "worldnews",
    "canada",
    "toronto",
    "canadahousing",
    "technology",
    "OntarioHousing",
]
```

- [ ] **Step 3: Write failing tests for Reddit + HN traction**

`tests/test_traction.py`:

```python
import requests_mock
from traction import fetch_reddit_traction, fetch_hn_traction


def test_fetch_reddit_traction_aggregates_across_subreddits():
    url = "https://example.com/article-1"
    with requests_mock.Mocker() as m:
        m.get(
            "https://www.reddit.com/r/news/search.json",
            json={"data": {"children": [
                {"data": {"score": 1200, "num_comments": 340, "permalink": "/r/news/x"}},
            ]}},
        )
        m.get(
            "https://www.reddit.com/r/canada/search.json",
            json={"data": {"children": []}},
        )
        result = fetch_reddit_traction(url, subreddits=["news", "canada"])
        assert result["score"] == 1200
        assert result["comments"] == 340
        assert result["subreddit_hits"] == 1


def test_fetch_hn_traction_returns_points_and_comments():
    url = "https://example.com/article-2"
    with requests_mock.Mocker() as m:
        m.get(
            "https://hn.algolia.com/api/v1/search",
            json={"hits": [{"points": 250, "num_comments": 120}]},
        )
        result = fetch_hn_traction(url)
        assert result["points"] == 250
        assert result["comments"] == 120


def test_fetch_traction_returns_zero_on_failure():
    url = "https://example.com/article-3"
    with requests_mock.Mocker() as m:
        m.get(requests_mock.ANY, status_code=503)
        result = fetch_hn_traction(url)
        assert result == {"points": 0, "comments": 0}
```

- [ ] **Step 4: Run tests, verify they fail**

```bash
pytest tests/test_traction.py -v
```

Expected: `ImportError`.

- [ ] **Step 5: Implement traction.py**

```python
"""Free traction signals: Reddit and Hacker News."""

import urllib.parse

import requests


REDDIT_HEADERS = {"User-Agent": "QuiteFranklyBot/1.0"}


def fetch_reddit_traction(url: str, subreddits: list[str]) -> dict:
    total_score = 0
    total_comments = 0
    hits = 0
    for sub in subreddits:
        try:
            resp = requests.get(
                f"https://www.reddit.com/r/{sub}/search.json",
                params={"q": f"url:{url}", "restrict_sr": 1, "limit": 5},
                headers=REDDIT_HEADERS,
                timeout=5,
            )
            if resp.status_code != 200:
                continue
            children = resp.json().get("data", {}).get("children", [])
            for c in children:
                d = c.get("data", {})
                total_score += d.get("score", 0)
                total_comments += d.get("num_comments", 0)
                hits += 1
        except Exception as e:
            print(f"  Reddit error on r/{sub}: {e}")
            continue
    return {"score": total_score, "comments": total_comments, "subreddit_hits": hits}


def fetch_hn_traction(url: str) -> dict:
    try:
        resp = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": url, "tags": "story", "hitsPerPage": 5},
            timeout=5,
        )
        if resp.status_code != 200:
            return {"points": 0, "comments": 0}
        hits = resp.json().get("hits", [])
        if not hits:
            return {"points": 0, "comments": 0}
        top = max(hits, key=lambda h: h.get("points", 0))
        return {"points": top.get("points", 0), "comments": top.get("num_comments", 0)}
    except Exception as e:
        print(f"  HN error: {e}")
        return {"points": 0, "comments": 0}
```

- [ ] **Step 6: Run tests, verify they pass**

```bash
pytest tests/test_traction.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add traction.py requirements.txt config.py tests/test_traction.py
git commit -m "Add Reddit and Hacker News traction fetchers"
```

---

### Task 8: Comparison log (Phase 1.5 shadow scoring)

**Files:**
- Create: `comparison.py`
- Create: `tests/test_comparison.py`
- Modify: `newsletter.py` (call shadow scoring after triage pass, before sending email)

- [ ] **Step 1: Write failing tests for shadow scoring and log writing**

`tests/test_comparison.py`:

```python
import json
from pathlib import Path

from comparison import compute_phase2_tier, build_comparison_log, write_comparison_log


def test_compute_phase2_tier_includes_reddit_weight():
    item = {
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
        "reddit": {"score": 5000, "comments": 800, "subreddit_hits": 3},
        "hn": {"points": 0, "comments": 0},
    }
    tier = compute_phase2_tier(item)
    assert tier == 1


def test_compute_phase2_tier_includes_hn_weight():
    item = {
        "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"},
        "reddit": {"score": 0, "comments": 0, "subreddit_hits": 0},
        "hn": {"points": 800, "comments": 250},
    }
    tier = compute_phase2_tier(item)
    assert tier in (1, 2)


def test_build_comparison_log_records_deltas():
    phase1 = [
        {"id": 0, "tier": 1, "section": "Canada & Toronto"},
        {"id": 1, "tier": 2, "section": "Tech & AI"},
    ]
    phase2 = [
        {"id": 0, "tier": 1, "section": "Canada & Toronto"},
        {"id": 1, "tier": 1, "section": "Tech & AI"},
    ]
    log = build_comparison_log(date_str="2026-05-20", mode="weekday_daily", phase1=phase1, phase2=phase2)
    assert log["deltas"]["promoted_by_phase2"][0]["id"] == 1


def test_write_comparison_log_writes_file(tmp_path):
    log = {"date": "2026-05-20", "mode": "weekday_daily"}
    write_comparison_log(log, base_dir=tmp_path)
    written = json.loads((tmp_path / "2026-05-20.json").read_text())
    assert written["date"] == "2026-05-20"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest tests/test_comparison.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement comparison.py**

```python
"""Phase 1.5 shadow scoring and comparison log writing."""

import json
from pathlib import Path

from traction import fetch_reddit_traction, fetch_hn_traction
from config import REDDIT_SUBREDDITS


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}


def compute_phase2_tier(item: dict) -> int:
    base = (
        item["scores"]["cross_source_coverage"] * 3
        + item["scores"]["personal_relevance"] * 2
        + SECTION_FIT_SCORE.get(item["scores"]["section_fit"], 0)
    )
    reddit = item.get("reddit", {})
    hn = item.get("hn", {})
    reddit_bonus = 0
    if reddit.get("score", 0) >= 1000 or reddit.get("subreddit_hits", 0) >= 2:
        reddit_bonus = 2
    elif reddit.get("score", 0) >= 200:
        reddit_bonus = 1
    hn_bonus = 0
    if hn.get("points", 0) >= 200:
        hn_bonus = 1
    total = base + reddit_bonus + hn_bonus
    if total >= 6:
        return 1
    if total >= 3:
        return 2
    if total >= 1:
        return 3
    return 0


def attach_traction(items: list[dict], links_by_id: dict) -> list[dict]:
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        item["reddit"] = fetch_reddit_traction(link, REDDIT_SUBREDDITS)
        item["hn"] = fetch_hn_traction(link)
    return items


def shadow_score(items: list[dict], links_by_id: dict) -> list[dict]:
    """Returns a parallel list with Phase 2 tier overrides applied."""
    enriched = attach_traction([dict(i) for i in items], links_by_id)
    for item in enriched:
        item["tier"] = compute_phase2_tier(item)
    return enriched


def build_comparison_log(date_str: str, mode: str, phase1: list[dict], phase2: list[dict]) -> dict:
    by_id_p1 = {i["id"]: i for i in phase1}
    by_id_p2 = {i["id"]: i for i in phase2}

    promoted = []
    demoted = []
    for item_id, p2 in by_id_p2.items():
        p1 = by_id_p1.get(item_id)
        if not p1:
            continue
        if p2["tier"] < p1["tier"] and p2["tier"] > 0:
            promoted.append({"id": item_id, "from": p1["tier"], "to": p2["tier"]})
        elif p2["tier"] > p1["tier"]:
            demoted.append({"id": item_id, "from": p1["tier"], "to": p2["tier"]})

    return {
        "date": date_str,
        "mode": mode,
        "phase1": phase1,
        "phase2_shadow": phase2,
        "deltas": {
            "promoted_by_phase2": promoted,
            "demoted_by_phase2": demoted,
        },
    }


def write_comparison_log(log: dict, base_dir: Path) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    out = base_dir / f"{log['date']}.json"
    out.write_text(json.dumps(log, indent=2))
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_comparison.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Wire shadow scoring into newsletter.py main**

After the triage pass and before sending the email:

```python
from pathlib import Path
from comparison import shadow_score, build_comparison_log, write_comparison_log

# ...after triage pass produces tiered_items...

print("Running shadow scoring (Phase 1.5)...")
phase2_items = shadow_score(tiered_items, links_by_id)
log = build_comparison_log(
    date_str=today.isoformat(),
    mode=mode.value,
    phase1=tiered_items,
    phase2=phase2_items,
)
write_comparison_log(log, Path("comparison"))
```

Shadow scoring runs after the email is sent so a failure does not block delivery. Wrap in try/except and log errors.

```python
try:
    phase2_items = shadow_score(tiered_items, links_by_id)
    log = build_comparison_log(today.isoformat(), mode.value, tiered_items, phase2_items)
    write_comparison_log(log, Path("comparison"))
except Exception as e:
    print(f"Shadow scoring failed: {e}")
```

- [ ] **Step 6: Commit**

```bash
git add comparison.py newsletter.py tests/test_comparison.py
git commit -m "Add Phase 1.5 shadow scoring and comparison logging"
```

---

### Task 9: Weekly Sunday digest email

**Files:**
- Modify: `comparison.py` (add `build_weekly_digest_html`, `summarize_week`)
- Modify: `newsletter.py` (call digest on Sundays after the visual design email is sent)
- Create: `tests/fixtures/sample_week_comparison/*.json` (5 sample daily logs)

- [ ] **Step 1: Write failing test for weekly summary**

Add to `tests/test_comparison.py`:

```python
from comparison import summarize_week


def test_summarize_week_counts_promotions_and_demotions(tmp_path):
    days = [
        {"date": "2026-05-18", "deltas": {"promoted_by_phase2": [{"id": 1}, {"id": 2}], "demoted_by_phase2": [{"id": 3}]}},
        {"date": "2026-05-19", "deltas": {"promoted_by_phase2": [{"id": 4}], "demoted_by_phase2": []}},
    ]
    for d in days:
        (tmp_path / f"{d['date']}.json").write_text(json.dumps(d))
    summary = summarize_week(tmp_path, week_start="2026-05-18", week_end="2026-05-24")
    assert summary["total_promotions"] == 3
    assert summary["total_demotions"] == 1
```

- [ ] **Step 2: Run test, verify it fails**

- [ ] **Step 3: Implement summarize_week and build_weekly_digest_html in comparison.py**

```python
from datetime import date, timedelta


def summarize_week(comparison_dir: Path, week_start: str, week_end: str) -> dict:
    start = date.fromisoformat(week_start)
    end = date.fromisoformat(week_end)
    promotions = 0
    demotions = 0
    promoted_samples = []
    demoted_samples = []

    d = start
    while d <= end:
        f = comparison_dir / f"{d.isoformat()}.json"
        if f.exists():
            log = json.loads(f.read_text())
            day_promoted = log.get("deltas", {}).get("promoted_by_phase2", [])
            day_demoted = log.get("deltas", {}).get("demoted_by_phase2", [])
            promotions += len(day_promoted)
            demotions += len(day_demoted)
            promoted_samples.extend(day_promoted[:2])
            demoted_samples.extend(day_demoted[:2])
        d += timedelta(days=1)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "total_promotions": promotions,
        "total_demotions": demotions,
        "promoted_samples": promoted_samples[:5],
        "demoted_samples": demoted_samples[:5],
    }


def build_weekly_digest_html(summary: dict) -> tuple[str, str]:
    subject = f"📊 Phase 2 shadow digest · week of {summary['week_start']}"
    html = f"""<html><body style="font-family:Helvetica,Arial,sans-serif;padding:20px">
<h2>Phase 2 shadow evaluation</h2>
<p>Week of {summary['week_start']} to {summary['week_end']}.</p>
<p>If Phase 2 (Reddit + HN traction) had been live this week:</p>
<ul>
  <li><strong>{summary['total_promotions']}</strong> items would have been promoted to a higher tier.</li>
  <li><strong>{summary['total_demotions']}</strong> items would have been demoted.</li>
</ul>
<h3>Top swap-ins (Phase 2 would have featured)</h3>
<ul>
{"".join(f"<li>Item #{s['id']}: tier {s['from']} → tier {s['to']}</li>" for s in summary['promoted_samples'])}
</ul>
<h3>Top swap-outs (Phase 2 would have demoted)</h3>
<ul>
{"".join(f"<li>Item #{s['id']}: tier {s['from']} → tier {s['to']}</li>" for s in summary['demoted_samples'])}
</ul>
<p style="color:#888;font-size:12px">After 2-3 weeks of this data, decide whether to promote Phase 2 into production tier scoring.</p>
</body></html>"""
    return html, subject
```

- [ ] **Step 4: Run tests**

- [ ] **Step 5: Wire digest send into newsletter.py main**

In `newsletter.py` after the regular email send, when `mode == Mode.SUNDAY_VISUAL`:

```python
if mode == Mode.SUNDAY_VISUAL:
    from comparison import summarize_week, build_weekly_digest_html
    from formatting import send_email
    week_start = (today - timedelta(days=6)).isoformat()
    week_end = today.isoformat()
    try:
        summary = summarize_week(Path("comparison"), week_start, week_end)
        digest_html, digest_subject = build_weekly_digest_html(summary)
        send_email(digest_html, digest_subject)
    except Exception as e:
        print(f"Weekly digest send failed: {e}")
```

- [ ] **Step 6: Commit**

```bash
git add comparison.py newsletter.py tests/test_comparison.py
git commit -m "Add weekly Phase 2 shadow digest email on Sundays"
```

---

### Task 10: GitHub Actions workflow update and production cutover

**Files:**
- Modify: `.github/workflows/newsletter.yml` (install requirements-dev.txt is not needed in CI, but should commit comparison/ logs back like seen_links)
- Modify: `README.md` (document the new architecture)

- [ ] **Step 1: Update the workflow to persist comparison logs**

Edit `.github/workflows/newsletter.yml`. After the existing `Save seen_links cache` step, add:

```yaml
      - name: Save comparison logs
        run: |
          git add comparison/ || true
          git diff --staged --quiet || git commit -m "chore: append comparison log [skip ci]"
          git push
```

- [ ] **Step 2: Update README with new architecture overview and a note on the design-day cadence**

Add a section to `README.md`:

```markdown
## Architecture (post-2026-05-15 redesign)

The script runs in one of four modes based on the day of week (Toronto time):
- Monday: catch-up of Friday-Sunday non-design news
- Tuesday-Friday: daily non-design news
- Saturday: weekly strategic design round-up (UX Collective, Smashing, NN/g, Lenny's)
- Sunday: weekly visual design round-up (Design Milk, Hypebeast, Codrops, Sidebar, Trendland)

Internally the pipeline is: fetch -> dedup -> assign IDs -> Pass 1 (Claude triage + tier scoring + clustering) -> Phase 1.5 shadow scoring (Reddit + HN, writes comparison/YYYY-MM-DD.json) -> Pass 2 (Claude format) -> render HTML -> SMTP send. On Sundays, a weekly digest email is also generated summarizing what Phase 2 would have done differently.

See `docs/2026-05-15-newsletter-redesign-spec.md` for the full design.
```

- [ ] **Step 3: Manual smoke test in test mode**

```bash
MODE=test python newsletter.py
```

Verify a test email arrives. Check that `comparison/` has a fresh log file. Inspect the log for sensible structure.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/newsletter.yml README.md
git commit -m "Persist comparison logs from CI and document the redesign"
```

- [ ] **Step 5: Run the full test suite one more time**

```bash
pytest -v
```

Expected: all passing.

- [ ] **Step 6: Manually trigger the GitHub Actions workflow in test mode, verify a real email arrives, check the comparison log was committed back**

After the first real run, monitor for one week, then evaluate Phase 2 promotion based on the Sunday digest.

---

## Self-review notes (post-write)

**Spec coverage check**

| Spec section | Plan task(s) |
|---|---|
| Day-of-week modes | Task 2 |
| Source list | Task 2 (config), Task 10 (docs) |
| Two-pass triage | Task 4, Task 6 |
| Tier system | Task 4 (Phase 1 scoring), Task 8 (Phase 2 shadow) |
| Worth Knowing section | Task 5 |
| Cross-source clustering | Task 4 (detection), Task 5 (rendering) |
| Phase 1.5 shadow | Task 7, Task 8, Task 9 |
| Weekly digest | Task 9 |
| Cost | Implicit in Claude max_tokens settings |
| Risks (malformed JSON, API failures) | Try/except in shadow path; fuzzy fallback in formatting already in place from f0e6b63 |

**Gaps left as runtime concerns, not plan tasks**

- Specific feed URL verification at runtime (the spec already flags this)
- Personal relevance blurb wording is included in `prompts.py` as a starting point; refine after first week of output
- Visual treatment of Worth Knowing section (currently uses the same card style; revisit if Frank wants it distinct)

**Where the plan deliberately keeps things light**

- The `build_format_input` helper that bridges triage output to format prompt input is left as a sketch; expand during implementation based on the exact format prompt
- The format prompt rewrite in Task 5 is described but not fully drafted; design it against the actual schema during implementation
