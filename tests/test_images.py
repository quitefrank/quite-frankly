import io
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


def test_fetch_remote_thumbnail_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(images_mod.requests, "get", boom)
    assert images_mod.fetch_remote_thumbnail("http://x/y.jpg") is None


def test_generate_thumbnail_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert images_mod.generate_thumbnail("Headline", "snippet") is None


def test_resolve_prefers_og_image_then_caches(tmp_path):
    calls = {"fetch": 0, "gen": 0}

    def fake_fetch(url):
        calls["fetch"] += 1
        return _png(120, 120)

    def fake_gen(title, snippet):
        calls["gen"] += 1
        return _png(120, 120)

    items = [(1, {"link": "http://a/1", "image": "http://a/og.jpg",
                  "title": "T1", "snippet": "s1"})]

    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out) == {1}
    assert out[1].cid == "ee-1@quitefrankly"
    assert out[1].mime == "image/png"
    assert calls == {"fetch": 1, "gen": 0}

    out2 = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out2) == {1}
    assert calls == {"fetch": 1, "gen": 0}


def test_resolve_generates_when_no_og_image(tmp_path):
    def fake_fetch(url):
        raise AssertionError("should not fetch")

    def fake_gen(title, snippet):
        return _png(64, 64)

    items = [(2, {"link": "http://a/2", "image": "",
                  "title": "T2", "snippet": "s2"})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=fake_fetch, gen=fake_gen
    )
    assert set(out) == {2}


def test_resolve_omits_item_on_total_failure(tmp_path):
    items = [(3, {"link": "http://a/3", "image": "", "title": "T3", "snippet": ""})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path),
        fetch=lambda u: None, gen=lambda t, s: None,
    )
    assert out == {}


def test_resolve_omits_item_when_fetch_raises(tmp_path):
    def boom(url):
        raise RuntimeError("network exploded")
    items = [(5, {"link": "http://a/5", "image": "http://a/og.jpg",
                  "title": "T5", "snippet": ""})]
    # Must NOT raise; item is simply omitted.
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=boom, gen=lambda t, s: None
    )
    assert out == {}


def test_resolve_omits_item_when_fetched_bytes_are_garbage(tmp_path):
    items = [(6, {"link": "http://a/6", "image": "http://a/og.jpg",
                  "title": "T6", "snippet": ""})]
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path),
        fetch=lambda u: b"not an image", gen=lambda t, s: None,
    )
    assert out == {}
    # Nothing valid should have been cached (no file, or only empty/tmp leftovers).
    cache_files = list(tmp_path.iterdir())
    assert cache_files == [] or all(p.stat().st_size == 0 for p in cache_files)


def test_resolve_treats_empty_cache_file_as_miss(tmp_path):
    import hashlib
    url = "http://a/7"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    (tmp_path / f"{digest}.png").write_bytes(b"")  # simulate a partial write
    items = [(7, {"link": url, "image": "", "title": "T7", "snippet": "s"})]
    # gen supplies a real image; the empty cache file must NOT be served.
    out = images_mod.resolve_ee_thumbnails(
        items, cache_dir=str(tmp_path), fetch=lambda u: None, gen=lambda t, s: _png(40, 40)
    )
    assert set(out) == {7}
    assert out[7].data  # non-empty, real image bytes
