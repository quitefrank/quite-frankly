from unittest.mock import patch

from pipeline import assign_ids, fetch_feed, monday_dedup_bypass


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


def test_fetch_feed_uses_og_image_when_rss_has_no_image(monkeypatch):
    # BetterDwelling-style: RSS exposes no image fields anywhere.
    entries = [
        ("Vacant homes pile up", "https://betterdwelling.com/vacant-homes/",
         "Canadian developers are sitting on a glut of completed and unsold homes."),
    ]
    monkeypatch.setattr("pipeline._fetch_og_image",
                        lambda url, **kw: "https://betterdwelling.com/wp-content/og.jpg")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "BetterDwelling"})
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


def test_fetch_feed_skips_og_image_fallback_for_podcast_sources(monkeypatch):
    # Podcast feeds (e.g., CBC Frontburner) ship URLs that resolve to audio
    # endpoints, not article pages — og:image fetch would always 404. Skip it.
    entries = [
        ("Episode 123", "https://www.cbc.ca/podcasting/includes/frontburner-abc",
         "A podcast episode with a meaningful summary sentence."),
    ]
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_image",
                        lambda url, **kw: calls.append(url) or "https://should-not-be-used.jpg")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "CBC Frontburner"})
    assert items[0]["image"] == ""
    assert calls == []  # _fetch_og_image must not have been called


def test_fetch_feed_image_falls_back_to_empty_string_when_og_image_unavailable(monkeypatch):
    entries = [
        ("A story", "https://example.com/story",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    # autouse fixture already neutralizes _fetch_og_image, but be explicit.
    monkeypatch.setattr("pipeline._fetch_og_image", lambda url, **kw: "")
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_feed({"url": "x", "source": "Whatever"})
    assert items[0]["image"] == ""


def test_monday_bypass_keeps_items_with_cluster_size_3_plus():
    seen = {"u1": 0, "u2": 0, "u3": 0}
    items = [
        {"id": 0, "title": "Story A", "link": "u1", "source": "CBC", "cluster_size": 4},
        {"id": 1, "title": "Story B", "link": "u2", "source": "BBC", "cluster_size": 2},
        {"id": 2, "title": "Story C", "link": "u3", "source": "NYT", "cluster_size": 1},
    ]
    result = monday_dedup_bypass(items, seen)
    assert {i["id"] for i in result} == {0}
