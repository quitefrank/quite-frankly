# Markets block in Finance & Markets: Design

**Date:** 2026-11-11
**Status:** Draft, awaiting Frank's review

## Problem

Morning Brew opens with a MARKETS block: a strip of index closes, one featured
stock, and a short paragraph on why the market and that stock moved. Quite
Frankly's Finance & Markets section has news stories but no numbers. Frank wants
the Brew's block adapted to his newsletter, Canada-first, with 3 featured stocks
from the previous session's movers.

## Decisions already made (2026-11-11)

- **Universe:** US and TSX large caps. No micro-caps, no leveraged ETFs.
- **Selection:** biggest gainer, biggest loser, and one mover weighted toward
  Frank's interests (AI, design tools, Canadian housing and banks).
- **Strip:** SPX, Tech, Energy, Finance, Realty, Gold: a sector overview,
  daily % only, no price levels, to save width. All six come straight from
  the FMP free tier, so the strip needs no citation check.
  - SPX: `quote?symbol=^GSPC`.
  - Sectors: `sector-performance-snapshot` for NYSE and Nasdaq, averaged.
    This is the equal-weighted average stock, not a size-weighted sector ETF
    (XLK, XLE, XLF, XLRE are premium), so a Tech tile can read red on a day
    Nvidia rallies. The footnote says "average US stock".
  - Gold: daily closes for `GCUSD`, because futures trade overnight and an
    8am quote is that morning's move.
  - History, all 2026-11-11: TSX/S&P/Nasdaq/10Y/CAD-USD with values →
    SPX/IXIC/XGRO/XEQT/Gold as % only → this sector set. XGRO and XEQT were
    dropped because they needed web search (premium on FMP) and Frank wanted
    a sector read rather than his own funds.
- **Data:** hybrid. FMP free tier for the numbers it serves, Claude web search
  for the TSX close and the 3 movers.
- **Grounding rule:** every "why" comes from a retrieved article. A mover without
  one is dropped, never explained from model knowledge.

## What the free FMP tier serves (probed 2026-11-11)

| Endpoint | Result |
|---|---|
| `quote?symbol=^GSPC`, `^IXIC` | works |
| `quote?symbol=USDCAD` | works |
| `treasury-rates?from&to` | works (`year10`) |
| `quote` for some US large caps (AAPL, SHOP) | works |
| `^GSPTSE`, any `.TO`, US-listed Canadians (RY, TD, ENB), EWC | premium |
| `batch-quote`, `company-screener`, `news/stock` | premium |
| `biggest-gainers` / `biggest-losers` | free but unusable: micro-caps and leveraged ETFs |

Limit: 250 calls/day. The block uses about 8.

## Layout

Rendered at the top of the Finance & Markets card, above the featured story.
Everything already in the section stays unchanged.

```
📈 FINANCE & MARKETS
┌ SPX ──┬ Tech ─┬ Energy┬Finance┬ Realty┬ Gold ─┐
│+1.45% │+0.46% │+1.19% │+0.99% │+0.71% │-2.05% │
└───────┴───────┴───────┴───────┴───────┴───────┘
Markets: One sentence on the day, from the cited market wrap.

▲ CRWV  CoreWeave   +25.4%  Why it moved, one sentence.
▼ XXX   Name         −8.1%  Why it moved, one sentence.
▲ SHOP  Shopify      +2.3%  Why it moved, one sentence.
As of Nov 10 close.

[featured story, Other Headlines, What this means: unchanged]
```

- Tiles: 5 columns on desktop. The email is a fixed-width table layout, so
  tiles use a single-row `<table>`, which survives Gmail and Outlook.
- Up/down colour: green and red text on the % only, plus ▲/▼ glyphs so the
  direction never depends on colour alone. Dark-mode palette gets its own pair.
- Ticker links go to the cited article, matching how stories link to sources.
- No left-border accent on rows (standing rule). Rows separate with a top
  border, as Other Headlines do.

## Pipeline

New module `markets.py`, called from `newsletter.py` on weekday editions only
(weekend editions are design-only and have no Finance section).

1. **`fetch_strip()`** (FMP, 4 calls). S&P 500 and Nasdaq from `quote`; CAD/USD
   as `1 / USDCAD` with the % change inverted; US 10Y from the last two
   `treasury-rates` rows, change shown in bps.
2. **`research_movers(session_date)`** (one Claude call with the
   `web_search` server tool, max 5 searches). Claude finds the previous
   session's market wrap and returns structured output via tool use:
   - `tsx_close`, `tsx_change_pct`, `market_summary` (one sentence)
   - up to 6 candidate movers: `symbol`, `name`, `exchange`, `change_pct`,
     `why` (one sentence), `source_url`, `interest_tag` (ai, design, housing,
     banks, or none)
   Search is steered to S&P 500 and TSX 60 names and to wire and
   newspaper coverage (Reuters, AP, Globe and Mail, CNBC, Bloomberg).
3. **`verify(candidates, citations)`**, in code:
   - Each % figure must appear in the cited text Claude returns for that
     candidate (tolerance: rounding to 1 decimal). Fail → drop.
   - `source_url` must be one of the URLs the search actually returned. Fail → drop.
   - If FMP serves the symbol, a quote call cross-checks the %. A gap over
     0.5 points → drop. A premium response skips this check, and the article
     check alone still applies.
   - Same rules for the TSX tile. If it fails, the strip shows 4 tiles.
4. **`pick_three(verified)`**, in code: largest positive %, largest negative %,
   then the largest |%| remaining among candidates with an `interest_tag`,
   falling back to the largest |%| remaining. Fewer than 3 verified → show
   what survived. Zero → render the strip without stock rows.
5. **Render** in `formatting.py` as a new `render_markets_block(data, palette)`,
   inserted into the Finance & Markets card ahead of its stories.

The `why` sentences follow the newsletter voice: dry, specific, no em dashes. The
prompt includes the voice rules already in `prompts.py`.

## Failure behaviour

The block is additive and must never stop the email going out.

- Any exception in `markets.py` → log it, render the section without the block.
- FMP down → no strip; movers can still render.
- Web search unavailable → strip without TSX and without stock rows.
- Stale data guard: if FMP's quote timestamp is older than 4 calendar days
  (long weekend plus holiday), skip the strip. The "As of" line always shows
  the session date the data belongs to.
- Monday editions cover Friday's session.

## Cost

- FMP: free, about 8 of 250 daily calls.
- Claude: web search is $10 per 1,000 searches, so up to 5 a day is about
  $1.50/month, plus about $0.03/day in tokens. Roughly $2.50/month total, billed
  to the existing Anthropic key.

## Prerequisites

- `FMP_API_KEY`: saved as a GitHub secret and in local `.env` (2026-11-11).
  The workflow's run step needs `FMP_API_KEY: ${{ secrets.FMP_API_KEY }}`
  added to its `env:`.
- Web search must be enabled for the Anthropic organisation. Not yet verified.
  The first build step is a single test call, and the build stops there if it
  fails.

## Testing

- Unit: `pick_three` ordering and fallbacks; `verify` drops on missing
  number, foreign URL, FMP mismatch; CAD/USD inversion; bps calculation;
  stale-data guard.
- Fixtures: recorded FMP JSON and a recorded web-search response in
  `tests/fixtures/`, so tests never hit the network.
- Render: snapshot of the block in light and dark palettes; screenshot review
  against this layout before shipping.
- Integration: block failure leaves the rest of the email byte-identical.

## Out of scope

- A weekly deep-dive ("Stock of the week").
- Historical charts or sparklines.
- TSX 60 movers ranked from a full price scan (needs a paid plan).
