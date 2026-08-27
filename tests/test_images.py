import io

import pytest
from PIL import Image

from images import to_square_thumbnail


def _png(width, height, color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def test_to_square_thumbnail_resizes_nonsquare_to_80x80():
    out = to_square_thumbnail(_png(200, 100), size=80)
    assert out is not None
    img = Image.open(io.BytesIO(out))
    assert img.size == (80, 80)


def test_to_square_thumbnail_returns_none_on_garbage():
    assert to_square_thumbnail(b"not an image", size=80) is None


import images as images_mod


class _FakeResp:
    def __init__(self, chunks, status=200):
        self._chunks = chunks
        self.status_code = status

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_remote_thumbnail_returns_bytes(monkeypatch):
    monkeypatch.setattr(
        images_mod.requests, "get",
        lambda *a, **k: _FakeResp([b"ab", b"cd"]),
    )
    assert images_mod.fetch_remote_thumbnail("http://x/y.jpg") == b"abcd"


def test_fetch_remote_thumbnail_sends_browser_headers(monkeypatch):
    # Bot-sensitive / hotlink-protected hosts (e.g. betterdwelling) reject a
    # bare requests UA. The server-side thumbnail download must look like a
    # browser, with a Referer, or those article images fall to the AI fallback.
    captured = {}

    def fake_get(url, *a, **k):
        captured["headers"] = k.get("headers") or {}
        return _FakeResp([b"img"])

    monkeypatch.setattr(images_mod.requests, "get", fake_get)
    images_mod.fetch_remote_thumbnail("https://betterdwelling.com/wp/x.jpg")
    headers = captured["headers"]
    assert "User-Agent" in headers and "Mozilla" in headers["User-Agent"]
    assert headers.get("Referer", "").startswith("https://betterdwelling.com")


def test_fetch_remote_thumbnail_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(images_mod.requests, "get", boom)
    assert images_mod.fetch_remote_thumbnail("http://x/y.jpg") is None


def _solid_png(color, w=120, h=120) -> bytes:
    """A solid-colour PNG, so a tile is distinguishable from an article image."""
    import io as _io
    from PIL import Image as _Image
    buf = _io.BytesIO()
    _Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


TILE_RGB = (7, 11, 13)      # near-black, nothing else in these tests uses it
ARTICLE_RGB = (200, 30, 40)


def _corner(data: bytes):
    import io as _io
    from PIL import Image as _Image
    return _Image.open(_io.BytesIO(data)).convert("RGB").getpixel((0, 0))


def _is_tile(data: bytes) -> bool:
    # Resizing is lossless for a solid fill, but allow a small tolerance.
    return all(abs(a - b) <= 4 for a, b in zip(_corner(data), TILE_RGB))


@pytest.fixture
def tiles(tmp_path, monkeypatch):
    """A tile directory holding only the neutral default."""
    d = tmp_path / "tiles"
    d.mkdir()
    (d / "_default.png").write_bytes(_solid_png(TILE_RGB))
    images_mod._read_tile.cache_clear()
    monkeypatch.setattr(images_mod, "EE_TILE_DIR", str(d))
    yield d
    images_mod._read_tile.cache_clear()


def test_source_tile_prefers_source_file_over_default(tiles):
    (tiles / "national-post.png").write_bytes(_solid_png((1, 2, 3)))
    assert _corner(images_mod.source_tile("National Post")) == (1, 2, 3)
    assert _is_tile(images_mod.source_tile("Some Unmapped Source"))


def test_tile_slug_matches_source_names():
    assert images_mod._tile_slug("National Post") == "national-post"
    assert images_mod._tile_slug("r/toronto") == "r-toronto"
    assert images_mod._tile_slug("Globe & Mail Finance") == "globe-mail-finance"
    assert images_mod._tile_slug("It's Nice That") == "it-s-nice-that"


def test_resolve_prefers_og_image_then_caches(tmp_path, tiles):
    calls = {"fetch": 0}

    def fake_fetch(url):
        calls["fetch"] += 1
        return _solid_png(ARTICLE_RGB)

    items = [(1, {"link": "http://a/1", "image": "http://a/og.jpg",
                  "title": "T1", "snippet": "s1", "source": "National Post"})]

    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch
    )
    assert set(out) == {1}
    assert out[1].cid == "ee-1@quitefrankly"
    assert out[1].mime == "image/png"
    assert calls == {"fetch": 1}
    assert not _is_tile(out[1].data)  # a real image beats the tile

    out2 = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch
    )
    assert set(out2) == {1}
    assert calls == {"fetch": 1}  # served from cache, no second download


def test_resolve_uses_tile_when_no_og_image(tmp_path, tiles):
    def fake_fetch(url):
        raise AssertionError("must not fetch when there is no image url")

    items = [(2, {"link": "http://a/2", "image": "",
                  "title": "T2", "snippet": "s2", "source": "r/toronto"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch
    )
    assert set(out) == {2}
    assert _is_tile(out[2].data)


def _fetch_none(url):
    return None            # silent failure, the Aug 26 shape


def _fetch_raises(url):
    raise RuntimeError("network exploded")


def _fetch_garbage(url):
    return b"not an image"  # downloads fine, fails to decode


@pytest.mark.parametrize("bad_fetch", [_fetch_none, _fetch_raises, _fetch_garbage])
def test_resolve_uses_tile_when_download_fails(tmp_path, tiles, bad_fetch):
    items = [(5, {"link": "http://a/5", "image": "http://a/og.jpg",
                  "title": "T5", "snippet": "", "source": "Economist"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=bad_fetch
    )
    assert set(out) == {5}
    assert _is_tile(out[5].data)


def test_tile_is_never_cached(tmp_path, tiles):
    """A tile must not be written under the article's cache key.

    _cache_path keys on the article link and _read_valid_cache only checks that
    bytes decode, never what they depict — so a cached tile would be served for
    that article forever, outliving whatever caused the download to fail.
    """
    items = [(6, {"link": "http://a/6", "image": "http://a/og.jpg",
                  "title": "T6", "snippet": "", "source": "Economist"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=lambda u: None
    )
    assert _is_tile(out[6].data)
    cache_files = [p for p in tmp_path.iterdir() if p.is_file()]
    assert cache_files == [] or all(p.stat().st_size == 0 for p in cache_files)

    # The real catch: once the download recovers, the article image must win.
    out2 = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=lambda u: _solid_png(ARTICLE_RGB)
    )
    assert not _is_tile(out2[6].data)


def test_resolve_omits_item_when_tile_missing(tmp_path, monkeypatch):
    """With no tile on disk the row still degrades to text rather than raising.

    This is why formatting.py keeps its text-only branch.
    """
    empty = tmp_path / "no-tiles"
    empty.mkdir()
    images_mod._read_tile.cache_clear()
    monkeypatch.setattr(images_mod, "EE_TILE_DIR", str(empty))
    items = [(3, {"link": "http://a/3", "image": "", "title": "T3",
                  "snippet": "", "source": "Nowhere"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=lambda u: None
    )
    assert out == {}
    images_mod._read_tile.cache_clear()


def test_resolve_treats_empty_cache_file_as_miss(tmp_path, tiles):
    import hashlib
    url = "http://a/7"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (tmp_path / f"{digest}.png").write_bytes(b"")  # simulate a partial write
    items = [(7, {"link": url, "image": "http://a/og.jpg", "title": "T7",
                  "snippet": "s", "source": "CBC"})]
    # fetch supplies a real image; the empty cache file must NOT be served.
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=lambda u: _solid_png(ARTICLE_RGB)
    )
    assert set(out) == {7}
    assert out[7].data
    assert not _is_tile(out[7].data)
