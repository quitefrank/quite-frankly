"""Markets block for the Finance & Markets section.

Morning-Brew-style strip (TSX, S&P 500, Nasdaq, US 10Y, CAD/USD) plus three
featured movers from the previous session, each with a sourced one-line "why".

Two sources, one rule:
  - FMP free tier supplies the numbers it serves (S&P, Nasdaq, USD/CAD, the
    10-year) straight from a feed.
  - One Claude call with the web_search server tool supplies the TSX close and
    the mover candidates, because the free tier has no Canadian data and its
    gainers/losers lists are micro-caps and leveraged ETFs.
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
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
MAX_CONTINUATIONS = 3  # pause_turn resumes for long server-tool turns

STALE_AFTER_DAYS = 4        # long weekend plus a holiday
FMP_MAX_GAP_POINTS = 0.5    # article % vs FMP % disagreement that drops a mover
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "NYSEARCA", "NYSE AMERICAN"}
INTEREST_TAGS = {"ai", "design", "housing", "banks"}


# ── FMP strip ─────────────────────────────────────────────────────────────────

class FMPUnavailable(Exception):
    """Premium-gated symbol, restricted endpoint, or bad response."""


def _fmp_get(path: str, params: dict, session=requests) -> list:
    key = os.environ.get("FMP_API_KEY")
    if not key:
        raise FMPUnavailable("FMP_API_KEY not set")
    resp = session.get(f"{FMP_BASE}/{path}", params={**params, "apikey": key}, timeout=FMP_TIMEOUT)
    # Gated requests come back 200/402 with a plain-text "Premium ..." or
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


def _tile(label: str, value: str, change: str, change_num: float) -> dict:
    return {
        "label": label,
        "value": value,
        "change": change,
        "direction": "up" if change_num > 0 else "down" if change_num < 0 else "flat",
    }


def format_index(price: float) -> str:
    """Indices at 10,000+ drop decimals so five tiles fit a phone width."""
    return f"{price:,.0f}" if price >= 10000 else f"{price:,.2f}"


def format_pct(pct: float) -> str:
    return f"{pct:+.2f}%"


def cad_usd_from_usdcad(price: float, previous_close: float) -> tuple[float, float]:
    """Invert USD/CAD into the loonie's price in USD and its own % change."""
    cad = 1 / price
    pct = (previous_close / price - 1) * 100
    return cad, pct


def ten_year_tile(rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: r["date"])
    if len(rows) < 2:
        raise FMPUnavailable("need two treasury rows for a bps change")
    latest, prior = rows[-1]["year10"], rows[-2]["year10"]
    bps = round((latest - prior) * 100)
    return _tile("US 10Y", f"{latest:.2f}%", f"{bps:+d} bps", bps)


def session_date_from_quote(quote: dict) -> date:
    return datetime.fromtimestamp(quote["timestamp"], TORONTO).date()


def fetch_strip(today: date, session=requests) -> tuple[list[dict], date | None]:
    """The FMP-backed tiles plus the session date they belong to.

    Each tile fails on its own, so one gated endpoint costs one tile. The
    session date comes from the S&P quote timestamp; a stale timestamp skips
    the whole strip rather than showing last week's numbers as yesterday's.
    """
    tiles: list[dict] = []
    as_of: date | None = None

    for symbol, label in (("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq")):
        try:
            q = fmp_quote(symbol, session)
        except (FMPUnavailable, requests.RequestException, KeyError) as e:
            print(f"[markets] {label} unavailable ({e})", flush=True)
            continue
        if as_of is None:
            as_of = session_date_from_quote(q)
            if (today - as_of).days > STALE_AFTER_DAYS:
                print(f"[markets] FMP data stale (as of {as_of}); skipping strip", flush=True)
                return [], None
        tiles.append(_tile(label, format_index(q["price"]), format_pct(q["changePercentage"]), q["changePercentage"]))

    try:
        rows = _fmp_get("treasury-rates", {"from": (today - timedelta(days=10)).isoformat(), "to": today.isoformat()}, session)
        tiles.append(ten_year_tile(rows))
    except (FMPUnavailable, requests.RequestException, KeyError) as e:
        print(f"[markets] US 10Y unavailable ({e})", flush=True)

    try:
        q = fmp_quote("USDCAD", session)
        cad, pct = cad_usd_from_usdcad(q["price"], q["previousClose"])
        tiles.append(_tile("CAD/USD", f"{cad:.4f}", format_pct(pct), pct))
    except (FMPUnavailable, requests.RequestException, KeyError, ZeroDivisionError) as e:
        print(f"[markets] CAD/USD unavailable ({e})", flush=True)

    return tiles, as_of


# ── Web-search research ───────────────────────────────────────────────────────

REPORT_TOOL = {
    "name": "report_markets",
    "description": "Report the session's TSX close, a one-line market summary, and mover candidates. Call exactly once, after searching and after writing the evidence lines.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tsx_close": {"type": ["number", "null"]},
            "tsx_change_pct": {"type": ["number", "null"]},
            "tsx_source_url": {"type": ["string", "null"]},
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
        "required": ["tsx_close", "tsx_change_pct", "tsx_source_url", "market_summary", "summary_source_url", "candidates"],
    },
}


def research_prompt(session_date: date) -> str:
    day = session_date.strftime("%A, %B %-d, %Y")
    return f"""Research the stock market session of {day} for a Toronto reader's morning newsletter.

Search for that day's closing market coverage from wire services and newspapers (Reuters, AP, The Globe and Mail, CNBC, Bloomberg, Financial Post). Find:
1. The S&P/TSX composite index close and its % change that day.
2. A one-sentence summary of why markets moved that day.
3. Up to 6 large-cap stocks (S&P 500 or TSX 60 members only) that made notable moves that day and have a reported reason. Include the biggest reported gainers and losers. Prefer, where they moved notably, companies in AI, design and creative software, Canadian housing, or Canadian banks, and tag those. No penny stocks, no ETFs, no stocks without a reported reason.

Before calling report_markets, write one short evidence line per figure, quoting the article text that states it (the TSX close and %, the market summary's reason, and each stock's % move). These lines must cite the source; they are how the figures get checked. Then call report_markets once.

Rules:
- Only report figures and reasons stated in the sources you found. If a source doesn't state a stock's % move or reason, leave that stock out. If you can't find the TSX close, report null.
- change_pct is the % move for that session, signed. source_url is the page the figure and reason came from.
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
    """True if |pct| is stated in text, allowing the article's own rounding."""
    target = abs(pct)
    for m in _PCT_RE.finditer(text):
        raw = m.group(1)
        n = float(raw)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if round(target, decimals) == round(n, decimals):
            return True
    return False


def _close_in_text(close: float, text: str) -> bool:
    """The close's integer part appears, with or without thousands separators."""
    whole = str(int(close))
    return whole in text.replace(",", "")


def _evidence_for(url: str | None, evidence: dict) -> str:
    if not url or url not in evidence["searched"]:
        return ""
    return " ".join(evidence["cited"].get(url, []))


def verify_tsx(evidence: dict) -> dict | None:
    rep = evidence["report"]
    close, pct = rep.get("tsx_close"), rep.get("tsx_change_pct")
    if close is None or pct is None:
        return None
    text = _evidence_for(rep.get("tsx_source_url"), evidence)
    if text and _pct_in_text(pct, text) and _close_in_text(close, text):
        return _tile("TSX", format_index(close), format_pct(pct), pct)
    print("[markets] TSX figure failed verification; dropping tile", flush=True)
    return None


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
            continue
        if not _pct_in_text(c["change_pct"], text):
            print(f"[markets] {sym}: {c['change_pct']}% not in cited text; dropped", flush=True)
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

def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def build_markets_data(today: date | None = None, client=None, session=requests) -> dict | None:
    """Assemble the block. Never raises; returns None when nothing survives."""
    today = today or datetime.now(TORONTO).date()
    try:
        fmp_tiles, as_of = fetch_strip(today, session)
    except Exception as e:
        print(f"[markets] strip failed ({e})", flush=True)
        fmp_tiles, as_of = [], None
    # The 8am run sees yesterday's close. A manual run during market hours
    # sees live prices stamped today: label those intraday, and point the
    # movers research at the last completed session instead.
    intraday = as_of == today
    session_date = previous_weekday(today) if (intraday or as_of is None) else as_of

    tsx_tile, movers, summary = None, [], ""
    try:
        evidence = research_movers(session_date, client)
        if evidence:
            tsx_tile = verify_tsx(evidence)
            movers = pick_three(verify_candidates(evidence, quote_fn=lambda s: fmp_quote(s, session)))
            summary = verify_summary(evidence)
    except Exception as e:
        print(f"[markets] research failed ({e})", flush=True)

    tiles = ([tsx_tile] if tsx_tile else []) + fmp_tiles
    if not tiles and not movers:
        return None
    for m in movers:
        m["why"] = _clean(m["why"])
    return {
        "as_of": session_date,
        "strip_intraday": intraday,
        "tiles": tiles,
        "summary": summary,
        "movers": movers,
    }
