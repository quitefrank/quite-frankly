import json
from unittest.mock import patch

import pipeline
from pipeline import assign_ids, deduplicate, fetch_all_feeds, fetch_feed, monday_dedup_bypass, record_seen


def test_assign_ids_returns_dict_keyed_by_id():
    items = [
        {"title": "a", "link": "u1", "source": "CBC"},
        {"title": "b", "link": "u2", "source": "BBC"},
    ]
    by_id = assign_ids(items)
    assert by_id == {0: items[0], 1: items[1]}


def test_assign_ids_attaches_id_to_each_item():
    items = [{"title": "a", "link": "u1", "source": "CBC"}]
    by_id = assign_ids(items)
    assert by_id[0]["id"] == 0


def _fake_parsed(entries):
    parsed = type("Parsed", (), {})()
    parsed.entries = []
    for title, link, summary in entries:
        e = type("Entry", (), {})()
        e.title = title
        e.link = link
        e.summary = summary
        parsed.entries.append(e)
    return parsed


def test_fetch_feed_drops_items_with_empty_or_too_short_snippets():
    # Mirrors the Economist "the-world-this-week" hub items that ship with
    # empty <description> blocks and broke the test email.
    entries = [
        ("The weekly cartoon", "https://example.com/cartoon", ""),
        ("Politics", "https://example.com/politics", ""),
        ("A real article with body", "https://example.com/real",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "Economist"})
    assert [i["title"] for i in items] == ["A real article with body"]


def test_fetch_feed_strips_hnrss_metadata_from_hacker_news_snippets():
    # hnrss.org ships every entry with a metadata-only <description>:
    #   "Article URL: <url> Comments URL: <hn-thread> Points: N # Comments: N"
    # That blob is not an article excerpt — it would render verbatim in
    # Other Headlines as a URL dump. Strip it at ingest so the renderer
    # falls back to a title-only row.
    entries = [
        ("Claude Code as a Daily", "https://arps18.github.io/posts/claude-code-mastery/",
         "Article URL: https://arps18.github.io/posts/claude-code-mastery/ "
         "Comments URL: https://news.ycombinator.com/item?id=48289950 "
         "Points: 94 # Comments: 74"),
    ]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "Hacker News"})
    assert len(items) == 1
    assert items[0]["title"] == "Claude Code as a Daily"
    assert items[0]["snippet"] == ""


def test_fetch_feed_preserves_real_snippets_from_hacker_news():
    # Not every HN entry is metadata-only — Ask HN posts and similar can
    # carry real prose. Only the hnrss "Article URL: ..." prefix should
    # trigger stripping.
    entries = [
        ("Ask HN: How do you stay sane?", "https://news.ycombinator.com/item?id=1",
         "I have been working remotely for years and find myself struggling to focus."),
    ]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "Hacker News"})
    assert len(items) == 1
    assert items[0]["snippet"].startswith("I have been working remotely")


def test_fetch_all_feeds_enriches_with_og_image_when_rss_has_no_image(monkeypatch):
    # BetterDwelling-style: RSS exposes no image fields anywhere; the
    # enrichment pass fills item['image'] from og:image after dedup.
    entries = [
        ("Vacant homes pile up", "https://betterdwelling.com/vacant-homes/",
         "Canadian developers are sitting on a glut of completed and unsold homes."),
    ]
    monkeypatch.setattr("pipeline._fetch_og_image",
                        lambda url, **kw: "https://betterdwelling.com/wp-content/og.jpg")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "BetterDwelling"}])
    assert items[0]["image"] == "https://betterdwelling.com/wp-content/og.jpg"


def test_extract_og_image_handles_unquoted_attribute_values():
    # National Post serves <meta content=https://... property=og:image> with no quotes.
    from pipeline import _extract_og_image_from_html
    html = (
        '<html><head>'
        '<meta content=https://example.com/og.jpg property=og:image>'
        '<meta content="900" property="og:image:width">'
        '</head><body></body></html>'
    )
    assert _extract_og_image_from_html(html) == "https://example.com/og.jpg"


def test_extract_og_image_handles_quoted_attribute_values():
    from pipeline import _extract_og_image_from_html
    html = (
        '<html><head>'
        '<meta property="og:image" content="https://example.com/og.jpg">'
        '</head></html>'
    )
    assert _extract_og_image_from_html(html) == "https://example.com/og.jpg"


def test_extract_og_image_skips_og_image_width_and_height_meta_tags():
    # If the only og:image* tag is og:image:width, must not return that value.
    from pipeline import _extract_og_image_from_html
    html = (
        '<html><head>'
        '<meta property="og:image:width" content="1200">'
        '<meta property="og:image:height" content="800">'
        '</head></html>'
    )
    assert _extract_og_image_from_html(html) == ""


def test_extract_og_image_returns_empty_when_no_og_image_present():
    from pipeline import _extract_og_image_from_html
    html = '<html><head><title>foo</title></head></html>'
    assert _extract_og_image_from_html(html) == ""


def test_fetch_all_feeds_skips_og_image_enrichment_for_podcast_sources(monkeypatch):
    # Podcast feeds (e.g., CBC Frontburner) ship URLs that resolve to audio
    # endpoints, not article pages — og:image fetch would always 404. Skip them.
    entries = [
        ("Episode 123", "https://www.cbc.ca/podcasting/includes/frontburner-abc",
         "A podcast episode with a meaningful summary sentence."),
    ]
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_image",
                        lambda url, **kw: calls.append(url) or "https://should-not-be-used.jpg")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "CBC Frontburner"}])
    assert items[0]["image"] == ""
    assert calls == []  # _fetch_og_image must not have been called


def test_fetch_all_feeds_image_stays_empty_when_og_image_unavailable(monkeypatch):
    entries = [
        ("A story", "https://example.com/story",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    monkeypatch.setattr("pipeline._fetch_og_image", lambda url, **kw: "")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "Whatever"}])
    assert items[0]["image"] == ""


def test_enrich_images_with_og_image_runs_concurrently(monkeypatch):
    # Verify the enrichment pass actually runs in parallel: 5 items, each
    # 100ms to fetch. Sequential would take >=500ms; with 10 workers it
    # should finish well under 200ms.
    from pipeline import enrich_images_with_og_image
    import time as _time

    def slow_fetch(url, **kw):
        _time.sleep(0.1)
        return f"{url}/og.jpg"

    monkeypatch.setattr("pipeline._fetch_og_image", slow_fetch)
    items = [
        {"link": f"https://example.com/{i}", "image": "", "source": "X"}
        for i in range(5)
    ]
    start = _time.time()
    enrich_images_with_og_image(items)
    elapsed = _time.time() - start
    assert elapsed < 0.4, f"Enrichment should be parallel; took {elapsed:.2f}s"
    assert all(item["image"].endswith("og.jpg") for item in items)


def test_enrich_images_with_og_image_skips_items_with_existing_image(monkeypatch):
    from pipeline import enrich_images_with_og_image
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_image",
                        lambda url, **kw: calls.append(url) or "https://x")
    items = [
        {"link": "u1", "image": "already-have-this.jpg", "source": "X"},
        {"link": "u2", "image": "", "source": "X"},
    ]
    enrich_images_with_og_image(items)
    # Only the empty-image item should have triggered a fetch.
    assert calls == ["u2"]


def test_fetch_all_feeds_dedupes_items_with_identical_links():
    # NBC Meet the Press shipped two separate RSS entries that both pointed to
    # https://nbcnews.com/dateline (the show landing page). Both made it through
    # fetch and ended up as separate items in Worth Knowing, where they showed up
    # as a duplicate-feeling pair in the briefing.
    entries_feed_a = [
        ("In the Matter of Alex Murdaugh",
         "https://nbcnews.com/dateline",
         "A meaningful summary sentence that gives the formatter something to work with."),
        ("Alex Murdaugh's murder convictions thrown out.",
         "https://nbcnews.com/dateline",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries_feed_a)):
        items = fetch_all_feeds([{"url": "x", "source": "NBC Meet the Press"}])
    assert len(items) == 1, "Within-batch link dedup should keep only one item per link"
    assert items[0]["link"] == "https://nbcnews.com/dateline"


def test_monday_bypass_keeps_items_with_cluster_size_3_plus():
    seen = {"u1": 0, "u2": 0, "u3": 0}
    items = [
        {"id": 0, "title": "Story A", "link": "u1", "source": "CBC", "cluster_size": 4},
        {"id": 1, "title": "Story B", "link": "u2", "source": "BBC", "cluster_size": 2},
        {"id": 2, "title": "Story C", "link": "u3", "source": "NYT", "cluster_size": 1},
    ]
    result = monday_dedup_bypass(items, seen)
    assert {i["id"] for i in result} == {0}


def test_deduplicate_does_not_persist_seen_links(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text("{}")
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", False)

    items = [
        {"title": "a", "link": "https://example.com/a", "source": "Codrops"},
        {"title": "b", "link": "https://example.com/b", "source": "Sidebar"},
    ]
    fresh = deduplicate(items)
    assert len(fresh) == 2
    assert json.loads(seen_file.read_text()) == {}, (
        "deduplicate must not persist seen_links; record_seen does that after a successful send"
    )


def test_record_seen_persists_items(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text("{}")
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", False)

    items = [
        {"title": "a", "link": "https://example.com/a", "source": "Codrops"},
        {"title": "b", "link": "https://example.com/b", "source": "Sidebar"},
    ]
    record_seen(items)
    saved = json.loads(seen_file.read_text())
    assert set(saved.keys()) == {"https://example.com/a", "https://example.com/b"}


def test_record_seen_is_noop_in_test_mode(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text("{}")
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", True)

    record_seen([{"title": "a", "link": "https://example.com/a", "source": "Codrops"}])
    assert json.loads(seen_file.read_text()) == {}


def test_deduplicate_then_record_seen_round_trip(tmp_path, monkeypatch):
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text("{}")
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", False)

    first_run = [{"title": "a", "link": "https://example.com/a", "source": "Codrops"}]
    fresh = deduplicate(first_run)
    assert len(fresh) == 1
    record_seen(fresh)

    second_run = [
        {"title": "a", "link": "https://example.com/a", "source": "Codrops"},
        {"title": "b", "link": "https://example.com/b", "source": "Sidebar"},
    ]
    fresh = deduplicate(second_run)
    assert [i["link"] for i in fresh] == ["https://example.com/b"]
