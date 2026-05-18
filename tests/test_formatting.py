import json

from formatting import build_format_input, parse_and_render_sections, render_source_line


def test_single_source_renders_plain():
    line = render_source_line(
        primary_source="CBC",
        also_in=[],
        article_link="https://example.com/a",
    )
    assert "CBC" in line
    assert "also in" not in line.lower()


def test_two_source_cluster_renders_both_inline():
    line = render_source_line(
        primary_source="CBC",
        also_in=["Toronto Star"],
        article_link="https://example.com/a",
    )
    assert "CBC, Toronto Star" in line


def test_three_plus_cluster_renders_with_also_in_suffix():
    line = render_source_line(
        primary_source="NYT",
        also_in=["BBC", "Economist", "NPR World"],
        article_link="https://example.com/a",
    )
    assert "NYT" in line
    assert "BBC" in line
    assert "Economist" in line


def _item(id_, section, tier, ccov=1, prel=0, fit="weak"):
    return {
        "id": id_,
        "section": section,
        "tier": tier,
        "cluster_id": f"cl_{id_}",
        "scores": {"cross_source_coverage": ccov, "personal_relevance": prel, "section_fit": fit},
    }


def test_fallback_promotes_highest_scored_item_when_tier_1_empty():
    tiered_items = [
        _item(1, "Toronto Housing", tier=2, ccov=1, prel=1, fit="weak"),
        _item(2, "Toronto Housing", tier=3, ccov=1, prel=0, fit="none"),
        _item(3, "Canada & Toronto", tier=1, ccov=3, prel=2, fit="good"),
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "CBC", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 1
    assert housing["tier_1"][0]["id"] == 1


def test_section_order_is_by_max_score_descending():
    tiered_items = [
        _item(10, "Canada & Toronto", tier=1, ccov=1, prel=1, fit="weak"),  # score 2
        _item(20, "US & Global",      tier=1, ccov=4, prel=3, fit="good"),  # score 8
        _item(30, "Tech & AI",        tier=1, ccov=2, prel=2, fit="good"),  # score 5
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "CBC", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    populated_order = [s for s, b in payload["sections"].items() if any(b.values())]
    assert populated_order[0] == "US & Global"
    assert populated_order[1] == "Tech & AI"
    assert populated_order[2] == "Canada & Toronto"


def test_worth_knowing_section_renders():
    text = """## Worth Knowing

**Big global story [#5]**
Body paragraph one.

Body paragraph two.
Source: NYT
"""
    links_by_id = {5: {"link": "https://example.com/5", "image": "", "title": "Big global story"}}
    clusters_by_item_id = {5: {"primary_source": "NYT", "also_in": ["BBC"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    assert "Worth Knowing" in html
    assert "NYT, BBC" in html
