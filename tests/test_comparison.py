"""Tests for the Phase 1.5 comparison-log layer."""

import json

from comparison import (
    build_comparison_log,
    build_weekly_digest_html,
    compute_phase2_tier,
    shadow_score,
    summarize_week,
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


def test_build_comparison_log_enriches_deltas_with_story_metadata():
    phase1 = [{
        "id": 7,
        "tier": 2,
        "section": "Canada & Toronto",
        "headline": "Housing prices spike in GTA",
        "source": "Globe & Mail",
        "link": "https://example.com/gta",
    }]
    phase2 = [{"id": 7, "tier": 1, "section": "Canada & Toronto"}]
    log = build_comparison_log("2026-05-25", "weekday_daily", phase1, phase2)
    entry = log["deltas"]["promoted_by_phase2"][0]
    assert entry["headline"] == "Housing prices spike in GTA"
    assert entry["source"] == "Globe & Mail"
    assert entry["link"] == "https://example.com/gta"
    assert entry["section"] == "Canada & Toronto"


def test_build_comparison_log_falls_back_to_title_when_no_headline():
    phase1 = [{"id": 0, "tier": 1, "section": "Tech & AI", "title": "Old-style title key"}]
    phase2 = [{"id": 0, "tier": 3, "section": "Tech & AI"}]
    log = build_comparison_log("2026-05-25", "weekday_daily", phase1, phase2)
    assert log["deltas"]["demoted_by_phase2"][0]["headline"] == "Old-style title key"


def _write_day(tmp_path, date_str, promoted, demoted):
    log = {
        "date": date_str,
        "mode": "weekday_daily",
        "deltas": {"promoted_by_phase2": promoted, "demoted_by_phase2": demoted},
    }
    (tmp_path / f"{date_str}.json").write_text(json.dumps(log))


def test_summarize_week_counts_promotions_and_demotions(tmp_path):
    _write_day(tmp_path, "2026-05-18", [{"id": 1}, {"id": 2}], [{"id": 3}])
    _write_day(tmp_path, "2026-05-19", [{"id": 4}], [])
    summary = summarize_week(tmp_path, "2026-05-18", "2026-05-24")
    assert summary["total_promotions"] == 3
    assert summary["total_demotions"] == 1
    assert summary["days_with_data"] == 2


def test_summarize_week_returns_zero_when_no_files(tmp_path):
    summary = summarize_week(tmp_path, "2026-05-18", "2026-05-24")
    assert summary["days_with_data"] == 0
    assert summary["total_promotions"] == 0
    assert summary["total_demotions"] == 0
    assert summary["promoted_samples"] == []
    assert summary["demoted_samples"] == []


def test_summarize_week_caps_samples_at_five(tmp_path):
    _write_day(
        tmp_path, "2026-05-18",
        [{"id": i, "from": 2, "to": 1} for i in range(10)],
        [],
    )
    summary = summarize_week(tmp_path, "2026-05-18", "2026-05-18")
    assert summary["total_promotions"] == 10
    assert len(summary["promoted_samples"]) == 5


def test_summarize_week_skips_missing_days(tmp_path):
    _write_day(tmp_path, "2026-05-20", [{"id": 1}], [])
    summary = summarize_week(tmp_path, "2026-05-18", "2026-05-24")
    assert summary["days_with_data"] == 1
    assert summary["total_promotions"] == 1


def test_digest_subject_includes_week_start():
    summary = {
        "week_start": "2026-05-18", "week_end": "2026-05-24",
        "days_with_data": 0, "total_promotions": 0, "total_demotions": 0,
        "promoted_samples": [], "demoted_samples": [],
    }
    _, subject = build_weekly_digest_html(summary)
    assert "2026-05-18" in subject
    assert "Phase 2" in subject


def test_digest_zero_data_window_shows_explicit_message():
    summary = {
        "week_start": "2026-05-18", "week_end": "2026-05-24",
        "days_with_data": 0, "total_promotions": 0, "total_demotions": 0,
        "promoted_samples": [], "demoted_samples": [],
    }
    html_body, _ = build_weekly_digest_html(summary)
    assert "No comparison data yet" in html_body
    assert "next weekday run" in html_body


def test_digest_renders_promoted_samples_with_headline_and_source():
    summary = {
        "week_start": "2026-05-18", "week_end": "2026-05-24",
        "days_with_data": 5, "total_promotions": 1, "total_demotions": 0,
        "promoted_samples": [{
            "id": 7, "from": 2, "to": 1,
            "headline": "Housing prices spike in GTA",
            "source": "Globe & Mail",
            "link": "https://example.com/gta",
        }],
        "demoted_samples": [],
    }
    html_body, _ = build_weekly_digest_html(summary)
    assert "Housing prices spike in GTA" in html_body
    assert "Globe &amp; Mail" in html_body  # escaped ampersand
    assert "https://example.com/gta" in html_body
    assert "tier 2 → tier 1" in html_body
    assert "Top swap-ins" in html_body
    assert "Top swap-outs" not in html_body  # no demoted samples, section hidden


def test_digest_renders_promotion_and_demotion_counts():
    summary = {
        "week_start": "2026-05-18", "week_end": "2026-05-24",
        "days_with_data": 5, "total_promotions": 12, "total_demotions": 4,
        "promoted_samples": [], "demoted_samples": [],
    }
    html_body, _ = build_weekly_digest_html(summary)
    assert "<strong>12</strong> items promoted" in html_body
    assert "<strong>4</strong> items demoted" in html_body
    assert "Comparison data: 5 day" in html_body


def test_digest_escapes_html_in_headlines():
    summary = {
        "week_start": "2026-05-18", "week_end": "2026-05-24",
        "days_with_data": 1, "total_promotions": 1, "total_demotions": 0,
        "promoted_samples": [{
            "id": 1, "from": 2, "to": 1,
            "headline": "<script>alert('x')</script> headline",
            "source": "Source & Co",
            "link": "https://example.com",
        }],
        "demoted_samples": [],
    }
    html_body, _ = build_weekly_digest_html(summary)
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "Source &amp; Co" in html_body
