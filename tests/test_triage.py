from pathlib import Path
import triage
from triage import parse_triage_response, select_items_by_tier, apply_phase2_tier


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


def test_apply_phase2_tier_recomputes_using_traction(monkeypatch):
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 5000, "comments": 800, "subreddit_hits": 3})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})

    items = [{
        "id": 0,
        "tier": 3,
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
    }]
    links_by_id = {0: {"link": "https://example.com/x"}}

    result = apply_phase2_tier(items, links_by_id)
    assert result[0]["tier"] == 1
    assert items[0]["tier"] == 1  # in-place overwrite, unlike shadow_score


def test_apply_phase2_tier_recomputes_without_traction(monkeypatch):
    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 0, "comments": 0, "subreddit_hits": 0})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0, "comments": 0})

    items = [{
        "id": 7,
        "tier": 2,
        "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"},
    }]
    links_by_id = {7: {"link": "https://example.com/y"}}

    result = apply_phase2_tier(items, links_by_id)
    # 2*3 + 2*2 + 1 = 11 → tier 1 even with no traction
    assert result[0]["tier"] == 1
