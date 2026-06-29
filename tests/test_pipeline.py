import json
from unittest.mock import patch

import pipeline
from pipeline import assign_ids, deduplicate, fetch_all_feeds, fetch_feed, record_seen

# conftest's autouse _no_og_image_http fixture patches pipeline._fetch_og_meta to a
# no-network stub. Capture the real implementation at import time (before any fixture
# runs) so the brotli decode test below can exercise the genuine HTTP path.
_REAL_FETCH_OG_META = pipeline._fetch_og_meta


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
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: {"image": "https://betterdwelling.com/wp-content/og.jpg", "description": ""})
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


def test_extract_og_image_skips_generic_placeholder_logo():
    # Yahoo Finance serves a site-wide default logo as og:image on articles that
    # have no real hero image. Treat it as "no image" so the resolver falls back
    # to an AI illustration instead of repeating the same Yahoo logo.
    from pipeline import _extract_og_image_from_html
    html = (
        '<html><head>'
        '<meta property="og:image" '
        'content="https://s.yimg.com/cv/apiv2/social/images/yahoo-finance-default-logo.png">'
        '</head></html>'
    )
    assert _extract_og_image_from_html(html) == ""


def test_extract_og_image_prefers_real_image_over_generic_logo():
    # If both a generic logo and a real article image are present, return the real one.
    from pipeline import _extract_og_image_from_html
    html = (
        '<html><head>'
        '<meta property="og:image" '
        'content="https://s.yimg.com/cv/apiv2/social/images/yahoo-finance-default-logo.png">'
        '<meta property="og:image" content="https://example.com/real-hero.jpg">'
        '</head></html>'
    )
    assert _extract_og_image_from_html(html) == "https://example.com/real-hero.jpg"


def test_ee_image_prompt_is_thumbnail_optimized():
    # The AI fallback renders at 80x80; the prompt must forbid text and ask for a
    # single bold subject so it stays legible at thumbnail size.
    from config import EE_IMAGE_PROMPT_TEMPLATE
    low = EE_IMAGE_PROMPT_TEMPLATE.lower()
    assert "80" in EE_IMAGE_PROMPT_TEMPLATE  # references the target pixel size
    assert "no text" in low
    assert "{title}" in EE_IMAGE_PROMPT_TEMPLATE


def test_og_image_max_bytes_covers_deep_head_tags():
    # Yahoo Finance puts og:image at ~62KB into the page; the fetch cap must be
    # large enough to reach it, or finance articles never get a real image.
    from pipeline import OG_IMAGE_MAX_BYTES
    assert OG_IMAGE_MAX_BYTES >= 96 * 1024


def test_fetch_og_meta_decodes_brotli_encoded_head():
    # Hosts like moneysense.ca honor the `br` in our Accept-Encoding and reply
    # with Content-Encoding: br. requests only decodes brotli when the `brotli`
    # package is installed; without it, _fetch_og_meta sees raw compressed bytes,
    # the og:image regex matches nothing, and every article on that host silently
    # drops to the AI fallback. This exercises the real requests decode path
    # (not a mock) against a live br-encoded response, so it fails if `brotli`
    # is ever dropped from requirements.
    import http.server
    import threading

    import brotli  # must be installed for the og:image path to work at all

    body = brotli.compress(
        b'<html><head><meta property="og:image" '
        b'content="https://example.com/hero.jpg"></head><body>x</body></html>'
    )

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=UTF-8")
            self.send_header("Content-Encoding", "br")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass  # keep test output clean

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/article"
        meta = _REAL_FETCH_OG_META(url)
    finally:
        server.shutdown()
        thread.join()

    assert meta["image"] == "https://example.com/hero.jpg"


def test_fetch_all_feeds_skips_og_image_enrichment_for_podcast_sources(monkeypatch):
    # Podcast feeds (e.g., CBC Frontburner) ship URLs that resolve to audio
    # endpoints, not article pages — og:image fetch would always 404. Skip them.
    entries = [
        ("Episode 123", "https://www.cbc.ca/podcasting/includes/frontburner-abc",
         "A podcast episode with a meaningful summary sentence."),
    ]
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: calls.append(url) or {"image": "https://should-not-be-used.jpg", "description": ""})
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "CBC Frontburner"}])
    assert items[0]["image"] == ""
    assert calls == []  # _fetch_og_meta must not have been called for skip-list sources


def _fake_podcast_parsed(channel_link, entries):
    """Fake feedparser output for a podcast feed.

    entries: list of (title, link, summary, enclosure_href). A bare/relative
    `link` (e.g. a guid) mimics CBC Frontburner, whose items carry no <link>
    and whose guid feedparser resolves into a 404ing /podcasting/includes/ path.
    """
    parsed = type("Parsed", (), {})()
    parsed.feed = type("Feed", (), {"link": channel_link})()
    parsed.entries = []
    for title, link, summary, enclosure_href in entries:
        e = type("Entry", (), {})()
        e.title = title
        e.link = link
        e.summary = summary
        e.enclosures = [{"type": "audio/mpeg", "href": enclosure_href}] if enclosure_href else []
        parsed.entries.append(e)
    return parsed


def test_fetch_feed_repairs_frontburner_guid_link_to_channel_homepage():
    # CBC Frontburner items have no <link>; feedparser exposes the <guid>
    # (a bare "frontburner-<uuid>") as entry.link, which it resolves against
    # the feed dir into https://www.cbc.ca/podcasting/includes/frontburner-<uuid>
    # — a path that 404s. A non-absolute link must be repaired to the channel
    # homepage so the newsletter never ships the dead URL.
    entries = [
        ("What's fueling residential school denialism?",
         "frontburner-53387ff5-49dd-493e-acdc-e9ae6a374965",
         "A podcast episode with a meaningful summary sentence for the formatter.",
         "https://mgln.ai/e/12/cbc.mc.tritondigital.com/frontburner.mp3"),
    ]
    parsed = _fake_podcast_parsed("https://www.cbc.ca/frontburner", entries)
    with patch("pipeline.feedparser.parse", return_value=parsed):
        items = fetch_feed({"url": "x", "source": "CBC Frontburner"})
    assert len(items) == 1
    assert items[0]["link"] == "https://www.cbc.ca/frontburner"


def test_fetch_feed_falls_back_to_audio_enclosure_when_no_channel_link():
    # If a guid-only feed also lacks a usable channel link, the audio enclosure
    # is the only real resource left — better than a 404 page.
    entries = [
        ("Episode", "frontburner-abc",
         "A podcast episode with a meaningful summary sentence for the formatter.",
         "https://mgln.ai/e/12/audio.mp3"),
    ]
    parsed = _fake_podcast_parsed("", entries)
    with patch("pipeline.feedparser.parse", return_value=parsed):
        items = fetch_feed({"url": "x", "source": "CBC Frontburner"})
    assert items[0]["link"] == "https://mgln.ai/e/12/audio.mp3"


def test_fetch_feed_preserves_absolute_item_links():
    # NYT The Daily / NBC ship valid absolute item links — repair must not touch them.
    entries = [
        ("Daily episode", "https://www.nytimes.com/the-daily",
         "A podcast episode with a meaningful summary sentence for the formatter.",
         "https://chrt.fm/the-daily.mp3"),
    ]
    parsed = _fake_podcast_parsed("https://www.nytimes.com/the-daily", entries)
    with patch("pipeline.feedparser.parse", return_value=parsed):
        items = fetch_feed({"url": "x", "source": "NYT The Daily"})
    assert items[0]["link"] == "https://www.nytimes.com/the-daily"


def test_fetch_all_feeds_image_stays_empty_when_og_image_unavailable(monkeypatch):
    entries = [
        ("A story", "https://example.com/story",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    monkeypatch.setattr("pipeline._fetch_og_meta", lambda url, **kw: {"image": "", "description": ""})
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "Whatever"}])
    assert items[0]["image"] == ""


def test_enrich_from_og_metadata_runs_concurrently(monkeypatch):
    # Verify the enrichment pass actually runs in parallel: 5 items, each
    # 100ms to fetch. Sequential would take >=500ms; with 10 workers it
    # should finish well under 200ms.
    from pipeline import enrich_from_og_metadata
    import time as _time

    def slow_fetch(url, **kw):
        _time.sleep(0.1)
        return {"image": f"{url}/og.jpg", "description": ""}

    monkeypatch.setattr("pipeline._fetch_og_meta", slow_fetch)
    items = [
        {"link": f"https://example.com/{i}", "image": "", "snippet": "have", "source": "X"}
        for i in range(5)
    ]
    start = _time.time()
    enrich_from_og_metadata(items)
    elapsed = _time.time() - start
    assert elapsed < 0.4, f"Enrichment should be parallel; took {elapsed:.2f}s"
    assert all(item["image"].endswith("og.jpg") for item in items)


def test_enrich_from_og_metadata_skips_items_with_image_and_snippet(monkeypatch):
    from pipeline import enrich_from_og_metadata
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: calls.append(url) or {"image": "https://x", "description": "d"})
    items = [
        {"link": "u1", "image": "already-have-this.jpg", "snippet": "have", "source": "X"},
        {"link": "u2", "image": "", "snippet": "have", "source": "X"},
    ]
    enrich_from_og_metadata(items)
    # u1 has both image and snippet, so no fetch; only u2 (missing image).
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
    # Keys are stored normalized (scheme/www/tracking stripped) for cross-run
    # matching, not as the raw RSS URL.
    assert set(saved.keys()) == {"example.com/a", "example.com/b"}


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


from pipeline import youtube_id, canonical_key, normalize_text


def test_youtube_id_extracts_from_watch_and_short_forms():
    assert youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube_id("see https://youtu.be/dQw4w9WgXcQ now") == "dQw4w9WgXcQ"
    assert youtube_id("https://example.com/article") == ""
    assert youtube_id("") == ""


def test_canonical_key_keys_off_shared_youtube_video():
    a = {"link": "https://siteA.com/post", "snippet": "watch https://youtu.be/dQw4w9WgXcQ"}
    b = {"link": "https://youtube.com/watch?v=dQw4w9WgXcQ", "snippet": ""}
    c = {"link": "https://siteC.com/other", "snippet": "no video here"}
    assert canonical_key(a) == canonical_key(b) == "yt:dQw4w9WgXcQ"
    assert canonical_key(c) == ""


def test_normalize_text_drops_stopwords_and_short_tokens():
    tokens = normalize_text("How Keith Lee built a no-code Fitness App")
    assert "keith" in tokens and "fitness" in tokens and "built" in tokens
    assert "how" not in tokens and "a" not in tokens


from pipeline import normalize_url


def test_extract_og_description_prefers_og_then_twitter_then_name():
    from pipeline import _extract_og_description_from_html
    og = ('<head><meta property="og:description" content="The og one">'
          '<meta name="twitter:description" content="The twitter one">'
          '<meta name="description" content="The name one"></head>')
    assert _extract_og_description_from_html(og) == "The og one"
    tw = ('<head><meta name="twitter:description" content="The twitter one">'
          '<meta name="description" content="The name one"></head>')
    assert _extract_og_description_from_html(tw) == "The twitter one"
    nm = '<head><meta name="description" content="The name one"></head>'
    assert _extract_og_description_from_html(nm) == "The name one"
    assert _extract_og_description_from_html("<head></head>") == ""


def test_extract_og_description_unescapes_entities():
    from pipeline import _extract_og_description_from_html
    html = '<head><meta property="og:description" content="Mom &amp; Pop won&#39;t quit"></head>'
    assert _extract_og_description_from_html(html) == "Mom & Pop won't quit"


def test_enrich_backfills_empty_snippet_from_og_description(monkeypatch):
    # The HN case: a link-post enters with snippet="" (hnrss metadata stripped).
    # The og metadata pass should fill it so triage clustering and the token
    # backstop have story vocabulary to work with.
    from pipeline import enrich_from_og_metadata
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: {"image": "", "description": "Real article summary about Acme Corp layoffs."})
    items = [{"link": "https://acme.example/news", "image": "x.jpg", "snippet": "", "source": "Hacker News"}]
    enrich_from_og_metadata(items)
    assert items[0]["snippet"] == "Real article summary about Acme Corp layoffs."


def test_enrich_does_not_overwrite_existing_snippet(monkeypatch):
    from pipeline import enrich_from_og_metadata
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: {"image": "", "description": "Should not replace."})
    items = [{"link": "u", "image": "x.jpg", "snippet": "Original snippet from RSS.", "source": "X"}]
    enrich_from_og_metadata(items)
    assert items[0]["snippet"] == "Original snippet from RSS."


def test_enrich_skips_fetch_when_image_and_snippet_both_present(monkeypatch):
    from pipeline import enrich_from_og_metadata
    calls = []
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: calls.append(url) or {"image": "y", "description": "z"})
    items = [
        {"link": "u1", "image": "have.jpg", "snippet": "have snippet", "source": "X"},
        {"link": "u2", "image": "", "snippet": "have snippet", "source": "X"},
        {"link": "u3", "image": "have.jpg", "snippet": "", "source": "X"},
    ]
    enrich_from_og_metadata(items)
    assert sorted(calls) == ["u2", "u3"], "Fetch only when image OR snippet missing"


def test_fetch_all_feeds_backfills_hacker_news_snippet_end_to_end(monkeypatch):
    # hnrss strips the snippet to "" at ingest; the og pass should restore it.
    entries = [
        ("Claude Code as a Daily", "https://arps18.github.io/posts/x/",
         "Article URL: https://arps18.github.io/posts/x/ "
         "Comments URL: https://news.ycombinator.com/item?id=1 Points: 94 # Comments: 74"),
    ]
    monkeypatch.setattr("pipeline._fetch_og_meta",
                        lambda url, **kw: {"image": "", "description": "A hands-on guide to running Claude Code daily."})
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "Hacker News"}])
    assert items[0]["snippet"] == "A hands-on guide to running Claude Code daily."


def test_normalize_url_strips_scheme_www_and_fragment():
    # http vs https, a www prefix, and a #fragment are the same article.
    a = normalize_url("https://www.cbc.ca/news/story-123#top")
    b = normalize_url("http://cbc.ca/news/story-123")
    assert a == b == "cbc.ca/news/story-123"


def test_normalize_url_strips_tracking_params_but_keeps_content_params():
    # utm_*/fbclid/gclid are tracking noise; ?p= and ?id= identify the article.
    assert (
        normalize_url("https://example.com/post?utm_source=newsletter&fbclid=abc")
        == "example.com/post"
    )
    # WordPress encodes the article id in ?p= — must NOT be stripped, or every
    # post on the site collapses to one.
    assert (
        normalize_url("https://example.com/?p=12345&utm_medium=rss")
        == "example.com?p=12345"
    )
    assert normalize_url("https://site.com/a?id=1") != normalize_url("https://site.com/a?id=2")


def test_normalize_url_collapses_trailing_slash_amp_and_mobile_host():
    assert normalize_url("https://theverge.com/article/") == "theverge.com/article"
    assert normalize_url("https://m.theverge.com/article") == "theverge.com/article"
    assert normalize_url("https://theverge.com/article/amp/") == "theverge.com/article"


def test_normalize_url_handles_empty_and_garbage():
    assert normalize_url("") == ""
    assert normalize_url(None) == ""


def test_fetch_all_feeds_dedupes_links_differing_only_by_tracking_params():
    # Two RSS entries for one article, one carrying a utm tag. Raw-string dedup
    # let both through; normalized within-batch dedup collapses them.
    entries = [
        ("Bank of Canada holds rate", "https://cbc.ca/news/boc-holds",
         "A meaningful summary sentence that gives the formatter something to work with."),
        ("Bank of Canada holds rate", "https://www.cbc.ca/news/boc-holds?utm_source=rss",
         "A meaningful summary sentence that gives the formatter something to work with."),
    ]
    with patch("pipeline.feedparser.parse", return_value=_fake_parsed(entries)):
        items = fetch_all_feeds([{"url": "x", "source": "CBC"}])
    assert len(items) == 1, "Within-batch dedup should normalize tracking-param variants"


def test_deduplicate_treats_tracking_param_variant_as_seen(tmp_path, monkeypatch):
    # Yesterday's article re-arrives today with a tracking param and an http
    # scheme. The 7-day cache must recognize it as already sent.
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text("{}")
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", False)

    record_seen([{"title": "a", "link": "https://www.cbc.ca/news/boc-holds", "source": "CBC"}])
    second_run = [
        {"title": "a", "link": "http://cbc.ca/news/boc-holds?utm_source=rss", "source": "CBC"},
        {"title": "b", "link": "https://cbc.ca/news/new-story", "source": "CBC"},
    ]
    fresh = deduplicate(second_run)
    assert [i["link"] for i in fresh] == ["https://cbc.ca/news/new-story"]


def test_deduplicate_matches_legacy_raw_seen_keys(tmp_path, monkeypatch):
    # Existing seen_links.json holds raw (un-normalized) URLs from before this
    # change. They must still match incoming normalized links so the cutover
    # doesn't re-send a week of history.
    seen_file = tmp_path / "seen_links.json"
    seen_file.write_text(json.dumps({"https://www.example.com/a/": 9999999999}))
    monkeypatch.setattr(pipeline, "SEEN_LINKS_FILE", str(seen_file))
    monkeypatch.setattr(pipeline, "TEST_MODE", False)

    # Second item is genuinely new, so fresh is non-empty and the
    # "all seen -> return everything" fallback doesn't mask the result.
    fresh = deduplicate([
        {"title": "a", "link": "https://example.com/a", "source": "X"},
        {"title": "b", "link": "https://example.com/b", "source": "X"},
    ])
    assert [i["link"] for i in fresh] == ["https://example.com/b"], (
        "Legacy raw seen key should match its normalized incoming form"
    )
