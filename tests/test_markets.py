from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

import markets
from markets import (
    FMPUnavailable,
    build_markets_data,
    cad_usd_from_usdcad,
    fetch_strip,
    pick_three,
    previous_weekday,
    research_movers,
    ten_year_tile,
    verify_candidates,
    verify_summary,
    verify_tsx,
)
from formatting import DARK, LIGHT, render_markets_block

TODAY = date(2026, 11, 11)
SESSION_TS = int(datetime(2026, 11, 10, 16, 0, tzinfo=markets.TORONTO).timestamp())
REUTERS = "https://www.reuters.com/markets/wrap"
GLOBE = "https://www.theglobeandmail.com/investing/tsx-close"


# ── FMP fakes ─────────────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, payload=None, text=""):
        self._payload, self.text = payload, text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Routes FMP paths to canned payloads; anything else is 'premium'."""

    def __init__(self, routes):
        self.routes = routes

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/stable/", 1)[1]
        key = params.get("symbol", path) if path == "quote" else path
        if key in self.routes:
            return FakeResp(self.routes[key])
        return FakeResp(text="Premium Query Parameter: not available")


def quote(price, pct, prev=None, ts=SESSION_TS):
    return [{"price": price, "changePercentage": pct, "previousClose": prev or price, "timestamp": ts}]


GOOD_ROUTES = {
    "^GSPC": quote(7629.97, 1.44982),
    "^IXIC": quote(25602.314, 2.14012),
    "USDCAD": quote(1.42463, 0.41799, prev=1.4187),
    "treasury-rates": [{"date": "2026-11-10", "year10": 4.98}, {"date": "2026-11-07", "year10": 4.95}],
}


@pytest.fixture(autouse=True)
def fmp_key(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test")


# ── Strip ─────────────────────────────────────────────────────────────────────

def test_fetch_strip_builds_four_tiles_in_order():
    tiles, as_of = fetch_strip(TODAY, FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in tiles] == ["S&P 500", "Nasdaq", "US 10Y", "CAD/USD"]
    assert tiles[0]["value"] == "7,629.97" and tiles[0]["change"] == "+1.45%"
    assert tiles[1]["value"] == "25,602"  # 10,000+ drops decimals
    assert as_of == date(2026, 11, 10)


def test_one_gated_endpoint_costs_one_tile():
    routes = {k: v for k, v in GOOD_ROUTES.items() if k != "^IXIC"}
    tiles, _ = fetch_strip(TODAY, FakeSession(routes))
    assert "Nasdaq" not in [t["label"] for t in tiles]
    assert len(tiles) == 3


def test_stale_quote_skips_strip():
    old = int(datetime(2026, 11, 2, 16, tzinfo=markets.TORONTO).timestamp())
    routes = {**GOOD_ROUTES, "^GSPC": quote(7000, 1.0, ts=old)}
    assert fetch_strip(TODAY, FakeSession(routes)) == ([], None)


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY")
    with pytest.raises(FMPUnavailable):
        markets.fmp_quote("^GSPC", FakeSession(GOOD_ROUTES))


def test_cad_usd_inverts_price_and_direction():
    cad, pct = cad_usd_from_usdcad(1.42463, 1.4187)
    assert round(cad, 4) == 0.7019
    assert pct < 0  # USD/CAD up means the loonie fell


def test_ten_year_bps_sorted_by_date():
    tile = ten_year_tile([{"date": "2026-11-10", "year10": 4.98}, {"date": "2026-11-07", "year10": 4.95}])
    assert tile["value"] == "4.98%" and tile["change"] == "+3 bps" and tile["direction"] == "up"


def test_previous_weekday_monday_covers_friday():
    assert previous_weekday(date(2026, 11, 16)) == date(2026, 11, 13)


# ── Verification ──────────────────────────────────────────────────────────────

def cand(sym, pct, url=REUTERS, tag="none", exchange="NASDAQ"):
    return {"symbol": sym, "name": sym.title(), "exchange": exchange, "change_pct": pct,
            "why": "Because reasons — apparently.", "source_url": url, "interest_tag": tag}


def evidence(candidates, cited=None, searched=None, **report):
    return {
        "report": {"candidates": candidates, **report},
        "cited": cited if cited is not None else {REUTERS: ["Micron jumped 19% while Ferrari fell 5.0% and Nvidia rose 3.2 percent"]},
        "searched": searched if searched is not None else {REUTERS, GLOBE},
    }


def no_fmp(sym):
    raise FMPUnavailable("premium")


def test_candidate_kept_when_pct_in_cited_text():
    out = verify_candidates(evidence([cand("MU", 19.0)]), quote_fn=no_fmp)
    assert [c["symbol"] for c in out] == ["MU"]


def test_article_rounding_is_respected():
    # Article says "19%", model reports 19.2: matches at the article's precision.
    assert verify_candidates(evidence([cand("MU", 19.2)]), quote_fn=no_fmp)
    # Article says "5.0%", model says -5.4: no match at one decimal.
    assert not verify_candidates(evidence([cand("RACE", -5.4, exchange="NYSE")]), quote_fn=no_fmp)


def test_dropped_when_pct_not_cited():
    assert verify_candidates(evidence([cand("AAPL", 7.7)]), quote_fn=no_fmp) == []


def test_dropped_when_url_not_from_search():
    ev = evidence([cand("MU", 19.0, url="https://made.up/story")],
                  cited={"https://made.up/story": ["Micron jumped 19%"]})
    assert verify_candidates(ev, quote_fn=no_fmp) == []


def test_dropped_when_fmp_disagrees():
    assert verify_candidates(evidence([cand("NVDA", 3.2)]), quote_fn=lambda s: {"changePercentage": 1.1}) == []


def test_fmp_agreement_keeps_and_tsx_skips_cross_check():
    calls = []

    def q(sym):
        calls.append(sym)
        return {"changePercentage": 3.3}

    ev = evidence([cand("NVDA", 3.2), cand("SHOP", 19.0, exchange="TSX")])
    out = verify_candidates(ev, quote_fn=q)
    assert [c["symbol"] for c in out] == ["NVDA", "SHOP"]
    assert calls == ["NVDA"]


def test_tsx_needs_close_and_pct_in_citation():
    ev = evidence([], cited={GLOBE: ["The S&P/TSX composite index closed up 0.4% at 25,812.34"]},
                  tsx_close=25812.34, tsx_change_pct=0.4, tsx_source_url=GLOBE)
    assert verify_tsx(ev)["value"] == "25,812"
    ev["report"]["tsx_close"] = 26100.0
    assert verify_tsx(ev) is None


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
    assert len(pick_three([cand("A", 1.0)])) == 1


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
        fake_response([text_block(REUTERS, "Micron jumped 19%"), report_block(candidates=[cand("MU", 19.0)])]),
    ])
    ev = research_movers(date(2026, 11, 10), client)
    assert ev["searched"] == {REUTERS}
    assert ev["cited"] == {REUTERS: ["Micron jumped 19%"]}
    # Continuation resends one assistant turn holding everything so far.
    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant"]


def test_research_without_report_returns_none():
    assert research_movers(date(2026, 11, 10), FakeClient([fake_response([search_block(REUTERS)])])) is None


# ── Orchestrator ──────────────────────────────────────────────────────────────

def full_client():
    return FakeClient([fake_response([
        search_block(REUTERS, GLOBE),
        text_block(GLOBE, "The S&P/TSX composite index closed up 0.4% at 25,812.34"),
        text_block(REUTERS, "Micron jumped 19% while Ferrari fell 5.0%"),
        report_block(tsx_close=25812.34, tsx_change_pct=0.4, tsx_source_url=GLOBE,
                     market_summary="AI names carried the day.", summary_source_url=REUTERS,
                     candidates=[cand("MU", 19.0), cand("RACE", -5.0, exchange="NYSE"), cand("FAKE", 40.0)]),
    ])])


def test_build_markets_data_end_to_end():
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    assert [t["label"] for t in data["tiles"]] == ["TSX", "S&P 500", "Nasdaq", "US 10Y", "CAD/USD"]
    assert [m["symbol"] for m in data["movers"]] == ["MU", "RACE"]  # FAKE uncited, dropped
    assert data["summary"] == "AI names carried the day."
    assert data["movers"][0]["why"] == "Because reasons, apparently."
    assert data["as_of"] == date(2026, 11, 10)


def test_build_markets_data_never_raises():
    class Boom:
        messages = property(lambda self: (_ for _ in ()).throw(RuntimeError("api down")))

    data = build_markets_data(TODAY, client=Boom(), session=FakeSession(GOOD_ROUTES))
    assert data["movers"] == [] and len(data["tiles"]) == 4


def test_build_markets_data_none_when_nothing_survives():
    assert build_markets_data(TODAY, client=FakeClient([fake_response([])]), session=FakeSession({})) is None


# ── Render ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("palette", [LIGHT, DARK])
def test_render_block(palette):
    data = build_markets_data(TODAY, client=full_client(), session=FakeSession(GOOD_ROUTES))
    html = render_markets_block(data, palette)
    for s in ("TSX", "S&amp;P 500", "CAD/USD", "Markets:", "MU", "&#9650; +19.0%", "&#9660; -5.0%", "As of Nov 10 close", REUTERS):
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


def test_intraday_strip_is_labelled_and_research_targets_last_session():
    live = int(datetime(2026, 11, 11, 12, 30, tzinfo=markets.TORONTO).timestamp())
    routes = {**GOOD_ROUTES, "^GSPC": quote(7634.17, 1.51, ts=live)}
    client = full_client()
    data = build_markets_data(TODAY, client=client, session=FakeSession(routes))
    assert data["strip_intraday"] is True and data["as_of"] == date(2026, 11, 10)
    assert "Tuesday, November 10, 2026" in client.calls[0]["messages"][0]["content"]
    assert "Index tiles intraday" in render_markets_block(data, LIGHT)
