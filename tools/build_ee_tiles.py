"""Generate the per-source Everything Else fallback tiles.

Run manually when a source is added or a brand colour changes:

    python tools/build_ee_tiles.py

Writes one PNG per source into assets/ee_tiles/, named by images._tile_slug, plus
a neutral _default.png for anything unmapped. The output is committed, so the
newsletter never touches the network for a tile at send time. That is the whole
point: the AI generation this replaced was billed per call, unbounded in the send
path, and failed three separate ways in two weeks.

Each tile is a publisher's icon mark centred on that publisher's brand colour.
Icons come from Google's favicon service, the same source config.SOURCE_FAVICONS
already uses for the source line, requested at the largest size it will serve.
Brand colours come from tools/brand_colours.json.
"""
from __future__ import annotations

import io
import json
import sys
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import EE_TILE_DEFAULT, EE_TILE_DIR, SOURCE_FAVICONS  # noqa: E402
from images import _tile_slug  # noqa: E402

# 2x the 80px render size. to_square_thumbnail downsamples with LANCZOS at send
# time, which is sharper than shipping exactly 80px and hoping nothing rescales.
TILE_PX = 160
# Optical sizing. Favicons disagree wildly about their own internal padding:
# measured across the set, marks ranged from 0.46 of the tile (Reddit, adrift in
# its field) to 1.00 (NN/g, Smashing, CBC, running into the edge). Rather than
# resize everything, only outliers are pulled to TARGET_COVER; anything already
# inside KEEP_BAND is left as its designers drew it.
TARGET_COVER = 0.72
KEEP_BAND = (0.50, 0.82)
# Fallback when a mark has no measurable bounding box.
ICON_FRAC = 0.58
FAVICON_TMPL = "https://www.google.com/s2/favicons?domain={domain}&sz=256"

# Below this the favicon is too small to upscale cleanly, so a monogram beats a
# blurred or postage-stamp mark. Hacker News ships 18px, Simon Willison 16px.
MIN_ICON_PX = 64
# Above this share of transparent pixels the favicon is a floating mark rather
# than a self-contained square, so it goes on the researched brand colour.
TRANSPARENT_MIN = 0.10
# Overscale before centre-cropping an opaque favicon, to eat its rounded-corner
# gutter. 1.14 clears typical corner radii without reaching centred artwork.
BLEED = 1.14
# Sources whose favicon is large enough but unusable at 80px: Sidebar's is a
# low-contrast wireframe that turns to mush, Simon Willison's is a generic
# document glyph carrying no identity.
FORCE_MONOGRAM = {"Sidebar", "Simon Willison"}
# Where initials are not what the brand actually uses as its mark.
MONOGRAM_TEXT = {"Hacker News": "Y"}
# Sources whose favicon ships the right mark on the wrong ground. The mark is
# lifted to a mask and repainted as (mark colour, ground colour). CBC presents
# its gem in white on brand red, and its favicon does neither reliably.
MARK_ON = {
    "CBC": ("#FFFFFF", "#D8232A"),
    "CBC Frontburner": ("#FFFFFF", "#D8232A"),
    # Canadaland ships a black hexagon-C; the brand pairs blue on yellow.
    # #FEF039 is their own brand yellow, 18 occurrences across their CSS.
    "Canadaland": ("#0731F9", "#FEF039"),
}
# Multiplier on a mark's coverage before painting, for marks too faint to read.
MARK_GAIN: "dict[str, float]" = {}
# Sources whose mark is drawn to touch the edge. Normalising these would invent
# padding their designers deliberately left out.
NO_NORMALIZE = {"National Newswatch", "Yahoo Finance", "TechCrunch"}
# Publishers whose own asset beats Google's 192px. Canadaland serves 512px, and
# Storeys' RebelMouse CDN honours a width parameter, so ask it for 512 too.
ICON_OVERRIDE = {
    "Canadaland": "https://www.canadaland.com/wp-content/uploads/2020/10/"
                  "cropped-ms-icon-310x310-3.png",
    # Their favicon is a 32px origin the CDN upscales, so every "512px" variant
    # is fake resolution. The conventional apple-touch-icon path serves real
    # 980px artwork, and in the brand's own colours: black and blue on white,
    # where the favicon is an inverted dark variant.
    "Storeys": "https://storeys.com/apple-touch-icon.png",
    # Their own 512px flower mark. Their SVG is a 853x236 lockup of flower plus
    # wordmark, unusable in a square, and it defines the brand as fill #51B3CD
    # with petals at opacity 0.35 — the rosette is meant to be translucent, so
    # it is shown as drawn rather than darkened for contrast.
    "BetterDwelling": "https://betterdwelling.com/wp-content/uploads/2016/07/"
                      "cropped-better-dwelling-flower-logo.png",
}
# Per-source optical size, where the common 0.72 target reads wrong for a
# particular mark. Design Milk's carton is fine line-art that needs more of the
# frame to stay legible at 80px.
TARGET_OVERRIDE = {"Design Milk": 0.82}
# The unmapped-source tile is Quite Frankly's own mark, so a row with no matching
# publisher reads as ours rather than as a missing asset. White on the same black
# the newsletter header uses (formatting.LIGHT["header_bg"]).
DEFAULT_MARK_URL = "https://quitefrank.co/wp-content/uploads/2021/01/favicon.png"
DEFAULT_MARK_COLOURS = ("#FFFFFF", "#1F1F1F")
# Monograms are type, not marks, so they sit slightly smaller than a logo would.
MONOGRAM_COVER = 0.58
# Supersample factor for vector-redrawn tiles.
SUPERSAMPLE = 4

BRAND_FILE = Path(__file__).with_name("brand_colours.json")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _domain_of(favicon_url: str) -> str:
    """Pull the domain= query param out of a Google favicon URL."""
    return (parse_qs(urlparse(favicon_url).query).get("domain") or [""])[0]


def _hex_rgb(value: str) -> "tuple[int, int, int]":
    v = value.lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


@lru_cache(maxsize=None)
def _icon_bytes(domain: str, url: "str | None" = None) -> "bytes | None":
    """Fetch once per domain and memoise.

    Google's favicon service is not deterministic: two requests for cbc.ca in
    the same build returned different artwork, which gave CBC a black tile and
    CBC Frontburner a red one from the same source. Caching also halves the
    requests, since several sources share a domain.
    """
    try:
        r = requests.get(url or FAVICON_TMPL.format(domain=domain), timeout=20,
                         headers={"User-Agent": _UA})
        r.raise_for_status()
        return r.content
    except Exception as e:  # noqa: BLE001 — a missing icon falls back to a monogram
        print(f"    ! icon fetch failed for {domain}: {type(e).__name__}")
        return None


def _fetch_icon(domain: str, url: "str | None" = None) -> "Image.Image | None":
    raw = _icon_bytes(domain, url)
    if raw is None:
        return None
    try:
        # Open a fresh copy each call: callers resize in place.
        return Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def _load_font(px: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, px)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _transparent_frac(icon: Image.Image) -> float:
    a = icon.getchannel("A")
    return sum(1 for p in a.getdata() if p < 32) / (icon.width * icon.height)


def _icon_ground(icon: Image.Image) -> "tuple[int, int, int]":
    """The icon's own background colour, sampled inside its rounded corners.

    Favicons are usually a rounded square, so the literal corner pixel is the
    white or transparent gutter outside the shape, not the brand ground. Sample
    the edge midpoints instead and take the most common value.
    """
    px = icon.convert("RGB").load()
    w, h = icon.size
    inset = max(2, int(min(w, h) * 0.06))
    samples = []
    for t in range(inset, min(w, h) - inset, max(1, min(w, h) // 24)):
        samples += [px[t, inset], px[t, h - 1 - inset], px[inset, t], px[w - 1 - inset, t]]
    return max(set(samples), key=samples.count) if samples else (255, 255, 255)


def _draw_toronto_star() -> Image.Image:
    """Redraw the Toronto Star chevron as vector.

    Their largest published icon is 192px with aliasing baked into the diagonals,
    so every resampling path stair-steps at 80px. The mark is three parallel
    chevrons, measured off that icon: apex at mid-height, slope dx/dy = 0.584,
    apex x at 55 / 69.5 / 80.5 of 192. Drawn at 4x and downsampled, the diagonals
    come out clean. This is the only tile that needs redrawing.
    """
    BLUE, WHITE = (0, 110, 210), (255, 255, 255)
    S, slope = TILE_PX * SUPERSAMPLE, 0.5844
    apexes = [55 / 192, 69.5 / 192, 80.5 / 192]

    def edge(ax, t):          # x of the chevron at vertical position t (0..1)
        return (ax - slope * abs(t - 0.5)) * S

    def band(left_ax, right_ax):
        """Polygon between two parallel chevrons, apex-to-apex."""
        pts = [(edge(left_ax, 0.0), 0), (edge(right_ax, 0.0), 0),
               (edge(right_ax, 0.5), S / 2), (edge(right_ax, 1.0), S),
               (edge(left_ax, 1.0), S), (edge(left_ax, 0.5), S / 2)]
        return pts

    big = Image.new("RGB", (S, S), BLUE)
    d = ImageDraw.Draw(big)
    d.polygon(band(-1.0, apexes[0]), fill=WHITE)          # white field, left of the mark
    d.polygon(band(apexes[1], apexes[2]), fill=WHITE)     # the thin white chevron
    return big.resize((TILE_PX, TILE_PX), Image.LANCZOS)


def _draw_bbc() -> Image.Image:
    """Redraw the BBC blocks with their letters.

    Every BBC icon asset — Google's favicon and their own apple-touch-icon alike
    — ships three empty black boxes with the lettering dropped. Three anonymous
    squares are not a recognisable mark, so the letters are set back in.
    """
    S = TILE_PX * SUPERSAMPLE
    span = 0.76 * S                       # width of the three-box row
    box = span / 3.24                     # 3 boxes + 2 gaps at 0.12 box widths
    gap = 0.12 * box
    x0, y0 = (S - span) / 2, (S - box) / 2

    img = Image.new("RGB", (S, S), (255, 255, 255))
    d = ImageDraw.Draw(img)
    font = _load_font(round(box * 0.78))
    for i, ch in enumerate("BBC"):
        x = x0 + i * (box + gap)
        d.rectangle([x, y0, x + box, y0 + box], fill=(0, 0, 0))
        l, t, r, b = d.textbbox((0, 0), ch, font=font)
        d.text((x + (box - (r - l)) / 2 - l, y0 + (box - (b - t)) / 2 - t),
               ch, font=font, fill=(255, 255, 255))
    return img.resize((TILE_PX, TILE_PX), Image.LANCZOS)


def _draw_storeys() -> Image.Image:
    """Redraw the Storeys chevrons as vector.

    Their mark exists nowhere above 32px: assets.rbl.ms serves a 32px origin and
    the CDN upscales it, so the 192/512/1024 variants are fake resolution. The
    site ships only the wordmark as SVG, which is 2.6:1 and useless in a square.

    Measured off the 32px original, the geometry is exactly linear: apex at
    x=17/32, band thickness 5/32, left arm slope -0.25, right arm slope +0.5,
    second chevron offset +12/32. Four quadrilaterals.
    """
    BLACK, WHITE, BLUE = (0, 0, 0), (255, 255, 255), (148, 185, 248)
    apex_x, top_y, thick, gap = 17 / 32, 2 / 32, 5 / 32, 12 / 32
    m_left, m_right = 0.25, 0.5
    mark_h = (gap + top_y + thick) - top_y      # full vertical extent of both bands

    S = TILE_PX * SUPERSAMPLE
    k = TARGET_COVER * S                        # mark spans the full normalised width
    x0 = (S - k) / 2
    y0 = (S - mark_h * k) / 2

    def P(nx, ny):
        return (x0 + nx * k, y0 + (ny - top_y) * k)

    img = Image.new("RGB", (S, S), BLACK)
    d = ImageDraw.Draw(img)
    for dy in (0.0, gap):
        ya = top_y + dy                          # apex, top edge
        yl = ya + m_left * apex_x                # left end, top edge
        yr = ya + m_right * (1 - apex_x)         # right end, top edge
        d.polygon([P(0, yl), P(apex_x, ya), P(apex_x, ya + thick), P(0, yl + thick)],
                  fill=WHITE)
        d.polygon([P(apex_x, ya), P(1, yr), P(1, yr + thick), P(apex_x, ya + thick)],
                  fill=BLUE)
    return img.resize((TILE_PX, TILE_PX), Image.LANCZOS)


VECTOR_TILES = {
    "Toronto Star": _draw_toronto_star,
    "BBC": _draw_bbc,
}
# _draw_storeys is kept but unused: storeys.com serves a real 980px
# apple-touch-icon (see ICON_OVERRIDE), which beats any reconstruction. It is
# retained only as the record of how the 32px favicon was measured, in case that
# asset ever disappears.


def _mark_mask(icon: Image.Image) -> Image.Image:
    """An L-mode coverage mask of the mark, whatever form the favicon takes.

    Google's favicon service is not consistent about which variant it serves for
    a domain — cbc.ca has returned both an opaque black square with a white gem
    and a transparent red gem. Deriving a mask from either, then filling it with
    a chosen colour, makes the tile identical no matter which one arrives.
    """
    # Floor low coverage to zero: source compression leaves a haze of near-zero
    # values that otherwise mottles the flat ground.
    floor = lambda m: m.point(lambda v: 0 if v < 28 else v)  # noqa: E731

    rgba = icon.convert("RGBA")
    alpha = rgba.getchannel("A")
    if sum(1 for p in alpha.getdata() if p < 32) / (icon.width * icon.height) > 0.05:
        return floor(alpha)                # transparent variant: alpha is the mark
    ground = _icon_ground(icon)            # opaque variant: distance from its ground
    px = rgba.convert("RGB").load()
    mask = Image.new("L", icon.size, 0)
    mp = mask.load()
    for y in range(icon.height):
        for x in range(icon.width):
            d = sum(abs(c - g) for c, g in zip(px[x, y], ground))
            mp[x, y] = min(255, round(d * 255 / 210))
    return floor(mask)


def _place_mark(icon: Image.Image, mask: Image.Image, bg: "tuple[int, int, int]",
                paint: "tuple[int, int, int] | None" = None,
                target: "float | None" = None,
                band: "tuple[float, float] | None" = None) -> "tuple[Image.Image, float]":
    """Centre a mark on a ground at a consistent optical size.

    Scales by the mark's own bounding box rather than the icon's canvas, because
    the canvas padding is exactly what varies between publishers. Returns the
    tile and the coverage actually used, so the build can report it.
    """
    # Measure the extent from solid coverage only. Faint anti-aliasing haze can
    # reach the canvas edge and reports a mark far larger than the one you see,
    # which then scales the real artwork down too far (Axios, NYT, CBC).
    bb = mask.point(lambda v: 255 if v > 110 else 0).getbbox() or mask.getbbox()
    if bb is None:
        return Image.new("RGB", (TILE_PX, TILE_PX), bg), 0.0

    tgt = TARGET_COVER if target is None else target
    lo, hi = KEEP_BAND if band is None else band
    mark_px = max(bb[2] - bb[0], bb[3] - bb[1])
    cover = mark_px / min(icon.size)
    scale = ((tgt * TILE_PX) / mark_px if not (lo <= cover <= hi)
             else (cover * TILE_PX) / mark_px)

    src = Image.new("RGBA", icon.size, bg + (0,))
    if paint is not None:
        src.paste(Image.new("RGBA", icon.size, paint + (255,)), (0, 0), mask)
    else:
        src.paste(icon.convert("RGBA"), (0, 0), mask)

    new_size = (max(1, round(icon.width * scale)), max(1, round(icon.height * scale)))
    src = src.resize(new_size, Image.LANCZOS)
    cx, cy = ((bb[0] + bb[2]) / 2 * scale, (bb[1] + bb[3]) / 2 * scale)

    tile = Image.new("RGBA", (TILE_PX, TILE_PX), bg + (255,))
    tile.alpha_composite(src, (round(TILE_PX / 2 - cx), round(TILE_PX / 2 - cy)))
    return tile.convert("RGB"), min(cover, TARGET_COVER) if scale != 1 else cover


def _has_gutter(icon: Image.Image, ground: "tuple[int, int, int]") -> bool:
    """True when the icon's literal corners differ from its ground colour.

    A rounded-square favicon leaves a white or transparent gutter at each corner;
    a square one does not. Only the former needs cropping.
    """
    rgba = icon.convert("RGBA").load()
    w, h = icon.size
    off = 0
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b, a = rgba[x, y]
        if a < 200 or sum(abs(c - d) for c, d in zip((r, g, b), ground)) > 60:
            off += 1
    # All four, not any: a rounded square is cut at every corner. Toronto Star's
    # white chevron notch reaches only the two left corners, and treating that as
    # a gutter cropped 11px off each side of a logo that needed no crop at all.
    return off == 4


def _monogram(source: str) -> str:
    """Initials for a source with no usable icon. 'r/toronto' -> 'RT'."""
    if source in MONOGRAM_TEXT:
        return MONOGRAM_TEXT[source]
    words = [w for w in source.replace("/", " ").replace("&", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def build_tile(source: str, favicon_url: str, brand: dict) -> "tuple[Image.Image, str, str]":
    """Return (tile, mode, ground_hex).

    The colour field always reaches the tile edge. Nesting an opaque favicon
    inside a brand-coloured square produced a badge with a padding ring, which
    is the artifact this avoids. Three routes:

      opaque      the favicon already carries its own brand ground, so bleed it
                  edge to edge and crop off the rounded-corner gutter
      transparent the mark floats, so it sits on the researched brand colour
      monogram    no usable mark, so initials on the researched brand colour
    """
    if source in VECTOR_TILES:
        tile = VECTOR_TILES[source]()
        return tile, "vector", "#%02X%02X%02X" % tile.convert("RGB").getpixel(
            (TILE_PX - 2, TILE_PX // 2)
        )

    icon = (None if source in FORCE_MONOGRAM
            else _fetch_icon(_domain_of(favicon_url), ICON_OVERRIDE.get(source)))
    if icon is not None and min(icon.size) < MIN_ICON_PX:
        print(f"    · {source}: favicon is {icon.width}px, using a monogram instead")
        icon = None

    if icon is not None and source in MARK_ON:
        mark_hex, ground_hex = MARK_ON[source]
        mask = _mark_mask(icon)
        gain = MARK_GAIN.get(source)
        if gain:
            mask = mask.point(lambda v: min(255, int(v * gain)))
        tile, _ = _place_mark(icon, mask, _hex_rgb(ground_hex), paint=_hex_rgb(mark_hex))
        return tile, "recolored", ground_hex.upper()

    if icon is not None and _transparent_frac(icon) < TRANSPARENT_MIN:
        # Opaque: the favicon carries its own ground, so that colour becomes the
        # field and its mark is re-placed on it at the common optical size.
        ground = _icon_ground(icon)
        if source in TARGET_OVERRIDE:
            t = TARGET_OVERRIDE[source]
            tile, _ = _place_mark(icon, _mark_mask(icon), ground, target=t, band=(t, t))
            return tile, "opaque", "#%02X%02X%02X" % ground
        if source in NO_NORMALIZE:
            # Drawn to bleed. Fill to the edge and leave the composition alone.
            scale = TILE_PX / min(icon.size)
            big = icon.resize((max(1, round(icon.width * scale)),
                               max(1, round(icon.height * scale))), Image.LANCZOS)
            tile = Image.new("RGBA", (TILE_PX, TILE_PX), ground + (255,))
            tile.alpha_composite(big, (-(big.width - TILE_PX) // 2,
                                       -(big.height - TILE_PX) // 2))
            return tile.convert("RGB"), "bleed", "#%02X%02X%02X" % ground
        tile, _ = _place_mark(icon, _mark_mask(icon), ground)
        return tile, "opaque", "#%02X%02X%02X" % ground

    bg = _hex_rgb(brand["bg"])
    if icon is not None:
        tile, _ = _place_mark(icon, icon.convert("RGBA").getchannel("A"), bg)
        return tile, "transparent", brand["bg"].upper()
    tile = Image.new("RGBA", (TILE_PX, TILE_PX), bg + (255,))

    # Set the initials oversized on a transparent layer, then size them through
    # the same bounding-box normalisation the logos use, so a monogram sits at a
    # comparable optical weight instead of floating in its field.
    text = _monogram(source)
    fg = (255, 255, 255) if brand.get("fg_hint") == "light" else (17, 17, 17)
    S = TILE_PX * SUPERSAMPLE
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    font = _load_font(round(S * 0.42))
    l, t, r, b = ld.textbbox((0, 0), text, font=font)
    ld.text(((S - (r - l)) / 2 - l, (S - (b - t)) / 2 - t), text, font=font,
            fill=fg + (255,))
    tile, _ = _place_mark(layer, layer.getchannel("A"), bg, paint=fg,
                          target=MONOGRAM_COVER, band=(MONOGRAM_COVER, MONOGRAM_COVER))
    return tile, "monogram", brand["bg"].upper()


def main() -> int:
    if not BRAND_FILE.exists():
        print(f"missing {BRAND_FILE}; cannot build tiles.")
        return 1
    brands = json.loads(BRAND_FILE.read_text())

    out_dir = Path(__file__).resolve().parent.parent / EE_TILE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    written, fallbacks = 0, []
    modes: "dict[str, int]" = {}
    grounds: "dict[str, str]" = {}
    for source, favicon_url in SOURCE_FAVICONS.items():
        domain = _domain_of(favicon_url)
        brand = brands.get(domain)
        if brand is None:
            brand = brands["__default__"]
            fallbacks.append(f"{source} ({domain})")
        path = out_dir / f"{_tile_slug(source)}.png"
        tile, mode, ground = build_tile(source, favicon_url, brand)
        tile.save(path, format="PNG")
        modes[mode] = modes.get(mode, 0) + 1
        grounds[source] = ground
        print(f"  {path.name:<28} {ground}  {mode:<11} {source}")
        written += 1

    mark_hex, ground_hex = DEFAULT_MARK_COLOURS
    dpath = out_dir / EE_TILE_DEFAULT
    qf = _fetch_icon("quitefrank.co", DEFAULT_MARK_URL)
    if qf is not None:
        tile, _ = _place_mark(qf, qf.convert("RGBA").getchannel("A"),
                              _hex_rgb(ground_hex), paint=_hex_rgb(mark_hex))
        note = "(unmapped sources · Quite Frankly mark)"
    else:
        # Never let a network hiccup leave the default tile missing: a missing
        # default is the one failure that drops rows to text.
        tile = Image.new("RGB", (TILE_PX, TILE_PX), _hex_rgb(brands["__default__"]["bg"]))
        ground_hex = brands["__default__"]["bg"]
        note = "(unmapped sources · fell back to flat)"
    tile.save(dpath, format="PNG")
    grounds["__default__"] = ground_hex.upper()
    print(f"  {dpath.name:<28} {ground_hex.upper()}  {note}")

    print(f"\n{written} source tiles + 1 default -> {out_dir}")
    print("modes: " + ", ".join(f"{k}={v}" for k, v in sorted(modes.items())))
    (Path(__file__).with_name("tile_grounds.json")).write_text(
        json.dumps(grounds, indent=1, sort_keys=True)
    )
    if fallbacks:
        print(f"no brand colour, used default: {', '.join(fallbacks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
