from pathlib import Path
from triage import parse_triage_response, select_items_by_tier


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
