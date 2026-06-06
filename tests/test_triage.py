from pathlib import Path
import pytest
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


def test_shape_tool_output_raises_when_all_items_malformed():
    payload = {
        "items": [{"foo": "bar"}, {"baz": 1}, {}],
        "clusters": [],
    }
    with pytest.raises(RuntimeError, match="malformed"):
        triage._shape_tool_output(payload)


def test_shape_tool_output_allows_legitimate_empty_response():
    items, clusters = triage._shape_tool_output({"items": [], "clusters": []})
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


def test_apply_phase2_tier_falls_back_when_attach_traction_raises(monkeypatch, capsys):
    def boom(items, links_by_id):
        raise RuntimeError("Reddit blew up")

    monkeypatch.setattr(triage, "attach_traction", boom)

    items = [
        {"id": 0, "tier": 1, "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 1, "tier": 3, "scores": {"cross_source_coverage": 0, "personal_relevance": 1, "section_fit": "weak"}},
    ]
    links_by_id = {0: {"link": "https://a"}, 1: {"link": "https://b"}}

    result = apply_phase2_tier(items, links_by_id)

    assert result[0]["tier"] == 1  # Claude's tier preserved
    assert result[1]["tier"] == 3  # Claude's tier preserved
    out = capsys.readouterr().out
    assert "attach_traction failed" in out


from triage import build_triage_user_message


def test_triage_message_includes_snippet():
    items = [{
        "id": 7, "title": "Codex goals explained", "source": "IAI",
        "section_label": "Design & Product",
        "snippet": "Bryce Ratner shows how Keith Lee built a no-code fitness app.",
    }]
    msg = build_triage_user_message(items)
    assert "[#7]" in msg
    assert "Bryce Ratner" in msg
    assert "no-code fitness app" in msg


def test_triage_message_omits_separator_when_snippet_empty():
    items = [{
        "id": 8, "title": "Just a title", "source": "CBC",
        "section_label": "Canada & Toronto", "snippet": "",
    }]
    msg = build_triage_user_message(items)
    assert "[#8]" in msg
    assert " — " not in msg


from triage import enrich_cluster_metrics


def test_enrich_sets_coverage_to_distinct_source_count():
    items = [
        {"id": 1, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
        {"id": 2, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
        {"id": 3, "cluster_id": "c1", "scores": {"cross_source_coverage": 9}},
    ]
    links_by_id = {
        1: {"source": "CBC"}, 2: {"source": "CBC"}, 3: {"source": "BBC"},
    }
    enrich_cluster_metrics(items, links_by_id)
    assert [it["cluster_size"] for it in items] == [3, 3, 3]
    assert [it["scores"]["cross_source_coverage"] for it in items] == [2, 2, 2]


def test_enrich_treats_empty_cluster_as_singleton():
    items = [{"id": 5, "cluster_id": "", "scores": {"cross_source_coverage": 4}}]
    enrich_cluster_metrics(items, {5: {"source": "NYT"}})
    assert items[0]["cluster_size"] == 1
    assert items[0]["scores"]["cross_source_coverage"] == 1
