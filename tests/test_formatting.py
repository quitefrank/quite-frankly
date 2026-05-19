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
    assert html.count("<li") == 7
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

**Big global story [#5]**
Body paragraph one.

Body paragraph two.
Source: NYT
"""
    links_by_id = {5: {"link": "https://example.com/5", "image": "", "title": "Big global story"}}
    clusters_by_item_id = {5: {"primary_source": "NYT", "also_in": ["BBC"]}}
    html, _ = parse_and_render_sections(text, links_by_id, clusters_by_item_id)
    assert "Today in the World" in html
    assert "NYT, BBC" in html


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
    tiered_items = [
        {"id": 60, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 2, "section_fit": "good"}},
        {"id": 61, "section": "Finance & Markets", "tier": 2, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"}},
    ]
    links_by_id = {
        60: {"title": "FOMC", "source": "WSJ", "snippet": "x",
             "link": "https://wsj.example/60", "image": ""},
        61: {"title": "FOMC angle", "source": "Yahoo Finance", "snippet": "x",
             "link": "https://yf.example/61", "image": ""},
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
