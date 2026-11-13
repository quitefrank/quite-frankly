from datetime import date
from types import SimpleNamespace as NS

import pytest

import markets
from markets import (
    FMPUnavailable,
    build_markets_data,
    fetch_strip,
    latest_session,
    pick_three,
    previous_weekday,
    research_movers,
    session_change_pct,
    verify_candidates,
    verify_summary,
    verify_watch,
)
from formatting import DARK, LIGHT, render_markets_block

TODAY = date(2026, 11, 11)
SESSION = date(2026, 11, 10)
REUTERS = "https://www.reuters.com/markets/wrap"
TMX = "https://money.tmx.com/quote/XEQT"


# ── FMP fakes ─────────────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, payload=None, text=""):
        self._payload, self.text = payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Routes FMP daily-close requests by symbol; anything else is 'premium'."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        if "twelvedata" in url:
            key = f"td:{params.get('symbol')}"
            self.calls.append(key)
            return FakeResp(self.routes.get(key, {"status": "error", "message": "needs Grow plan"}))
        path = url.rsplit("/stable/", 1)[1]
        key = f"eod:{params.get('symbol')}" if path == "historical-price-eod/light" else path
        self.calls.append(key)
        if key in self.routes:
            return FakeResp(self.routes[key])
        return FakeResp(text="Premium Query Parameter: not available")


def closes(nov9, nov10, nov11=None):
    """Daily rows, newest first like FMP. nov11 is today's partial session."""
    rows = [{"date": "2026-11-10", "price": nov10}, {"date": "2026-11-09", "price": nov9}]
    return ([{"date": "2026-11-11", "price": nov11}] if nov11 else []) + rows


def td_closes(nov9, nov10, nov11=None):
    """Twelve Data time_series payload, newest first, closes as strings."""
    rows = closes(nov9, nov10, nov11)
    return {"status": "ok", "values": [{"datetime": r["date"], "close": str(r["price"])} for r in rows]}


GOOD_ROUTES = {
    "eod:SPY": closes(675.0, 672.5, 683.0),       # FMP, -0.37% on Nov 10
    "eod:NVDA": closes(178.67, 168.89, 176.49),   # FMP, -5.47%
    "td:XLK": td_closes(174.0, 172.0, 175.0),     # Twelve Data from here on
    "td:XLE": td_closes(63.0, 63.0),              # flat
    "td:XLF": td_closes(58.5, 58.6),
    "td:XLRE": td_closes(44.3, 44.5),
    "td:GLD": td_closes(365.0, 357.0, 356.0),
}


class NoSleep:
    """Throttle with a fake clock, so tests never actually wait."""

    def __init__(self):
        self.now, self.slept = 0.0, []

    def throttle(self, per_minute=8):
        return markets._Throttle(per_minute, clock=lambda: self.now, sleep=self._sleep)

    def _sleep(self, secs):
        self.slept.append(secs)
        self.now += secs


@pytest.fixture(autouse=True)
def fmp_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test")


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(markets.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def default_strip_style(monkeypatch, tmp_path):
    """Render with the built-in defaults, whatever strip_style.json says."""
    import formatting
    monkeypatch.setattr(formatting, "STRIP_STYLE_FILE", str(tmp_path / "absent.json"))


# ── Strip ─────────────────────────────────────────────────────────────────────

def test_strip_is_tickers_with_session_moves():
    tiles = fetch_strip(SESSION, FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in tiles] == ["SPY", "XLK", "XLE", "XLF", "XLRE", "GLD"]
    assert [t["area"] for t in tiles] == ["Market", "Tech", "Energy", "Banks", "Real Estate", "Gold"]
    assert tiles[1] == {"label": "XLK", "area": "Tech", "url": "https://finance.yahoo.com/quote/XLK",
                        "price": 172.0, "pct": -1.15, "change": "-1.15%", "direction": "down"}
    assert tiles[0]["price"] == 672.5          # SPY from FMP, Nov 10 (today's partial row skipped)
    assert tiles[2]["direction"] == "flat"

def test_near_zero_move_is_flat_not_red():
    assert markets.tile("JPM", -0.003) == {"label": "JPM", "area": "", "url": "", "price": None, "pct": 0.0, "change": "0.00%", "direction": "flat"}


def test_one_gated_symbol_costs_one_tile():
    routes = {k: v for k, v in GOOD_ROUTES.items() if k != "td:XLE"}
    assert [t["label"] for t in fetch_strip(SESSION, FakeSession(routes))] == ["SPY", "XLK", "XLF", "XLRE", "GLD"]


def test_quotes_try_fmp_first_then_twelve_data_once_each():
    fake = FakeSession(GOOD_ROUTES)
    q = markets.SessionQuotes(SESSION, fake, NoSleep().throttle())
    assert q("SPY") == (672.5, pytest.approx(-0.3704, abs=1e-3))
    q("XLK"); q("XLK")
    assert fake.calls == ["eod:SPY", "eod:XLK", "td:XLK"]   # FMP gated XLK; TD fetched once


def test_missing_from_both_sources_raises():
    q = markets.SessionQuotes(SESSION, FakeSession({}), NoSleep().throttle())
    with pytest.raises(FMPUnavailable):
        q("XIU")


def test_twelve_data_calls_are_paced_to_the_free_limit():
    clock = NoSleep()
    t = clock.throttle(per_minute=8)
    for _ in range(9):
        t.wait()
    assert len(clock.slept) == 1 and 60 <= clock.slept[0] <= 61

def test_latest_session_skips_todays_partial_row():
    assert latest_session(TODAY, FakeSession(GOOD_ROUTES)) == SESSION


def test_latest_session_stale_or_missing_is_none():
    old = {"eod:SPY": [{"date": "2026-11-02", "price": 1.0}, {"date": "2026-10-30", "price": 1.0}]}
    assert latest_session(TODAY, FakeSession(old)) is None
    assert latest_session(TODAY, FakeSession({})) is None


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY")
    with pytest.raises(FMPUnavailable):
        markets.fmp_quote("SPY", FakeSession(GOOD_ROUTES))


def test_session_change_uses_session_close_not_this_morning():
    pct = session_change_pct(closes(4114.5, 4030.2, 4009.7), SESSION)
    assert round(pct, 2) == round((4030.2 / 4114.5 - 1) * 100, 2)
    with pytest.raises(FMPUnavailable):
        session_change_pct(closes(4114.5, 4030.2, 4009.7), date(2026, 11, 12))


def test_mover_cross_check_uses_session_close():
    # Today's partial row says +4.5%; the Nov 10 close says -5.47%, as the article does.
    client = FakeClient([
        fake_response([search_block(REUTERS), text_block(REUTERS, "Nvidia fell 5.47% on Tuesday")]),
        fake_response([report_block(market_summary="", summary_source_url=None,
                                    candidates=[cand("NVDA", -5.47, name="Nvidia Corp")])]),
    ])
    data = build_markets_data(TODAY, client=client, session=FakeSession(GOOD_ROUTES))
    assert [(m["symbol"], m["change_pct"]) for m in data["movers"]] == [("NVDA", -5.47)]


def test_yahoo_url_handles_tsx_and_class_shares():
    assert markets.yahoo_url("NVDA", "NASDAQ") == "https://finance.yahoo.com/quote/NVDA"
    assert markets.yahoo_url("BMO", "TSX") == "https://finance.yahoo.com/quote/BMO.TO"
    assert markets.yahoo_url("BRK.B", "NYSE") == "https://finance.yahoo.com/quote/BRK-B"


def test_previous_weekday_monday_covers_friday():
    assert previous_weekday(date(2026, 11, 16)) == date(2026, 11, 13)


# ── Verification ──────────────────────────────────────────────────────────────

def cand(sym, pct, url=REUTERS, tag="none", exchange="NASDAQ", name=None):
    return {"symbol": sym, "name": name or sym.title(), "exchange": exchange, "change_pct": pct,
            "why": "Because reasons — apparently.", "source_url": url, "interest_tag": tag}


def evidence(candidates, cited=None, searched=None, **report):
    return {
        "report": {"candidates": candidates, **report},
        "cited": cited if cited is not None else {REUTERS: ["Micron jumped 19% while Ferrari fell 5.0% and Nvidia rose 3.2 percent"]},
        "searched": searched if searched is not None else {REUTERS, TMX},
    }


def no_fmp(sym):
    raise FMPUnavailable("premium")


def test_candidate_kept_when_pct_in_cited_text():
    out = verify_candidates(evidence([cand("MU", 19.0)]), change_fn=no_fmp)
    assert [c["symbol"] for c in out] == ["MU"]


def test_article_rounding_is_respected():
    # Article says "19%", model reports 19.2: matches at the article's precision.
    assert verify_candidates(evidence([cand("MU", 19.2)]), change_fn=no_fmp)
    # Article says "5.0%", model says -5.4: no match at one decimal.
    assert not verify_candidates(evidence([cand("RACE", -5.4, exchange="NYSE")]), change_fn=no_fmp)


def test_dropped_when_pct_not_cited():
    assert verify_candidates(evidence([cand("AAPL", 7.7)]), change_fn=no_fmp) == []


def test_dropped_when_url_not_from_search():
    ev = evidence([cand("MU", 19.0, url="https://made.up/story")],
                  cited={"https://made.up/story": ["Micron jumped 19%"]})
    assert verify_candidates(ev, change_fn=no_fmp) == []


def test_dropped_when_fmp_disagrees():
    assert verify_candidates(evidence([cand("NVDA", 3.2)]), change_fn=lambda s: 1.1) == []


def test_fmp_agreement_keeps_and_tsx_skips_cross_check():
    calls = []

    def q(sym):
        calls.append(sym)
        return 3.3

    ev = evidence([cand("NVDA", 3.2, name="Nvidia Corp"), cand("SHOP", 19.0, exchange="TSX")])
    out = verify_candidates(ev, change_fn=q)
    assert [c["symbol"] for c in out] == ["NVDA", "SHOP"]
    assert out[0]["change_pct"] == 3.3  # FMP's figure is what renders
    assert out[0]["quote_url"] == "https://finance.yahoo.com/quote/NVDA"
    assert out[1]["quote_url"] == "https://finance.yahoo.com/quote/SHOP.TO"
    assert calls == ["NVDA"]


def test_feed_match_accepts_without_verbatim_figure():
    # Cited snippet is a cut-off table: names the company, no % for it.
    ev = evidence([cand("CHTR", 11.2, name="Charter Communications", exchange="NASDAQ")],
                  cited={REUTERS: ["Top S&P 500 movers Tuesday | Ticker | CHTR | Charter Communications |"]})
    out = verify_candidates(ev, change_fn=lambda s: 11.04)
    assert out[0]["change_pct"] == 11.04


def test_feed_match_still_needs_company_named():
    ev = evidence([cand("LEN", -5.4, name="Lennar Corp", exchange="NYSE")],
                  cited={REUTERS: ["The 10 S&P 500 stocks with the highest returns on Tuesday"]})
    assert verify_candidates(ev, change_fn=lambda s: -5.4) == []


def test_company_named_in_url_counts():
    url = "https://www.tikr.com/blog/charter-soars-11-on-tender-offer"
    ev = evidence([cand("CHTR", 11.0, url=url, name="Charter Communications")],
                  cited={url: ["The company announced a $1.5 billion tender offer."]}, searched={url})
    assert verify_candidates(ev, change_fn=lambda s: 11.1)


def test_premium_us_symbol_falls_back_to_verbatim():
    ev = evidence([cand("NVDA", 3.2, name="Nvidia Corp")])
    assert verify_candidates(ev, change_fn=no_fmp)  # "3.2 percent" is in the text
    ev = evidence([cand("NVDA", 4.0, name="Nvidia Corp")])
    assert verify_candidates(ev, change_fn=no_fmp) == []


def test_summary_needs_cited_source():
    ev = evidence([], market_summary="Tech rallied — again.", summary_source_url=REUTERS)
    assert verify_summary(ev) == "Tech rallied, again."
    ev["report"]["summary_source_url"] = "https://made.up"
    assert verify_summary(ev) == ""


def test_watch_items_need_cited_source():
    ev = evidence([], cited={REUTERS: ["October CPI is due at 8:30 a.m. ET"]},
                  watch=[{"time": "8:30 ET", "event": "US CPI — October", "source_url": REUTERS},
                         {"time": "After close", "event": "Made-up earnings", "source_url": "https://made.up"}])
    stocks, also = verify_watch(ev)
    assert stocks == [] and also == [{"time": "8:30 ET", "event": "US CPI, October", "source_url": REUTERS}]


def test_watch_company_with_quote_becomes_a_row():
    item = {"time": "After close", "event": "Fiscal Q1 earnings", "symbol": "csco", "name": "Cisco",
            "exchange": "NASDAQ", "angle": "AI networking demand in focus.", "source_url": REUTERS}
    stocks, also = verify_watch(evidence([], watch=[item]), quote_fn=lambda s: (100.76, 2.6592))
    assert also == []
    assert stocks == [{"time": "After close", "event": "Fiscal Q1 earnings", "source_url": REUTERS,
                       "symbol": "CSCO", "name": "Cisco", "angle": "AI networking demand in focus.",
                       "price": 100.76, "change_pct": 2.66, "quote_url": "https://finance.yahoo.com/quote/CSCO"}]


def test_watch_company_without_quote_drops_to_also_today():
    item = {"time": "Before open", "event": "Q4 earnings", "symbol": "RY", "name": "Royal Bank",
            "exchange": "TSX", "angle": None, "source_url": REUTERS}
    stocks, also = verify_watch(evidence([], watch=[item]), quote_fn=no_fmp)
    assert stocks == [] and also == [{"time": "Before open", "event": "Royal Bank Q4 earnings", "source_url": REUTERS}]


def test_watch_caps_rows_at_three_and_events_at_four():
    econ = [{"time": "9:00", "event": f"E{i}", "source_url": REUTERS} for i in range(6)]
    assert len(verify_watch(evidence([], watch=econ))[1]) == 4
    cos = [{"time": "After close", "event": "earnings", "symbol": f"S{i}", "name": f"Co{i}",
            "exchange": "NYSE", "angle": None, "source_url": REUTERS} for i in range(5)]
    stocks, also = verify_watch(evidence([], watch=cos), quote_fn=lambda s: (10.0, 1.0))
    assert len(stocks) == 3 and len(also) == 2


# ── Picking ───────────────────────────────────────────────────────────────────

def test_pick_three_gainer_loser_then_interest():
    picks = pick_three([cand("A", 9.0), cand("B", -7.0), cand("C", 12.0), cand("D", 2.0, tag="ai"), cand("E", -11.0)])
    assert [p["symbol"] for p in picks] == ["C", "E", "D"]


def test_pick_three_falls_back_to_size_without_tags():
    picks = pick_three([cand("A", 9.0), cand("B", -7.0), cand("C", 12.0)])
    assert [p["symbol"] for p in picks] == ["C", "B", "A"]


def test_pick_three_one_direction_fills_by_size():
    picks = pick_three([cand("A", 9.0), cand("B", 3.0), cand("C", 12.0), cand("D", 1.0)])
    assert [p["symbol"] for p in picks] == ["C", "A", "B"]


def test_pick_three_short_list():
    assert pick_three([]) == []
    assert len(pick_three([cand("A", 2.5)])) == 1


def test_lead_story_takes_the_first_slot_even_when_smaller():
    # Nov 12: Nvidia's CEO resigned (-4.3%) while AMD, GPN and SMCI moved further.
    picks = pick_three([cand("AMD", 5.9), cand("GPN", -12.0), cand("SMCI", -11.3, tag="ai"),
                        cand("NVDA", -4.3, tag="ai") | {"is_lead_story": True}])
    assert [p["symbol"] for p in picks] == ["NVDA", "AMD", "GPN"]


def test_lead_story_below_minimum_move_is_ignored():
    picks = pick_three([cand("A", 9.0), cand("B", -7.0), cand("L", 1.2) | {"is_lead_story": True}])
    assert [p["symbol"] for p in picks] == ["A", "B"]


def test_why_without_a_cause_is_dropped():
    ev = evidence([cand("NVDA", 3.2, name="Nvidia Corp") | {"has_cause": False}])
    assert verify_candidates(ev, change_fn=no_fmp) == []


def test_pick_three_ignores_small_moves():
    # The Nov 10 test picked BMO at -0.2% as the interest slot.
    picks = pick_three([cand("A", 9.0), cand("B", -7.0), cand("BMO", -0.2, tag="banks"), cand("C", 1.9)])
    assert [p["symbol"] for p in picks] == ["A", "B"]


# ── Research call ─────────────────────────────────────────────────────────────

def fake_response(content, stop="end_turn"):
    return NS(content=content, stop_reason=stop)


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def search_block(*urls):
    return NS(type="web_search_tool_result", content=[NS(url=u) for u in urls])


def text_block(url, cited_text):
    return NS(type="text", text="evidence", citations=[NS(url=url, cited_text=cited_text)])


def report_block(**inp):
    return NS(type="tool_use", name="report_markets", input=inp)


def test_research_collects_evidence_across_pause_turn():
    client = FakeClient([
        fake_response([search_block(REUTERS)], stop="pause_turn"),
        fake_response([text_block(REUTERS, "Micron jumped 19%")]),
        fake_response([report_block(candidates=[cand("MU", 19.0)])]),
    ])
    ev = research_movers(SESSION, client)
    assert ev["searched"] == {REUTERS}
    assert ev["cited"] == {REUTERS: ["Micron jumped 19%"]}
    assert ev["report"]["candidates"][0]["symbol"] == "MU"
    # Phase 1 offers only search; a pause resumes as one assistant turn.
    assert [t["name"] for t in client.calls[0]["tools"]] == ["web_search"]
    assert [m["role"] for m in client.calls[1]["messages"]] == ["user", "assistant"]
    # Phase 2 forces the report over the findings.
    final = client.calls[2]
    assert final["tool_choice"] == {"type": "tool", "name": "report_markets"}
    assert [m["role"] for m in final["messages"]] == ["user", "assistant", "user"]
    # Phase 2 is handed the exact URLs cited in phase 1 to copy from.
    assert "copied exactly from this list" in final["messages"][2]["content"]
    assert f"- {REUTERS}" in final["messages"][2]["content"]


def test_citations_in_phase_two_do_not_count():
    client = FakeClient([
        fake_response([search_block(REUTERS)]),
        fake_response([text_block(REUTERS, "Micron jumped 19%"), report_block(candidates=[])]),
    ])
    assert research_movers(SESSION, client)["cited"] == {}


def test_research_without_report_returns_none():
    client = FakeClient([fake_response([search_block(REUTERS)]), fake_response([])])
    assert research_movers(SESSION, client) is None


# ── Orchestrator ──────────────────────────────────────────────────────────────

def full_client():
    return FakeClient([fake_response([
        search_block(REUTERS, TMX),
        text_block(REUTERS, "Micron jumped 19% while Ferrari fell 5.0%"),
        text_block(TMX, "Statistics Canada releases September retail sales at 8:30 a.m.; Nvidia reports after the close"),
    ]), fake_response([
        report_block(market_summary="AI names carried the day.", summary_source_url=REUTERS,
                     watch=[{"time": "After close", "event": "Q3 earnings", "symbol": "NVDA", "name": "Nvidia",
                             "exchange": "NASDAQ", "angle": "Data-centre guidance in focus.", "source_url": TMX},
                            {"time": "8:30 ET", "event": "Canada retail sales", "symbol": None, "name": None,
                             "exchange": None, "angle": None, "source_url": TMX}],
                     candidates=[cand("MU", 19.0), cand("RACE", -5.0, exchange="NYSE"), cand("FAKE", 40.0)]),
    ])])


def test_build_markets_data_end_to_end():
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in data["tiles"]] == ["SPY", "XLK", "XLE", "XLF", "XLRE", "GLD"]
    assert [m["symbol"] for m in data["movers"]] == ["MU", "RACE"]  # FAKE uncited, dropped
    assert data["summary"] == "AI names carried the day."
    assert data["movers"][0]["why"] == "Because reasons, apparently."
    assert data["as_of"] == SESSION
    assert data["also_today"] == [{"time": "8:30 ET", "event": "Canada retail sales", "source_url": TMX}]
    nvda = data["watch_stocks"][0]
    assert (nvda["symbol"], nvda["price"], nvda["change_pct"]) == ("NVDA", 168.89, -5.47)  # FMP close, same session


def test_build_markets_data_never_raises():
    class Boom:
        messages = property(lambda self: (_ for _ in ()).throw(RuntimeError("api down")))

    data = build_markets_data(TODAY, client=Boom(), session=FakeSession(GOOD_ROUTES))
    assert data["movers"] == [] and [t["label"] for t in data["tiles"]] == ["SPY", "XLK", "XLE", "XLF", "XLRE", "GLD"]


def test_build_markets_data_none_when_nothing_survives():
    client = FakeClient([fake_response([]), fake_response([])])
    assert build_markets_data(TODAY, client=client, session=FakeSession({})) is None


def test_midday_run_still_targets_last_completed_session():
    client = full_client()
    data = build_markets_data(TODAY, client=client, session=FakeSession(GOOD_ROUTES))
    assert data["as_of"] == SESSION
    prompt = client.calls[0]["messages"][0]["content"]
    assert "session of Tuesday, November 10, 2026" in prompt
    assert "What to watch on Wednesday, November 11, 2026" in prompt


def test_no_fmp_still_researches_previous_weekday():
    client = full_client()
    data = build_markets_data(TODAY, client=client, session=FakeSession({}))
    assert data["tiles"] == [] and data["as_of"] == SESSION


# ── Render ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_render_block(palette):
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    html = render_markets_block(data, palette)
    for s in ("Market", "Tech", "Energy", "Banks", "Real Estate", "Gold", "SPY", "XLK", "XLE", "XLF", "XLRE", "GLD",
              "SPY tracks the S&amp;P 500", "Markets:", "MU",
              "+19.00%", "-5.00%", "Closing prices and daily % moves, Nov 10", REUTERS,
              ">Markets</td>", ">Movers</td>", "$172.00", "$672.50", "$168.89",
              ">What to watch</td>", "After close:</strong> Q3 earnings. Data-centre guidance in focus.",
              "Also today:", "Canada retail sales", "8:30 ET", "reuters.com",
              'href="https://finance.yahoo.com/quote/XLK"', 'href="https://finance.yahoo.com/quote/MU"'):
        assert s in html
    assert palette["up"] in html and palette["down"] in html
    assert "border-left" not in html


def _strip(n):
    return [markets.tile(f"T{i}", 1.0, "Area", f"https://finance.yahoo.com/quote/T{i}") for i in range(n)]


def test_footnote_explains_only_tickers_shown():
    from datetime import date as d
    html = render_markets_block({"tiles": _strip(3), "movers": [], "as_of": d(2026, 11, 10)}, LIGHT)
    assert "GC is gold" not in html and "SPY tracks" not in html
    gc = [markets.tile("GC", -2.0, "Gold", "u")]
    assert "GC is gold futures." in render_markets_block({"tiles": gc, "movers": [], "as_of": d(2026, 11, 10)}, LIGHT)


def test_rows_layout_one_row_per_market_then_movers_with_explainers():
    data = {"tiles": _strip(5), "as_of": None,
            "movers": [cand("MU", 19.0) | {"price": 101.5, "quote_url": "https://finance.yahoo.com/quote/MU"},
                       cand("SHOP", -4.2, exchange="TSX") | {"price": None}]}
    html = render_markets_block(data, LIGHT)
    # 2 group labels + 5 market rows + 2 mover rows + 2 explainer rows
    assert html.count("<tr>") == 11
    assert html.index(">Markets</td>") < html.index(">Movers</td>")
    assert "$101.50" in html and "&mdash;" in html          # missing price shows a dash
    assert "padding:10px 4px 6px" in html                    # 6px between a mover and its explainer
    assert 'colspan="5" style="padding:0 4px 10px' in html   # explainer spans from the arrow's edge
    assert LIGHT["up_bg"] in html and LIGHT["down_bg"] in html
    assert f'border-collapse:collapse;border-bottom:1px solid {LIGHT["divider"]}' in html  # rule under the last explainer


def test_recap_leads_movers_and_watch_comes_last():
    html = render_markets_block(build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES)), LIGHT)
    assert (html.index(">Movers</td>") < html.index("Markets:</strong>") < html.index(">MU</a>")
            < html.index(">What to watch</td>") < html.index(">NVDA</a>") < html.index("Also today:"))
    assert "Featured movers" not in html
    assert html.count("text-transform:uppercase") == 3   # Markets, Movers, What to watch


def test_what_to_watch_label_shows_with_only_events():
    html = render_markets_block({"tiles": [], "movers": [], "as_of": None, "summary": "",
                                 "also_today": [{"time": "8:30 ET", "event": "CPI", "source_url": "u"}]}, LIGHT)
    assert ">What to watch</td>" in html and "Also today:" in html


def test_decimals_setting_applies_to_rows():
    from formatting import STRIP_STYLE_DEFAULTS
    html = render_markets_block({"tiles": _strip(1), "movers": [], "as_of": None}, LIGHT,
                                dict(STRIP_STYLE_DEFAULTS, pct_decimals=1))
    assert "+1.0%" in html and "+1.00%" not in html


def test_empty_groups_are_omitted():
    html = render_markets_block({"tiles": [], "movers": [cand("MU", 19.0)], "as_of": None}, LIGHT)
    assert ">Markets</td>" not in html and ">Movers</td>" in html and ">What to watch</td>" not in html


def test_zero_decimals_never_show_red_minus_zero():
    from formatting import format_strip_pct
    assert format_strip_pct(-0.3, 0) == ("0%", "flat")
    assert format_strip_pct(-0.6, 0) == ("-1%", "down")


def test_bad_style_file_falls_back_to_defaults(tmp_path):
    from formatting import STRIP_STYLE_DEFAULTS, load_strip_style
    f = tmp_path / "s.json"
    f.write_text('{"rows": 9, "columns": "three", "ticker_size": 18}')
    st = load_strip_style(str(f))
    assert st["rows"] == 2 and st["columns"] == STRIP_STYLE_DEFAULTS["columns"] and st["ticker_size"] == 18
    f.write_text("not json")
    assert load_strip_style(str(f)) == STRIP_STYLE_DEFAULTS


def test_every_strip_ticker_is_a_link():
    html = render_markets_block({"tiles": _strip(6), "movers": [], "as_of": None}, LIGHT)
    assert all(f'href="https://finance.yahoo.com/quote/T{i}"' in html for i in range(6))


def test_render_escapes_model_text():
    data = {"tiles": [], "summary": "", "as_of": None,
            "movers": [cand("X", 2.0) | {"why": "<script>alert(1)</script>", "source_url": 'https://a.b/"x'}]}
    html = render_markets_block(data, LIGHT)
    assert "<script>" not in html and '&quot;x' in html


def test_render_empty_is_blank():
    assert render_markets_block(None, LIGHT) == ""
    assert render_markets_block({"tiles": [], "movers": []}, LIGHT) == ""


# ── Email integration ─────────────────────────────────────────────────────────

def test_block_renders_inside_finance_card_above_story(sample_format_response):
    from formatting import build_email_html

    links = {0: {"link": "https://cbc.example/0", "image": "", "title": "Council"},
             1: {"link": "https://yahoo.example/1", "image": "", "title": "BoC"}}
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    with_block, _, _ = build_email_html(sample_format_response, links, {}, tiered_items=[], markets_data=data)
    without, _, _ = build_email_html(sample_format_response, links, {}, tiered_items=[])

    finance = with_block.index("Finance &amp; Markets") if "Finance &amp; Markets" in with_block else with_block.index("Finance & Markets")
    assert finance < with_block.index("Markets:") < with_block.index("Bank of Canada holds rates steady")
    assert with_block.index("Canada") < finance  # Canada card untouched, still above
    assert "Markets:" not in without
