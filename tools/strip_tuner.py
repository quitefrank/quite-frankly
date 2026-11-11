#!/usr/bin/env python3
"""Local slider panel for tuning the Markets strip by eye.

Renders the real formatting.render_markets_block inside the real Finance &
Markets card markup, at phone and desktop widths, light and dark. "Save"
writes strip_style.json, which the newsletter reads on every run, so what you
see here is what ships (after the file is committed).

Run from the project root:
    venv/bin/python tools/strip_tuner.py        # then open http://127.0.0.1:8790

Local only: binds 127.0.0.1 and is never imported by the pipeline.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def _load_env() -> None:
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        for line in open(path):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


_load_env()

import formatting  # noqa: E402
import markets  # noqa: E402

PORT = 8790
Y = markets.YAHOO_QUOTE


def _live_tiles() -> tuple[list[dict], date]:
    today = datetime.now(markets.TORONTO).date()
    session = markets.latest_session(today)
    if session:
        tiles = markets.fetch_strip(session)
        if tiles:
            return tiles, session
    return [], markets.previous_weekday(today)


LIVE_TILES, SESSION = _live_tiles()
TARGET_TILES = [  # the planned fund strip, sample numbers until a data source covers it
    markets.tile("SPY", -0.37, "Market", Y.format("SPY")),
    markets.tile("XLK", -1.12, "Tech", Y.format("XLK")),
    markets.tile("XLE", -0.21, "Energy", Y.format("XLE")),
    markets.tile("XLF", 0.14, "Banks", Y.format("XLF")),
    markets.tile("XLRE", 0.52, "Real Estate", Y.format("XLRE")),
    markets.tile("GLD", -2.08, "Gold", Y.format("GLD")),
]
SAMPLE = {  # from the 2026-11-11 test edition
    "summary": "Hot U.S. CPI data and hawkish Fed comments sent Treasury yields toward 5%, pulling the S&P 500 down 0.38%.",
    "movers": [
        {"symbol": "TTWO", "name": "Take-Two Interactive", "change_pct": 8.3,
         "why": "Management confirmed the Nov. 19 GTA VI launch and said preorders are tracking at unprecedented levels.",
         "source_url": "https://www.tradingkey.com/", "quote_url": Y.format("TTWO")},
        {"symbol": "NVDA", "name": "Nvidia", "change_pct": -5.47,
         "why": "A report alleged its CEO's relationship with a suspected Chinese spy helped move restricted chips to China.",
         "source_url": "https://www.fool.com/", "quote_url": Y.format("NVDA")},
    ],
    "watch": [
        {"time": "8:30 ET", "event": "US CPI for October", "source_url": "https://example.com"},
        {"time": "10:00 ET", "event": "Bank of Canada Governor speech", "source_url": "https://example.com"},
        {"time": "After close", "event": "Shopify Q3 earnings", "source_url": "https://example.com"},
    ],
}


def _coerce(raw: dict) -> dict:
    """Keep known keys with the default's type, then apply the loader's clamps."""
    style = dict(formatting.STRIP_STYLE_DEFAULTS)
    for key, default in formatting.STRIP_STYLE_DEFAULTS.items():
        if key not in raw:
            continue
        v = raw[key]
        style[key] = bool(v) if isinstance(default, bool) else int(v)
    style["rows"] = min(max(style["rows"], 1), 2)
    style["columns"] = min(max(style["columns"], 1), 8)
    style["pct_decimals"] = min(max(style["pct_decimals"], 0), 2)
    return style


def render_preview(style: dict, tile_set: str, theme: str) -> str:
    palette = formatting.DARK if theme == "dark" else formatting.LIGHT
    tiles = TARGET_TILES if tile_set == "target" or not LIVE_TILES else LIVE_TILES
    data = {"as_of": SESSION, "tiles": tiles, **SAMPLE}
    block = formatting.render_markets_block(data, palette, style)
    # Same card markup as parse_and_render_sections, so spacing matches the email.
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:{palette['page_bg']}">
<div style="padding:20px 10px"><div style="max-width:670px;margin:0 auto">
<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette['card_border']};overflow:hidden;background:{palette['card_bg']};font-family:Helvetica,Arial,sans-serif">
  <div style="padding:15px 15px 0"><p style="color:{palette['accent']};margin:0 0 12px;font-size:13px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📈 Finance &amp; Markets</p></div>
  <div style="padding:0 15px 15px">{block}</div>
</div></div></div></body></html>"""


CONTROLS = [  # key, label, min, max (None = checkbox)
    ("rows", "Rows", 1, 2),
    ("columns", "Tickers per row", 2, 6),
    ("area_size", "Sector name size (px)", 8, 16),
    ("area_uppercase", "Sector name uppercase", None, None),
    ("ticker_size", "Ticker size (px)", 10, 20),
    ("pct_size", "Percentage size (px)", 10, 20),
    ("pct_decimals", "Percentage decimals", 0, 2),
    ("tile_pad_y", "Tile padding, top/bottom (px)", 0, 16),
    ("tile_pad_x", "Tile padding, sides (px)", 0, 12),
    ("area_gap", "Gap: sector name to ticker (px)", 0, 10),
    ("pct_gap", "Gap: ticker to percentage (px)", 0, 10),
    ("strip_gap_below", "Gap below strip (px)", 0, 24),
    ("row_dividers", "Row divider lines", None, None),
]


def tuner_page() -> str:
    current = formatting.load_strip_style()
    rows = ""
    for key, label, lo, hi in CONTROLS:
        if lo is None:
            checked = "checked" if current[key] else ""
            rows += (f'<label class="row check"><input type="checkbox" data-key="{key}" {checked}>'
                     f'<span>{label}</span></label>')
        else:
            rows += (f'<label class="row"><span>{label} <b id="v-{key}">{current[key]}</b></span>'
                     f'<input type="range" data-key="{key}" min="{lo}" max="{hi}" step="1" value="{current[key]}"></label>')
    live_note = (f"live FMP closes, {SESSION:%b %-d}" if LIVE_TILES else "FMP unavailable: showing target set")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Strip tuner</title>
<style>
  body{{margin:0;font:14px/1.4 -apple-system,Helvetica,Arial,sans-serif;background:#eceef2;color:#1a1a1a;display:flex;min-height:100vh}}
  aside{{width:300px;flex:none;background:#fff;padding:18px;border-right:1px solid #dcdfe5;overflow:auto}}
  h1{{font-size:15px;margin:0 0 4px}} p.sub{{margin:0 0 14px;color:#777;font-size:12px}}
  .row{{display:block;margin:0 0 12px}} .row span{{display:flex;justify-content:space-between;font-size:13px}}
  .row input[type=range]{{width:100%}} .check{{display:flex;gap:8px;align-items:center}}
  .seg{{display:flex;gap:6px;margin:0 0 12px}} .seg button{{flex:1}}
  button{{font:inherit;padding:7px 10px;border:1px solid #c9ced8;border-radius:8px;background:#fff;cursor:pointer}}
  button.on{{background:#1c7ff2;color:#fff;border-color:#1c7ff2}} button.primary{{background:#1a1a1a;color:#fff;border-color:#1a1a1a}}
  #status{{font-size:12px;color:#0f8a3c;min-height:18px;margin-top:6px}}
  main{{flex:1;display:flex;gap:24px;padding:24px;align-items:flex-start;overflow:auto}}
  figure{{margin:0}} figcaption{{font-size:12px;color:#666;margin:0 0 6px}}
  iframe{{border:1px solid #cfd3da;border-radius:10px;background:#fff}}
</style></head><body>
<aside>
  <h1>Markets strip tuner</h1>
  <p class="sub">Real renderer, real card markup. Tiles: {live_note}. Movers and watch list are sample text.</p>
  <div class="seg"><button data-set="live" class="on">Live strip</button><button data-set="target">Target funds</button></div>
  <div class="seg"><button data-theme="light" class="on">Light</button><button data-theme="dark">Dark</button></div>
  {rows}
  <div class="seg"><button class="primary" id="save">Save to strip_style.json</button></div>
  <div class="seg"><button id="copy">Copy JSON</button><button id="reset">Defaults</button></div>
  <div id="status"></div>
</aside>
<main>
  <figure><figcaption>Phone, 375px</figcaption><iframe id="phone" width="375" height="760"></iframe></figure>
  <figure><figcaption>Desktop, 670px email column</figcaption><iframe id="desk" width="720" height="760"></iframe></figure>
</main>
<script>
const DEFAULTS = {json.dumps(formatting.STRIP_STYLE_DEFAULTS)};
let tileSet = "live", theme = "light", timer;
const inputs = [...document.querySelectorAll("[data-key]")];
function style() {{
  const s = {{}};
  inputs.forEach(i => s[i.dataset.key] = i.type === "checkbox" ? i.checked : Number(i.value));
  return s;
}}
function refresh() {{
  inputs.forEach(i => {{ const v = document.getElementById("v-" + i.dataset.key); if (v) v.textContent = i.value; }});
  clearTimeout(timer);
  timer = setTimeout(() => {{
    const q = "/render?style=" + encodeURIComponent(JSON.stringify(style())) + "&set=" + tileSet + "&theme=" + theme;
    document.getElementById("phone").src = q;
    document.getElementById("desk").src = q;
  }}, 60);
}}
inputs.forEach(i => i.addEventListener("input", refresh));
document.querySelectorAll("[data-set]").forEach(b => b.onclick = () => {{
  tileSet = b.dataset.set; document.querySelectorAll("[data-set]").forEach(x => x.classList.toggle("on", x === b)); refresh();
}});
document.querySelectorAll("[data-theme]").forEach(b => b.onclick = () => {{
  theme = b.dataset.theme; document.querySelectorAll("[data-theme]").forEach(x => x.classList.toggle("on", x === b)); refresh();
}});
function say(t) {{ const s = document.getElementById("status"); s.textContent = t; setTimeout(() => s.textContent = "", 3000); }}
document.getElementById("save").onclick = async () => {{
  const r = await fetch("/save", {{method: "POST", body: JSON.stringify(style())}});
  say(r.ok ? "Saved. Tell Claude to ship it." : "Save failed");
}};
document.getElementById("copy").onclick = async () => {{
  await navigator.clipboard.writeText(JSON.stringify(style(), null, 2)); say("Copied");
}};
document.getElementById("reset").onclick = () => {{
  inputs.forEach(i => i.type === "checkbox" ? i.checked = DEFAULTS[i.dataset.key] : i.value = DEFAULTS[i.dataset.key]);
  refresh();
}};
refresh();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, body: str, status: int = 200, ctype: str = "text/html; charset=utf-8") -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(tuner_page())
        if url.path == "/render":
            q = parse_qs(url.query)
            try:
                style = _coerce(json.loads(q.get("style", ["{}"])[0]))
            except (ValueError, TypeError):
                style = formatting.load_strip_style()
            return self._send(render_preview(style, q.get("set", ["live"])[0], q.get("theme", ["light"])[0]))
        self._send("not found", 404, "text/plain")

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/save":
            return self._send("not found", 404, "text/plain")
        try:
            raw = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            style = _coerce(raw)
        except (ValueError, TypeError):
            return self._send("bad style", 400, "text/plain")
        with open(formatting.STRIP_STYLE_FILE, "w") as f:
            json.dump(style, f, indent=2)
            f.write("\n")
        print(f"saved {formatting.STRIP_STYLE_FILE}: {style}", flush=True)
        self._send("ok", 200, "text/plain")

    def log_message(self, *args):  # keep the console quiet
        pass


if __name__ == "__main__":
    print(f"Strip tuner on http://127.0.0.1:{PORT}  (tiles: {'live' if LIVE_TILES else 'target sample'})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
