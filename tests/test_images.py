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
