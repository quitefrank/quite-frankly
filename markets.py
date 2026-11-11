"""Markets block for the Finance & Markets section.

Morning-Brew-style strip of daily % moves (SPX, IXIC, XGRO, XEQT, Gold) plus
three featured movers from the previous session, each with a sourced one-line
"why". The strip shows movement only, no price levels, to keep it narrow.

Two sources, one rule:
  - FMP free tier supplies what it serves straight from a feed: the S&P 500
    and Nasdaq quotes, and gold's daily closes.
  - One Claude call with the web_search server tool supplies XGRO and XEQT
    (TSX-listed, premium on FMP) and the mover candidates, because the free
    tier has no Canadian data and its gainers/losers lists are micro-caps and
    leveraged ETFs.
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

# Strip order, left to right. Labels are tickers, except gold: its ticker GOLD
# is Barrick's, and the futures code GC means nothing to a reader.
INDEX_TILES = (("^GSPC", "SPX"), ("^IXIC", "IXIC"))
ETF_TILES = ("XGRO", "XEQT")
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
    """SPX and IXIC tiles keyed by label, plus the date their quotes carry.

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


def gold_change_pct(rows: list[dict], session_date: date) -> float:
    """Close-to-close % for session_date from daily rows.

    Gold futures trade overnight, so a live quote at 8am is that morning's
    move. Daily closes pin it to the same session as everything else.
    """
    by_date = sorted((r for r in rows if r["date"] <= session_date.isoformat()), key=lambda r: r["date"])
    if len(by_date) < 2 or by_date[-1]["date"] != session_date.isoformat():
        raise FMPUnavailable(f"no gold close for {session_date}")
    close, prior = by_date[-1]["price"], by_date[-2]["price"]
    return (close / prior - 1) * 100


def fetch_gold_tile(session_date: date, session=requests) -> dict | None:
    try:
        rows = _fmp_get(
            "historical-price-eod/light",
            {"symbol": GOLD_SYMBOL, "from": (session_date - timedelta(days=10)).isoformat()},
            session,
        )
        return tile(GOLD_LABEL, gold_change_pct(rows, session_date))
    except (FMPUnavailable, requests.RequestException, KeyError, ZeroDivisionError) as e:
        print(f"[markets] Gold unavailable ({e})", flush=True)
        return None


# ── Web-search research ───────────────────────────────────────────────────────

REPORT_TOOL = {
    "name": "report_markets",
    "description": "Report the session's ETF moves, a one-line market summary, and mover candidates. Call exactly once, after searching and after writing the evidence lines.",
    "input_schema": {
        "type": "object",
        "properties": {
            "etfs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "enum": list(ETF_TILES)},
                        "change_pct": {"type": "number", "description": "Signed, e.g. -0.42"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["symbol", "change_pct", "source_url"],
                },
            },
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
        "required": ["etfs", "market_summary", "summary_source_url", "candidates"],
    },
}


def research_prompt(session_date: date) -> str:
    day = session_date.strftime("%A, %B %-d, %Y")
    return f"""Research the stock market session of {day} for a Toronto reader's morning newsletter.

Find:
1. The daily % change on that session for two TSX-listed ETFs: XGRO (iShares Core Growth ETF Portfolio) and XEQT (iShares Core Equity ETF Portfolio). Use a quote or price-history page (TMX Money, The Globe and Mail, Morningstar, BlackRock iShares Canada, Barchart) that states the % change for that date.
2. A one-sentence summary of why markets moved that day, from wire or newspaper closing coverage (Reuters, AP, The Globe and Mail, CNBC, Bloomberg, Financial Post).
3. Up to 6 large-cap stocks (S&P 500 or TSX 60 members only) that made notable moves that day and have a reported reason. Include the biggest reported gainers and losers. Prefer, where they moved notably, companies in AI, design and creative software, Canadian housing, or Canadian banks, and tag those. No penny stocks, no ETFs, no stocks without a reported reason.

Before calling report_markets, write one short evidence line per figure, quoting the source text that states it (each ETF's % change, the market summary's reason, and each stock's % move). These lines must cite the source; they are how the figures get checked. Then call report_markets once.

Rules:
- Only report figures and reasons stated in the sources you found. If a source doesn't state a figure for that session, leave it out (omit the ETF or stock).
- change_pct is the % move for that session, signed. source_url is the page the figure came from.
- "why" is one sentence, under 25 words, plain and specific, with a light dry touch at most. No em dashes. Don't start with the company name.
- market_summary is one sentence, under 30 words, no em dashes."""


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
    """One Claude call with web search. Returns report + evidence, or None."""
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages = [{"role": "user", "content": research_prompt(session_date)}]
    all_content: list = []
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = client.messages.create(
            model=MARKETS_MODEL,
            max_tokens=4000,
            tools=[WEB_SEARCH_TOOL, REPORT_TOOL],
            messages=messages,
        )
        all_content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        # Resume the paused turn: resend it as one assistant message so the
        # model continues where it stopped.
        messages = [messages[0], {"role": "assistant", "content": list(all_content)}]

    cited, searched, report = _collect_evidence(all_content)
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


def verify_etfs(evidence: dict) -> dict[str, dict]:
    """XGRO/XEQT tiles keyed by label; each needs its % in a cited, searched source."""
    tiles: dict[str, dict] = {}
    for e in evidence["report"].get("etfs") or []:
        sym = e.get("symbol")
        if sym not in ETF_TILES or sym in tiles:
            continue
        text = _evidence_for(e.get("source_url"), evidence)
        if text and _pct_in_text(e["change_pct"], text):
            tiles[sym] = tile(sym, e["change_pct"])
        else:
            print(f"[markets] {sym} {e.get('change_pct')}% failed verification; dropping tile", flush=True)
            _explain_drop(sym, e.get("source_url"), evidence)
    return tiles


def verify_summary(evidence: dict) -> str:
    """The summary has no number to match, so it needs a searched, cited source."""
    rep = evidence["report"]
    summary = _clean(rep.get("market_summary") or "")
    if summary and _evidence_for(rep.get("summary_source_url"), evidence):
        return summary
    if summary:
        print("[markets] market summary uncited; dropping it", flush=True)
    return ""


def verify_candidates(evidence: dict, quote_fn=fmp_quote) -> list[dict]:
    verified = []
    for c in evidence["report"].get("candidates", []):
        sym = c.get("symbol", "?")
        text = _evidence_for(c.get("source_url"), evidence)
        if not text:
            print(f"[markets] {sym}: source not from search or uncited; dropped", flush=True)
            _explain_drop(sym, c.get("source_url"), evidence)
            continue
        if not _pct_in_text(c["change_pct"], text):
            print(f"[markets] {sym}: {c['change_pct']}% not in cited text; dropped", flush=True)
            _explain_drop(sym, c.get("source_url"), evidence)
            continue
        if c.get("exchange", "").upper() in US_EXCHANGES:
            try:
                fmp_pct = quote_fn(sym)["changePercentage"]
                if abs(fmp_pct - c["change_pct"]) > FMP_MAX_GAP_POINTS:
                    print(f"[markets] {sym}: article {c['change_pct']}% vs FMP {fmp_pct:.2f}%; dropped", flush=True)
                    continue
            except (FMPUnavailable, requests.RequestException, KeyError):
                pass  # premium symbol: article check alone stands
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

    gold = fetch_gold_tile(session_date, session)

    etf_tiles: dict[str, dict] = {}
    movers, summary = [], ""
    try:
        evidence = research_movers(session_date, client)
        if evidence:
            rep = evidence["report"]
            print(
                f"[markets] research: {len(evidence['searched'])} urls searched, "
                f"{len(evidence['cited'])} cited, {len(rep.get('etfs') or [])} etfs, "
                f"{len(rep.get('candidates') or [])} candidates",
                flush=True,
            )
            etf_tiles = verify_etfs(evidence)
            movers = pick_three(verify_candidates(evidence, quote_fn=lambda s: fmp_quote(s, session)))
            summary = verify_summary(evidence)
    except Exception as e:
        print(f"[markets] research failed ({e})", flush=True)

    by_label = {**index_tiles, **etf_tiles, **({GOLD_LABEL: gold} if gold else {})}
    order = [label for _, label in INDEX_TILES] + list(ETF_TILES) + [GOLD_LABEL]
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
