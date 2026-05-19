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
