import json

from formatting import (
    build_email_html,
    build_everything_else,
    build_format_input,
    parse_and_render_sections,
    pick_everything_else_emoji,
    render_other_headlines_for_section,
    render_source_line,
    suppressed_cluster_ids,
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
    # Swamp the global pickoff with 5 higher-scored items in another section so
    # Toronto Housing's tier-1 items stay in place. Housing items max score is 7;
    # the swamp items score 9 so they get picked into Today in the World instead.
    tiered_items = [
        _item(1, "Toronto Housing", tier=1, ccov=3, prel=3, fit="good"),  # score 7
        _item(2, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(3, "Toronto Housing", tier=1, ccov=1, prel=1, fit="weak"),  # score 2
        _item(4, "Toronto Housing", tier=1, ccov=1, prel=0, fit="weak"),  # score 1
        # Swamp pickoff with 5 highly-scored items in another section.
        _item(91, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(92, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(93, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(94, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(95, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "BetterDwelling", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 2
    assert {x["id"] for x in housing["tier_1"]} == {1, 2}


def test_build_format_input_prioritises_images_within_tier_1():
    # Section has 3 tier_1 candidates, cap=2.
    # Top scorer has no image (score 7); next has image (score 5); third has image (score 4).
    # Expected: items with images surface first, sorted by score within the image group.
    # Picks: id=2 (image, 5), id=3 (image, 4). The score-7 no-image item drops out.
    # Swamp the global pickoff with 5 higher-scored items elsewhere so Housing
    # tier-1 items aren't pulled into Today in the World.
    tiered_items = [
        _item(1, "Toronto Housing", tier=1, ccov=3, prel=3, fit="good"),  # score 7
        _item(2, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(3, "Toronto Housing", tier=1, ccov=2, prel=1, fit="good"),  # score 4
        _item(91, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(92, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(93, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(94, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(95, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
    ]
    links_by_id = {
        1: {"title": "t1", "source": "BetterDwelling", "snippet": "x", "image": ""},
        2: {"title": "t2", "source": "BetterDwelling", "snippet": "x", "image": "https://img/2.jpg"},
        3: {"title": "t3", "source": "BetterDwelling", "snippet": "x", "image": "https://img/3.jpg"},
        91: {"title": "t91", "source": "TechCrunch", "snippet": "x", "image": "https://img/91.jpg"},
        92: {"title": "t92", "source": "TechCrunch", "snippet": "x", "image": "https://img/92.jpg"},
        93: {"title": "t93", "source": "TechCrunch", "snippet": "x", "image": "https://img/93.jpg"},
        94: {"title": "t94", "source": "TechCrunch", "snippet": "x", "image": "https://img/94.jpg"},
        95: {"title": "t95", "source": "TechCrunch", "snippet": "x", "image": "https://img/95.jpg"},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    housing = payload["sections"]["Toronto Housing"]
    assert len(housing["tier_1"]) == 2
    # Items with images come first, sorted by score within that group.
    assert [x["id"] for x in housing["tier_1"]] == [2, 3]


def test_build_format_input_fills_tier_1_to_cap_from_tier_2_when_short():
    # Section has only 1 tier_1 item; cap is 2 → promote 1 from tier_2.
    # Swamp the global pickoff with 5 higher-scored items elsewhere so
    # Design & Product's single tier-1 stays in the section.
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(2, "Design & Product", tier=2, ccov=2, prel=1, fit="good"),  # score 4
        _item(3, "Design & Product", tier=2, ccov=1, prel=1, fit="weak"),  # score 2
        _item(91, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(92, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(93, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(94, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(95, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
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
    # Swamp the global pickoff with 5 higher-scored items elsewhere so the
    # Finance & Markets and US & Global tier-1s aren't pulled into Today in
    # the World.
    tiered_items = [
        _item(10, "Finance & Markets", tier=1, ccov=3, prel=2, fit="good"),  # score 6
        _item(11, "Finance & Markets", tier=1, ccov=2, prel=2, fit="good"),  # score 5
        _item(20, "US & Global",       tier=1, ccov=4, prel=3, fit="good"),  # score 8
        _item(21, "US & Global",       tier=1, ccov=3, prel=2, fit="good"),  # score 6
        _item(91, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(92, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(93, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(94, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(95, "Tech & AI", tier=1, ccov=4, prel=4, fit="good"),  # score 9
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
    # With the global pickoff, top tier-1 items get lifted into Today in the
    # World, which then naturally sorts first by max score. Remaining sections
    # sort by their highest-scored leftover item. Use tier-2 items that stay
    # in their home sections (the pickoff only pulls from tier-1) to verify
    # inter-section ordering still holds for the non-TitW sections.
    tiered_items = [
        _item(10, "Canada & Toronto", tier=2, ccov=1, prel=1, fit="weak"),  # score 2
        _item(20, "US & Global",      tier=2, ccov=4, prel=3, fit="good"),  # score 8
        _item(30, "Tech & AI",        tier=2, ccov=2, prel=2, fit="good"),  # score 5
        # Tier-1 items in another section so Today in the World is populated.
        _item(91, "Toronto Housing", tier=1, ccov=4, prel=4, fit="good"),  # score 9
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "CBC", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    populated_order = [s for s, b in payload["sections"].items() if any(b.values())]
    # Today in the World sorts first (holds the global top pick, score 9).
    assert populated_order[0] == "Today in the World"
    # Remaining sections sort by max score of leftover items.
    assert populated_order[1] == "US & Global"   # score 8
    assert populated_order[2] == "Tech & AI"     # score 5
    assert populated_order[3] == "Canada & Toronto"  # score 2


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


def test_other_headlines_includes_tier_1_overflow_above_tier_2():
    # Section has 3 tier_1 items; cap=2 means 1 demotes to Other Headlines.
    # The demoted tier_1 (id=3) has a LOW score; a competing tier_2 (id=4)
    # has a HIGH score. Tier ordering must beat score ordering: the tier_1
    # overflow surfaces above the higher-scored tier_2 item.
    tiered_items = [
        {"id": 1, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 3, "section_fit": "good"}},  # score 7
        {"id": 2, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},  # score 6
        # Overflow tier_1 with a deliberately LOW score (1).
        {"id": 3, "section": "Toronto Housing", "tier": 1,
         "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"}},  # score 1
        # Tier_2 with a deliberately HIGH score (6) — would beat id=3 under score-only sort.
        {"id": 4, "section": "Toronto Housing", "tier": 2,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},  # score 6
    ]
    links_by_id = {
        n: {"link": f"https://example.com/{n}", "title": f"Story {n}",
            "snippet": "First sentence.", "source": "Storeys", "image": ""}
        for n in range(1, 5)
    }
    used_ids = {1, 2}  # featured slots took the top two tier_1
    html = render_other_headlines_for_section("Toronto Housing", tiered_items, links_by_id, used_ids)
    pos_3 = html.find("Story 3")
    pos_4 = html.find("Story 4")
    assert pos_3 >= 0 and pos_4 >= 0, "Both overflow and tier-2 must render"
    # Tier-1 overflow (low score 1) must beat tier-2 (high score 6) by virtue of tier alone.
    assert pos_3 < pos_4, "Tier-1 overflow must surface above tier-2 regardless of score"
    assert used_ids == {1, 2, 3, 4}


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
    # New structure: <p> per item, no <ul>/<li>. Each item carries an emoji span
    # and a <strong>-wrapped first-words link.
    assert "<ul" not in html
    assert "<li" not in html
    assert html.count("<p style=\"margin:0 0 14px") == 7
    assert html.count("<strong>") == 7
    # Every item uses source "CBC" → 🇨🇦 via EVERYTHING_ELSE_SOURCE_EMOJIS.
    # Titles are "Headline {i}", which match no keyword regex, so source wins.
    # The section header text "Everything Else" carries no 🇨🇦, so exactly 7.
    assert html.count("🇨🇦") == 7
    # The two tier_1 overflows must appear (highest priority).
    assert "Headline 0" in html
    assert "Headline 1" in html


def test_build_everything_else_returns_empty_when_no_unused_items():
    links_by_id = {0: {"id": 0, "title": "X", "link": "https://x", "image": "", "source": "CBC"}}
    html = build_everything_else(links_by_id, used_ids={0}, clusters_by_item_id={}, tiered_items=[])
    assert html == ""


def test_today_in_the_world_pulls_global_top_five():
    # Five sections, three tier_1 items each. Today in the World should
    # get the top 5 globally by composite score and they should NOT appear
    # in their home sections' tier_1.
    tiered_items = [
        # Tech & AI: scores 8, 6, 5
        _item(101, "Tech & AI", tier=1, ccov=4, prel=3, fit="good"),  # 8
        _item(102, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),  # 6
        _item(103, "Tech & AI", tier=1, ccov=2, prel=2, fit="good"),  # 5
        # Toronto Housing: scores 8, 5, 4
        _item(201, "Toronto Housing", tier=1, ccov=4, prel=3, fit="good"),  # 8
        _item(202, "Toronto Housing", tier=1, ccov=2, prel=2, fit="good"),  # 5
        _item(203, "Toronto Housing", tier=1, ccov=2, prel=1, fit="good"),  # 4
        # Finance & Markets: score 7
        _item(301, "Finance & Markets", tier=1, ccov=3, prel=3, fit="good"),  # 7
        # US & Global: score 8
        _item(401, "US & Global", tier=1, ccov=4, prel=3, fit="good"),  # 8
    ]
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "x", "image": f"https://img/{i['id']}.jpg"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    titw = payload["sections"]["Today in the World"]
    # Top 5 by composite score: 101 (8), 201 (8), 401 (8), 301 (7), 102 (6)
    assert {x["id"] for x in titw["tier_1"]} == {101, 201, 401, 301, 102}
    # Picked items must not reappear in their home sections.
    assert 101 not in {x["id"] for x in payload["sections"]["Tech & AI"]["tier_1"]}
    assert 201 not in {x["id"] for x in payload["sections"]["Toronto Housing"]["tier_1"]}
    assert 301 not in {x["id"] for x in payload["sections"]["Finance & Markets"]["tier_1"]}
    assert 401 not in {x["id"] for x in payload["sections"]["US & Global"]["tier_1"]}


def test_build_format_input_collapses_same_cluster_within_section():
    # Triage clustered both NBC Meet the Press items together (cluster_id
    # "alex_murdaugh"), but build_format_input was treating them as independent
    # items and featuring both in Today in the World. One cluster, one feature.
    tiered_items = [
        _item(213, "Today in the World", tier=1, ccov=2, prel=0, fit="good"),  # score 3
        _item(214, "Today in the World", tier=1, ccov=2, prel=1, fit="good"),  # score 4 (winner)
    ]
    for it in tiered_items:
        it["cluster_id"] = "alex_murdaugh"
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "NBC Meet the Press", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    titw = payload["sections"]["Today in the World"]
    assert len(titw["tier_1"]) == 1
    assert titw["tier_1"][0]["id"] == 214


def test_build_format_input_does_not_collapse_items_with_empty_cluster_id():
    # Missing/empty cluster_id means "no cluster known" - never merge.
    # Five high-scoring swamp items in Canada & Toronto absorb the global
    # pickoff into Today in the World; the test items stay in Tech & AI.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(900, "Canada & Toronto", tier=1, ccov=5, prel=3, fit="good"),
        _item(901, "Canada & Toronto", tier=1, ccov=5, prel=3, fit="good"),
        _item(902, "Canada & Toronto", tier=1, ccov=5, prel=3, fit="good"),
        _item(903, "Canada & Toronto", tier=1, ccov=5, prel=3, fit="good"),
        _item(904, "Canada & Toronto", tier=1, ccov=5, prel=3, fit="good"),
    ]
    for it in tiered_items[:2]:
        it["cluster_id"] = ""
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    tech = payload["sections"]["Tech & AI"]
    assert {x["id"] for x in tech["tier_1"]} == {1, 2}


def test_today_in_the_world_hero_is_highest_scored_with_image():
    # Top scorer has no image; second-top has an image. Hero must be the second.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=4, prel=3, fit="good"),  # 8, no image
        _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),  # 6, with image
        _item(3, "Tech & AI", tier=1, ccov=2, prel=2, fit="good"),  # 5, with image
    ]
    links_by_id = {
        1: {"title": "t1", "source": "X", "snippet": "x", "image": ""},
        2: {"title": "t2", "source": "X", "snippet": "x", "image": "https://img/2.jpg"},
        3: {"title": "t3", "source": "X", "snippet": "x", "image": "https://img/3.jpg"},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    titw = payload["sections"]["Today in the World"]
    # All three picked (top 5 but only 3 candidates).
    assert {x["id"] for x in titw["tier_1"]} == {1, 2, 3}
    # Position 0 (hero) must be id=2 (highest-scored with image).
    assert titw["tier_1"][0]["id"] == 2


def test_today_in_the_world_replaces_worth_knowing_in_section_order():
    from formatting import SECTION_ORDER
    assert "Today in the World" in SECTION_ORDER
    assert "Worth Knowing" not in SECTION_ORDER


def test_today_in_the_world_replaces_worth_knowing_in_section_map():
    from config import SECTION_MAP
    assert "Today in the World" in SECTION_MAP.values()
    assert "Worth Knowing" not in SECTION_MAP.values()


def test_today_in_the_world_has_an_emoji():
    from config import SECTION_EMOJIS
    assert "Today in the World" in SECTION_EMOJIS
    assert "Worth Knowing" not in SECTION_EMOJIS


def test_today_in_the_world_section_renders():
    text = """## Today in the World

🌐 **Big global story [#5]:** Body sentence with the gist.
"""
    links_by_id = {5: {"link": "https://example.com/5", "image": "", "title": "Big global story"}}
    clusters_by_item_id = {5: {"primary_source": "NYT", "also_in": ["BBC"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    assert "In the World" in html
    assert "Today in the World" not in html
    assert "🌐" in html
    assert "Big global story" in html


def test_today_in_the_world_renders_as_in_design_for_weekend():
    text = """## Today in the World

🎨 **Studio launches identity refresh [#7]:** Body sentence with the gist.
"""
    links_by_id = {7: {"link": "https://example.com/7", "image": "", "title": "Studio identity"}}
    html, _ = parse_and_render_sections(text, links_by_id, {}, is_design_edition=True)
    assert "In Design" in html
    assert "In the World" not in html
    assert "🎨" in html
    assert "Today in the World" not in html


def test_today_in_the_world_layout_renders_hero_and_emoji_items():
    text = """## Today in the World

🤖 **Odyssey ships two world models [#10]:** The AI lab released [Agora-1](https://odyssey.example/agora) for multiplayer simulation and Starchild-1 for audio.

🏠 **Toronto rents drop again [#11]:** Average asking rent slid 4 percent for the third consecutive month.

⚖️ **Privacy bill passes committee [#12]:** Auto-delete defaults move closer to law.

📈 **Markets rally on rate cut [#13]:** S&P closed up 1.2 percent after the Fed signaled easing.

🚇 **TTC subway extension funded [#14]:** Federal commitment closes the funding gap.
"""
    links_by_id = {
        10: {"link": "https://odyssey.example/news", "image": "https://img/10.jpg",
             "title": "Odyssey ships two world models"},
        11: {"link": "https://rent.example/", "image": "", "title": "Toronto rents drop"},
        12: {"link": "https://privacy.example/", "image": "", "title": "Privacy bill"},
        13: {"link": "https://markets.example/", "image": "", "title": "Markets rally"},
        14: {"link": "https://ttc.example/", "image": "", "title": "TTC funded"},
    }
    html, used_ids = parse_and_render_sections(text, links_by_id, {}, tiered_items=[])
    # Hero image from item 10 appears once.
    assert html.count('src="https://img/10.jpg"') == 1
    # All 5 emoji + bold headers render.
    assert "🤖" in html and "🏠" in html and "⚖️" in html and "📈" in html and "🚇" in html
    # Inline markdown link in item 10's body becomes an anchor.
    assert '<a href="https://odyssey.example/agora"' in html
    # All 5 IDs are tracked as used.
    assert {10, 11, 12, 13, 14}.issubset(used_ids)


def test_build_format_input_embeds_sibling_urls_for_multi_source_clusters():
    # Swamp the global pickoff with 5 higher-scored items in another section so
    # the Tech & AI cluster's tier-1 item stays in Tech & AI rather than being
    # promoted into Today in the World.
    tiered_items = [
        {"id": 50, "section": "Tech & AI", "tier": 1, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 51, "section": "Tech & AI", "tier": 2, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 1, "section_fit": "good"}},
        {"id": 52, "section": "Tech & AI", "tier": 3, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 0, "section_fit": "good"}},
        _item(91, "Canada & Toronto", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(92, "Canada & Toronto", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(93, "Canada & Toronto", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(94, "Canada & Toronto", tier=1, ccov=4, prel=4, fit="good"),  # score 9
        _item(95, "Canada & Toronto", tier=1, ccov=4, prel=4, fit="good"),  # score 9
    ]
    links_by_id = {
        50: {"title": "Primary headline", "source": "TechCrunch",
             "snippet": "x", "link": "https://tc.example/50", "image": ""},
        51: {"title": "Same story diff angle", "source": "The Verge",
             "snippet": "x", "link": "https://verge.example/51", "image": ""},
        52: {"title": "Wire copy", "source": "Reuters",
             "snippet": "x", "link": "https://reut.example/52", "image": ""},
        91: {"title": "t91", "source": "CBC", "snippet": "x", "link": "https://cbc/91", "image": ""},
        92: {"title": "t92", "source": "CBC", "snippet": "x", "link": "https://cbc/92", "image": ""},
        93: {"title": "t93", "source": "CBC", "snippet": "x", "link": "https://cbc/93", "image": ""},
        94: {"title": "t94", "source": "CBC", "snippet": "x", "link": "https://cbc/94", "image": ""},
        95: {"title": "t95", "source": "CBC", "snippet": "x", "link": "https://cbc/95", "image": ""},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    tech = payload["sections"]["Tech & AI"]["tier_1"]
    # Locate the primary cluster item (id=50). The cap=2 fallback may also
    # promote a tier-2 sibling into tier_1, but we only care about item 50's
    # sibling list here.
    primary = next(item for item in tech if item["id"] == 50)
    siblings = primary["siblings"]
    # Siblings exclude the primary item itself.
    sources_with_urls = {(s["source"], s["url"]) for s in siblings}
    assert ("The Verge", "https://verge.example/51") in sources_with_urls
    assert ("Reuters", "https://reut.example/52") in sources_with_urls
    assert ("TechCrunch", "https://tc.example/50") not in sources_with_urls


def test_build_format_input_omits_siblings_for_finance_and_us_global():
    # Swamp items in Canada & Toronto absorb the global pickoff so the
    # Finance & Markets item stays in its home section for the assertion.
    tiered_items = [
        {"id": 60, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 61, "section": "Finance & Markets", "tier": 2, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"}},
        {"id": 70, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_c1",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 71, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_c2",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 72, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_c3",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 73, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_c4",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 74, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_c5",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},
    ]
    links_by_id = {
        60: {"title": "FOMC", "source": "WSJ", "snippet": "x",
             "link": "https://wsj.example/60", "image": ""},
        61: {"title": "FOMC angle", "source": "Yahoo Finance", "snippet": "x",
             "link": "https://yf.example/61", "image": ""},
        70: {"title": "swamp", "source": "CBC", "snippet": "x", "link": "https://cbc.example/70", "image": ""},
        71: {"title": "swamp", "source": "CBC", "snippet": "x", "link": "https://cbc.example/71", "image": ""},
        72: {"title": "swamp", "source": "CBC", "snippet": "x", "link": "https://cbc.example/72", "image": ""},
        73: {"title": "swamp", "source": "CBC", "snippet": "x", "link": "https://cbc.example/73", "image": ""},
        74: {"title": "swamp", "source": "CBC", "snippet": "x", "link": "https://cbc.example/74", "image": ""},
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    fm = payload["sections"]["Finance & Markets"]["tier_1"][0]
    assert fm.get("siblings", []) == []


def test_body_paragraphs_render_markdown_links_as_html():
    text = """## Tech & AI

**Multi-source story [#200]**
Claude says [The Verge](https://verge.example/x) covered this first.

Source: TechCrunch
"""
    links_by_id = {200: {"link": "https://tc.example/200", "image": "",
                         "title": "Multi-source story"}}
    clusters_by_item_id = {200: {"primary_source": "TechCrunch",
                                 "also_in": ["The Verge"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    # Markdown link survives as a real anchor tag.
    assert '<a href="https://verge.example/x"' in html
    assert ">The Verge</a>" in html
    # Raw markdown brackets must not leak through.
    assert "[The Verge]" not in html


def test_body_paragraphs_render_markdown_bold_as_html():
    text = """## Tech & AI

**Story headline [#201]**
The Fed's **rate cut** signal moved markets. Body continues normally.

Source: WSJ
"""
    links_by_id = {201: {"link": "https://example.com/201", "image": "",
                         "title": "Story headline"}}
    clusters_by_item_id = {201: {"primary_source": "WSJ", "also_in": []}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    # Stray **rate cut** inside body becomes a strong tag.
    assert "<strong>rate cut</strong>" in html
    # Raw markdown asterisks must not leak through.
    assert "**rate cut**" not in html


def test_body_paragraphs_render_link_with_bold_in_label():
    # Edge case: link label contains bold. Link converts first, so the bold
    # markers inside the label get converted at the second pass.
    text = """## Tech & AI

**Story headline [#202]**
Read [**this**](https://example.com/x) for more.

Source: WSJ
"""
    links_by_id = {202: {"link": "https://example.com/202", "image": "",
                         "title": "Story headline"}}
    clusters_by_item_id = {202: {"primary_source": "WSJ", "also_in": []}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    # Anchor renders with bold-tagged label inside.
    assert '<a href="https://example.com/x"' in html
    assert "<strong>this</strong>" in html


def test_format_prompt_describes_today_in_the_world_layout():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Layout description must mention the emoji-led item structure for TitW.
    assert "Today in the World" in FORMAT_SYSTEM_PROMPT
    assert "emoji" in FORMAT_SYSTEM_PROMPT.lower()
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()


def test_format_prompt_describes_from_the_front_page_fallback():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Single-featured section fallback must be documented.
    assert "single featured story" in FORMAT_SYSTEM_PROMPT.lower()
    assert "3 to 4" in FORMAT_SYSTEM_PROMPT or "three to four" in FORMAT_SYSTEM_PROMPT.lower()


def test_format_prompt_describes_inline_source_links_rule():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Inline link rule and the Finance/US & Global exclusion must both be stated.
    assert "siblings" in FORMAT_SYSTEM_PROMPT.lower()
    assert "Finance & Markets" in FORMAT_SYSTEM_PROMPT
    assert "US & Global" in FORMAT_SYSTEM_PROMPT


def test_featured_story_caps_body_paragraphs_at_two():
    """Renderer caps featured-story body paragraphs at 2 even if Claude emits more."""
    text = """## Toronto Housing

**Stronger protection has arrived [#100]**
**Enhanced safeguards.** Ontario has new protections for pre-construction buyers.

**Market confidence building.** These protections restore trust in the new home market.

**Economic ripple effects.** A more secure marketplace boosts construction activity.
Source: Storeys

**Hidden townhouse hits the market [#101]**
**Exclusive enclave.** A rare Annex townhouse appeared on MLS.

**Understated luxury.** The community values privacy over flash.

**Market positioning.** At $2M, it targets discreet buyers.
Source: BlogTO
"""
    links_by_id = {
        100: {"link": "https://storeys.example/100", "image": "", "title": "Stronger protection"},
        101: {"link": "https://blogto.example/101", "image": "", "title": "Hidden townhouse"},
    }
    html, _ = parse_and_render_sections(text, links_by_id, {}, tiered_items=[])

    # First two paragraphs of story 100 render.
    assert "<strong>Enhanced safeguards.</strong>" in html
    assert "<strong>Market confidence building.</strong>" in html
    # Third paragraph of story 100 must NOT render.
    assert "<strong>Economic ripple effects.</strong>" not in html
    assert "Economic ripple effects" not in html

    # First two paragraphs of story 101 render.
    assert "<strong>Exclusive enclave.</strong>" in html
    assert "<strong>Understated luxury.</strong>" in html
    # Third paragraph of story 101 must NOT render.
    assert "<strong>Market positioning.</strong>" not in html
    assert "Market positioning" not in html


def test_single_story_section_renders_micro_headers_via_default_path():
    """Sections with exactly one story still render bold micro-headers on
    each paragraph after the longform branch is removed."""
    text = """## Finance & Markets

**Fed signals rate cut [#200]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back to one.

**Threading the needle.** Powell framed the move as data-dependent.
Source: WSJ
"""
    links_by_id = {200: {"link": "https://wsj.example/200", "image": "https://img/200.jpg",
                         "title": "Fed signals rate cut"}}
    clusters_by_item_id = {200: {"primary_source": "WSJ", "also_in": []}}
    html, used_ids = parse_and_render_sections(text, links_by_id, clusters_by_item_id, tiered_items=[])

    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    # Hero image rendered.
    assert 'src="https://img/200.jpg"' in html
    # Source line rendered.
    assert "WSJ" in html
    # ID tracked.
    assert 200 in used_ids


def test_featured_story_renders_micro_headers():
    """Featured-story body paragraphs that open with **Cap.** render as
    <strong>Cap.</strong> inline."""
    text = """## Finance & Markets

**Fed signals rate cut by year end [#300]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back to one.

**Threading the needle.** Powell framed the move as data-dependent without naming a trigger.

Source: WSJ
"""
    links_by_id = {300: {"link": "https://wsj.example/300", "image": "https://img/300.jpg",
                         "title": "Fed signals rate cut"}}
    clusters_by_item_id = {300: {"primary_source": "WSJ", "also_in": []}}
    html, used_ids = parse_and_render_sections(text, links_by_id, clusters_by_item_id, tiered_items=[])
    # Two paragraph micro-headers render as bold inside the paragraph.
    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    # Hero image rendered.
    assert 'src="https://img/300.jpg"' in html
    # Source line still rendered.
    assert "WSJ" in html
    # ID tracked.
    assert 300 in used_ids


def test_end_to_end_renders_both_layouts(tmp_path):
    """Synthetic Claude response covering Featured Layout (Today in the
    World) and Layout A (every other section). Smoke test — verifies all
    section blocks render without error and produce non-empty HTML."""
    from formatting import build_email_html
    response = """SUBJECT: 🤖 Odyssey ships world models

## Today in the World

🤖 **Odyssey ships two world models [#10]:** The AI lab released [Agora-1](https://odyssey.example/agora) and Starchild-1.

🏠 **Toronto rents drop again [#11]:** Asking rent fell 4 percent for the third month.

⚖️ **Privacy bill passes committee [#12]:** Auto-delete defaults move closer to law.

📈 **Markets rally on rate cut [#13]:** S&P up 1.2 percent on Fed signal.

🚇 **TTC subway extension funded [#14]:** Federal commitment closes the gap.

## Tech & AI

**Two big AI announcements today [#20]**
**Setup.** Body paragraph one with [a link](https://example.com/x).

**Stakes.** Body paragraph two.
Source: TechCrunch

**Second featured story [#21]**
**Opening.** Body paragraph one.

**Implication.** Body paragraph two.
Source: Hacker News

## US & Global

**Fed signals rate cut by year end [#30]**
**Decreasing optimism.** Markets had priced in two cuts. The Fed walked it back.

**Threading the needle.** Powell framed the move as data-dependent.
Source: WSJ
"""
    links_by_id = {
        10: {"link": "https://odyssey.example/news", "image": "https://img/10.jpg", "title": "Odyssey"},
        11: {"link": "https://rent.example/", "image": "", "title": "Rents"},
        12: {"link": "https://privacy.example/", "image": "", "title": "Privacy bill"},
        13: {"link": "https://markets.example/", "image": "", "title": "Markets"},
        14: {"link": "https://ttc.example/", "image": "", "title": "TTC"},
        20: {"link": "https://tc.example/20", "image": "https://img/20.jpg", "title": "AI announcements"},
        21: {"link": "https://hn.example/21", "image": "", "title": "Second story"},
        30: {"link": "https://wsj.example/30", "image": "https://img/30.jpg", "title": "Fed cut"},
    }
    html, subject = build_email_html(response, links_by_id, {}, tiered_items=[])
    assert "In the World" in html
    assert "Tech & AI" in html
    assert "US & Global" in html
    assert "Odyssey ships world models" in subject
    # Featured Layout markers
    assert '<img src="https://img/10.jpg"' in html  # Featured Layout hero
    assert "🤖" in html and "🚇" in html             # Featured Layout emojis
    # Layout A markers
    assert '<a href="https://example.com/x"' in html  # inline link in Tech & AI body
    assert "<strong>Decreasing optimism.</strong>" in html
    assert "<strong>Threading the needle.</strong>" in html
    assert "<strong>Setup.</strong>" in html
    assert "<strong>Stakes.</strong>" in html

    # Write the rendered HTML to a tmp file so Frank can open it visually.
    out = tmp_path / "sample-newsletter.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nSample newsletter rendered to: {out}")


def test_end_to_end_pipeline_from_build_format_input_to_html(tmp_path):
    """Walk the full pipeline: tier scoring → build_format_input → synthesized
    Claude response → build_email_html. Verifies that the global top-5 pickoff,
    sibling URL plumbing, and per-section caps all behave correctly when
    chained together with the renderer."""
    from formatting import build_format_input, build_email_html
    import json as _json

    # 8 candidates across multiple sections. After build_format_input runs:
    #   - Today in the World should receive the top 5 by composite score
    #     (lifted from their home sections, removed from those sections).
    #   - Cluster cl_a has 2 members (10 and 11) so item 10 should carry a
    #     siblings entry pointing at item 11's URL.
    #   - Finance & Markets has 1 item (left after pickoff lifts the highest
    #     scorer), which renders through the unified Layout A path.
    tiered_items = [
        # Top-5 candidates (highest scores → pickoff lifts these into TitW)
        {"id": 10, "section": "Tech & AI", "tier": 1, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 3, "section_fit": "good"}},  # 9
        {"id": 20, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # 8
        {"id": 30, "section": "US & Global", "tier": 1, "cluster_id": "cl_c",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # 8
        {"id": 40, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_d",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # 8
        {"id": 50, "section": "Toronto Housing", "tier": 1, "cluster_id": "cl_e",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # 8
        # Sibling for cluster cl_a — same cluster as item 10 but tier 2; should
        # appear in item 10's siblings array but NOT be picked into TitW.
        {"id": 11, "section": "Tech & AI", "tier": 2, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 5, "personal_relevance": 2, "section_fit": "good"}},
        # Remaining Finance & Markets candidate so the section keeps an item
        # after pickoff drains item 40.
        {"id": 41, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_f",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},  # 6
        # Tech & AI extra so the section keeps a tier-1 after item 10 leaves.
        {"id": 12, "section": "Tech & AI", "tier": 1, "cluster_id": "cl_g",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},  # 6
    ]
    links_by_id = {
        10: {"title": "Hero TitW story", "source": "TechCrunch", "snippet": "x",
             "link": "https://tc.example/10", "image": "https://img/10.jpg"},
        11: {"title": "Sibling story", "source": "The Verge", "snippet": "x",
             "link": "https://verge.example/11", "image": ""},
        12: {"title": "Tech leftover", "source": "Hacker News", "snippet": "x",
             "link": "https://hn.example/12", "image": ""},
        20: {"title": "Canada lift", "source": "CBC", "snippet": "x",
             "link": "https://cbc.example/20", "image": ""},
        30: {"title": "US lift", "source": "BBC", "snippet": "x",
             "link": "https://bbc.example/30", "image": ""},
        40: {"title": "Finance lift", "source": "WSJ", "snippet": "x",
             "link": "https://wsj.example/40", "image": ""},
        41: {"title": "Finance leftover", "source": "Yahoo Finance", "snippet": "x",
             "link": "https://yf.example/41", "image": ""},
        50: {"title": "Housing lift", "source": "Storeys", "snippet": "x",
             "link": "https://storeys.example/50", "image": ""},
    }

    # Step 1: build_format_input — this is what Claude would normally receive.
    payload_json = build_format_input(tiered_items, {}, links_by_id)
    payload = _json.loads(payload_json)

    # Step 2: structural assertions on the payload.
    titw = payload["sections"]["Today in the World"]["tier_1"]
    titw_ids = {item["id"] for item in titw}
    assert titw_ids == {10, 20, 30, 40, 50}, \
        f"Expected top-5 pickoff to lift {{10, 20, 30, 40, 50}}, got {titw_ids}"

    # Hero is the only image-bearer in the top 5.
    assert titw[0]["id"] == 10, "Hero must be the image-bearing item"

    # Item 10's siblings should include item 11's URL (same cluster cl_a, Tech & AI not excluded).
    hero_siblings = {(s["source"], s["url"]) for s in titw[0]["siblings"]}
    assert ("The Verge", "https://verge.example/11") in hero_siblings, \
        f"Hero siblings missing The Verge: {hero_siblings}"

    # Finance & Markets after pickoff: item 40 should be gone, item 41 should remain.
    fm_tier1 = payload["sections"]["Finance & Markets"]["tier_1"]
    fm_ids = {item["id"] for item in fm_tier1}
    assert fm_ids == {41}, f"Finance & Markets should have item 41 only, got {fm_ids}"
    # Cap=1 means the section has a single Layout A story. Siblings should be empty (Finance & Markets is excluded).
    assert fm_tier1[0]["siblings"] == [], "Finance & Markets items must have empty siblings"

    # Tech & AI after pickoff: item 10 gone, item 12 should remain.
    tech_tier1 = payload["sections"]["Tech & AI"]["tier_1"]
    tech_ids = {item["id"] for item in tech_tier1}
    assert 10 not in tech_ids, "Item 10 should have left Tech & AI"
    assert 12 in tech_ids, "Item 12 should still be in Tech & AI"

    # Step 3: synthesize a Claude response that uses the IDs build_format_input emitted.
    # Today in the World: Layout A (hero is item 10).
    titw_lines = []
    for item in titw:
        emoji = "🌐"
        header = f"{item['title']}"
        titw_lines.append(f"{emoji} **{header} [#{item['id']}]:** Body text.")
    titw_block = "\n\n".join(titw_lines)

    response = f"""SUBJECT: 🌐 Test subject

## Today in the World

{titw_block}

## Finance & Markets

**{fm_tier1[0]['title']} [#{fm_tier1[0]['id']}]**
**Setup.** First paragraph of body.

**Turn.** Second paragraph of body.

Source: Yahoo Finance

## Tech & AI

**{tech_tier1[0]['title']} [#{tech_tier1[0]['id']}]**
Body paragraph one.

Body paragraph two.
Source: Hacker News
"""

    # Step 4: render through build_email_html.
    html, subject = build_email_html(response, links_by_id, {}, tiered_items=tiered_items)

    # Assertions: pipeline produced a coherent email.
    assert "In the World" in html
    assert "Finance & Markets" in html
    assert "Tech & AI" in html
    assert "🌐 Test subject" in subject
    # Hero image rendered exactly once.
    assert html.count('src="https://img/10.jpg"') == 1
    # Featured Layout emoji items render.
    assert "🌐" in html
    # Layout A micro-header markers render as bold inside paragraphs.
    assert "<strong>Setup.</strong>" in html
    assert "<strong>Turn.</strong>" in html


def test_suppressed_cluster_ids_keeps_highest_scored_representative():
    # Four feed items, one underlying story, one cluster (the real
    # cuba_raul_castro_charges case). One item survives as the
    # representative; the other three ids are suppressed.
    items = [
        _item(57, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(83, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(85, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
        _item(76, "US & Global", tier=2, ccov=4, prel=0, fit="good"),  # score 5
    ]
    for it in items:
        it["cluster_id"] = "cuba_raul_castro_charges"
    # All four tie at score 5; the lowest id (57) wins the tiebreak and
    # survives, so the other three are suppressed.
    assert suppressed_cluster_ids(items) == {83, 85, 76}


def test_suppressed_cluster_ids_ignores_singletons_and_empty_clusters():
    # _item gives each item a unique cluster_id (cl_<id>), so items 1 and 2
    # are singleton clusters. Items 3 and 4 carry an explicit empty
    # cluster_id ("no cluster known"). Nothing is suppressed.
    items = [
        _item(1, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=2, prel=1, fit="good"),
        _item(3, "Tech & AI", tier=2),
        _item(4, "Tech & AI", tier=2),
    ]
    items[2]["cluster_id"] = ""
    items[3]["cluster_id"] = ""
    assert suppressed_cluster_ids(items) == set()


def test_build_format_input_collapses_cluster_across_sections():
    # Triage clustered the same story under two different sections. The
    # global collapse keeps only the highest-scored member, so the
    # cross-section duplicate never reaches the formatter.
    tiered_items = [
        _item(10, "US & Global", tier=1, ccov=4, prel=1, fit="good"),        # score 6
        _item(11, "Finance & Markets", tier=1, ccov=3, prel=0, fit="good"),  # score 4
    ]
    for it in tiered_items:
        it["cluster_id"] = "trump_iran_attack"
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "Reuters", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    surviving = [
        it["id"]
        for sec in payload["sections"].values()
        for bucket in sec.values()
        for it in bucket
    ]
    assert surviving == [10]


def test_suppressed_cluster_sibling_absent_from_rendered_html():
    # The real cuba_raul_castro_charges case: four articles, one cluster.
    # The representative is featured; the other three must not reappear in
    # Other Headlines or Everything Else.
    tiered_items = [
        _item(57, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(83, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(85, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
        _item(76, "US & Global", tier=2, ccov=4, prel=0, fit="good"),
    ]
    for it in tiered_items:
        it["cluster_id"] = "cuba_raul_castro_charges"
    links_by_id = {
        57: {"title": "US charges Raul Castro over plane downing",
             "link": "https://bbc.com/57", "image": "", "source": "BBC",
             "snippet": "The indictment names the former leader."},
        83: {"title": "Cuba's Raul Castro indicted over 1996 downing",
             "link": "https://npr.org/83", "image": "", "source": "NPR World",
             "snippet": "A grand jury returned the indictment."},
        85: {"title": "US grand jury indicts Raul Castro",
             "link": "https://npr.org/85", "image": "", "source": "NPR World",
             "snippet": "The charges relate to the 1996 shootdown."},
        76: {"title": "News of indictment slow to reach Cubans",
             "link": "https://nyt.com/76", "image": "", "source": "NYT",
             "snippet": "Cubans waiting for a breakthrough."},
    }
    suppressed = suppressed_cluster_ids(tiered_items)  # {83, 85, 76}
    formatter_output = (
        "SUBJECT: 🌐 Castro charged\n\n"
        "## US & Global\n"
        "**US charges Raul Castro over plane downing [#57]**\n"
        "**The indictment.** A federal court has charged the former leader.\n\n"
        "**The backdrop.** Two civilian planes were shot down in 1996.\n\n"
        "**What is alleged.** Prosecutors tie the order to the chain of command.\n"
        "Source: BBC\n"
    )
    cluster_info = {"primary_source": "BBC", "also_in": ["NPR World", "NYT"]}
    html, _ = build_email_html(
        formatter_output, links_by_id,
        clusters_by_item_id={i: cluster_info for i in (57, 83, 85, 76)},
        tiered_items=tiered_items,
        suppressed_ids=suppressed,
    )
    assert "bbc.com/57" in html        # representative is featured
    assert "npr.org/83" not in html    # suppressed siblings never reappear
    assert "npr.org/85" not in html
    assert "nyt.com/76" not in html


def test_distinct_clusters_are_never_suppressed():
    # Two items in the same section but different stories (distinct
    # cluster_ids, supplied by the _item helper as cl_1 and cl_2). Neither
    # is a duplicate, so neither is suppressed and both survive into the
    # formatter input. This guards against the global collapse over-reaching.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),
        _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good"),
    ]
    assert suppressed_cluster_ids(tiered_items) == set()
    links_by_id = {
        i["id"]: {"title": f"t{i['id']}", "source": "TechCrunch", "snippet": "x"}
        for i in tiered_items
    }
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id))
    surviving = {
        it["id"]
        for sec in payload["sections"].values()
        for bucket in sec.values()
        for it in bucket
    }
    assert surviving == {1, 2}


def test_pick_everything_else_emoji_keyword_match_wins_over_source():
    # Title contains an AI-vendor keyword; source map says 📈 for WSJ,
    # but the keyword regex must win because it comes first in resolution.
    assert pick_everything_else_emoji("OpenAI raises Series F", "WSJ") == "🤖"


def test_pick_everything_else_emoji_source_used_when_no_keyword_match():
    # Title has no mapped keyword; source map kicks in.
    assert pick_everything_else_emoji("Quiet Monday at the market", "WSJ") == "📈"


def test_pick_everything_else_emoji_safety_net_when_neither_matches():
    # Unmapped source, unmapped keyword set → 📰 safety net.
    assert pick_everything_else_emoji("A poem about clouds", "Unknown Source") == "📰"


def test_pick_everything_else_emoji_is_case_insensitive():
    assert pick_everything_else_emoji("OPENAI hires research lead", "WSJ") == "🤖"
    assert pick_everything_else_emoji("OpEnAi releases benchmark", "WSJ") == "🤖"


def test_pick_everything_else_emoji_respects_word_boundaries():
    # "capitalism" must not match the \b(apple|...)\b rule via substring.
    # Source "WSJ" still resolves to 📈 via the source map.
    assert pick_everything_else_emoji("Capitalism and its critics", "WSJ") == "📈"


def test_pick_everything_else_emoji_empty_title_falls_through_to_source():
    assert pick_everything_else_emoji("", "WSJ") == "📈"
    assert pick_everything_else_emoji(None, "WSJ") == "📈"


def test_pick_everything_else_emoji_first_keyword_in_declared_order_wins():
    # Title mentions both "apple" (🍎) and "google" (🔎). The keyword list
    # declares apple before google, so apple wins.
    assert pick_everything_else_emoji("Apple and Google announce partnership", "WSJ") == "🍎"
