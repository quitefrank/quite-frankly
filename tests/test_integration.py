"""Integration tests: verify Phase 2 tier promotion reaches the format pass."""

import json


def test_phase2_traction_promotes_borderline_item_into_format_input(monkeypatch):
    """An item Claude tiered as 2 with strong Reddit/HN traction should reach the
    format pass at tier 1 after apply_phase2_tier rewrites it."""
    import triage
    from triage import apply_phase2_tier
    from formatting import build_format_input

    monkeypatch.setattr(triage, "fetch_reddit_traction", lambda url, subs: {"score": 5000, "comments": 800, "subreddit_hits": 3})
    monkeypatch.setattr(triage, "fetch_hn_traction", lambda url: {"points": 250, "comments": 10})

    # Seed two tier-1 items in Canada & Toronto to fill its featured cap (2),
    # preventing fallback fill from pulling lower-tier items. This ensures id=42
    # in Tech & AI is promoted to tier-1 purely by Phase 2 traction, not by the
    # fallback fill mechanism.
    tiered_items = [
        {
            "id": 1,
            "tier": 1,
            "section": "Canada & Toronto",
            "cluster_id": "",
            "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"},
            "promotion_to_today_in_the_world": False,
        },
        {
            "id": 2,
            "tier": 1,
            "section": "Canada & Toronto",
            "cluster_id": "",
            "scores": {"cross_source_coverage": 1, "personal_relevance": 2, "section_fit": "good"},
            "promotion_to_today_in_the_world": False,
        },
        {
            "id": 42,
            "tier": 2,
            "section": "Tech & AI",
            "cluster_id": "",
            "scores": {"cross_source_coverage": 0, "personal_relevance": 2, "section_fit": "weak"},
            "promotion_to_today_in_the_world": False,
        },
    ]
    links_by_id = {
        1: {"link": "https://example.com/story1", "title": "Story 1", "source": "CBC", "image": ""},
        2: {"link": "https://example.com/story2", "title": "Story 2", "source": "Globe", "image": ""},
        42: {"link": "https://example.com/sleeper", "title": "Sleeper story", "source": "TechCrunch", "image": ""},
    }
    clusters: dict = {}
    suppressed_ids: set = set()

    apply_phase2_tier(tiered_items, links_by_id)
    assert tiered_items[2]["tier"] == 1, f"Phase 2 should promote id=42 to tier 1; got {tiered_items[2]['tier']}"

    format_input_json = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids)
    parsed = json.loads(format_input_json)

    ids_in_tier_1: set[int] = set()
    ids_in_tier_2_or_3: set[int] = set()
    for section_buckets in parsed["sections"].values():
        for item in section_buckets.get("tier_1", []):
            ids_in_tier_1.add(item["id"])
        for bucket_name in ("tier_2", "tier_3"):
            for item in section_buckets.get(bucket_name, []):
                ids_in_tier_2_or_3.add(item["id"])

    assert 42 in ids_in_tier_1, "Phase 2 promotion didn't reach the format input as tier 1"
    assert 42 not in ids_in_tier_2_or_3, "Item appears in both tier 1 and a lower tier"
