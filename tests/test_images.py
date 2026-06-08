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
