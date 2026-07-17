import json
import archive
from config import FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL
from routing import Mode


def Mode_SAT(): return Mode.SATURDAY_STRATEGIC
def Mode_SUN(): return Mode.SUNDAY_VISUAL
def Mode_WEEKDAY(): return Mode.WEEKDAY_DAILY


def _archived(link, source, first_seen_ts):
    return {"title": f"t-{link}", "source": source, "snippet": "s", "image": "",
            "published_ts": None, "first_seen_ts": first_seen_ts, "link": link}


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "nope.json"))
    assert archive.load() == {}


def test_save_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "a.json"))
    archive.save({"k": {"title": "t"}})
    assert archive.load() == {"k": {"title": "t"}}


def test_design_feeds_and_source_sets_cover_all_nine():
    # DESIGN_FEEDS is the union of the two weekend feed sets.
    assert archive.DESIGN_FEEDS == FEEDS_SATURDAY_STRATEGIC + FEEDS_SUNDAY_VISUAL
    assert archive.STRATEGIC_SOURCES == {f["source"] for f in FEEDS_SATURDAY_STRATEGIC}
    assert archive.VISUAL_SOURCES == {f["source"] for f in FEEDS_SUNDAY_VISUAL}
    assert len(archive.STRATEGIC_SOURCES | archive.VISUAL_SOURCES) == 9


def _entry(link, source, snippet="a real snippet", image="", published_ts=None):
    return {"title": f"t-{link}", "link": link, "snippet": snippet,
            "image": image, "source": source, "published_ts": published_ts}


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "a.json"))


def test_accumulate_upserts_new_items_with_first_seen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    result = archive.accumulate(
        now=1000.0,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Design Milk" else [],
        enrich_fn=lambda items: None,
    )
    key = archive.normalize_url("https://design-milk.com/x")
    assert key in result
    assert result[key]["first_seen_ts"] == 1000.0
    assert result[key]["source"] == "Design Milk"
    assert result[key]["link"] == "https://design-milk.com/x"


def test_accumulate_keeps_original_first_seen_on_reseen(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    ff = lambda fc, limit: fetched if fc["source"] == "Design Milk" else []
    archive.accumulate(now=1000.0, fetch_feed_fn=ff, enrich_fn=lambda i: None)
    result = archive.accumulate(now=5000.0, fetch_feed_fn=ff, enrich_fn=lambda i: None)
    key = archive.normalize_url("https://design-milk.com/x")
    assert result[key]["first_seen_ts"] == 1000.0  # unchanged on re-sighting


def test_accumulate_skips_junk_dated_first_sightings(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    now = 1_000_000_000.0
    stale = now - archive.JUNK_DATE_MAX_AGE_S - 1
    fetched = [_entry("https://trendland.com/old", "Trendland", published_ts=stale)]
    result = archive.accumulate(
        now=now,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Trendland" else [],
        enrich_fn=lambda i: None,
    )
    assert result == {}  # 2023-dated item never enters the archive


def test_accumulate_keeps_undated_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://sidebar.io/z", "Sidebar", published_ts=None)]
    result = archive.accumulate(
        now=1000.0,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Sidebar" else [],
        enrich_fn=lambda i: None,
    )
    assert archive.normalize_url("https://sidebar.io/z") in result


def test_accumulate_prunes_entries_older_than_seven_days(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from config import SEVEN_DAYS_S
    archive.save({"old": {"title": "t", "source": "Sidebar", "link": "https://sidebar.io/old",
                          "snippet": "", "image": "", "published_ts": None,
                          "first_seen_ts": 100.0}})
    now = 100.0 + SEVEN_DAYS_S + 1
    result = archive.accumulate(now=now, fetch_feed_fn=lambda fc, limit: [],
                                enrich_fn=lambda i: None)
    assert "old" not in result


def test_accumulate_enriches_only_new_items(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = []
    fetched = [_entry("https://design-milk.com/x", "Design Milk")]
    ff = lambda fc, limit: fetched if fc["source"] == "Design Milk" else []
    archive.accumulate(now=1000.0, fetch_feed_fn=ff, enrich_fn=lambda items: seen.append(len(items)))
    archive.accumulate(now=2000.0, fetch_feed_fn=ff, enrich_fn=lambda items: seen.append(len(items)))
    assert seen == [1, 0]  # enriched 1 new item first run, 0 on the re-sighting


def test_accumulate_dedupes_same_link_across_feeds_in_one_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    dup = "https://design-milk.com/dup"
    # Two different design sources both surface the same link this run.
    def ff(fc, limit):
        if fc["source"] in ("Design Milk", "It's Nice That"):
            return [_entry(dup, fc["source"])]
        return []
    result = archive.accumulate(now=1000.0, fetch_feed_fn=ff, enrich_fn=lambda i: None)
    matches = [k for k in result if k == archive.normalize_url(dup)]
    assert len(matches) == 1  # collapsed to a single entry


def test_accumulate_persists_enrich_mutations(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    fetched = [_entry("https://design-milk.com/x", "Design Milk", image="")]
    def enrich(items):
        for it in items:
            it["image"] = "https://cdn/og.jpg"  # mimic og:image backfill
    result = archive.accumulate(
        now=1000.0,
        fetch_feed_fn=lambda fc, limit: fetched if fc["source"] == "Design Milk" else [],
        enrich_fn=enrich,
    )
    key = archive.normalize_url("https://design-milk.com/x")
    assert result[key]["image"] == "https://cdn/og.jpg"


def test_pool_for_saturday_returns_only_strategic_sources(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({
        "a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0),
        "b": _archived("https://design-milk.com/1", "Design Milk", 20.0),
    })
    pool = archive.pool_for(Mode_SAT())
    sources = {i["source"] for i in pool}
    assert sources == {"UX Collective"}


def test_pool_for_sunday_returns_only_visual_sources(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({
        "a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0),
        "b": _archived("https://design-milk.com/1", "Design Milk", 20.0),
    })
    pool = archive.pool_for(Mode_SUN())
    assert {i["source"] for i in pool} == {"Design Milk"}


def test_pool_for_caps_per_source_to_most_recent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    entries = {f"k{i}": _archived(f"https://sidebar.io/{i}", "Sidebar", float(i))
               for i in range(40)}
    archive.save(entries)
    pool = archive.pool_for(Mode_SUN())
    sidebar = [i for i in pool if i["source"] == "Sidebar"]
    assert len(sidebar) == archive.ARCHIVE_PER_SOURCE_CAP
    links = [i["link"] for i in sidebar]
    assert links[0] == "https://sidebar.io/39"
    assert "https://sidebar.io/0" not in links


def test_pool_for_items_have_pipeline_shape(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({"a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0)})
    item = archive.pool_for(Mode_SAT())[0]
    assert set(item) == {"title", "link", "snippet", "image", "source"}


def test_pool_for_weekday_mode_returns_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    archive.save({"a": _archived("https://uxdesign.cc/1", "UX Collective", 10.0)})
    assert archive.pool_for(Mode_WEEKDAY()) == []
