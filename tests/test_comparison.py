"""Tests for the Phase 1.5 comparison-log layer."""

import json

from comparison import (
    build_comparison_log,
    compute_phase2_tier,
    shadow_score,
    write_comparison_log,
)


def test_compute_phase2_tier_includes_reddit_weight():
    item = {
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
        "reddit": {"score": 5000, "comments": 800, "subreddit_hits": 3},
        "hn": {"points": 0, "comments": 0},
    }
    tier = compute_phase2_tier(item)
    assert tier == 1


def test_compute_phase2_tier_includes_hn_weight():
    item = {
        "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"},
        "reddit": {"score": 0, "comments": 0, "subreddit_hits": 0},
        "hn": {"points": 800, "comments": 250},
    }
    tier = compute_phase2_tier(item)
    assert tier in (1, 2)


def test_compute_phase2_tier_returns_zero_when_no_signal():
    item = {
        "scores": {"cross_source_coverage": 0, "personal_relevance": 0, "section_fit": "none"},
        "reddit": {"score": 0, "comments": 0, "subreddit_hits": 0},
        "hn": {"points": 0, "comments": 0},
    }
    assert compute_phase2_tier(item) == 0


def test_compute_phase2_tier_handles_missing_traction_keys():
    item = {
        "scores": {"cross_source_coverage": 2, "personal_relevance": 1, "section_fit": "good"},
    }
    assert compute_phase2_tier(item) == 1


def test_build_comparison_log_records_promotions():
    phase1 = [
        {"id": 0, "tier": 1, "section": "Canada & Toronto"},
        {"id": 1, "tier": 2, "section": "Tech & AI"},
    ]
    phase2 = [
        {"id": 0, "tier": 1, "section": "Canada & Toronto"},
        {"id": 1, "tier": 1, "section": "Tech & AI"},
    ]
    log = build_comparison_log(date_str="2026-05-20", mode="weekday_daily", phase1=phase1, phase2=phase2)
    assert log["deltas"]["promoted_by_phase2"][0]["id"] == 1
    assert log["deltas"]["promoted_by_phase2"][0]["from"] == 2
    assert log["deltas"]["promoted_by_phase2"][0]["to"] == 1
    assert log["deltas"]["demoted_by_phase2"] == []


def test_build_comparison_log_records_demotions():
    phase1 = [{"id": 0, "tier": 1, "section": "Tech & AI"}]
    phase2 = [{"id": 0, "tier": 3, "section": "Tech & AI"}]
    log = build_comparison_log(date_str="2026-05-21", mode="weekday_daily", phase1=phase1, phase2=phase2)
    assert log["deltas"]["demoted_by_phase2"][0]["id"] == 0
    assert log["deltas"]["demoted_by_phase2"][0]["from"] == 1
    assert log["deltas"]["demoted_by_phase2"][0]["to"] == 3
    assert log["deltas"]["promoted_by_phase2"] == []


def test_build_comparison_log_carries_metadata():
    log = build_comparison_log(date_str="2026-05-22", mode="weekday_daily", phase1=[], phase2=[])
    assert log["date"] == "2026-05-22"
    assert log["mode"] == "weekday_daily"
    assert log["phase1"] == []
    assert log["phase2_shadow"] == []


def test_shadow_score_applies_phase2_tier(monkeypatch):
    def fake_reddit(url, subreddits):
        return {"score": 5000, "comments": 800, "subreddit_hits": 3}

    def fake_hn(url):
        return {"points": 0, "comments": 0}

    monkeypatch.setattr("comparison.fetch_reddit_traction", fake_reddit)
    monkeypatch.setattr("comparison.fetch_hn_traction", fake_hn)

    items = [{
        "id": 0,
        "tier": 3,
        "scores": {"cross_source_coverage": 1, "personal_relevance": 1, "section_fit": "good"},
    }]
    links_by_id = {0: {"link": "https://example.com/x"}}

    result = shadow_score(items, links_by_id)
    assert result[0]["tier"] == 1
    assert items[0]["tier"] == 3  # original list untouched


def test_shadow_score_skips_items_without_link(monkeypatch):
    called = []
    monkeypatch.setattr("comparison.fetch_reddit_traction", lambda u, s: called.append("r") or {"score": 0, "comments": 0, "subreddit_hits": 0})
    monkeypatch.setattr("comparison.fetch_hn_traction", lambda u: called.append("hn") or {"points": 0, "comments": 0})

    items = [{
        "id": 99,
        "tier": 2,
        "scores": {"cross_source_coverage": 1, "personal_relevance": 0, "section_fit": "weak"},
    }]
    links_by_id = {}  # no entry for id 99
    result = shadow_score(items, links_by_id)
    assert called == []
    assert result[0]["tier"] == 2  # recomputed from existing scores, no traction


def test_write_comparison_log_writes_file(tmp_path):
    log = {"date": "2026-05-20", "mode": "weekday_daily", "phase1": [], "phase2_shadow": [], "deltas": {}}
    write_comparison_log(log, base_dir=tmp_path)
    written = json.loads((tmp_path / "2026-05-20.json").read_text())
    assert written["date"] == "2026-05-20"
    assert written["mode"] == "weekday_daily"


def test_write_comparison_log_creates_dir(tmp_path):
    target = tmp_path / "nested" / "comparison"
    log = {"date": "2026-05-23"}
    write_comparison_log(log, base_dir=target)
    assert (target / "2026-05-23.json").exists()
