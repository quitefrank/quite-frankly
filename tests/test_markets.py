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
        self.routes = routes

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/stable/", 1)[1]
        key = f"eod:{params.get('symbol')}" if path == "historical-price-eod/light" else path
        if key in self.routes:
            return FakeResp(self.routes[key])
        return FakeResp(text="Premium Query Parameter: not available")


def closes(nov9, nov10, nov11=None):
    """Daily rows, newest first like FMP. nov11 is today's partial session."""
    rows = [{"date": "2026-11-10", "price": nov10}, {"date": "2026-11-09", "price": nov9}]
    return ([{"date": "2026-11-11", "price": nov11}] if nov11 else []) + rows


GOOD_ROUTES = {
    "eod:SPY": closes(675.0, 672.5, 683.0),       # -0.37% on Nov 10
    "eod:NVDA": closes(178.67, 168.89, 176.49),   # -5.47%
    "eod:XOM": closes(118.0, 117.81),
    "eod:JPM": closes(305.0, 305.0),              # flat
    "eod:GCUSD": closes(4114.5, 4030.2, 4009.7),  # -2.05%
}


@pytest.fixture(autouse=True)
def fmp_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")


# ── Strip ─────────────────────────────────────────────────────────────────────

def test_strip_is_tickers_with_session_moves():
    tiles = fetch_strip(SESSION, FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in tiles] == ["SPY", "NVDA", "XOM", "JPM", "GC"]
    assert tiles[1] == {"label": "NVDA", "change": "-5.47%", "direction": "down"}
    assert tiles[3]["direction"] == "flat"


def test_near_zero_move_is_flat_not_red():
    assert markets.tile("JPM", -0.003) == {"label": "JPM", "change": "0.00%", "direction": "flat"}


def test_one_gated_symbol_costs_one_tile():
    routes = {k: v for k, v in GOOD_ROUTES.items() if k != "eod:XOM"}
    assert [t["label"] for t in fetch_strip(SESSION, FakeSession(routes))] == ["SPY", "NVDA", "JPM", "GC"]


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
    pct = session_change_pct(GOOD_ROUTES["eod:GCUSD"], SESSION)
    assert round(pct, 2) == round((4030.2 / 4114.5 - 1) * 100, 2)
    with pytest.raises(FMPUnavailable):
        session_change_pct(GOOD_ROUTES["eod:GCUSD"], date(2026, 11, 12))


def test_mover_cross_check_uses_session_close():
    # Today's partial row says +4.5%; the Nov 10 close says -5.47%, as the article does.
    client = FakeClient([
        fake_response([search_block(REUTERS), text_block(REUTERS, "Nvidia fell 5.47% on Tuesday")]),
        fake_response([report_block(market_summary="", summary_source_url=None,
                                    candidates=[cand("NVDA", -5.47, name="Nvidia Corp")])]),
    ])
    data = build_markets_data(TODAY, client=client, session=FakeSession(GOOD_ROUTES))
    assert [(m["symbol"], m["change_pct"]) for m in data["movers"]] == [("NVDA", -5.47)]


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
    ]), fake_response([
        report_block(market_summary="AI names carried the day.", summary_source_url=REUTERS,
                     candidates=[cand("MU", 19.0), cand("RACE", -5.0, exchange="NYSE"), cand("FAKE", 40.0)]),
    ])])


def test_build_markets_data_end_to_end():
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in data["tiles"]] == ["SPY", "NVDA", "XOM", "JPM", "GC"]
    assert [m["symbol"] for m in data["movers"]] == ["MU", "RACE"]  # FAKE uncited, dropped
    assert data["summary"] == "AI names carried the day."
    assert data["movers"][0]["why"] == "Because reasons, apparently."
    assert data["as_of"] == SESSION


def test_build_markets_data_never_raises():
    class Boom:
        messages = property(lambda self: (_ for _ in ()).throw(RuntimeError("api down")))

    data = build_markets_data(TODAY, client=Boom(), session=FakeSession(GOOD_ROUTES))
    assert data["movers"] == [] and [t["label"] for t in data["tiles"]] == ["SPY", "NVDA", "XOM", "JPM", "GC"]


def test_build_markets_data_none_when_nothing_survives():
    client = FakeClient([fake_response([]), fake_response([])])
    assert build_markets_data(TODAY, client=client, session=FakeSession({})) is None


def test_midday_run_still_targets_last_completed_session():
    client = full_client()
    data = build_markets_data(TODAY, client=client, session=FakeSession(GOOD_ROUTES))
    assert data["as_of"] == SESSION
    assert "Tuesday, November 10, 2026" in client.calls[0]["messages"][0]["content"]


def test_no_fmp_still_researches_previous_weekday():
    client = full_client()
    data = build_markets_data(TODAY, client=client, session=FakeSession({}))
    assert data["tiles"] == [] and data["as_of"] == SESSION


# ── Render ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_render_block(palette):
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    html = render_markets_block(data, palette)
    for s in ("SPY", "NVDA", "XOM", "JPM", "GC", "-5.47%", "gold futures", "Markets:", "MU",
              "&#9650; +19.0%", "&#9660; -5.0%", "Daily % moves, Nov 10 close", REUTERS):
        assert s in html
    assert palette["up"] in html and palette["down"] in html
    assert "border-left" not in html


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
