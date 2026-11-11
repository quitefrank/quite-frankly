"""Markets block for the Finance & Markets section.

Morning-Brew-style strip of daily % moves (SPX, Tech, Energy, Finance,
Real Estate, Gold) plus three featured movers from the previous session, each
with a sourced one-line "why". The strip shows movement only, no price levels,
to keep it narrow.

Two sources, one rule:
  - FMP free tier supplies the whole strip straight from a feed: the S&P 500
    quote, the sector snapshot, and gold's daily closes.
  - One Claude call with the web_search server tool supplies the mover
    candidates, because the free tier's gainers/losers lists are micro-caps
    and leveraged ETFs and it has no stock news.
  - A model-reported number only renders if it appears in text Claude cited
    from the URL it names, and the URL came back from a real search. When FMP
    also serves the symbol, the % has to agree with FMP's quote. Anything that
    fails is dropped, never explained from model knowledge.

Everything here is additive: build_markets_data() swallows every failure and
returns None (or a partial block), so the email always goes out.

Spec: docs/superpowers/specs/2026-11-11-markets-block-design.md
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_TIMEOUT = 15
TORONTO = ZoneInfo("America/Toronto")

MARKETS_MODEL = "claude-sonnet-4-6"
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}
MAX_CONTINUATIONS = 3  # pause_turn resumes for long server-tool turns

STALE_AFTER_DAYS = 4        # long weekend plus a holiday
FMP_MAX_GAP_POINTS = 0.5    # article % vs FMP % disagreement that drops a mover
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSEARCA", "NYSE AMERICAN"}
INTEREST_TAGS = {"ai", "design", "housing", "banks"}

# Strip order, left to right: market anchor, four sectors, gold.
# Gold isn't labelled by ticker: GOLD is Barrick's, and the futures code GC
# means nothing to a reader.
INDEX_TILES = (("^GSPC", "SPX"),)
# FMP sector name -> tile label. The sector snapshot is the equal-weighted
# average stock per exchange, so a Tech tile is breadth, not XLK: hundreds of
# small Nasdaq names can pull it red on a day Nvidia rallies. The size-weighted
# sector ETFs (XLK, XLE, XLF, XLRE) are premium on FMP.
SECTOR_TILES = (
    ("Technology", "Tech"),
    ("Energy", "Energy"),
    ("Financial Services", "Finance"),
    ("Real Estate", "Realty"),
)
SECTOR_EXCHANGES = ("NYSE", "NASDAQ")
GOLD_SYMBOL, GOLD_LABEL = "GCUSD", "Gold"


# ── FMP ───────────────────────────────────────────────────────────────────────

class FMPUnavailable(Exception):
    """Premium-gated symbol, restricted endpoint, or bad response."""


def _fmp_get(path: str, params: dict, session=requests) -> list:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise FMPUnavailable("FMP_API_KEY not set")
    resp = session.get(f"{FMP_BASE}/{path}", params={**params, "apikey": key}, timeout=FMP_TIMEOUT)
    # Gated requests come back with a plain-text "Premium ..." or
    # "Restricted Endpoint ..." body instead of JSON.
    try:
        data = resp.json()
    except ValueError:
        raise FMPUnavailable(resp.text[:80])
    if not isinstance(data, list) or not data:
        raise FMPUnavailable(f"empty response for {path}")
    return data


def fmp_quote(symbol: str, session=requests) -> dict:
    return _fmp_get("quote", {"symbol": symbol}, session)[0]


def tile(label: str, pct: float) -> dict:
    return {
        "label": label,
        "change": format_pct(pct),
        "direction": "up" if pct > 0 else "down" if pct < 0 else "flat",
    }


def format_pct(pct: float) -> str:
    return f"{pct:+.2f}%"


def session_date_from_quote(quote: dict) -> date:
    return datetime.fromtimestamp(quote["timestamp"], TORONTO).date()


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_index_tiles(today: date, session=requests) -> tuple[dict[str, dict], date | None]:
    """Index tiles (SPX) keyed by label, plus the date their quotes carry.

    Each tile fails on its own. A stale quote timestamp drops both rather
    than showing last week's move as yesterday's.
    """
    tiles: dict[str, dict] = {}
    as_of: date | None = None
    for symbol, label in INDEX_TILES:
        try:
            q = fmp_quote(symbol, session)
            stamp = session_date_from_quote(q)
        except (FMPUnavailable, requests.RequestException, KeyError) as e:
            print(f"[markets] {label} unavailable ({e})", flush=True)
            continue
        if (today - stamp).days > STALE_AFTER_DAYS:
            print(f"[markets] {label} stale (as of {stamp}); skipping", flush=True)
            continue
        as_of = as_of or stamp
        tiles[label] = tile(label, q["changePercentage"])
    return tiles, as_of


def fetch_sector_tiles(session_date: date, session=requests) -> dict[str, dict]:
    """Sector tiles keyed by label: the mean of the NYSE and Nasdaq averages.

    Either exchange alone still produces a tile; a sector missing from both
    is skipped.
    """
    by_sector: dict[str, list[float]] = {}
    for exchange in SECTOR_EXCHANGES:
        try:
            rows = _fmp_get(
                "sector-performance-snapshot",
                {"date": session_date.isoformat(), "exchange": exchange},
                session,
            )
        except (FMPUnavailable, requests.RequestException) as e:
            print(f"[markets] sectors on {exchange} unavailable ({e})", flush=True)
            continue
        for r in rows:
            if r.get("date") == session_date.isoformat() and "averageChange" in r:
                by_sector.setdefault(r.get("sector"), []).append(r["averageChange"])
    tiles = {}
    for sector, label in SECTOR_TILES:
        values = by_sector.get(sector)
        if values:
            tiles[label] = tile(label, sum(values) / len(values))
    return tiles


def session_change_pct(rows: list[dict], session_date: date) -> float:
    """Close-to-close % for session_date from FMP daily rows.

    Used for gold (futures trade overnight, so a live quote at 8am is that
    morning's move) and the movers cross-check (a live quote during market
    hours is today's move: CI run 43074369231 compared NVDA's Nov 10 -5.47%
    against a live +4.55% and dropped a correct figure).
    """
    by_date = sorted((r for r in rows if r["date"] <= session_date.isoformat()), key=lambda r: r["date"])
    if len(by_date) < 2 or by_date[-1]["date"] != session_date.isoformat():
        raise FMPUnavailable(f"no close for {session_date}")
    close, prior = by_date[-1]["price"], by_date[-2]["price"]
    return (close / prior - 1) * 100


def fmp_session_change(symbol: str, session_date: date, session=requests) -> float:
    rows = _fmp_get(
        "historical-price-eod/light",
        {"symbol": symbol, "from": (session_date - timedelta(days=10)).isoformat()},
        session,
    )
    return session_change_pct(rows, session_date)


def fetch_gold_tile(session_date: date, session=requests) -> dict | None:
    try:
        rows = _fmp_get(
            "historical-price-eod/light",
            {"symbol": GOLD_SYMBOL, "from": (session_date - timedelta(days=10)).isoformat()},
            session,
        )
        return tile(GOLD_LABEL, session_change_pct(rows, session_date))
    except (FMPUnavailable, requests.RequestException, KeyError, ZeroDivisionError) as e:
        print(f"[markets] Gold unavailable ({e})", flush=True)
        return None


# ── Web-search research ───────────────────────────────────────────────────────

REPORT_TOOL = {
    "name": "report_markets",
    "description": "Report the session's one-line market summary and mover candidates. Call exactly once, after searching and after writing the evidence lines.",
    "input_schema": {
        "type": "object",
        "properties": {
            "market_summary": {"type": "string"},
            "summary_source_url": {"type": ["string", "null"]},
            "candidates": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "name": {"type": "string"},
                        "exchange": {"type": "string", "description": "NYSE, NASDAQ, or TSX"},
                        "change_pct": {"type": "number", "description": "Signed, e.g. -5.2"},
                        "why": {"type": "string"},
                        "source_url": {"type": "string"},
                        "interest_tag": {"type": "string", "enum": ["ai", "design", "housing", "banks", "none"]},
                    },
                    "required": ["symbol", "name", "exchange", "change_pct", "why", "source_url", "interest_tag"],
                },
            },
        },
        "required": ["market_summary", "summary_source_url", "candidates"],
    },
}


def research_prompt(session_date: date) -> str:
    """Phase 1: search and write the evidence as cited prose. No report tool
    is offered here, because given one the model skips straight to it and
    writes no text for citations to attach to (CI run 43073024456: 40 URLs
    searched, 0 cited)."""
    day = session_date.strftime("%A, %B %-d, %Y")
    return f"""Research the stock market session of {day} for a Toronto reader's morning newsletter.

Find:
1. Why markets moved that day, from wire or newspaper closing coverage (Reuters, AP, The Globe and Mail, CNBC, Bloomberg, Financial Post).
2. Up to 6 large-cap stocks (S&P 500 or TSX 60 members only) that made notable moves that day and have a reported reason. Include the biggest reported gainers and losers. Prefer, where they moved notably, companies in AI, design and creative software, Canadian housing, or Canadian banks. No penny stocks, no ETFs, no stocks without a reported reason.

Write your findings as short plain sentences: one for the market's move, and one per stock stating its ticker, its % move for that session as the source states it, and the reported reason. Each sentence must draw directly on a search result so it carries a citation; the cited figures are checked against the source. Leave out any stock whose % move or reason for that session you can't find in a source."""


REPORT_INSTRUCTIONS = """Now call report_markets once, using only the findings you just wrote.

- Include only stocks whose % move and reason appear in your cited findings. source_url is the URL of the search result you cited for that stock; summary_source_url likewise for the market sentence.
- change_pct is the session's % move, signed, exactly as the source states it.
- "why" is one sentence, under 25 words, plain and specific, with a light dry touch at most. No em dashes. Don't start with the company name.
- market_summary is one sentence, under 30 words, no em dashes.
- interest_tag: ai, design, housing or banks where it clearly fits, else none."""


def _collect_evidence(content: list) -> tuple[dict[str, list[str]], set[str], dict | None]:
    """Cited text per URL, every URL search returned, and the report tool input."""
    cited: dict[str, list[str]] = {}
    searched: set[str] = set()
    report = None
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "web_search_tool_result":
            results = getattr(block, "content", None)
            if isinstance(results, list):
                for r in results:
                    url = getattr(r, "url", None)
                    if url:
                        searched.add(url)
        elif btype == "text":
            for c in getattr(block, "citations", None) or []:
                url = getattr(c, "url", None)
                text = getattr(c, "cited_text", None)
                if url and text:
                    cited.setdefault(url, []).append(text)
        elif btype == "tool_use" and getattr(block, "name", None) == "report_markets":
            report = block.input
    return cited, searched, report


def research_movers(session_date: date, client=None) -> dict | None:
    """Two Claude calls: cited research, then a forced report. Returns report +
    evidence, or None."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Phase 1: search and cited findings, resuming any paused server-tool turn
    # as one assistant message so the model continues where it stopped.
    user = {"role": "user", "content": research_prompt(session_date)}
    messages = [user]
    findings: list = []
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = client.messages.create(
            model=MARKETS_MODEL,
            max_tokens=4000,
            tools=[WEB_SEARCH_TOOL],
            messages=messages,
        )
        findings.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        messages = [user, {"role": "assistant", "content": list(findings)}]

    # Phase 2: structure the findings. Forced tool choice, so no new searching.
    # web_search stays defined because the history contains its blocks.
    resp = client.messages.create(
        model=MARKETS_MODEL,
        max_tokens=2000,
        tools=[WEB_SEARCH_TOOL, REPORT_TOOL],
        tool_choice={"type": "tool", "name": "report_markets"},
        messages=[
            user,
            {"role": "assistant", "content": list(findings)},
            {"role": "user", "content": REPORT_INSTRUCTIONS},
        ],
    )

    cited, searched, _ = _collect_evidence(findings)
    _, _, report = _collect_evidence(resp.content)
    if report is None:
        print("[markets] research returned no report", flush=True)
        return None
    return {"report": report, "cited": cited, "searched": searched}


# ── Verification ──────────────────────────────────────────────────────────────

_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s?cent|percent)", re.IGNORECASE)


def _pct_in_text(pct: float, text: str) -> bool:
    """True if |pct| is stated in text, allowing the source's own rounding."""
    target = abs(pct)
    for m in _PCT_RE.finditer(text):
        raw = m.group(1)
        n = float(raw)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if round(target, decimals) == round(n, decimals):
            return True
    return False


def _explain_drop(label: str, url: str | None, evidence: dict) -> None:
    """Log what the check saw, so a high drop rate can be diagnosed from CI."""
    in_search = bool(url) and url in evidence["searched"]
    snippets = evidence["cited"].get(url or "", [])
    print(f"[markets]   {label}: url={url} in_search={in_search} cited_snippets={len(snippets)}", flush=True)
    for s in snippets[:3]:
        print(f"[markets]     cited: {s[:200]!r}", flush=True)
    if not snippets:
        print(f"[markets]     cited urls available: {sorted(evidence['cited'])[:8]}", flush=True)


def _evidence_for(url: str | None, evidence: dict) -> str:
    if not url or url not in evidence["searched"]:
        return ""
    return " ".join(evidence["cited"].get(url, []))


def verify_summary(evidence: dict) -> str:
    """The summary has no number to match, so it needs a searched, cited source."""
    rep = evidence["report"]
    summary = _clean(rep.get("market_summary") or "")
    if summary and _evidence_for(rep.get("summary_source_url"), evidence):
        return summary
    if summary:
        print("[markets] market summary uncited; dropping it", flush=True)
    return ""


_NAME_STOPWORDS = {"the", "inc", "corp", "corporation", "company", "co", "group", "holdings", "ltd", "limited", "plc"}


def _mentions_company(c: dict, text: str, url: str) -> bool:
    """Ticker (as a word) or the first distinctive word of the name appears in
    the cited text or the page URL. Ties the cited page to this stock, so a
    reason can't be borrowed from a page about something else."""
    sym = c.get("symbol", "")
    if sym and (re.search(rf"\b{re.escape(sym)}\b", text) or re.search(rf"\b{re.escape(sym.lower())}\b", url.lower())):
        return True
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&'-]+", c.get("name", "")) if w.lower() not in _NAME_STOPWORDS]
    if words and len(words[0]) >= 3:
        word = words[0].lower()
        return word in text.lower() or word in url.lower()
    return False


def verify_candidates(evidence: dict, change_fn) -> list[dict]:
    """Keep movers whose figure and source hold up. change_fn(symbol) returns
    the session's % from FMP daily closes.

    US stocks FMP serves: the article's % must match FMP within 0.5 points,
    the page must be a searched, cited result that names the company, and the
    tile shows FMP's figure. Cited snippets are short and often cut-off
    tables, so a word-for-word match rejected correct figures (CI run
    43074369231: 6 of 6 dropped). Everything else (TSX, FMP-premium symbols)
    keeps the word-for-word check.
    """
    verified = []
    for c in evidence["report"].get("candidates", []):
        sym = c.get("symbol", "?")
        url = c.get("source_url") or ""
        text = _evidence_for(url, evidence)
        if not text:
            print(f"[markets] {sym}: source not from search or uncited; dropped", flush=True)
            _explain_drop(sym, url, evidence)
            continue

        fmp_pct = None
        if c.get("exchange", "").upper() in US_EXCHANGES:
            try:
                fmp_pct = change_fn(sym)
            except (FMPUnavailable, requests.RequestException, KeyError, ZeroDivisionError):
                fmp_pct = None  # premium symbol: fall back to the word-for-word check

        if fmp_pct is not None:
            if abs(fmp_pct - c["change_pct"]) > FMP_MAX_GAP_POINTS:
                print(f"[markets] {sym}: article {c['change_pct']}% vs FMP {fmp_pct:.2f}%; dropped", flush=True)
                continue
            if not _mentions_company(c, text, url):
                print(f"[markets] {sym}: cited page doesn't name the company; dropped", flush=True)
                _explain_drop(sym, url, evidence)
                continue
            verified.append({**c, "change_pct": round(fmp_pct, 2)})
            continue

        if not _pct_in_text(c["change_pct"], text):
            print(f"[markets] {sym}: {c['change_pct']}% not in cited text; dropped", flush=True)
            _explain_drop(sym, url, evidence)
            continue
        verified.append(c)
    return verified


def pick_three(verified: list[dict]) -> list[dict]:
    """Biggest gainer, biggest loser, then the biggest remaining interest-tagged
    mover (falling back to the biggest remaining move). Order: as picked."""
    picks: list[dict] = []
    remaining = list(verified)

    def take(pool, key):
        if pool:
            best = max(pool, key=key)
            picks.append(best)
            remaining.remove(best)

    take([c for c in remaining if c["change_pct"] > 0], lambda c: c["change_pct"])
    take([c for c in remaining if c["change_pct"] < 0], lambda c: -c["change_pct"])
    tagged = [c for c in remaining if c.get("interest_tag") in INTEREST_TAGS]
    take(tagged or remaining, lambda c: abs(c["change_pct"]))
    # Fewer than two directions available: fill up to 3 by size.
    while len(picks) < 3 and remaining:
        take(remaining, lambda c: abs(c["change_pct"]))
    return picks


def _clean(text: str) -> str:
    return text.replace(" — ", ", ").replace("—", ", ").strip()


# ── Orchestrator ──────────────────────────────────────────────────────────────

def build_markets_data(today: date | None = None, client=None, session=requests) -> dict | None:
    """Assemble the block. Never raises; returns None when nothing survives."""
    today = today or datetime.now(TORONTO).date()
    try:
        index_tiles, as_of = fetch_index_tiles(today, session)
    except Exception as e:
        print(f"[markets] index tiles failed ({e})", flush=True)
        index_tiles, as_of = {}, None
    # The 8am run sees yesterday's close. A manual run during market hours
    # sees live index prices stamped today: label those intraday, and point
    # gold and the research at the last completed session instead.
    intraday = as_of == today
    session_date = previous_weekday(today) if (intraday or as_of is None) else as_of

    try:
        sector_tiles = fetch_sector_tiles(session_date, session)
    except Exception as e:
        print(f"[markets] sector tiles failed ({e})", flush=True)
        sector_tiles = {}
    gold = fetch_gold_tile(session_date, session)

    movers, summary = [], ""
    try:
        evidence = research_movers(session_date, client)
        if evidence:
            rep = evidence["report"]
            print(
                f"[markets] research: {len(evidence['searched'])} urls searched, "
                f"{len(evidence['cited'])} cited, "
                f"{len(rep.get('candidates') or [])} candidates",
                flush=True,
            )
            movers = pick_three(verify_candidates(
                evidence, change_fn=lambda s: fmp_session_change(s, session_date, session)
            ))
            summary = verify_summary(evidence)
    except Exception as e:
        print(f"[markets] research failed ({e})", flush=True)

    by_label = {**index_tiles, **sector_tiles, **({GOLD_LABEL: gold} if gold else {})}
    order = [label for _, label in INDEX_TILES] + [label for _, label in SECTOR_TILES] + [GOLD_LABEL]
    tiles = [by_label[label] for label in order if label in by_label]
    if not tiles and not movers:
        return None
    for m in movers:
        m["why"] = _clean(m["why"])
    return {
        "as_of": session_date,
        "strip_intraday": intraday and bool(index_tiles),
        "tiles": tiles,
        "summary": summary,
        "movers": movers,
    }
