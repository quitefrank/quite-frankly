"""Claude formatter call, HTML rendering, and email send."""

from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import anthropic

from config import (
    EVERYTHING_ELSE_FALLBACK_POOL,
    EVERYTHING_ELSE_KEYWORD_EMOJIS,
    EVERYTHING_ELSE_SOURCE_EMOJIS,
    RECIPIENT,
    SECTION_EMOJIS,
    SECTION_MAP,
    SENDER,
    SOURCE_FAVICONS,
    TEST_MODE,
)
from prompts import (
    SUBJECT_BLURB_SYSTEM_PROMPT,
    FORMAT_SYSTEM_PROMPT,
    LEGACY_FORMAT_SYSTEM_PROMPT,
)
from pipeline import canonical_key, normalize_text


# ── Colour themes ───────────────────────────────────────────────────────────
# LIGHT = current weekday palette (values identical to prior hardcoded hexes).
# DARK  = weekend palette, the inverse. build_email_html picks one per edition.
LIGHT = {
    "page_bg": "#f4f4f4",
    "card_bg": "#ffffff",
    "card_border": "#e6e6e6",
    "header_bg": "#1f1f1f",
    "header_text": "#ffffff",
    "header_border": "#222222",
    "heading": "#1a1a1a",
    "body": "#333333",
    "meta": "#999999",
    "meta_label": "#888888",
    "accent": "#1c7ff2",
    "callout_bg": "#f0f4ff",
    "divider": "#f0f0f0",
    "footer_bg": "#E9EBF7",
    "footer_text": "#79787d",
    "color_scheme": "light",
}
DARK = {
    "page_bg": "#202226",
    "card_bg": "#2b2d33",
    "card_border": "#3a3d45",
    "header_bg": "#ffffff",
    "header_text": "#1a1a1a",
    "header_border": "#e6e6e6",
    "heading": "#f5f5f5",
    "body": "#c8c8c8",
    "meta": "#7f7f7f",
    "meta_label": "#8a8a8a",
    "accent": "#4d9bff",
    "callout_bg": "#16243a",
    "divider": "#3a3d45",
    "footer_bg": "#1a1c2e",
    "footer_text": "#8b8ba3",
    "color_scheme": "dark",
}


SECTION_ORDER = [
    "Canada & Toronto",
    "Toronto Housing",
    "Tech & AI",
    "Design & Product",
    "Finance & Markets",
    "US & Global",
    "Today in the World",
]


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}

TODAY_IN_THE_WORLD = "Today in the World"
TODAY_IN_THE_WORLD_CAP = 5

SECTIONS_WITHOUT_INLINE_LINKS = {"Finance & Markets", "US & Global"}

DEFAULT_FEATURED_CAP = 2
SECTION_FEATURED_CAPS = {
    "Finance & Markets": 1,
    "US & Global": 1,
    # Today in the World is populated by the global pickoff; per-section
    # filling is skipped for it (cap=0 here means "don't fill from this
    # section's own items").
    TODAY_IN_THE_WORLD: 0,
}
MAX_OTHER_HEADLINES_PER_SECTION = 3
MAX_EVERYTHING_ELSE = 7
FEATURED_STORY_PARAGRAPH_CAP = 2


def _item_score(scores: dict) -> int:
    return (
        scores.get("cross_source_coverage", 0)
        + scores.get("personal_relevance", 0)
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "weak"), 0)
    )


def suppressed_cluster_ids(tiered_items: list[dict]) -> set[int]:
    """Return the ids of non-representative cluster members.

    For each non-empty cluster_id with 2+ members, the highest-scored item
    is the representative; every other member's id is returned. The
    newsletter must show a cluster exactly once, so these ids are
    suppressed from every surface: featured stories, Other Headlines, and
    Everything Else. Scope is global: a cluster whose members span two
    sections still collapses to a single representative.

    Ties on _item_score are broken by lowest id so the result is
    deterministic. Items with an empty cluster_id are never suppressed -
    an empty cluster_id is triage's "no cluster known" signal.
    """
    by_cluster: dict[str, list[dict]] = {}
    for item in tiered_items:
        cid = item.get("cluster_id") or ""
        if not cid:
            continue
        by_cluster.setdefault(cid, []).append(item)

    suppressed: set[int] = set()
    for members in by_cluster.values():
        if len(members) < 2:
            continue
        rep = max(
            members,
            key=lambda it: (_item_score(it.get("scores", {})), -it["id"]),
        )
        for item in members:
            if item["id"] != rep["id"]:
                suppressed.add(item["id"])
    return suppressed


def near_duplicate_ids(
    tiered_items: list[dict],
    links_by_id: dict[int, dict],
    overlap_threshold: float = 0.5,
    min_shared_tokens: int = 3,
) -> set[int]:
    """Deterministic backstop for clustering misses (the deferred F1 detector).

    suppressed_cluster_ids keys off cluster_id, so it can't catch two articles
    about one story that triage gave DIFFERENT cluster_ids (different URLs,
    differently-worded headlines, sometimes different sections). This pass
    re-detects them from content and returns the ids to hide, contributing to
    the same suppressed_ids set every surface already honors.

    Two items are near-duplicates when EITHER:
      - they share a non-empty canonical key (e.g. the same embedded YouTube
        video), or
      - their combined title+snippet token sets share at least
        min_shared_tokens significant tokens AND their overlap coefficient
        (shared / size of the smaller set) is >= overlap_threshold.

    Overlap coefficient, not Jaccard: a featured story carries a long headline
    plus snippet while its duplicate may be a short headline, so the union is
    lopsided and Jaccard understates a real match. Overlap measures how fully
    the smaller item is contained in the larger, which is what "same story,
    less text" looks like. min_shared_tokens (significant tokens only) is the
    precision guard against a short generic title being swallowed.

    Within each near-duplicate group the highest-scored item survives (ties to
    lowest id, matching suppressed_cluster_ids); the rest are returned.
    Conservative by design: a wrong merge silently drops a real story, so the
    thresholds favour precision over recall.
    """
    ids = [it["id"] for it in tiered_items]
    text: dict[int, frozenset] = {}
    keys: dict[int, str] = {}
    for it in tiered_items:
        src = links_by_id.get(it["id"], {})
        text[it["id"]] = normalize_text(f"{src.get('title', '')} {src.get('snippet', '')}")
        keys[it["id"]] = canonical_key(src)

    parent = {i: i for i in ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    n = len(ids)
    for a_idx in range(n):
        for b_idx in range(a_idx + 1, n):
            a, b = ids[a_idx], ids[b_idx]
            ka, kb = keys[a], keys[b]
            if ka and ka == kb:
                union(a, b)
                continue
            shared = text[a] & text[b]
            if len(shared) < min_shared_tokens:
                continue
            smaller = min(len(text[a]), len(text[b]))
            if smaller and len(shared) / smaller >= overlap_threshold:
                union(a, b)

    groups: dict[int, list[dict]] = {}
    for it in tiered_items:
        groups.setdefault(find(it["id"]), []).append(it)

    suppressed: set[int] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        rep = max(
            members,
            key=lambda it: (_item_score(it.get("scores", {})), -it["id"]),
        )
        for it in members:
            if it["id"] != rep["id"]:
                suppressed.add(it["id"])
    return suppressed


def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict], suppressed_ids: set[int] | None = None) -> str:
    # Build cluster_members from the UNCOLLAPSED tiered_items so siblings
    # surface every cluster member's URL — even ones that the global cluster
    # collapse below drops. Order matters: the collapse keeps only one item
    # per cluster, but a surviving story might still want to link to a
    # sibling that lost the collapse tiebreak. Building this map first
    # preserves that visibility.
    cluster_members: dict[str, list[dict]] = {}
    for item in tiered_items:
        cid = item.get("cluster_id")
        if not cid:
            continue
        link = links_by_id.get(item["id"], {})
        url = link.get("link", "")
        source = link.get("source", "")
        if not url or not source:
            continue
        cluster_members.setdefault(cid, []).append({
            "id": item["id"],
            "source": source,
            "url": url,
        })

    # Global cluster collapse: triage clusters the same underlying story into
    # multiple feed items. Drop every non-representative cluster member so a
    # single story occupies at most one slot anywhere in the briefing. The
    # cluster_members map above was built from the uncollapsed list, so a
    # surviving story still links to every sibling's URL.
    if suppressed_ids is None:
        suppressed_ids = suppressed_cluster_ids(tiered_items)
    tiered_items = [it for it in tiered_items if it["id"] not in suppressed_ids]

    by_section: dict[str, dict[str, list]] = {
        s: {"tier_1": [], "tier_2": [], "tier_3": []} for s in SECTION_ORDER
    }
    for item in tiered_items:
        section = item.get("section")
        tier = item.get("tier", 0)
        if section not in by_section or tier == 0:
            continue
        bucket = f"tier_{tier}"
        if bucket not in by_section[section]:
            continue
        link = links_by_id.get(item["id"], {})
        by_section[section][bucket].append({
            "id": item["id"],
            "title": link.get("title", ""),
            "snippet": link.get("snippet", ""),
            "source": link.get("source", ""),
            "cluster_id": item.get("cluster_id"),
            "_score": _item_score(item.get("scores", {})),
            "_has_image": bool(link.get("image")),
        })

    # Attach siblings to each featured-eligible item. The sibling list excludes
    # the item itself and is empty for Finance & Markets / US & Global.
    for section, buckets in by_section.items():
        if section in SECTIONS_WITHOUT_INLINE_LINKS:
            for item in buckets["tier_1"] + buckets["tier_2"] + buckets["tier_3"]:
                item["siblings"] = []
            continue
        for item in buckets["tier_1"] + buckets["tier_2"] + buckets["tier_3"]:
            cid = item.get("cluster_id")
            members = cluster_members.get(cid, [])
            item["siblings"] = [
                {"source": m["source"], "url": m["url"]}
                for m in members
                if m["id"] != item["id"]
            ]

    # Tier 1 buckets sort by (has_image desc, score desc) so image-bearing
    # stories surface before image-less ones within the same tier. Tier 2 and
    # Tier 3 buckets keep pure score ordering — image priority only matters
    # for the featured slot.
    for section_buckets in by_section.values():
        for bucket_name, bucket in section_buckets.items():
            if bucket_name == "tier_1":
                bucket.sort(key=lambda x: (x["_has_image"], x["_score"]), reverse=True)
            else:
                bucket.sort(key=lambda x: x["_score"], reverse=True)

    # Global pickoff: pull the top TODAY_IN_THE_WORLD_CAP tier-1 items
    # across every section EXCEPT Today in the World itself, move them into
    # the Today in the World tier_1 bucket, and delete them from their home
    # sections. Hero (position 0) is the highest-scored picked item that has
    # an image; if none of the picks have images, look for an image-bearing
    # tier-1 candidate beyond the picks and swap one in.
    global_pool = []
    for sec, sec_buckets in by_section.items():
        if sec == TODAY_IN_THE_WORLD:
            continue
        for item in sec_buckets["tier_1"]:
            global_pool.append((sec, item))
    # Sort by pure score desc to pick the top 5 regardless of image.
    global_pool.sort(key=lambda pair: pair[1]["_score"], reverse=True)
    picked = global_pool[:TODAY_IN_THE_WORLD_CAP]

    # Hero promotion: if any picked item has an image, move the
    # highest-scored image-bearer to position 0. If none has an image,
    # try to swap in a lower-scored image-bearer from the remaining pool.
    if picked:
        hero_idx_in_picked = next(
            (i for i, (_, item) in enumerate(picked) if item["_has_image"]),
            None,
        )
        if hero_idx_in_picked is None:
            swap_idx = next(
                (i for i, (_, item) in enumerate(global_pool[TODAY_IN_THE_WORLD_CAP:], start=TODAY_IN_THE_WORLD_CAP)
                 if item["_has_image"]),
                None,
            )
            if swap_idx is not None:
                # Replace the lowest-scored pick with the image-bearer.
                picked[-1] = global_pool[swap_idx]
                hero_idx_in_picked = len(picked) - 1
        if hero_idx_in_picked is not None and hero_idx_in_picked != 0:
            picked[0], picked[hero_idx_in_picked] = picked[hero_idx_in_picked], picked[0]

    # Move picks into Today in the World, delete from home sections.
    # Triage may also route items directly to Today in the World; combine
    # those with the picks (triage-routed first), then cap to the section
    # size so a busy triage day doesn't overflow the layout.
    picked_ids = {item["id"] for _, item in picked}
    for sec, _ in picked:
        by_section[sec]["tier_1"] = [
            it for it in by_section[sec]["tier_1"] if it["id"] not in picked_ids
        ]
    combined = (
        by_section[TODAY_IN_THE_WORLD]["tier_1"]
        + [item for _, item in picked]
    )
    by_section[TODAY_IN_THE_WORLD]["tier_1"] = combined[:TODAY_IN_THE_WORLD_CAP]

    # Per-section featured cap. Most sections aim for 2, Finance & Markets and
    # US & Global aim for 1. If tier_1 is short, fill from tier_2 then tier_3
    # (already score-sorted) so the section still has *something* featured.
    # Overflow drops out of the JSON entirely; build_everything_else picks
    # them up because they're not in used_ids.
    for section, buckets in by_section.items():
        cap = SECTION_FEATURED_CAPS.get(section, DEFAULT_FEATURED_CAP)
        if cap == 0:
            # cap=0 means "skip per-section filling for this section"
            # (used for Today in the World, which is populated by the
            # global pickoff above).
            continue
        while len(buckets["tier_1"]) < cap:
            promoted = False
            for fallback_tier in ("tier_2", "tier_3"):
                if buckets[fallback_tier]:
                    buckets["tier_1"].append(buckets[fallback_tier].pop(0))
                    promoted = True
                    break
            if not promoted:
                break
        buckets["tier_1"] = buckets["tier_1"][:cap]

    def _section_max_score(buckets: dict) -> int:
        all_scores = [item["_score"] for bucket in buckets.values() for item in bucket]
        return max(all_scores) if all_scores else -100

    sorted_sections = dict(sorted(
        by_section.items(),
        key=lambda kv: _section_max_score(kv[1]),
        reverse=True,
    ))

    for section_buckets in sorted_sections.values():
        for bucket in section_buckets.values():
            for item in bucket:
                item.pop("_score", None)
                item.pop("_has_image", None)

    return json.dumps({
        "sections": sorted_sections,
        "clusters": clusters,
    }, indent=2)


# ── Claude API ─────────────────────────────────────────────────────────────────

def call_formatter(headlines_text):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = (
        "Here are today's real headlines from my RSS feeds. Use ONLY these real stories:\n\n"
        + headlines_text
        + "\n\nGenerate my daily briefing following the exact format specified."
    )
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=FORMAT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


def call_legacy_formatter(headlines_text):
    """Fallback formatter using the pre-redesign single-pass prompt.

    Used when the two-pass triage pipeline fails. Accepts raw headlines
    text (one item per line, `[#N] [Section] Title | Source: src`).
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = (
        "Here are today's real headlines from my RSS feeds. Use ONLY these real stories:\n\n"
        + headlines_text
        + "\n\nGenerate my daily briefing following the exact format specified."
    )
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=LEGACY_FORMAT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


# ── HTML Formatting ────────────────────────────────────────────────────────────

ID_TAG_RE = re.compile(r"\s*\[#(\d+)\]\s*$")


# Layout A item: <emoji> **<micro-header> [#N]:** <body>
# Emoji is any sequence of non-space, non-asterisk characters before the
# first ** marker on the line.
LAYOUT_A_ITEM_RE = re.compile(
    r"^(?P<emoji>\S+)\s+\*\*(?P<header>.+?)\s*\[#(?P<id>\d+)\]:\*\*\s*(?P<body>.*)$"
)


def _is_today_in_the_world_section(title: str) -> bool:
    return title.strip() == "Today in the World"


def _global_pickoff_display(is_design_edition: bool) -> tuple[str, str]:
    if is_design_edition:
        return ("In Design", "🎨")
    return ("In the World", "🌐")


def render_source_line(primary_source: str, also_in: list[str], article_link: str | None, palette: dict = LIGHT) -> str:
    favicon = SOURCE_FAVICONS.get(
        primary_source,
        f"https://www.google.com/s2/favicons?domain={primary_source}&sz=64",
    )
    img = (
        f'<img src="{favicon}" width="16" height="16" '
        f'style="width:16px;height:16px;vertical-align:middle;margin-right:4px;'
        f'border-radius:3px;display:inline-block">'
    )
    # Triage occasionally lists the primary_source inside also_in (multiple
    # articles from the same source clustered together), or repeats sources.
    # Strip both so we never render "Source, Source".
    seen = {primary_source}
    deduped_also_in = []
    for src in also_in:
        if src in seen:
            continue
        seen.add(src)
        deduped_also_in.append(src)
    also_in = deduped_also_in

    if not also_in:
        label = primary_source
    elif len(also_in) == 1:
        label = f"{primary_source}, {also_in[0]}"
    else:
        also_str = ", ".join(also_in)
        label = f"{primary_source} (also in {also_str})"

    if article_link:
        return (
            f'{img}<a href="{article_link}" '
            f'style="color:{palette["accent"]};text-decoration:none;vertical-align:middle;font-size:12px;">{label}</a>'
        )
    return f'{img}<span style="vertical-align:middle;font-size:12px;color:{palette["meta"]};">{label}</span>'


def extract_id(text):
    m = ID_TAG_RE.search(text)
    if m:
        return text[:m.start()].rstrip(), int(m.group(1))
    return text, None


def find_article_data(headline, links_by_id):
    """Look up the article record for a Claude-emitted headline.

    Extracts an inline [#N] id from the headline and resolves it through
    links_by_id. Falls back to fuzzy title-prefix matching against the dict
    values when no id is present (or the id is unknown), to tolerate stray
    Claude output.
    """
    _, item_id = extract_id(headline)
    if item_id is not None and item_id in links_by_id:
        l = links_by_id[item_id]
        return {"link": l["link"], "image": l["image"], "id": item_id}

    h = headline.lower()[:30]
    for lid, l in links_by_id.items():
        title_lower = l["title"].lower()
        if h in title_lower or title_lower[:30] in h:
            return {"link": l["link"], "image": l["image"], "id": lid}
    return {"link": None, "image": None, "id": None}


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _render_body_markdown(text: str, palette: dict = LIGHT) -> str:
    """Convert [label](url) markdown links and **bold** markers to HTML.

    Both links and bold are converted so Claude's body output renders
    cleanly even if it emits stray bold from the model.
    """
    text = _MARKDOWN_LINK_RE.sub(
        lambda m: (
            f'<a href="{m.group(2)}" '
            f'style="color:{palette["body"]};text-decoration:underline;text-decoration-color:{palette["accent"]};">{m.group(1)}</a>'
        ),
        text,
    )
    text = _MARKDOWN_BOLD_RE.sub(r"<strong>\1</strong>", text)
    return text


def _first_sentence(text: str, max_chars: int = 180) -> str:
    """Return the first sentence of text, truncated to max_chars."""
    if not text:
        return ""
    parts = _SENTENCE_SPLIT_RE.split(text, maxsplit=1)
    first = parts[0].strip()
    if len(first) > max_chars:
        first = first[:max_chars].rstrip() + "…"
    return first


def _other_headline_anchor(text, link, palette):
    """Wrap text in the Other Headlines link style, or return it plain."""
    if not link:
        return text
    return (
        f'<a href="{link}" '
        f'style="color:{palette["body"]};font-weight:400;text-decoration:underline;'
        f'text-decoration-color:{palette["accent"]};">'
        f"{text}</a>"
    )


def _other_headline_line(l, copy, palette):
    """Render the text of one Other Headlines item.

    With LLM copy ({subject, blurb}), the subject becomes the hyperlink and the
    blurb flows from it as one sentence (Morning Brew "what else is brewing"
    style). Without copy, or if it is malformed, fall back to the legacy
    rendering: first five words of the title linked, then a colon and the first
    sentence of the snippet.
    """
    copy = copy or {}
    subject = str(copy.get("subject", "")).strip()
    blurb = str(copy.get("blurb", "")).strip()
    if subject and blurb:
        rest = blurb[len(subject):] if blurb.startswith(subject) else " " + blurb
        return f"{_other_headline_anchor(subject, l.get('link'), palette)}{rest}"

    words = l["title"].split(" ")
    link_words = " ".join(words[:5])
    linked_part = _other_headline_anchor(link_words, l.get("link"), palette)
    summary = _first_sentence(l.get("snippet", ""))
    return f"{linked_part}: {summary}" if summary else linked_part


def render_other_headlines_for_section(section, tiered_items, links_by_id, used_ids,
                                       palette: dict = LIGHT, copy_by_id=None, collect=None):
    """Synthesize the Other Headlines subsection for one section.

    Picks the top MAX_OTHER_HEADLINES_PER_SECTION Tier 1 overflow and Tier 2
    items in this section whose IDs are not already in used_ids (i.e., not
    already featured), sorted by tier ascending then composite score desc so
    tier-1 overflow surfaces above tier-2. Adds the chosen IDs to used_ids so
    they don't duplicate in Everything Else.

    copy_by_id ({id: {subject, blurb}}) supplies Morning-Brew-style written copy
    per item; items without an entry render with the legacy title+snippet line.
    If collect is a list, the picked (id, link_dict) pairs are appended to it so
    a caller can write copy for exactly the items that surfaced.
    """
    candidates = []
    for it in tiered_items or []:
        if it.get("section") != section:
            continue
        tier = it.get("tier")
        if tier not in (1, 2):
            continue
        if it["id"] in used_ids:
            continue
        if it["id"] not in links_by_id:
            continue
        candidates.append((tier, -_item_score(it.get("scores", {})), it["id"]))

    candidates.sort()
    picked = [lid for _tier, _neg_score, lid in candidates[:MAX_OTHER_HEADLINES_PER_SECTION]]
    if not picked:
        return ""

    copy_by_id = copy_by_id or {}
    items_html = ""
    for lid in picked:
        used_ids.add(lid)
        l = links_by_id[lid]
        if collect is not None:
            collect.append((lid, l))
        body = _other_headline_line(l, copy_by_id.get(lid), palette)
        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:{palette["body"]};'
            f'font-family:Helvetica,Arial,sans-serif">{body}</li>'
        )

    return (
        f'<div style="margin-top:16px;padding-top:14px;border-top:1px solid {palette["divider"]};">'
        f'<p style="margin:0 0 8px;font-size:12px;font-weight:700;color:{palette["meta_label"]};'
        f'font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.08em">Other Headlines</p>'
        f'<ul style="margin:0;padding-left:20px">{items_html}</ul>'
        "</div>"
    )


def _render_today_in_the_world(lines: list[str], links_by_id: dict, used_ids: set, palette: dict = LIGHT) -> str:
    """Render the Today in the World list (Layout A) from Claude output lines.

    Hero image comes from the first item that has one. The hero image renders
    once at the top of the list. Each item is `<emoji> **<header> [#N]:** body`.
    """
    items = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = LAYOUT_A_ITEM_RE.match(line)
        if not m:
            continue
        item_id = int(m.group("id"))
        items.append({
            "emoji": m.group("emoji"),
            "header": m.group("header").strip(),
            "id": item_id,
            "body": m.group("body").strip(),
        })

    if not items:
        return ""

    hero_image_html = ""
    for it in items:
        link = links_by_id.get(it["id"], {})
        if link.get("image"):
            img = link["image"]
            href = link.get("link", "")
            img_tag = (
                f'<img src="{img}" alt="{it["header"]}" '
                f'style="width:100%;max-width:640px;height:200px;object-fit:cover;'
                f'display:block;margin:0 0 12px;border-radius:8px">'
            )
            hero_image_html = (
                f'<a href="{href}" style="text-decoration:none;display:block">{img_tag}</a>'
                if href else img_tag
            )
            break

    items_html = ""
    for it in items:
        used_ids.add(it["id"])
        link = links_by_id.get(it["id"], {})
        href = link.get("link", "")
        bold_inner = f'{it["header"]}.'
        if href:
            bold = (
                f'<a href="{href}" style="color:{palette["heading"]};text-decoration:underline;text-decoration-color:{palette["accent"]};">'
                f'<strong>{bold_inner}</strong></a>'
            )
        else:
            bold = f'<strong>{bold_inner}</strong>'
        rendered_body = _render_body_markdown(it["body"], palette)
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:{palette["body"]};'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{it["emoji"]}</span>'
            f'{bold} {rendered_body}</p>'
        )

    return hero_image_html + items_html


def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None, is_design_edition=False, palette: dict = LIGHT, oh_copy_by_id=None, oh_collect=None):
    clusters_by_item_id = clusters_by_item_id or {}
    tiered_items = tiered_items or []
    # Seed used_ids with suppressed cluster members so the programmatic
    # Other Headlines and Everything Else blocks can never re-surface a
    # duplicate that the formatter input already collapsed away. Both
    # render_other_headlines_for_section and build_everything_else skip
    # ids found in used_ids.
    used_ids = set(suppressed_ids or ())
    blocks   = re.split(r"\n## ", text)
    html     = ""

    for block in blocks:
        if not block.strip():
            continue

        lines = block.split("\n")
        title = lines[0].replace("## ", "").strip()

        if title.lower() == "everything else":
            continue

        emoji = SECTION_EMOJIS.get(title, "")

        if _is_today_in_the_world_section(title):
            display_title, display_emoji = _global_pickoff_display(is_design_edition)
            stories_html = _render_today_in_the_world(lines[1:], links_by_id, used_ids, palette)
            if not stories_html:
                continue
            html += (
                f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
                f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
                f'\n  <div style="padding:15px 15px 0">'
                f'\n    <p style="color:{palette["accent"]};margin:0 0 12px;font-size:13px;font-weight:700;'
                f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{display_emoji} {display_title}</p>'
                f'\n  </div>'
                f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
                f'\n</div>'
            )
            continue

        stories            = []
        current_story      = None
        in_discarded_block = False  # Claude shouldn't emit OH anymore; skip if it does.

        for line in lines[1:]:
            line = line.strip()

            if line.startswith("### "):
                # Any subheading from Claude (Other Headlines, etc.) is no longer
                # rendered from the model output; we synthesize OH below.
                in_discarded_block = True
                if current_story:
                    stories.append(current_story)
                    current_story = None
                continue

            if in_discarded_block:
                continue

            if line.startswith("**") and line.endswith("**") and "**" not in line[2:-2]:
                if current_story:
                    stories.append(current_story)
                headline_text, item_id = extract_id(line[2:-2])
                current_story = {"headline": headline_text, "id": item_id, "body": [], "source": "", "callout": ""}
            elif line.lower().startswith("source:") and current_story:
                current_story["source"] = line[7:].strip()
            elif re.match(r"^what this means for you:", line, re.IGNORECASE):
                callout = re.sub(r"^what this means for you:\s*", "", line, flags=re.IGNORECASE).strip()
                if current_story:
                    current_story["callout"] = callout
                elif stories:
                    stories[-1]["callout"] = callout
            elif current_story is not None:
                current_story["body"].append(line)

        if current_story:
            stories.append(current_story)

        # Other Headlines are synthesized below, after the render loop has
        # populated used_ids with featured-story IDs.

        stories_html = ""

        for i, s in enumerate(stories):
            border       = "" if i == len(stories) - 1 else f"border-bottom:1px solid {palette['divider']};padding-bottom:16px;margin-bottom:16px;"
            # find_article_data handles [#N] extraction itself; pass the raw headline.
            headline_for_lookup = s["headline"]
            if s.get("id") is not None:
                headline_for_lookup = f"{s['headline']} [#{s['id']}]"
            article_data = find_article_data(headline_for_lookup, links_by_id)
            article_link = article_data["link"]
            article_image= article_data["image"]
            if article_data["id"] is not None:
                used_ids.add(article_data["id"])

            stories_html += f'<div style="{border}">'

            if article_image:
                img_tag = (
                    f'<img src="{article_image}" alt="{s["headline"]}" '
                    f'style="width:100%;max-width:640px;height:200px;object-fit:cover;'
                    f'display:block;margin:0 0 12px;border-radius:8px">'
                )
                stories_html += (
                    f'<a href="{article_link}" style="text-decoration:none;display:block">{img_tag}</a>'
                    if article_link else img_tag
                )

            if s["headline"]:
                headline_inner = (
                    f'<a href="{article_link}" style="color:{palette["heading"]};text-decoration:none;">{s["headline"]}</a>'
                    if article_link else s["headline"]
                )
                stories_html += (
                    f'<p style="margin:0 0 8px;font-size:24px;font-weight:700;color:{palette["heading"]};'
                    f'line-height:26px;font-family:Helvetica,Arial,sans-serif">{headline_inner}</p>'
                )

            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs[:FEATURED_STORY_PARAGRAPH_CAP]:
                    rendered = _render_body_markdown(p, palette)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:{palette["body"]};'
                        f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
                    )

            cluster = clusters_by_item_id.get(article_data["id"]) if article_data["id"] is not None else None
            if cluster:
                primary_source = cluster.get("primary_source") or s["source"]
                also_in = cluster.get("also_in") or []
            else:
                primary_source = s["source"]
                also_in = []

            if primary_source:
                stories_html += (
                    f'<p style="margin:0 0 10px;font-size:12px;color:{palette["meta"]};'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'{render_source_line(primary_source, also_in, article_link, palette)}</p>'
                )

            if s["callout"]:
                stories_html += (
                    f'<div style="margin:10px 0 0;padding:12px 14px;background:{palette["callout_bg"]};'
                    f'border-left:3px solid {palette["accent"]};font-size:14px;line-height:20px;color:{palette["body"]};'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'<strong style="color:{palette["accent"]}">What this means for you:</strong> {s["callout"]}</div>'
                )

            stories_html += "</div>"

        oh_html = render_other_headlines_for_section(
            title, tiered_items, links_by_id, used_ids, palette,
            copy_by_id=oh_copy_by_id, collect=oh_collect,
        )
        stories_html += oh_html

        if not stories_html:
            continue

        html += (
            f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
            f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
            f'\n  <div style="padding:15px 15px 0">'
            f'\n    <p style="color:{palette["accent"]};margin:0 0 12px;font-size:13px;font-weight:700;'
            f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
            f'\n  </div>'
            f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
            f'\n</div>'
        )

    return html, used_ids


def pick_everything_else_emoji(title: str, source: str, used: set | None = None) -> str:
    """Pick the per-item emoji for an Everything Else entry.

    Resolution order:
      1. Case-insensitive keyword matches in EVERYTHING_ELSE_KEYWORD_EMOJIS,
         declared order.
      2. Exact match in EVERYTHING_ELSE_SOURCE_EMOJIS.
      3. EVERYTHING_ELSE_FALLBACK_POOL, in order.

    Every emoji within an Everything Else section must be unique. When
    `used` is provided, the first candidate not already in it wins. If
    every candidate collides (rare), the natural pick is returned anyway.
    """
    text = (title or "").lower()
    candidates: list[str] = []
    for pattern, emoji in EVERYTHING_ELSE_KEYWORD_EMOJIS:
        if re.search(pattern, text) and emoji not in candidates:
            candidates.append(emoji)
    source_emoji = EVERYTHING_ELSE_SOURCE_EMOJIS.get(source)
    if source_emoji and source_emoji not in candidates:
        candidates.append(source_emoji)
    for fallback in EVERYTHING_ELSE_FALLBACK_POOL:
        if fallback not in candidates:
            candidates.append(fallback)

    if used is None:
        return candidates[0]
    for c in candidates:
        if c not in used:
            return c
    return candidates[0]


def _select_everything_else(links_by_id, used_ids, tiered_items=None):
    """Pick and order the Everything Else items.

    Tier 1 overflow (items capped out of featured) ranks first, then tier 2
    overflow (capped out of Other Headlines), then tier 3. Items the triage
    dropped (tier 0) and items it never scored are excluded. Returns a list of
    (id, link_dict), capped at MAX_EVERYTHING_ELSE. Shared by the renderer and
    the copywriter so both operate on exactly the same items.
    """
    tiered_items = tiered_items or []

    # {id: (tier, composite_score)}
    rank_by_id: dict[int, tuple[int, int]] = {}
    for it in tiered_items:
        tier = it.get("tier", 0)
        if tier <= 0:
            continue
        rank_by_id[it["id"]] = (tier, _item_score(it.get("scores", {})))

    candidates = []
    for lid, l in links_by_id.items():
        if lid in used_ids:
            continue
        if lid not in rank_by_id:
            continue
        tier, score = rank_by_id[lid]
        candidates.append((tier, -score, lid, l))

    candidates.sort()  # tier asc, then score desc (because we stored -score)
    return [(lid, l) for _tier, _neg_score, lid, l in candidates[:MAX_EVERYTHING_ELSE]]


def _ee_anchor(text, link, palette):
    """Wrap text in the Everything Else item link style, or return it plain."""
    if not link:
        return text
    return (
        f'<a href="{link}" style="color:{palette["body"]};font-weight:700;'
        f'text-decoration:underline;text-decoration-color:{palette["accent"]};">'
        f'{text}</a>'
    )


def _everything_else_line(l, copy, palette):
    """Render the text of one Everything Else item.

    With LLM copy ({subject, blurb}), the subject becomes the hyperlink and the
    blurb flows from it as one sentence (Morning Brew "what else is brewing"
    style). Without copy, or if it is malformed, fall back to the legacy
    title-only rendering: first four words linked, the rest of the title plain.
    """
    copy = copy or {}
    subject = str(copy.get("subject", "")).strip()
    blurb = str(copy.get("blurb", "")).strip()
    if subject and blurb:
        # Subject is meant to be the literal opening of the blurb so the link
        # wraps it cleanly. If the model drifted, keep subject-first by linking
        # the subject and letting the blurb follow.
        rest = blurb[len(subject):] if blurb.startswith(subject) else " " + blurb
        return f"{_ee_anchor(subject, l.get('link'), palette)}{rest}"

    words = l["title"].split(" ")
    link_words = " ".join(words[:4])
    remaining = " ".join(words[4:])
    linked_part = _ee_anchor(link_words, l.get("link"), palette)
    return f"{linked_part} {remaining}" if remaining else linked_part


def write_subject_blurbs(items, sentences_by_id=None, client=None):
    """Ask Claude to write a subject + blurb for each short news item.

    Shared by Other Headlines and Everything Else. items: list of
    (id, link_dict). sentences_by_id ({id: int}) sets the per-item sentence
    target; defaults to 1 for any item not in the map. Returns
    {id: {"subject": str, "blurb": str}}. Any failure returns {} so the
    renderer falls back to its title-only copy. A bad API call must never
    break the send.
    """
    if not items:
        return {}

    sentences_by_id = sentences_by_id or {}
    payload = [
        {
            "id": lid,
            "title": l.get("title", ""),
            "snippet": l.get("snippet", ""),
            "source": l.get("source", ""),
            "sentences": sentences_by_id.get(lid, 1),
        }
        for lid, l in items
    ]
    try:
        client = client or anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=SUBJECT_BLURB_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        )
        cleaned = re.sub(
            r"^```(json)?\s*|\s*```$", "", message.content[0].text.strip(),
            flags=re.MULTILINE,
        )
        data = json.loads(cleaned)
    except Exception as e:  # noqa: BLE001 — any failure must degrade gracefully
        print(f"[subject_blurbs] copy generation failed ({e}); title-only fallback.", flush=True)
        return {}

    out: dict[int, dict] = {}
    for obj in data if isinstance(data, list) else []:
        try:
            lid = int(obj["id"])
        except (KeyError, ValueError, TypeError):
            continue
        subject = str(obj.get("subject", "")).strip()
        blurb = str(obj.get("blurb", "")).strip()
        if subject and blurb:
            out[lid] = {"subject": subject, "blurb": blurb}
    return out


def build_everything_else(links_by_id, used_ids, clusters_by_item_id=None,
                          tiered_items=None, palette: dict = LIGHT, copy_by_id=None,
                          images_by_id=None):
    """Render up to MAX_EVERYTHING_ELSE items globally, ranked by tier then score.

    copy_by_id ({id: {subject, blurb}}) supplies Morning-Brew-style written
    copy per item; items without an entry render title-only. Pass None to
    render every item title-only (used by offline tests).
    """
    top = _select_everything_else(links_by_id, used_ids, tiered_items)
    if not top:
        return ""

    copy_by_id = copy_by_id or {}
    images_by_id = images_by_id or {}
    items_html = ""
    used_emojis: set[str] = set()
    for lid, l in top:
        emoji = pick_everything_else_emoji(l.get("title", ""), l.get("source", ""), used_emojis)
        used_emojis.add(emoji)
        line = _everything_else_line(l, copy_by_id.get(lid), palette)
        cid = images_by_id.get(lid)
        if cid:
            items_html += (
                f'<table cellpadding="0" cellspacing="0" border="0" '
                f'style="width:100%;margin:0 0 14px"><tr>'
                f'<td valign="top" style="width:80px;padding-right:12px">'
                f'<img src="cid:{cid}" width="80" height="80" alt="" '
                f'style="display:block;width:80px;height:80px;object-fit:cover;'
                f'border-radius:8px"></td>'
                f'<td valign="top">'
                f'<p style="margin:0;line-height:22px;font-size:15px;color:{palette["body"]};'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<span style="margin-right:6px">{emoji}</span>{line}</p>'
                f'</td></tr></table>'
            )
        else:
            items_html += (
                f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:{palette["body"]};'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<span style="margin-right:6px">{emoji}</span>'
                f'{line}</p>'
            )

    return (
        f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid {palette["card_border"]};'
        f'overflow:hidden;background:{palette["card_bg"]};font-family:Helvetica,Arial,sans-serif">'
        f'\n  <div style="padding:15px 15px 0">'
        f'\n    <p style="color:{palette["accent"]};margin:0 0 14px;font-size:13px;font-weight:700;'
        f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        f'\n  </div>'
        f'\n  <div style="padding:0 15px 15px">{items_html}</div>'
        f'\n</div>'
    )


def parse_subject_line(claude_response):
    stripped = claude_response.lstrip()
    first_line, _, rest = stripped.partition("\n")
    if first_line.startswith("SUBJECT:"):
        return first_line[len("SUBJECT:"):].strip(), rest.lstrip()
    return None, claude_response


def build_email_html(claude_response, links_by_id, clusters_by_item_id=None, tiered_items=None, suppressed_ids=None, is_design_edition=False, blurb_writer=None, thumbnail_resolver=None):
    clusters_by_item_id = clusters_by_item_id or {}
    toronto_tz  = ZoneInfo("America/Toronto")
    now_toronto = datetime.now(toronto_tz)
    today_long  = now_toronto.strftime("%A, %B %-d, %Y")
    short_date  = now_toronto.strftime("%b %-d")

    c = DARK if is_design_edition else LIGHT

    parsed_subject, claude_response = parse_subject_line(claude_response)
    if parsed_subject:
        subject = f"{parsed_subject} · {short_date}"
    else:
        subject = f"Quite Frankly · {short_date}"

    if TEST_MODE:
        subject = f"[TEST] {subject}"

    # Pass 1 discovers which items surface: featured stories populate used_ids,
    # and oh_items collects the Other Headlines picks across every section.
    oh_items: list = []
    sections_html, used_ids = parse_and_render_sections(
        claude_response, links_by_id, clusters_by_item_id,
        tiered_items=tiered_items, suppressed_ids=suppressed_ids,
        is_design_edition=is_design_edition, palette=c, oh_collect=oh_items,
    )
    ee_items = _select_everything_else(links_by_id, used_ids, tiered_items)

    from config import EE_THUMB_CACHE_DIR
    ee_images = {}
    inline_images = []
    if thumbnail_resolver is not None and ee_items:
        assets = thumbnail_resolver(ee_items, cache_dir=EE_THUMB_CACHE_DIR)
        ee_images = {lid: a.cid for lid, a in assets.items()}
        inline_images = list(assets.values())

    # Write Morning-Brew-style subject + blurb copy for exactly the short items
    # that surfaced (Other Headlines + Everything Else), in one batched call.
    # Without a writer (offline tests), everything renders title-only.
    ee_copy = None
    if blurb_writer is not None:
        sentences_by_id = {lid: 1 for lid, _ in oh_items}
        sentences_by_id.update({lid: 2 for lid, _ in ee_items})
        blurb_copy = blurb_writer(oh_items + ee_items, sentences_by_id=sentences_by_id)
        oh_copy = {lid: blurb_copy[lid] for lid, _ in oh_items if lid in blurb_copy}
        ee_copy = {lid: blurb_copy[lid] for lid, _ in ee_items if lid in blurb_copy}
        if oh_copy:
            # Re-render sections with the Other Headlines copy in place.
            sections_html, used_ids = parse_and_render_sections(
                claude_response, links_by_id, clusters_by_item_id,
                tiered_items=tiered_items, suppressed_ids=suppressed_ids,
                is_design_edition=is_design_edition, palette=c, oh_copy_by_id=oh_copy,
            )
    everything_else_html    = build_everything_else(
        links_by_id, used_ids, clusters_by_item_id, tiered_items=tiered_items,
        palette=c, copy_by_id=ee_copy, images_by_id=ee_images,
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="{c['color_scheme']}">
<meta name="supported-color-schemes" content="{c['color_scheme']}"></head>
<body style="margin:0;padding:0;background:{c['page_bg']};color-scheme:{c['color_scheme']}">
<table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;background:{c['page_bg']}">
<tr><td style="padding:20px 10px">
<div style="max-width:670px;margin:0 auto">

  <div style="margin-bottom:10px;border-radius:15px;overflow:hidden;border:1px solid {c['card_border']};font-family:Helvetica,Arial,sans-serif">
    <div style="padding:16px 20px;border-bottom:1px solid {c['header_border']};background:{c['header_bg']};">
      <table border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;padding-right:10px;">
            <img src="https://quitefrank.co/wp-content/uploads/2021/03/favicon.svg" width="28" height="28" style="display:block;border-radius:50%;" alt="Quite Frankly">
          </td>
          <td style="vertical-align:middle;">
            <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:{c['header_text']};font-family:Helvetica,Arial,sans-serif">Quite Frankly</p>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:20px 20px 22px;background:{c['card_bg']};">
      <h1 style="margin:0 0 6px;font-size:26px;font-weight:700;color:{c['heading']};line-height:1.2;font-family:Helvetica,Arial,sans-serif">Here's what matters today.</h1>
      <p style="margin:0;font-size:13px;color:{c['meta_label']};font-family:Helvetica,Arial,sans-serif">{today_long}</p>
    </div>
  </div>

  {sections_html}
  {everything_else_html}

  <div style="margin-top:10px;border-radius:15px;overflow:hidden;background:{c['footer_bg']};font-family:Helvetica,Arial,sans-serif">
    <div style="padding:15px;font-size:12px;color:{c['footer_text']};text-align:center;line-height:20px">
      Generated daily by Quite Frankly &nbsp;·&nbsp; Sources: CBC, Globe and Mail, TechCrunch, UX Collective, BBC, Smashing Magazine, Yahoo Finance, Globe &amp; Mail Finance, r/toronto<br>
      <span style="font-size:11px">Quite Frankly &nbsp;·&nbsp; Toronto, Ontario</span>
    </div>
  </div>

</div>
</td></tr></table>
</body></html>"""

    return html, subject, inline_images


# ── Email Sending ──────────────────────────────────────────────────────────────

def build_email_message(html, subject, inline_images=None):
    """Build a multipart/related message: HTML plus inline CID images."""
    inline_images = inline_images or []
    root = MIMEMultipart("related")
    root["Subject"] = subject
    root["From"] = f"Quite Frankly <{SENDER}>"
    root["To"] = RECIPIENT

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html, "html"))
    root.attach(alt)

    for asset in inline_images:
        subtype = asset.mime.split("/", 1)[-1] if "/" in asset.mime else "png"
        img = MIMEImage(asset.data, _subtype=subtype)
        img.add_header("Content-ID", f"<{asset.cid}>")
        img.add_header("Content-Disposition", "inline")
        root.attach(img)

    return root


def send_email(html, subject, inline_images=None):
    gmail_user = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]
    msg = build_email_message(html, subject, inline_images)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())
    print(f"Sent: {subject}")
