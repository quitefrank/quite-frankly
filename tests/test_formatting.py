import json
import re

import formatting
from formatting import (
    build_email_html,
    build_everything_else,
    build_format_input,
    parse_and_render_sections,
    pick_everything_else_emoji,
    render_other_headlines_for_section,
    render_source_line,
    suppressed_cluster_ids,
    near_duplicate_ids,
)


def test_ee_borrows_cluster_sibling_image_when_item_has_none():
    # An EE item from an IP-blocked source (no image) should borrow an
    # image-bearing cluster sibling's image before the resolver falls to AI.
    links_by_id = {
        1: {"link": "http://bd/x", "image": "", "title": "BD", "snippet": "", "source": "BetterDwelling"},
        2: {"link": "http://st/x", "image": "http://st/og.jpg", "title": "Storeys", "snippet": "", "source": "Storeys"},
    }
    tiered_items = [
        {"id": 1, "cluster_id": "c1", "tier": 2, "scores": {}},
        {"id": 2, "cluster_id": "c1", "tier": 1, "scores": {}},
    ]
    out = dict(formatting._ee_items_with_cluster_image_fallback([(1, links_by_id[1])], links_by_id, tiered_items))
    assert out[1]["image"] == "http://st/og.jpg"
    assert links_by_id[1]["image"] == ""  # original dict not mutated


def test_write_subject_blurbs_requests_generous_max_tokens():
    # The batch covers every Other Headlines + Everything Else item (~28). At
    # max_tokens=1500 the JSON truncated mid-string and the whole batch fell to
    # title-only. The ceiling must be high enough to emit the full batch.
    captured = {}

    class _Block:
        text = '[{"id": 1, "subject": "Canada jobs", "blurb": "Sentence one. Sentence two."}]'

    class _Msg:
        content = [_Block()]
        stop_reason = "end_turn"

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Msg()

    class _Client:
        messages = _Messages()

    items = [(1, {"title": "t", "snippet": "s", "source": "x"})]
    out = formatting.write_subject_blurbs(items, sentences_by_id={1: 2}, client=_Client())
    assert out[1]["blurb"] == "Sentence one. Sentence two."
    assert captured["max_tokens"] >= 4000


def test_ee_keeps_own_image_and_skips_borrow_without_sibling():
    links_by_id = {
        1: {"link": "http://a/1", "image": "http://a/own.jpg", "title": "A", "snippet": ""},
        3: {"link": "http://b/3", "image": "", "title": "B", "snippet": ""},
    }
    tiered_items = [
        {"id": 1, "cluster_id": "c1", "tier": 1, "scores": {}},
        {"id": 3, "cluster_id": "c2", "tier": 2, "scores": {}},  # alone in its cluster
    ]
    out = dict(formatting._ee_items_with_cluster_image_fallback(
        [(1, links_by_id[1]), (3, links_by_id[3])], links_by_id, tiered_items))
    assert out[1]["image"] == "http://a/own.jpg"  # own image kept
    assert out[3]["image"] == ""                   # no sibling -> stays empty -> AI


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
        # fit="weak" so the weekday pickoff still pulls it (weak/no-fit only);
        # ccov=5 keeps its composite at 9 so Today in the World still sorts first.
        _item(91, "Toronto Housing", tier=1, ccov=5, prel=4, fit="weak"),  # score 9
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


def test_render_other_headlines_for_section_renders_title_only_when_snippet_is_empty():
    # When an item has no usable snippet (e.g. an hnrss item whose RSS
    # description is metadata-only and was cleared at ingest), the row
    # must render as the linked title alone — no trailing ": " separator.
    tiered_items = [
        {"id": 7, "section": "Tech & AI", "tier": 2,
         "scores": {"cross_source_coverage": 3, "personal_relevance": 2, "section_fit": "good"}},
    ]
    links_by_id = {
        7: {"link": "https://example.com/7", "title": "Claude Code as a Daily Driver",
            "snippet": "", "source": "Hacker News", "image": ""},
    }
    used_ids = set()
    html = render_other_headlines_for_section("Tech & AI", tiered_items, links_by_id, used_ids)
    assert "Claude Code as a Daily" in html
    assert "</a>: " not in html
    assert "</a></li>" in html


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
    # New structure: <p> per item, no <ul>/<li>. Each item carries an emoji
    # span and a first-words anchor link (no <strong> — item links are unbolded).
    assert "<ul" not in html
    assert "<li" not in html
    assert html.count("<p style=\"margin:0 0 14px") == 7
    assert html.count("<a href") == 7
    assert "<strong>" not in html
    # Every item uses source "CBC" → natural pick is 🇨🇦. Dedup kicks in:
    # the first item keeps 🇨🇦, the rest cascade through the fallback pool.
    assert html.count("🇨🇦") == 1
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
    # is_design_edition=True: top-5-by-score lift regardless of fit is the
    # weekend highlight-reel behaviour. Weekday now gates on weak/no fit.
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=True))
    titw = payload["sections"]["Today in the World"]
    # Top 5 by composite score: 101 (8), 201 (8), 401 (8), 301 (7), 102 (6)
    assert {x["id"] for x in titw["tier_1"]} == {101, 201, 401, 301, 102}
    # Picked items must not reappear in their home sections.
    assert 101 not in {x["id"] for x in payload["sections"]["Tech & AI"]["tier_1"]}
    assert 201 not in {x["id"] for x in payload["sections"]["Toronto Housing"]["tier_1"]}
    assert 301 not in {x["id"] for x in payload["sections"]["Finance & Markets"]["tier_1"]}
    assert 401 not in {x["id"] for x in payload["sections"]["US & Global"]["tier_1"]}


def test_pickoff_ranks_by_popularity_not_relevance():
    # #1: huge personal relevance, no coverage/traction.
    # #2: low relevance, wide coverage + reddit-hot → more "talked about".
    tiered_items = [
        {"id": 1, "section": "Design & Product", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 3, "section_fit": "good"}},
        {"id": 2, "section": "Tech & AI", "tier": 1, "cluster_id": "c2",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 0, "section_fit": "good"},
         "reddit": {"score": 1500, "subreddit_hits": 3}, "hn": {"points": 300}},
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "s", "image": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=True))
    world = payload["sections"]["Today in the World"]["tier_1"]
    assert world[0]["id"] == 2


def test_weekday_pickoff_pulls_only_misfit_stories():
    # Weekday (is_design_edition=False): only weak/none section_fit items are
    # eligible for "In the World" — the ones that don't land in a section.
    tiered_items = [
        {"id": 1, "section": "Tech & AI", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "good"}},  # great fit → stays in section
        {"id": 2, "section": "Tech & AI", "tier": 1, "cluster_id": "c2",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 0, "section_fit": "none"}},   # no fit → pickoff
        {"id": 3, "section": "US & Global", "tier": 1, "cluster_id": "c3",
         "scores": {"cross_source_coverage": 3, "personal_relevance": 0, "section_fit": "weak"}},   # weak fit → pickoff
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "s", "image": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=False))
    world_ids = {x["id"] for x in payload["sections"]["Today in the World"]["tier_1"]}
    assert world_ids == {2, 3}
    # The good-fit story stays in its home section, not the pickoff.
    assert payload["sections"]["Tech & AI"]["tier_1"][0]["id"] == 1


def test_weekday_pickoff_caps_at_five_by_popularity():
    # Seven eligible misfit (weak/none fit) items on a weekday: only the top 5
    # by popularity (cross_source_coverage dominates) survive into In the World.
    # ccov descends 7..1 so the ranking is unambiguous; ids 1-5 (ccov 7..3) win,
    # ids 6,7 (ccov 2,1) drop out, exercising the weekday cap + popularity sort.
    tiered_items = [
        {"id": i, "section": "Tech & AI", "tier": 1, "cluster_id": f"c{i}",
         "scores": {"cross_source_coverage": 8 - i, "personal_relevance": 0, "section_fit": "none"}}
        for i in range(1, 8)
    ]
    links_by_id = {i["id"]: {"title": f"t{i['id']}", "source": "X", "snippet": "s", "image": ""} for i in tiered_items}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=False))
    world_ids = {x["id"] for x in payload["sections"]["Today in the World"]["tier_1"]}
    assert world_ids == {1, 2, 3, 4, 5}


def test_weekend_pickoff_still_pulls_top_regardless_of_fit():
    # Weekend keeps the highlight-reel behaviour: best item wins even with good fit.
    tiered_items = [
        {"id": 1, "section": "Design & Product", "tier": 1, "cluster_id": "c1",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 2, "section_fit": "good"}},
    ]
    links_by_id = {1: {"title": "t1", "source": "X", "snippet": "s", "image": ""}}
    payload = json.loads(build_format_input(tiered_items, {}, links_by_id, is_design_edition=True))
    world_ids = {x["id"] for x in payload["sections"]["Today in the World"]["tier_1"]}
    assert world_ids == {1}


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
    # fit="none" so all three are pulled into the weekday pickoff; the test is
    # about image-based hero promotion, not section fit.
    tiered_items = [
        _item(1, "Tech & AI", tier=1, ccov=4, prel=3, fit="none"),  # highest score, no image
        _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="none"),  # 2nd score, with image
        _item(3, "Tech & AI", tier=1, ccov=2, prel=2, fit="none"),  # 3rd score, with image
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


def test_format_prompt_describes_featured_layout():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Featured Layout is the renamed Today in the World list layout.
    assert "Featured Layout" in FORMAT_SYSTEM_PROMPT
    assert "Today in the World" in FORMAT_SYSTEM_PROMPT
    assert "emoji" in FORMAT_SYSTEM_PROMPT.lower()
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()


def test_format_prompt_describes_layout_a_for_other_sections():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Layout A is the unified featured-story format for every non-Today section.
    assert "Layout A" in FORMAT_SYSTEM_PROMPT
    # Layout A requires exactly 2 body paragraphs.
    assert "2 body paragraphs" in FORMAT_SYSTEM_PROMPT or "two body paragraphs" in FORMAT_SYSTEM_PROMPT.lower()
    # Each paragraph opens with a bold micro-header.
    assert "micro-header" in FORMAT_SYSTEM_PROMPT.lower()
    # Layouts B and C are no longer mentioned.
    assert "Layout B" not in FORMAT_SYSTEM_PROMPT
    assert "Layout C" not in FORMAT_SYSTEM_PROMPT


def test_format_prompt_describes_inline_source_links_rule():
    from prompts import FORMAT_SYSTEM_PROMPT
    # Inline link rule and the Finance/US & Global exclusion must both be stated.
    assert "siblings" in FORMAT_SYSTEM_PROMPT.lower()
    assert "Finance & Markets" in FORMAT_SYSTEM_PROMPT
    assert "US & Global" in FORMAT_SYSTEM_PROMPT


def test_per_section_prompt_has_section_callout_rules():
    from prompts import (
        FORMAT_SYSTEM_PROMPT_PER_SECTION,
        FORMAT_SYSTEM_PROMPT_PER_ARTICLE,
    )
    # New per-section prompt: collective block, no "for you", whole-section scope.
    assert "What this means:" in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "What this means for you:" not in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "Other Headlines" in FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert "at least one" in FORMAT_SYSTEM_PROMPT_PER_SECTION.lower()
    # Legacy per-article prompt keeps the old single-sentence rule.
    assert "What this means for you:" in FORMAT_SYSTEM_PROMPT_PER_ARTICLE
    # Shared structure survives in both.
    for p in (FORMAT_SYSTEM_PROMPT_PER_SECTION, FORMAT_SYSTEM_PROMPT_PER_ARTICLE):
        assert "Layout A" in p
        assert "Featured Layout" in p


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
    """Sections with exactly one story render bold micro-headers on each
    paragraph through the unified default rendering path."""
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
    html, subject, _ = build_email_html(response, links_by_id, {}, tiered_items=[])
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
    # The top-5 lift candidates use section_fit="weak" so the weekday pickoff
    # (which gates on weak/no fit) still lifts them, keeping the downstream
    # siblings/hero/per-section-cap assertions exercising the same plumbing.
    # Item 10 carries ccov=6 so it still out-scores its cluster sibling 11 (8)
    # and stays the cl_a representative even with the weak-fit penalty gone.
    tiered_items = [
        # Top-5 candidates (highest scores → pickoff lifts these into TitW)
        {"id": 10, "section": "Tech & AI", "tier": 1, "cluster_id": "cl_a",
         "scores": {"cross_source_coverage": 6, "personal_relevance": 3, "section_fit": "weak"}},  # 9
        {"id": 20, "section": "Canada & Toronto", "tier": 1, "cluster_id": "cl_b",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "weak"}},  # 7
        {"id": 30, "section": "US & Global", "tier": 1, "cluster_id": "cl_c",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "weak"}},  # 7
        {"id": 40, "section": "Finance & Markets", "tier": 1, "cluster_id": "cl_d",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "weak"}},  # 7
        {"id": 50, "section": "Toronto Housing", "tier": 1, "cluster_id": "cl_e",
         "scores": {"cross_source_coverage": 4, "personal_relevance": 3, "section_fit": "weak"}},  # 7
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
    html, subject, _ = build_email_html(response, links_by_id, {}, tiered_items=tiered_items)

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
    html, _, _ = build_email_html(
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


def test_pick_everything_else_emoji_dedups_via_used_set():
    # Natural pick for an OpenAI headline is 🤖. With 🤖 already used,
    # the picker should walk to the next candidate (source, then fallback).
    used = {"🤖"}
    # No source match here ("WSJ" → 📈), so 📈 should be next.
    assert pick_everything_else_emoji("OpenAI announces new model", "WSJ", used) == "📈"


def test_pick_everything_else_emoji_falls_back_to_pool_when_keyword_and_source_used():
    # Headline keyword pick is 🇨🇦 (liberal), source pick is also 🇨🇦 (CBC).
    # Both taken → walk EVERYTHING_ELSE_FALLBACK_POOL. First entry is 📰.
    used = {"🇨🇦"}
    assert pick_everything_else_emoji("Liberal party rally in Ottawa", "CBC", used) == "📰"


def test_build_everything_else_emojis_are_all_unique():
    # All 7 items share source "CBC" → natural pick 🇨🇦 for each. With dedup
    # the section should still render 7 distinct emojis.
    links_by_id = {
        i: {
            "id": i,
            "title": f"Headline {i}",
            "link": f"https://example.com/{i}",
            "image": "",
            "source": "CBC",
        }
        for i in range(7)
    }
    tiered_items = [
        {"id": i, "tier": 2, "section": "Canada & Toronto",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}}
        for i in range(7)
    ]
    html = build_everything_else(links_by_id, used_ids=set(), clusters_by_item_id={},
                                 tiered_items=tiered_items)
    # Each rendered item carries one emoji inside <span style="margin-right:6px">…</span>.
    emojis = re.findall(r'<span style="margin-right:6px">([^<]+)</span>', html)
    assert len(emojis) == 7
    assert len(set(emojis)) == 7


# ── Weekend dark mode ────────────────────────────────────────────────────────

from formatting import LIGHT, DARK, build_email_html


def _weekend_html():
    html, _, _ = build_email_html("## Tech & AI\n\n**Hello world [#1]**\nBody text.\nSource: CBC",
                               {1: {"link": "https://x.co", "image": None, "title": "Hello world", "snippet": ""}},
                               is_design_edition=True)
    return html


def _weekday_html():
    html, _, _ = build_email_html("## Tech & AI\n\n**Hello world [#1]**\nBody text.\nSource: CBC",
                               {1: {"link": "https://x.co", "image": None, "title": "Hello world", "snippet": ""}},
                               is_design_edition=False)
    return html


def test_palettes_have_identical_keys():
    assert set(LIGHT) == set(DARK)


def test_weekend_shell_is_dark():
    html = _weekend_html()
    assert "#202226" in html                       # dark page bg (medium charcoal)
    assert 'background:#ffffff' in html             # inverted white header bar
    assert 'name="color-scheme" content="dark"' in html
    assert 'content="dark"' in html
    assert "color-scheme:dark" in html.replace(" ", "")


def test_weekday_shell_is_light():
    html = _weekday_html()
    assert "#f4f4f4" in html                        # light page bg
    assert "#202226" not in html
    assert 'name="color-scheme" content="light"' in html


from formatting import render_source_line, _render_body_markdown


def test_source_line_uses_palette_accent():
    light = render_source_line("CBC", [], "https://x.co", palette=LIGHT)
    dark = render_source_line("CBC", [], "https://x.co", palette=DARK)
    assert "#1c7ff2" in light
    assert "#4d9bff" in dark
    assert "#1c7ff2" not in dark


def test_body_markdown_link_uses_palette():
    dark = _render_body_markdown("see [docs](https://x.co)", palette=DARK)
    assert "#c8c8c8" in dark          # body link colour
    assert "#4d9bff" in dark          # underline accent
    assert "#1c7ff2" not in dark


from formatting import _render_today_in_the_world, render_other_headlines_for_section


def test_today_in_world_dark_palette():
    links = {1: {"link": "https://x.co", "image": None, "title": "T"}}
    html = _render_today_in_the_world(["🌍 **Header [#1]:** body"], links, set(), palette=DARK)
    assert "#f5f5f5" in html       # heading-coloured link
    assert "#4d9bff" in html       # underline accent
    assert "#c8c8c8" in html       # body paragraph
    assert "#1c7ff2" not in html


def test_other_headlines_dark_palette():
    items = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {}}]
    links = {1: {"link": "https://x.co", "title": "One two three four five six", "snippet": "A sentence."}}
    html = render_other_headlines_for_section("Tech & AI", items, links, set(), palette=DARK)
    assert "#c8c8c8" in html       # link + item body
    assert "#4d9bff" in html       # underline accent
    assert "#9e9e9e" in html       # "Other Headlines" label
    assert "#3a3d45" in html       # divider (dark)
    assert "#1c7ff2" not in html


from formatting import parse_and_render_sections


def test_section_card_dark_palette():
    text = "## Tech & AI\n\n**Big news [#1]**\nThe body paragraph.\nSource: CBC\nWhat this means for you: do X"
    links = {1: {"link": "https://x.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, palette=DARK)
    assert "background:#2b2d33" in html      # card bg
    assert "1px solid #3a3d45" in html       # card border
    assert "#f5f5f5" in html                 # headline
    assert "#c8c8c8" in html                 # body + callout text
    assert "background:#16243a" in html      # callout bg
    assert "#4d9bff" in html                 # accent label + callout stripe
    assert "#1c7ff2" not in html
    assert "#ffffff" not in html             # no light card bg leaked in section


def test_section_card_light_unchanged():
    text = "## Tech & AI\n\n**Big news [#1]**\nThe body paragraph.\nSource: CBC"
    links = {1: {"link": "https://x.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links)  # default LIGHT
    assert "background:#fff" in html
    assert "#1c7ff2" in html
    assert "#202226" not in html


from formatting import build_everything_else


def test_everything_else_dark_palette():
    links = {1: {"link": "https://x.co", "title": "One two three four five", "source": "CBC", "image": None}}
    items = [{"id": 1, "tier": 3, "scores": {}}]
    html = build_everything_else(links, set(), tiered_items=items, palette=DARK)
    assert "background:#2b2d33" in html      # card bg
    assert "1px solid #3a3d45" in html       # card border
    assert "#c8c8c8" in html                 # item text + link
    assert "#4d9bff" in html                 # accent (label + underline)
    assert "#1c7ff2" not in html


LIGHT_ONLY_MARKERS = ["#f4f4f4", "#1c7ff2", "#f0f4ff", "#E9EBF7", "#79787d", "#f0f0f0"]
DARK_ONLY_MARKERS = ["#202226", "#4d9bff", "#2b2d33", "#16243a", "#1a1c2e"]

# Two featured stories in Tech & AI so the inter-story divider renders; that
# hairline carries the divider colour (#f0f0f0 light / #3a3d45 dark), which a
# single-story fixture would never emit.
_FULL_TEXT = (
    "## Today in the World\n\n🌍 **Rates held [#1]:** markets mixed.\n\n"
    "## Tech & AI\n\n**Big news [#2]**\nBody paragraph here.\nSource: CBC\n"
    "What this means for you: test it\n\n"
    "**Second story [#3]**\nAnother body paragraph.\nSource: BBC"
)
_FULL_LINKS = {
    1: {"link": "https://a.co", "image": None, "title": "Rates held", "snippet": "x"},
    2: {"link": "https://b.co", "image": None, "title": "Big news", "snippet": "y"},
    3: {"link": "https://c.co", "image": None, "title": "Second story", "snippet": "z"},
}


def test_full_weekend_build_has_no_light_only_colours():
    html, _, _ = build_email_html(_FULL_TEXT, _FULL_LINKS, is_design_edition=True)
    for m in LIGHT_ONLY_MARKERS:
        assert m not in html, f"light-only colour {m} leaked into dark build"
    for m in DARK_ONLY_MARKERS:
        assert m in html


def test_full_weekday_build_has_no_dark_only_colours():
    html, _, _ = build_email_html(_FULL_TEXT, _FULL_LINKS, is_design_edition=False)
    for m in DARK_ONLY_MARKERS:
        assert m not in html, f"dark-only colour {m} leaked into light build"
    for m in LIGHT_ONLY_MARKERS:
        assert m in html


# ── Everything Else Morning-Brew-style copy (subject + blurb) ────────────────

from formatting import write_subject_blurbs, _everything_else_line, _other_headline_line, LIGHT


class _FakeMessage:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]


class _FakeClient:
    """Stands in for anthropic.Anthropic. Returns a canned response or raises."""
    def __init__(self, text=None, exc=None):
        self._text, self._exc = text, exc
        self.messages = self
        self.received = None

    def create(self, **kwargs):
        self.received = kwargs
        if self._exc:
            raise self._exc
        return _FakeMessage(self._text)


def _ee_links(n):
    return {
        i: {"id": i, "title": f"Headline number {i} here", "link": f"https://e.co/{i}",
            "image": "", "source": "CBC", "snippet": f"Snippet {i}."}
        for i in range(n)
    }


def _ee_tiers(n):
    return [{"id": i, "tier": 3, "section": "Tech & AI",
             "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "none"}}
            for i in range(n)]


def test_everything_else_renders_subject_blurb():
    links = _ee_links(1)
    copy = {0: {"subject": "Anthropic", "blurb": "Anthropic filed to go public, lodging a confidential prospectus with the SEC."}}
    html = build_everything_else(links, set(), tiered_items=_ee_tiers(1), copy_by_id=copy)
    # Subject is the anchor text; blurb follows with no colon glue.
    assert ">Anthropic</a> filed to go public" in html
    assert "Anthropic:" not in html
    # Emoji prefix preserved.
    assert '<span style="margin-right:6px">' in html


def test_everything_else_falls_back_to_title_when_copy_missing():
    links = _ee_links(1)
    # No copy_by_id at all → legacy title-only (first four words linked).
    html = build_everything_else(links, set(), tiered_items=_ee_tiers(1))
    assert ">Headline number 0 here</a>" in html


def test_everything_else_subject_first_when_blurb_not_prefixed():
    links = _ee_links(1)
    copy = {0: {"subject": "Colombia", "blurb": "The country heads to a runoff presidential election."}}
    html = build_everything_else(links, set(), tiered_items=_ee_tiers(1), copy_by_id=copy)
    # Subject still leads as the link, blurb follows after a space.
    assert ">Colombia</a> The country heads to a runoff" in html


def test_everything_else_line_blank_copy_uses_title():
    l = {"title": "First second third fourth fifth", "link": "https://e.co/1"}
    line = _everything_else_line(l, {"subject": "", "blurb": ""}, LIGHT)
    assert ">First second third fourth</a> fifth" in line


def test_write_subject_blurbs_parses_filters_and_strips():
    fake = _FakeClient(text=(
        "```json\n"
        '[{"id": 0, "subject": " Anthropic ", "blurb": " Anthropic filed to go public. "},'
        '{"id": 1, "subject": "OpenAI", "blurb": ""},'   # empty blurb → dropped
        '{"id": "x", "subject": "Bad", "blurb": "id"}]'   # bad id → dropped
        "\n```"
    ))
    out = write_subject_blurbs([(0, {"title": "t"}), (1, {"title": "t"})], client=fake)
    assert out == {0: {"subject": "Anthropic", "blurb": "Anthropic filed to go public."}}
    # Items were sent to the model.
    assert fake.received["model"]


def test_write_subject_blurbs_returns_empty_on_error():
    fake = _FakeClient(exc=RuntimeError("boom"))
    out = write_subject_blurbs([(0, {"title": "t"})], client=fake)
    assert out == {}


def test_write_subject_blurbs_empty_items_no_call():
    fake = _FakeClient(text="[]")
    out = write_subject_blurbs([], client=fake)
    assert out == {}
    assert fake.received is None  # never hit the API


def test_build_email_html_invokes_writer_with_selected_items():
    links = _ee_links(2)
    text = "## Tech & AI\n\n**Featured [#99]**\nBody.\nSource: CBC"
    links[99] = {"id": 99, "title": "Featured", "link": "https://e.co/99", "image": "", "source": "CBC", "snippet": ""}
    seen = {}

    def writer(items, sentences_by_id=None):
        for lid, _l in items:
            seen[lid] = True
        return {0: {"subject": "Anthropic", "blurb": "Anthropic filed to go public today."}}

    html, _, _ = build_email_html(text, links, {}, tiered_items=_ee_tiers(2) + [{"id": 99, "tier": 1, "section": "Tech & AI", "scores": {}}], blurb_writer=writer)
    assert ">Anthropic</a> filed to go public" in html
    assert 0 in seen and 1 in seen  # writer saw the selected EE items


def test_other_headline_line_renders_subject_blurb_without_colon():
    l = {"title": "Some headline words here", "link": "https://e.co/1", "snippet": "Ignored snippet."}
    copy = {"subject": "Andrew Left", "blurb": "Andrew Left was found guilty of securities fraud by a jury."}
    line = _other_headline_line(l, copy, LIGHT)
    assert ">Andrew Left</a> was found guilty of securities fraud" in line
    # No colon-glue and the legacy first-5-words/snippet path is not used.
    assert "Andrew Left:" not in line
    assert "Ignored snippet" not in line


def test_other_headline_line_falls_back_to_title_and_snippet():
    l = {"title": "First second third fourth fifth sixth", "link": "https://e.co/1", "snippet": "A summary sentence. More."}
    line = _other_headline_line(l, None, LIGHT)
    # Legacy: first five words linked, colon, first sentence of the snippet.
    assert ">First second third fourth fifth</a>: A summary sentence." in line


def test_build_email_html_writes_other_headlines_copy():
    # One featured story plus two tier-2 items in the same section become Other
    # Headlines; the writer should receive them and their copy should render.
    links = {
        99: {"id": 99, "title": "Featured", "link": "https://e.co/99", "image": "", "source": "CBC", "snippet": ""},
        1: {"id": 1, "title": "Rate decision lands today", "link": "https://e.co/1", "image": "", "source": "CBC", "snippet": "The bank held."},
        2: {"id": 2, "title": "Condo starts slow down", "link": "https://e.co/2", "image": "", "source": "CBC", "snippet": "Builders paused."},
    }
    tiered = [
        {"id": 99, "tier": 1, "section": "Finance & Markets", "scores": {}},
        {"id": 1, "tier": 2, "section": "Finance & Markets",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}},
        {"id": 2, "tier": 2, "section": "Finance & Markets",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "weak"}},
    ]
    text = "## Finance & Markets\n\n**Featured [#99]**\nBody.\nSource: CBC"
    seen_ids = []

    def writer(items, sentences_by_id=None):
        seen_ids.extend(lid for lid, _ in items)
        return {1: {"subject": "The Bank of Canada", "blurb": "The Bank of Canada held its rate at 4.25%."}}

    html, _, _ = build_email_html(text, links, {}, tiered_items=tiered, blurb_writer=writer)
    assert 1 in seen_ids and 2 in seen_ids           # OH picks reached the writer
    assert ">The Bank of Canada</a> held its rate" in html  # OH copy rendered
    assert "<li" in html                             # bullets kept, no emoji added


def test_near_duplicate_ids_catches_same_story_different_clusters():
    a = _item(7, "Design & Product", tier=1, ccov=1, prel=2, fit="good")   # score 4
    b = _item(8, "Tech & AI", tier=2, ccov=1, prel=1, fit="good")          # score 3
    links_by_id = {
        7: {"title": "IAI Codex goals explained for product teams",
            "link": "https://iai.com/codex",
            "snippet": "Bryce Ratner walks through how Keith Lee built a no-code fitness app."},
        8: {"title": "How she built a fitness app with no code",
            "link": "https://maker.com/keith-lee",
            "snippet": "Keith Lee built her no-code fitness app, profiled by Bryce Ratner."},
    }
    assert near_duplicate_ids([a, b], links_by_id) == {8}


def test_near_duplicate_ids_catches_shared_video_even_with_thin_text():
    a = _item(1, "Design & Product", tier=1, ccov=2, prel=1, fit="good")   # score 4
    b = _item(2, "Tech & AI", tier=2, ccov=1, prel=0, fit="weak")          # score 1
    links_by_id = {
        1: {"title": "Profile of a builder", "link": "https://a.com/x",
            "snippet": "full story at https://youtu.be/dQw4w9WgXcQ"},
        2: {"title": "Totally different framing", "link": "https://b.com/y",
            "snippet": "watch https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    }
    assert near_duplicate_ids([a, b], links_by_id) == {2}


def test_near_duplicate_ids_leaves_distinct_stories_alone():
    a = _item(1, "Tech & AI", tier=1, ccov=3, prel=2, fit="good")
    b = _item(2, "Tech & AI", tier=1, ccov=3, prel=2, fit="good")
    links_by_id = {
        1: {"title": "Anthropic ships prompt caching", "link": "https://x.com/1",
            "snippet": "Anthropic cut token costs on repeated context."},
        2: {"title": "Bank of Canada holds rates", "link": "https://y.com/2",
            "snippet": "The central bank kept its policy rate unchanged."},
    }
    assert near_duplicate_ids([a, b], links_by_id) == set()


def test_near_duplicate_ids_catches_2026_06_06_lennys_incident():
    # Real 2026-06-06 incident, verified against the live pages. The same
    # Lenny's "How I AI" episode (YouTube EJKwI4m0fZg) surfaced as two RSS
    # entries with different URLs and differently-framed titles: the full
    # episode in Design & Product, and the no-code fitness app segment in the
    # In Design list. Titles share "building an iphone app with zero technical
    # skills". Worst realistic shape: the segment carries its fitness-app
    # description, the episode carries title only -> overlap coefficient 0.5.
    a = _item(31, "Design & Product", tier=1, ccov=1, prel=2, fit="good")   # episode
    b = _item(32, "Design & Product", tier=2, ccov=1, prel=1, fit="good")   # segment
    links_by_id = {
        31: {"title": "🎙️ How I AI: Codex Goals explained & Claude Opus 4.8 review "
                      "& Building an iPhone app with zero technical skills",
             "link": "https://www.lennysnewsletter.com/p/how-i-ai-codex-goals-explained-and",
             "snippet": ""},
        32: {"title": "Building an iPhone app with zero technical skills | Bryce Rattner Keithley",
             "link": "https://www.lennysnewsletter.com/p/building-an-iphone-app-with-zero",
             "snippet": "How a non-technical talent leader built and shipped a fitness app "
                        "to the App Store, complete with AI-generated videos of animals doing exercises."},
    }
    suppressed = near_duplicate_ids([a, b], links_by_id)
    assert len(suppressed) == 1          # exactly one of the two survives
    assert suppressed == {32}            # higher-scored episode (31) is the representative


def test_write_subject_blurbs_payload_tags_sentence_targets():
    import formatting

    captured = {}

    class _FakeMsg:
        content = [type("B", (), {"text": "[]"})()]

    class _FakeMessages:
        def create(self, **kwargs):
            captured["user"] = kwargs["messages"][0]["content"]
            return _FakeMsg()

    class _FakeClient:
        messages = _FakeMessages()

    items = [(10, {"title": "A", "snippet": "", "source": "x"}),
             (11, {"title": "B", "snippet": "", "source": "y"})]
    formatting.write_subject_blurbs(
        items, sentences_by_id={10: 2, 11: 1}, client=_FakeClient()
    )

    import json
    payload = json.loads(captured["user"])
    by_id = {o["id"]: o["sentences"] for o in payload}
    assert by_id == {10: 2, 11: 1}


def test_build_everything_else_renders_thumbnail_when_cid_present():
    from formatting import build_everything_else, LIGHT

    links = {
        1: {"title": "Alpha story here now", "link": "http://a/1",
            "source": "Src", "scores": {}, "image": ""},
    }
    tiered = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {"composite": 5}}]
    html = build_everything_else(
        links, used_ids=set(), tiered_items=tiered, palette=LIGHT,
        images_by_id={1: "ee-1@quitefrankly"},
    )
    assert 'src="cid:ee-1@quitefrankly"' in html
    assert "border-radius:8px" in html


def test_build_everything_else_text_only_without_cid():
    from formatting import build_everything_else, LIGHT

    links = {
        1: {"title": "Alpha story here now", "link": "http://a/1",
            "source": "Src", "scores": {}, "image": ""},
    }
    tiered = [{"id": 1, "section": "Tech & AI", "tier": 2, "scores": {"composite": 5}}]
    html = build_everything_else(links, used_ids=set(), tiered_items=tiered, palette=LIGHT)
    assert "cid:" not in html
    assert "<img" not in html


def _minimal_build_email_inputs():
    """Minimal inputs for build_email_html with at least one EE item.

    One tier-1 item (#99) is mentioned in the Claude response so it becomes a
    featured story and lands in used_ids. Items #0 and #1 are tier-3 items that
    are in links_by_id but never featured, so _select_everything_else picks them
    up as Everything Else candidates.
    """
    claude_response = "## Tech & AI\n\n**Featured story [#99]**\nBody.\nSource: CBC\n"
    links_by_id = {
        99: {"id": 99, "title": "Featured story", "link": "https://e.co/99",
             "image": "", "source": "CBC", "snippet": ""},
        0: {"id": 0, "title": "Headline number 0 here", "link": "https://e.co/0",
            "image": "", "source": "CBC", "snippet": "Snippet 0."},
        1: {"id": 1, "title": "Headline number 1 here", "link": "https://e.co/1",
            "image": "", "source": "CBC", "snippet": "Snippet 1."},
    }
    tiered = [
        {"id": 99, "tier": 1, "section": "Tech & AI", "scores": {}},
        {"id": 0, "tier": 3, "section": "Tech & AI",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "none"}},
        {"id": 1, "tier": 3, "section": "Tech & AI",
         "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "none"}},
    ]
    return claude_response, links_by_id, tiered


def test_build_email_html_returns_inline_images():
    from formatting import build_email_html
    from images import ThumbAsset

    claude_response, links_by_id, tiered = _minimal_build_email_inputs()

    def fake_resolver(ee_items, *, cache_dir):
        return {lid: ThumbAsset(cid=f"ee-{lid}@quitefrankly", data=b"x")
                for lid, _ in ee_items}

    html, subject, inline_images = build_email_html(
        claude_response, links_by_id, tiered_items=tiered,
        thumbnail_resolver=fake_resolver,
    )
    # Every returned asset's cid must actually appear in the HTML.
    assert inline_images  # at least one Everything Else item resolved
    for a in inline_images:
        assert f"cid:{a.cid}" in html
    assert isinstance(subject, str)


def test_build_email_message_has_related_image_parts():
    from formatting import build_email_message
    from images import ThumbAsset

    assets = [ThumbAsset(cid="ee-1@quitefrankly", data=b"\x89PNG-bytes")]
    msg = build_email_message("<html><img src='cid:ee-1@quitefrankly'></html>",
                              "Subject", assets)

    assert msg.get_content_type() == "multipart/related"
    image_parts = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(image_parts) == 1
    assert image_parts[0]["Content-ID"] == "<ee-1@quitefrankly>"


def test_build_email_message_no_images_is_plain_html():
    from formatting import build_email_message
    msg = build_email_message("<html>hi</html>", "Subject", [])
    assert "text/html" in [p.get_content_type() for p in msg.walk()]


def test_callout_mode_defaults_to_section():
    import importlib, config
    importlib.reload(config)
    assert config.CALLOUT_MODE == "section"


def test_select_format_prompt_by_mode():
    from formatting import select_format_prompt
    from prompts import (
        FORMAT_SYSTEM_PROMPT_PER_SECTION,
        FORMAT_SYSTEM_PROMPT_PER_ARTICLE,
    )
    assert select_format_prompt("section") is FORMAT_SYSTEM_PROMPT_PER_SECTION
    assert select_format_prompt("article") is FORMAT_SYSTEM_PROMPT_PER_ARTICLE
    # Unknown / None falls back to the configured default ("section").
    assert select_format_prompt(None) is FORMAT_SYSTEM_PROMPT_PER_SECTION


def test_section_mode_single_hit_one_block_at_bottom():
    text = (
        "## Tech & AI\n\n**Big news [#1]**\nBody paragraph.\nSource: CBC\n"
        "**Second story [#2]**\nMore body.\nSource: BBC\n"
        "What this means: One relevant takeaway for you."
    )
    links = {
        1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""},
        2: {"link": "https://b.co", "image": None, "title": "Second story", "snippet": ""},
    }
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert html.count("What this means:") == 1
    assert "What this means for you:" not in html
    assert html.index("What this means:") > html.index("Second story")


def test_section_mode_zero_hits_no_block():
    text = "## Tech & AI\n\n**Big news [#1]**\nBody paragraph.\nSource: CBC"
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert "What this means" not in html


def test_section_mode_tolerates_legacy_for_you_text():
    text = (
        "## Tech & AI\n\n**Big news [#1]**\nBody.\nSource: CBC\n"
        "What this means for you: legacy phrasing still parses."
    )
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert "What this means:</strong> legacy phrasing" in html
    assert "What this means for you:" not in html


def test_article_mode_keeps_legacy_per_story_callout():
    text = "## Tech & AI\n\n**Big news [#1]**\nBody.\nSource: CBC\nWhat this means for you: do X"
    links = {1: {"link": "https://a.co", "image": None, "title": "Big news", "snippet": ""}}
    html, _ = parse_and_render_sections(text, links, callout_mode="article")
    assert "What this means for you:</strong> do X" in html


def test_section_mode_today_in_the_world_block_at_bottom():
    text = (
        "## Today in the World\n\n🌍 **Rates held [#1]:** markets mixed.\n\n"
        "🤖 **AI lab news [#2]:** a model shipped.\n"
        "What this means: The model ship touches the Quite Frankly pipeline."
    )
    links = {
        1: {"link": "https://a.co", "image": None, "title": "Rates held", "snippet": "x"},
        2: {"link": "https://b.co", "image": None, "title": "AI lab news", "snippet": "y"},
    }
    html, _ = parse_and_render_sections(text, links, callout_mode="section")
    assert html.count("What this means:") == 1
    assert html.index("What this means:") > html.index("AI lab news")


def test_section_mode_callout_only_section_renders_no_card():
    # A section with a callout line but no stories and no Other Headlines must
    # not render a stray card holding just the callout.
    text = "## Tech & AI\n\nWhat this means: nothing to anchor this to."
    html, _ = parse_and_render_sections(text, {}, callout_mode="section")
    assert "What this means" not in html
    assert "Tech & AI" not in html


def test_pickoff_item_not_duplicated_in_section_other_headlines():
    # Item #10 is featured in the global pickoff block AND is a tier-1
    # Design & Product item, so OH synthesis would re-list it (the bug).
    text = (
        "## Design & Product\n"
        "**DesignOps shifts [#1]**\nSource: UX Collective\nbody one\n\n"
        "## Today in the World\n"
        "🎨 **Figma goes code-native [#10]:** Config 2026 recap\n"
    )
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),
        _item(10, "Design & Product", tier=1, ccov=2, prel=1, fit="good"),
    ]
    links_by_id = {
        1: {"title": "DesignOps shifts", "source": "UX Collective", "snippet": "x", "link": "https://u/1", "image": ""},
        10: {"title": "Figma goes code-native", "source": "UX Collective", "snippet": "x", "link": "https://u/10", "image": ""},
    }
    html, used_ids = parse_and_render_sections(
        text, links_by_id, {}, tiered_items=tiered_items, is_design_edition=True,
    )
    assert html.count('href="https://u/10"') == 1
    assert 10 in used_ids


def test_pickoff_section_renders_first():
    text = (
        "## Design & Product\n**A [#1]**\nSource: UX Collective\nbody\n\n"
        "## Today in the World\n🎨 **B [#2]:** body two\n"
    )
    tiered_items = [
        _item(1, "Design & Product", tier=1, ccov=2, prel=2, fit="good"),
        _item(2, "Design & Product", tier=1, ccov=2, prel=1, fit="good"),
    ]
    links_by_id = {
        1: {"title": "A", "source": "UX Collective", "snippet": "x", "link": "https://u/1", "image": ""},
        2: {"title": "B", "source": "UX Collective", "snippet": "x", "link": "https://u/2", "image": ""},
    }
    html, _ = parse_and_render_sections(
        text, links_by_id, {}, tiered_items=tiered_items, is_design_edition=True,
    )
    in_design = html.index("In Design")
    section_idx = next(
        html.index(t) for t in ("Design &amp; Product", "Design & Product") if t in html
    )
    assert in_design < section_idx


def test_in_design_emoji_is_paintbrush():
    from formatting import _global_pickoff_display
    title, emoji = _global_pickoff_display(is_design_edition=True)
    assert title == "In Design"
    assert emoji == "🖌️"
    assert _global_pickoff_display(is_design_edition=False) == ("In the World", "🌐")
