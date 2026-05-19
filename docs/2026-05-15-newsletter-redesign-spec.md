---
title: Quite Frankly Newsletter Redesign
date: 2026-05-15
status: draft, pending approval
---

# Quite Frankly Newsletter Redesign — Spec

## Goal

Evolve the current single-mode daily briefing into a day-of-week-aware product that delivers two parallel signals:

1. **Personal relevance.** Stories that touch Frank's work as a senior product designer, his Toronto condo, his AI side projects, his job search, his transitional year.
2. **Cultural currency.** Stories that educated generalist friends and Canadian dinner-party conversations are running on, so Frank stays current without doomscrolling.

The redesign adds a wider source pool, a triage pass that scores and tiers items before formatting, day-of-week routing, and a shadow evaluation layer for the optional traction-signal upgrade.

---

## Product modes

The script branches on `datetime.weekday()` (Toronto time) and runs in one of three modes.

| Day | Mode | Window | Pool | Sections |
|---|---|---|---|---|
| Mon | Weekend catch-up | Fri 00:00 to Mon 06:00 Toronto | Weekday news pool (no design) | Standard 6 + Today in the World |
| Tue–Fri | Daily news | Previous 24h | Weekday news pool (no design) | Standard 6 + Today in the World |
| Sat | Designer day, strategic | Previous 7 days, minus items used in last design email | Strategic design pool | Single section: Design & Product, strategic |
| Sun | Designer day, visual | Previous 7 days, minus items used in last design email | Visual design pool | Single section: Design & Product, visual |

Monday's window is wider than 24 hours by design. RSS feeds typically still carry the previous week's items, so the Monday fetch naturally pulls Friday and weekend stories. The dedup check (`seen_links.json`) normally suppresses anything already shown. On Mondays only, dedup is bypassed for items whose current cross-source cluster size is ≥3, meaning the story is still being actively covered across multiple outlets. This lets Friday's biggest stories re-enter Monday's email if they're still dominating.

Weekend dedup is strict. Saturday and Sunday share a 7-day window, and Saturday marks items seen before Sunday runs.

---

## Source list

### Weekday news pool (Mon–Fri)

Grouped by default section assignment.

**Canada & Toronto**
- CBC (existing)
- Globe & Mail Toronto (existing)
- r/toronto (existing)
- BlogTO — hyperlocal city culture
- Toronto Star — Toronto daily currently missing
- National Post — Canadian political conversation
- National Newswatch — Canadian politics aggregator

**Toronto Housing**
- Globe & Mail Investing (existing, routed when content is housing-related)
- r/canadahousing (existing)
- Storeys — Toronto real estate news
- BetterDwelling — macro Canadian housing analysis
- MoneySense Real Estate — personal finance angle

**Tech & AI**
- TechCrunch (existing)
- Hacker News front page — dev culture signal
- Simon Willison — AI builder POV
- Stratechery — weekly tech strategy

**Finance & Markets**
- Yahoo Finance (existing)
- Globe & Mail Finance (existing)
- WSJ — markets and business
- MoneySense — Canadian personal finance

**US & Global**
- BBC (existing)
- NYT — educated generalist signal
- Economist — weekly global affairs
- NPR World — sober US/global
- Axios — Smart Brevity format

**Today in the World eligible (podcasts and other)**
- NYT The Daily — episode title and description
- Vox Today Explained — episode title and description
- CBC Frontburner — episode title and description
- NBC Meet the Press — weekly, Sunday episode surfaces in Monday catch-up

### Saturday design pool, strategic

- UX Collective
- Smashing Magazine
- NN/g
- Lenny's Newsletter

### Sunday design pool, visual

- Design Milk
- Hypebeast
- Codrops / tympanus.net
- Sidebar
- Trendland (low volume, occasional contributor)

### Source decisions and exclusions

| Source | Decision | Reason |
|---|---|---|
| The Cannabist | Excluded | Broken/defunct |
| James Altucher | Excluded | Dormant, no working feed |
| Publishers Weekly | Excluded | Book-industry niche, no fit |
| Trendland | Included (Sunday only) | Live but slow |
| Business of Fashion | Excluded | Blocks scrapers |
| Business Insider | Excluded | Blocks scrapers, low signal |
| Fox News Sunday | Excluded | No show-specific feed |
| Medium | Excluded | No usable site-wide top-stories feed |
| 4HWW / tim.blog | Excluded | Off-mission, self-improvement signal not selected |
| Quartz | Excluded | Off-mission |

---

## Architecture

### Pipeline phases

1. **Fetch.** Pull all feeds appropriate for the day's mode. Same dedup logic as today, with the Monday-catch-up exception above.
2. **Triage pass (new).** Send the full headline pool to Claude with a structured prompt. Claude returns JSON: per-item tier, section assignment, cluster ID, and reasoning trace.
3. **Shadow scoring (Phase 1.5, runs in parallel).** Hits Reddit JSON endpoints and HN Algolia API to fetch traction data. Recomputes tiers with traction signals weighted in. Writes alternate ranking to comparison log. Does not affect the sent email.
4. **Format pass (existing).** Send selected items to Claude with the current formatting prompt, plus cluster metadata so multi-source corroboration can render in the source line.
5. **Render and send.** Existing HTML build and SMTP logic, with one new section block for Today in the World.

### Two-pass Claude rationale

Pass 1 is doing fundamentally different work than pass 2. Pass 1 reasons about which items deserve attention. Pass 2 writes for a reader. Mixing both in one call (as today) means the model trades off between selection logic and prose quality. Splitting the calls gives each prompt a single job.

### Triage pass output schema

```json
{
  "items": [
    {
      "id": "abc123",
      "headline": "Original headline text",
      "source": "NYT",
      "tier": 1,
      "section": "US & Global",
      "cluster_id": "cl_004",
      "scores": {
        "cross_source_coverage": 3,
        "personal_relevance": 2,
        "section_fit": "good"
      },
      "promotion_to_today_in_the_world": false,
      "reasoning": "Major geopolitical story covered by NYT, BBC, Economist."
    }
  ],
  "clusters": [
    {
      "id": "cl_004",
      "primary_source": "NYT",
      "also_in": ["BBC", "Economist", "NPR World"],
      "canonical_headline": "..."
    }
  ]
}
```

---

## Tier system

Each item gets a total score from three free signals in Phase 1.

| Signal | Weight | Source | Phase |
|---|---|---|---|
| Cross-source coverage | 3 | Detected by Claude in triage pass | 1 |
| Personal relevance | 2 | Scored by Claude against Frank-context blurb | 1 |
| Section fit | 1 | Scored by Claude based on default mapping | 1 |
| Reddit traction | 2 | Reddit public JSON, upvotes + comments on r/news, r/worldnews, r/canada, r/toronto, r/technology, r/canadahousing | 1.5 shadow, 2 production |
| HN traction | 1 | HN Algolia API, points and comments | 1.5 shadow, 2 production |

### Tier thresholds (Phase 1)

| Tier | Total score | Treatment |
|---|---|---|
| 1 — Featured | ≥6 | Full story: headline, two paragraphs, image, "What this means for you" if applicable |
| 2 — Worth reading | 3–5 | One-line bullet in Other Headlines within the section |
| 3 — Background | 1–2 | Sent to Everything Else at the bottom of the email, capped at 5 items per section |
| Dropped | 0 | Excluded entirely (Claude judged it not worth surfacing) |

### Personal relevance blurb

Stored as a constant in `newsletter.py`, fed into the triage prompt. Initial draft:

> Frank is a senior product designer at theScore in Toronto, aiming for staff or principal product designer roles. He is rebuilding his portfolio, running AI side projects (Claude-based research tools, a workout PWA), and selling a Leslieville condo. He does not gamble or follow sports. He cares about Canadian politics in the dinner-table sense, Toronto housing market dynamics, AI tooling for designers, design industry moves at staff level, and personal finance for a transitional year. He is turning 38 in June.

Reviewed every 3 months or when his focus shifts materially.

---

## Section structure

### Weekday email

In order:
1. Canada & Toronto (2 featured + Other Headlines)
2. Toronto Housing (2 featured + Other Headlines)
3. Tech & AI (2 featured + Other Headlines)
4. Finance & Markets (1 featured + Other Headlines)
5. US & Global (1 featured + Other Headlines)
6. Today in the World (3–7 items, new)
7. Everything Else (Tier 3 background items, capped at 5 per section)

Design & Product is removed from weekday emails. Design news lives on weekends only.

### Today in the World logic

An item gets promoted to Today in the World when ALL of these are true:
- Tier 1 score
- Cultural currency signal strong (cross-source coverage ≥3 OR strong podcast match)
- Doesn't naturally fit Canada & Toronto, Toronto Housing, Tech & AI, Finance & Markets, or US & Global with a clean section_fit

Today in the World renders 3–7 items per day depending on what qualifies. Empty section is suppressed.

### Weekend email

Single-section layout. No Today in the World or Everything Else. 5–8 featured items, no Other Headlines bucket. Source list lives in the footer.

---

## Cross-source clustering

### How it works

Claude detects clusters in the triage pass. The prompt includes an explicit instruction: "When two or more items describe the same underlying story, assign them the same cluster_id. Pick the version with the most distinctive or well-written headline as the primary."

### How it renders

Source line shows corroboration. Examples:

- Single source: `CBC`
- Cluster of 2: `CBC, Toronto Star`
- Cluster of 3+: `NYT (also in BBC, Economist, NPR)`

This makes the corroboration signal visible to the reader without adding visual clutter.

---

## Phase 1.5 shadow evaluation

### What runs daily

After Phase 1's triage pass completes and the email is sent, a separate function:

1. For each item in the triage output, query Reddit JSON for cross-posts on relevant subreddits. Capture upvote count, comment count, post age.
2. For each item, query HN Algolia for the URL. Capture points, comments, post age.
3. Recompute tier scores with Reddit and HN signals included.
4. Write `comparison/YYYY-MM-DD.json` with:
   - Phase 1 tier assignments (the ones used in the actual email)
   - Phase 2 shadow tier assignments
   - Deltas: promoted, demoted, added, dropped
   - Traction signal summary: API call counts, items with non-zero traction data, hit rate

### Weekly digest

Sunday night, a separate digest email is generated and sent to Frank, summarizing the week's deltas:

- Total items where Phase 2 disagreed with Phase 1
- Top 5 swap-ins (stories Phase 2 would have featured, Phase 1 didn't)
- Top 5 swap-outs (stories Phase 1 featured, Phase 2 would have demoted)
- Trend observations (e.g., "Phase 2 consistently downgrades r/toronto top posts, consistently elevates HN front-page Tech & AI items")

### Evaluation criteria

After 2–3 weeks, Frank decides Phase 2 promotion based on subjective review:

- Do swap-ins look more important on reflection?
- Do demotions look right?
- Did Phase 2 catch the week's dominant stories earlier than Phase 1?

Promotion to production means deleting the shadow layer and wiring the traction signals into the live tier scoring. No new code, just a configuration flag.

---

## Cost

| Component | Monthly |
|---|---|
| Claude triage pass (Phase 1) | ~$1.50 |
| Claude format pass (existing) | ~$1.50 |
| Reddit API | $0 |
| HN Algolia API | $0 |
| GitHub Actions | $0 (well within free tier) |
| Gmail SMTP | $0 |
| Total | ~$3/month (up from $1.50) |

Phase 1.5 shadow mode adds no Claude cost (signals are appended to the same pass-1 output) but adds ~30 seconds of runtime per day for the Reddit/HN API calls.

---

## Risks and edge cases

| Risk | Mitigation |
|---|---|
| Triage pass returns malformed JSON | Strict schema parsing, fall back to current single-pass behavior if parsing fails. Email still ships. |
| Reddit or HN API rate-limits or fails | Shadow mode catches its own errors and logs them. Phase 1 email is unaffected. |
| Cross-source clustering misses obvious overlaps | Triage prompt includes 2–3 worked examples. Format pass uses cluster metadata but degrades gracefully if missing. |
| Today in the World is empty most days | Suppressed when empty. No "no stories today" placeholder. |
| Weekend design pool is thin on a slow week | Section renders with whatever's available, footer notes the date range covered. |
| Personal relevance blurb goes stale | Calendar reminder every 3 months to review. |
| Monday window pulls duplicate items already in Friday's email | Cluster-size-≥3 exception is the only path back in. Otherwise dedup holds. |

---

## Out of scope

- Twitter/X traction signals (API too expensive, too restrictive)
- Facebook/LinkedIn signals (closed)
- Google Trends integration
- Real engagement metrics (page views, clicks, impressions)
- A reader-facing feedback loop ("mark this as read/cared about")
- Multi-recipient support
- Newsletter web archive
- Email open-rate tracking

These belong in Phase 3 or never. They were considered and consciously cut.

---

## Roadmap

| Phase | Ships | Contents |
|---|---|---|
| 1 | First | Day-of-week routing, expanded source pool, two-pass Claude triage with cross-source clustering, tier system, Today in the World section, weekend strategic/visual split |
| 1.5 | Same release | Shadow Reddit/HN scoring writes comparison logs, Sunday weekly digest email |
| 2 | After 2–3 weeks of comparison data, if warranted | Promote traction signals into production tier scoring |
| 3 | Backlog, never if not needed | Google Trends, more sophisticated relevance modeling, reader feedback loop |

---

## Open questions for review

1. Source URL verification: a few feeds (BetterDwelling, podcast feeds for The Daily / Today Explained / Frontburner / Meet the Press, WSJ behind paywall, National Post and National Newswatch RSS) need to be confirmed working at implementation time. Treat as implementation detail; flag any that fail before going live.
2. The personal relevance blurb above is a first draft. Confirm it captures the right priorities before pass 1 prompt is finalized.
3. The Today in the World rendering: same card style as other sections, or visually distinct (e.g., gradient header) to signal "outside the regular rotation"?
4. Weekly digest email: should it go to the same inbox or a separate one to keep it from cluttering daily reads?
