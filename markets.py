"""Markets block for the Finance & Markets section.

Morning-Brew-style strip of daily % moves (SPY, NVDA, XOM, JPM, GC) plus
three featured movers from the previous session, each with a sourced one-line
"why". The strip shows ticker and movement only, no price levels, to keep it
narrow. Tickers rather than sector names so every tile is something a reader
could look up or buy.

Two sources, one rule:
  - FMP free tier supplies the whole strip from daily closes, so every tile
    and every mover cross-check is the same completed session.
  - One Claude call with the web_search server tool supplies the mover
    candidates, because the free tier's gainers/losers lists are micro-caps
    and leveraged ETFs and it has no stock news.
  - A model-reported number only renders if it appears in text Claude cited
    from the URL it names, and the URL came back from a real search. When FMP
    also serves the symbol, the % has to agree with FMP's close. Anything that
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

MIN_MOVE_PCT = 2.0  # below this a stock isn't a "mover" (the Nov 10 test picked BMO at -0.2%)

# Strip, left to right: (FMP symbol, label). One bellwether per area, because
# the free tier blocks every sector ETF (XLK, XLE, XLF, XLRE, GLD, QQQ), every
# real estate stock and every gold miner, so a ticker Frank could buy has to
# be one of the megacaps it does serve. A bellwether is one company, not its
# sector: NVDA fell 5.5% on Nov 10 while the average tech stock rose.
# (FMP symbol, ticker shown, area name shown above the ticker)
STRIP_TILES = (
    ("SPY", "SPY", "Market"),   # S&P 500 ETF
    ("NVDA", "NVDA", "Tech"),
    ("XOM", "XOM", "Energy"),
    ("JPM", "JPM", "Banks"),
    ("GCUSD", "GC", "Gold"),    # gold futures, the standard GC code
)
SESSION_ANCHOR = "SPY"  # its last completed daily close defines the session


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


def tile(label: str, pct: float, area: str = "") -> dict:
    # Direction from the displayed value, so -0.003% reads as a flat 0.00%,
    # not a red "-0.00%".
    shown = round(pct, 2) + 0.0  # + 0.0 turns -0.0 into 0.0
    return {
        "label": label,
        "area": area,
        "change": format_pct(shown) if shown else "0.00%",
        "direction": "up" if shown > 0 else "down" if shown < 0 else "flat",
    }


def format_pct(pct: float) -> str:
    return f"{pct:+.2f}%"


def previous_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _daily_rows(symbol: str, since: date, session=requests) -> list[dict]:
    return _fmp_get("historical-price-eod/light", {"symbol": symbol, "from": since.isoformat()}, session)


def session_change_pct(rows: list[dict], session_date: date) -> float:
    """Close-to-close % for session_date from FMP daily rows.

    Daily closes rather than live quotes everywhere: gold futures trade
    overnight (an 8am quote is that morning's move), and during market hours
    a live quote is today's move (CI run 43074369231 compared NVDA's Nov 10
    -5.47% against a live +4.55% and dropped a correct figure).
    """
    by_date = sorted((r for r in rows if r["date"] <= session_date.isoformat()), key=lambda r: r["date"])
    if len(by_date) < 2 or by_date[-1]["date"] != session_date.isoformat():
        raise FMPUnavailable(f"no close for {session_date}")
    close, prior = by_date[-1]["price"], by_date[-2]["price"]
    return (close / prior - 1) * 100


def fmp_session_change(symbol: str, session_date: date, session=requests) -> float:
    return session_change_pct(_daily_rows(symbol, session_date - timedelta(days=10), session), session_date)


def latest_session(today: date, session=requests) -> date | None:
    """The last completed session: SPY's newest daily close before today.

    Today's row (present during market hours) is a partial session and is
    skipped. A close older than STALE_AFTER_DAYS means FMP is behind, so the
    strip is skipped rather than showing last week's moves as yesterday's.
    """
    try:
        rows = _daily_rows(SESSION_ANCHOR, today - timedelta(days=10), session)
    except (FMPUnavailable, requests.RequestException) as e:
        print(f"[markets] session lookup failed ({e})", flush=True)
        return None
    dates = sorted(r["date"] for r in rows if r.get("date", "") < today.isoformat())
    if not dates:
        return None
    last = date.fromisoformat(dates[-1])
    if (today - last).days > STALE_AFTER_DAYS:
        print(f"[markets] FMP closes stale (last {last}); skipping strip", flush=True)
        return None
    return last


def fetch_strip(session_date: date, session=requests) -> list[dict]:
    """One tile per STRIP_TILES entry that has a close for session_date."""
    tiles = []
    for symbol, label, area in STRIP_TILES:
        try:
            tiles.append(tile(label, fmp_session_change(symbol, session_date, session), area))
        except (FMPUnavailable, requests.RequestException, KeyError, ZeroDivisionError) as e:
            print(f"[markets] {label} unavailable ({e})", flush=True)
    return tiles


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
    mover (falling back to the biggest remaining move). Order: as picked.
    Moves under MIN_MOVE_PCT never qualify."""
    picks: list[dict] = []
    remaining = [c for c in verified if abs(c["change_pct"]) >= MIN_MOVE_PCT]

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
        found = latest_session(today, session)
        tiles = fetch_strip(found, session) if found else []
    except Exception as e:
        print(f"[markets] strip failed ({e})", flush=True)
        found, tiles = None, []
    session_date = found or previous_weekday(today)

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

    if not tiles and not movers:
        return None
    for m in movers:
        m["why"] = _clean(m["why"])
    return {
        "as_of": session_date,
        "tiles": tiles,
        "summary": summary,
        "movers": movers,
    }
