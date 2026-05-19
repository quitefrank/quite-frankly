import json

from formatting import (
    build_everything_else,
    build_format_input,
    parse_and_render_sections,
    render_other_headlines_for_section,
    render_source_line,
)


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


def _label_text(line: str) -> str:
    import re as _re
    return _re.sub(r"<[^>]+>", "", line)


def test_render_source_line_drops_primary_from_also_in():
    line = render_source_line(
        primary_source="BetterDwelling",
        also_in=["BetterDwelling"],
        article_link="https://example.com/a",
    )
    assert _label_text(line).count("BetterDwelling") == 1


def test_render_source_line_dedupes_also_in_entries():
    line = render_source_line(
        primary_source="CBC",
        also_in=["BBC", "BBC", "NPR World"],
        article_link=None,
    )
    text = _label_text(line)
    assert text.count("BBC") == 1
    assert "NPR World" in text


def _item(id_, section, tier, ccov=1, prel=0, fit="weak"):
    return {
        "id": id_,
        "section": section,
        "tier": tier,
        "cluster_id": f"cl_{id_}",
        "scores": {"cross_source_coverage": ccov, "personal_relevance": prel, "section_fit": fit},
    }


def test_build_format_input_caps_tier_1_at_two_per_section():
    tiered_items = [
        _item(1, "Toronto Housing", tier=1, ccov=3, prel=3, fit="good"),  # score 7
        _item(2, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(3, "Toronto Housing", tier=1, ccov=1, prel=1, fit="weak"),  # score 2
        _item(4, "Toronto Housing", tier=1, ccov=1, prel=0, fit="weak"),  # score 1
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "BetterDwelling", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 2
    assert {x["id"] for x in housing["tier_1"]} == {1, 2}


def test_build_format_input_fills_tier_1_to_cap_from_tier_2_when_short():
    # Section has only 1 tier_1 item; cap is 2 → promote 1 from tier_2.
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(2, "Design & Product", tier=2, ccov=2, prel=1, fit="good"),  # score 4
        _item(3, "Design & Product", tier=2, ccov=1, prel=1, fit="weak"),  # score 2
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "UX Collective", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    dp = payload["sections"]["Design & Product"]
    assert len(dp["tier_1"]) == 2
    # Highest-scored tier_2 (id=2) gets promoted; the other tier_2 (id=3) stays
    assert {x["id"] for x in dp["tier_1"]} == {1, 2}
    assert [x["id"] for x in dp["tier_2"]] == [3]


def test_build_format_input_caps_finance_and_us_global_at_one():
    tiered_items = [
        _item(10, "Finance & Markets", tier=1, ccov=3, prel=2, fit="good"),  # score 6
        _item(11, "Finance & Markets", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(20, "US & Global",       tier=1, ccov=4, prel=3, fit="good"),  # score 8
        _item(21, "US & Global",       tier=1, ccov=3, prel=2, fit="good"),  # score 6
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "BBC", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    assert len(payload["sections"]["Finance & Markets"]["tier_1"]) == 1
    assert payload["sections"]["Finance & Markets"]["tier_1"][0]["id"] == 10
    assert len(payload["sections"]["US & Global"]["tier_1"]) == 1
    assert payload["sections"]["US & Global"]["tier_1"][0]["id"] == 20


def test_build_format_input_fills_finance_from_tier_2_when_no_tier_1():
    tiered_items = [
        _item(40, "Finance & Markets", tier=2, ccov=2, prel=1, fit="good"),  # score 4
        _item(41, "Finance & Markets", tier=2, ccov=1, prel=1, fit="weak"),  # score 2
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "Yahoo Finance", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    fm = payload["sections"]["Finance & Markets"]
    assert len(fm["tier_1"]) == 1  # only 1, even though we promoted
    assert fm["tier_1"][0]["id"] == 40


def test_fallback_fills_tier_1_to_section_cap_when_tier_1_empty():
    # Toronto Housing has cap=2, no tier_1 items, and 2 fallback candidates →
    # both should get promoted (tier_2 first, then tier_3).
    tiered_items = [
        _item(1, "Toronto Housing", tier=2, ccov=1, prel=1, fit="weak"),
        _item(2, "Toronto Housing", tier=3, ccov=1, prel=0, fit="none"),
        _item(3, "Canada & Toronto", tier=1, ccov=3, prel=2, fit="good"),
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "CBC", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 2
    assert {x["id"] for x in housing["tier_1"]} == {1, 2}


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


def test_render_other_headlines_for_section_caps_at_three_and_skips_used_ids():
    # 5 tier_2 items in US & Global; expect top 3 by score, none used.
    tiered_items = [
        {"id": 1, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 2, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 3, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}},
        {"id": 4, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"}},
        {"id": 5, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "none"}},
        # Different section — must be ignored.
        {"id": 6, "section": "Tech & AI", "tier": 2,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},
    ]
    links_by_id = {
        n: {"link": f"https://example.com/{n}", "title": f"Story {n} headline",
            "snippet": f"Snippet for story {n}. Second sentence.", "source": "BBC", "image": ""}
        for n in range(1, 7)
    }
    used_ids = set()
    html = render_other_headlines_for_section("US & Global", tiered_items, links_by_id, used_ids)
    assert html.count("<li") == 3
    # Highest-scored three are 1, 2, 3
    assert "Story 1" in html
    assert "Story 2" in html
    assert "Story 3" in html
    assert "Story 4" not in html
    # Cross-section item never appears.
    assert "Story 6" not in html
    assert used_ids == {1, 2, 3}


def test_render_other_headlines_for_section_skips_items_already_in_used_ids():
    tiered_items = [
        {"id": 10, "section": "Toronto Housing", "tier": 2,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 11, "section": "Toronto Housing", "tier": 2,
         "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"}},
    ]
    links_by_id = {
        10: {"link": "u10", "title": "Top story", "snippet": "Body.", "source": "CBC", "image": ""},
        11: {"link": "u11", "title": "Other story", "snippet": "Body.", "source": "CBC", "image": ""},
    }
    used_ids = {10}  # Already featured.
    html = render_other_headlines_for_section("Toronto Housing", tiered_items, links_by_id, used_ids)
    assert "Top story" not in html
    assert "Other story" in html


def test_parse_and_render_sections_synthesizes_other_headlines_when_claude_omits_them():
    # Simulate Claude producing only a Tier 1 story, no Other Headlines block.
    text = """## US & Global

**Big story [#100]**
Body paragraph one.

Body paragraph two.
Source: BBC
"""
    links_by_id = {
        100: {"link": "https://example.com/100", "image": "",
              "title": "Big story", "snippet": "Body.", "source": "BBC"},
        101: {"link": "https://example.com/101", "image": "",
              "title": "Second tier story", "snippet": "Tier 2 first sentence.",
              "source": "NYT"},
    }
    tiered_items = [
        {"id": 100, "section": "US & Global", "tier": 1,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 101, "section": "US & Global", "tier": 2,
         "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"}},
    ]
    html, used_ids = parse_and_render_sections(text, links_by_id, {}, tiered_items=tiered_items)
    assert "Other Headlines" in html
    assert "Second tier story" in html
    assert 100 in used_ids
    assert 101 in used_ids


def test_build_everything_else_caps_at_seven_globally():
    # 20 unused items across multiple sections; expect a flat top-7 list.
    links_by_id = {
        i: {
            "id": i,
            "title": f"Headline {i}",
            "link": f"https://example.com/{i}",
            "image": "",
            "source": "CBC",
        }
        for i in range(20)
    }
    tiered_items = [
        # Mix of tiers; lower tier number = higher priority in EE.
        {"id": 0, "tier": 1, "section": "Canada & Toronto",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 1, "tier": 1, "section": "Tech & AI",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        # tier_2 entries
        *[
            {"id": i, "tier": 2, "section": "Canada & Toronto",
             "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}}
            for i in range(2, 12)
        ],
        # tier_3 entries
        *[
            {"id": i, "tier": 3, "section": "Tech & AI",
             "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "none"}}
            for i in range(12, 18)
        ],
    ]
    used_ids = set()
    html = build_everything_else(links_by_id, used_ids, {}, tiered_items=tiered_items)
    assert html.count("<li") == 7
    # The two tier_1 overflows must appear (highest priority).
    assert "Headline 0" in html
    assert "Headline 1" in html


def test_build_everything_else_returns_empty_when_no_unused_items():
    links_by_id = {0: {"id": 0, "title": "X", "link": "https://x", "image": "", "source": "CBC"}}
    html = build_everything_else(links_by_id, used_ids={0}, clusters_by_item_id={}, tiered_items=[])
    assert html == ""


def test_build_format_input_collapses_same_cluster_within_section():
    # Triage clustered both NBC Meet the Press items together (cluster_id
    # "alex_murdaugh"), but build_format_input was treating them as independent
    # items and featuring both in Worth Knowing. One cluster, one feature.
    tiered_items = [
        _item(213, "Worth Knowing", tier=1, ccov=2, prel=0, fit="good"),  # score 3
        _item(214, "Worth Knowing", tier=1, ccov=2, prel=1, fit="good"),  # score 4 (winner)
    ]
    for it in tiered_items:
        it["cluster_id"] = "alex_murdaugh"
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "NBC Meet the Press", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    worth_knowing = payload["sections"]["Worth Knowing"]
    assert len(worth_knowing["tier_1"]) == 1
    assert worth_knowing["tier_1"][0]["id"] == 214


def test_build_format_input_does_not_collapse_items_with_empty_cluster_id():
    # Missing/empty cluster_id means "no cluster known" - never merge.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
    ]
    for it in tiered_items:
        it["cluster_id"] = ""
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    tech = payload["sections"]["Tech & AI"]
    assert {x["id"] for x in tech["tier_1"]} == {1, 2}


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
