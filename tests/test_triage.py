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


def _section_enum(tool):
    return tool["input_schema"]["properties"]["items"]["items"]["properties"]["section"]["enum"]


def test_build_triage_tool_gates_design_section_enum():
    # The tool schema enum is the hard gate: if "Design & Product" isn't in it,
    # the model literally cannot emit it, so a stray weekday item falls back to
    # its feed-origin section (Tech & AI) instead of spawning a one-item section.
    from triage import build_triage_tool
    assert "Design & Product" in _section_enum(build_triage_tool(design_allowed=True))
    assert "Design & Product" not in _section_enum(build_triage_tool(design_allowed=False))


def test_triage_tool_default_includes_design():
    # Back-compat: the module-level TRIAGE_TOOL keeps all seven sections.
    from triage import TRIAGE_TOOL
    assert "Design & Product" in _section_enum(TRIAGE_TOOL)


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


import types


def _fake_tool_block(payload, name="emit_triage"):
    return types.SimpleNamespace(type="tool_use", name=name, input=payload)


def _fake_message(blocks, stop_reason="tool_use"):
    return types.SimpleNamespace(content=blocks, stop_reason=stop_reason)


def test_interpret_raises_when_triage_empties_a_nonempty_input():
    # June 8 regression: 120 headlines went in, emit_triage came back with zero
    # items (output truncated at max_tokens). The pipeline shipped an empty
    # "No major stories today" edition because nothing raised. This must raise
    # so newsletter.py falls back to the legacy single-pass formatter.
    msg = _fake_message(
        [_fake_tool_block({"items": [], "clusters": []})],
        stop_reason="max_tokens",
    )
    with pytest.raises(RuntimeError, match="0 items"):
        triage._interpret_triage_message(msg, input_count=120)


def test_interpret_surfaces_max_tokens_in_the_error():
    # The stop_reason is the diagnostic that distinguishes truncation from a
    # genuinely empty model response, so it must reach the CI log via the error.
    msg = _fake_message(
        [_fake_tool_block({"items": [], "clusters": []})],
        stop_reason="max_tokens",
    )
    with pytest.raises(RuntimeError, match="max_tokens"):
        triage._interpret_triage_message(msg, input_count=120)


def test_interpret_allows_empty_result_for_empty_input():
    # An empty result is only legitimate when nothing was sent in.
    msg = _fake_message([_fake_tool_block({"items": [], "clusters": []})])
    items, clusters = triage._interpret_triage_message(msg, input_count=0)
    assert items == []
    assert clusters == {}


def test_interpret_returns_shaped_items_on_success():
    payload = {
        "items": [{
            "id": 0, "tier": 1, "section": "Tech & AI", "cluster_id": "c1",
            "cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good",
        }],
        "clusters": [{
            "id": "c1", "primary_source": "CBC", "also_in": [], "canonical_headline": "x",
        }],
    }
    msg = _fake_message([_fake_tool_block(payload)])
    items, clusters = triage._interpret_triage_message(msg, input_count=1)
    assert len(items) == 1
    assert clusters["c1"]["primary_source"] == "CBC"


def test_interpret_raises_when_tool_block_missing():
    msg = _fake_message([types.SimpleNamespace(type="text", text="hi")])
    with pytest.raises(RuntimeError, match="missing"):
        triage._interpret_triage_message(msg, input_count=5)


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


def test_apply_phase2_tier_uses_design_subreddits_on_design_editions(monkeypatch):
    import triage
    from config import DESIGN_SUBREDDITS
    captured = {}
    def fake_reddit(url, subreddits):
        captured["subs"] = subreddits
        return {"score": 0, "comments": 0, "subreddit_hits": 0}
    monkeypatch.setattr(triage, "fetch_reddit_traction", fake_reddit)
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 0})
    items = [{"id": 1, "tier": 1, "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"}}]
    links_by_id = {1: {"link": "https://example.com/a"}}
    triage.apply_phase2_tier(items, links_by_id, design_edition=True)
    assert captured["subs"] == DESIGN_SUBREDDITS
