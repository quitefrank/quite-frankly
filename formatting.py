"""Claude formatter call, HTML rendering, and email send."""

from __future__ import annotations

import json
import os
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import anthropic

from config import RECIPIENT, SECTION_EMOJIS, SECTION_MAP, SENDER, SOURCE_FAVICONS, TEST_MODE
from prompts import FORMAT_SYSTEM_PROMPT, LEGACY_FORMAT_SYSTEM_PROMPT


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


def _item_score(scores: dict) -> int:
    return (
        scores.get("cross_source_coverage", 0)
        + scores.get("personal_relevance", 0)
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "weak"), 0)
    )


def _collapse_by_cluster_within_section(items: list[dict]) -> list[dict]:
    """Keep one representative item per (section, cluster_id), highest score wins.

    Triage clusters by `cluster_id`, but every clustered item still flows through
    as its own dict. Without this collapse, a single underlying story with 2+
    items in the same section gets featured 2+ times. Items with empty
    cluster_id are never merged - that's the "no cluster known" signal.
    """
    best: dict[tuple[str, str], dict] = {}
    passthrough: list[dict] = []
    for item in items:
        cid = item.get("cluster_id") or ""
        section = item.get("section") or ""
        if not cid or not section:
            passthrough.append(item)
            continue
        key = (section, cid)
        current = best.get(key)
        if current is None or _item_score(item.get("scores", {})) > _item_score(current.get("scores", {})):
            best[key] = item
    return passthrough + list(best.values())


def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict]) -> str:
    # Build cluster_members from the UNCOLLAPSED tiered_items so siblings
    # surface every cluster member's URL — even ones that the within-section
    # collapse below removes from featuring. Order matters: collapse strips
    # duplicates from the same (section, cluster_id), but a Tech & AI story
    # might still want to link to a sibling Tech & AI item that lost the
    # collapse tiebreak. Building this map first preserves that visibility.
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

    # Within-section cluster collapse: triage clusters the same underlying
    # story into multiple feed items; without this, a single story can occupy
    # several featured slots in one section. Keep the highest-scored per
    # (section, cluster_id). Items with empty cluster_id pass through.
    tiered_items = _collapse_by_cluster_within_section(tiered_items)

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


# Layout C paragraph opener: a body paragraph starts with **<short cap>.**
LAYOUT_C_PARAGRAPH_RE = re.compile(r"^\*\*(?P<header>[^*]+)\*\*\s*(?P<rest>.*)$")


def _looks_like_longform(body_lines: list[str]) -> bool:
    """Body is longform if 2+ of its paragraphs start with **<short cap>.**"""
    joined = "\n".join(body_lines)
    paragraphs = [p.strip() for p in re.split(r"\n\n+", joined) if p.strip()]
    return sum(1 for p in paragraphs if LAYOUT_C_PARAGRAPH_RE.match(p)) >= 2


def _is_today_in_the_world_section(title: str) -> bool:
    return title.strip() == "Today in the World"


def render_source_line(primary_source: str, also_in: list[str], article_link: str | None) -> str:
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
            f'style="color:#1c7ff2;text-decoration:none;vertical-align:middle;font-size:12px;">{label}</a>'
        )
    return f'{img}<span style="vertical-align:middle;font-size:12px;color:#999;">{label}</span>'


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


def _render_body_markdown(text: str) -> str:
    """Convert [label](url) markdown links and **bold** markers to HTML.

    Both links and bold are converted so Claude's body output renders
    cleanly even if it emits stray bold (e.g., misformatted Layout C
    micro-headers that fell through to Layout B).
    """
    text = _MARKDOWN_LINK_RE.sub(
        lambda m: (
            f'<a href="{m.group(2)}" '
            f'style="color:#1c7ff2;text-decoration:underline;">{m.group(1)}</a>'
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


def render_other_headlines_for_section(section, tiered_items, links_by_id, used_ids):
    """Synthesize the Other Headlines subsection for one section.

    Picks the top MAX_OTHER_HEADLINES_PER_SECTION Tier 1 overflow and Tier 2
    items in this section whose IDs are not already in used_ids (i.e., not
    already featured), sorted by tier ascending then composite score desc so
    tier-1 overflow surfaces above tier-2. Adds the chosen IDs to used_ids so
    they don't duplicate in Everything Else.
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

    items_html = ""
    for lid in picked:
        used_ids.add(lid)
        l = links_by_id[lid]
        words = l["title"].split(" ")
        link_words = " ".join(words[:5])
        linked_part = (
            f'<a href="{l["link"]}" '
            f'style="color:#333;font-weight:400;text-decoration:underline;text-decoration-color:#1c7ff2;">'
            f"{link_words}</a>"
            if l.get("link") else link_words
        )
        summary = _first_sentence(l.get("snippet", ""))
        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">{linked_part}: {summary}</li>'
        )

    return (
        '<div style="margin-top:16px;padding-top:14px;border-top:1px solid #f0f0f0;">'
        '<p style="margin:0 0 8px;font-size:12px;font-weight:700;color:#888;'
        'font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.08em">Other Headlines</p>'
        f'<ul style="margin:0;padding-left:20px">{items_html}</ul>'
        "</div>"
    )


def _render_today_in_the_world(lines: list[str], links_by_id: dict, used_ids: set) -> str:
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
        bold_inner = f'{it["header"]}:'
        if href:
            bold = (
                f'<a href="{href}" style="color:#1a1a1a;text-decoration:none;">'
                f'<strong>{bold_inner}</strong></a>'
            )
        else:
            bold = f'<strong>{bold_inner}</strong>'
        rendered_body = _render_body_markdown(it["body"])
        items_html += (
            f'<p style="margin:0 0 14px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<span style="margin-right:6px">{it["emoji"]}</span>'
            f'{bold} {rendered_body}</p>'
        )

    return hero_image_html + items_html


def _render_from_the_front_page(story: dict, links_by_id: dict,
                                 clusters_by_item_id: dict, used_ids: set) -> str:
    """Render a single featured story as longform: hero image, headline,
    micro-headered paragraphs, source line, optional callout."""
    headline_for_lookup = story["headline"]
    if story.get("id") is not None:
        headline_for_lookup = f"{story['headline']} [#{story['id']}]"
    article_data = find_article_data(headline_for_lookup, links_by_id)
    article_link = article_data["link"]
    article_image = article_data["image"]
    if article_data["id"] is not None:
        used_ids.add(article_data["id"])

    out = '<div>'

    if article_image:
        img_tag = (
            f'<img src="{article_image}" alt="{story["headline"]}" '
            f'style="width:100%;max-width:640px;height:200px;object-fit:cover;'
            f'display:block;margin:0 0 12px;border-radius:8px">'
        )
        out += (
            f'<a href="{article_link}" style="text-decoration:none;display:block">{img_tag}</a>'
            if article_link else img_tag
        )

    if story["headline"]:
        headline_inner = (
            f'<a href="{article_link}" style="color:#1a1a1a;text-decoration:none;">{story["headline"]}</a>'
            if article_link else story["headline"]
        )
        out += (
            f'<p style="margin:0 0 8px;font-size:24px;font-weight:700;color:#1a1a1a;'
            f'line-height:26px;font-family:Helvetica,Arial,sans-serif">{headline_inner}</p>'
        )

    paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(story["body"])) if p.strip()]
    for p in paragraphs:
        m = LAYOUT_C_PARAGRAPH_RE.match(p)
        if m:
            header = m.group("header").strip()
            rest = _render_body_markdown(m.group("rest").strip())
            out += (
                f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                f'font-family:Helvetica,Arial,sans-serif">'
                f'<strong>{header}</strong> {rest}</p>'
            )
        else:
            rendered = _render_body_markdown(p)
            out += (
                f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                f'font-family:Helvetica,Arial,sans-serif">{rendered}</p>'
            )

    cluster = clusters_by_item_id.get(article_data["id"]) if article_data["id"] is not None else None
    if cluster:
        primary_source = cluster.get("primary_source") or story["source"]
        also_in = cluster.get("also_in") or []
    else:
        primary_source = story["source"]
        also_in = []

    if primary_source:
        out += (
            f'<p style="margin:0 0 10px;font-size:12px;color:#999;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'{render_source_line(primary_source, also_in, article_link)}</p>'
        )

    if story.get("callout"):
        out += (
            f'<div style="margin:10px 0 0;padding:12px 14px;background:#f0f4ff;'
            f'border-left:3px solid #1c7ff2;font-size:14px;line-height:20px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">'
            f'<strong style="color:#1c7ff2">What this means for you:</strong> {story["callout"]}</div>'
        )

    out += '</div>'
    return out


def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None, tiered_items=None):
    clusters_by_item_id = clusters_by_item_id or {}
    tiered_items = tiered_items or []
    used_ids = set()
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
            stories_html = _render_today_in_the_world(lines[1:], links_by_id, used_ids)
            if not stories_html:
                continue
            html += (
                f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
                f'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
                f'\n  <div style="padding:15px 15px 0">'
                f'\n    <p style="color:#1c7ff2;margin:0 0 12px;font-size:13px;font-weight:700;'
                f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
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

        # Synthesize Other Headlines from tier_2 items for this section now that
        # featured-story IDs have been gathered into used_ids.
        # Defer the actual call until after we've collected used_ids from stories.

        # From the Front Page longform: exactly one featured story whose
        # body uses **<header>.** paragraph openers.
        if len(stories) == 1 and _looks_like_longform(stories[0]["body"]):
            stories_html = _render_from_the_front_page(
                stories[0], links_by_id, clusters_by_item_id, used_ids
            )
            oh_html = render_other_headlines_for_section(title, tiered_items, links_by_id, used_ids)
            stories_html += oh_html
            if not stories_html:
                continue
            html += (
                f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
                f'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
                f'\n  <div style="padding:15px 15px 0">'
                f'\n    <p style="color:#1c7ff2;margin:0 0 12px;font-size:13px;font-weight:700;'
                f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
                f'\n  </div>'
                f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
                f'\n</div>'
            )
            continue

        stories_html = ""

        for i, s in enumerate(stories):
            border       = "" if i == len(stories) - 1 else "border-bottom:1px solid #f0f0f0;padding-bottom:16px;margin-bottom:16px;"
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
                    f'<a href="{article_link}" style="color:#1a1a1a;text-decoration:none;">{s["headline"]}</a>'
                    if article_link else s["headline"]
                )
                stories_html += (
                    f'<p style="margin:0 0 8px;font-size:24px;font-weight:700;color:#1a1a1a;'
                    f'line-height:26px;font-family:Helvetica,Arial,sans-serif">{headline_inner}</p>'
                )

            if s["body"]:
                paragraphs = [p.strip() for p in re.split(r"\n\n+", "\n".join(s["body"])) if p.strip()]
                for p in paragraphs:
                    rendered = _render_body_markdown(p)
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
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
                    f'<p style="margin:0 0 10px;font-size:12px;color:#999;'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'{render_source_line(primary_source, also_in, article_link)}</p>'
                )

            if s["callout"]:
                stories_html += (
                    f'<div style="margin:10px 0 0;padding:12px 14px;background:#f0f4ff;'
                    f'border-left:3px solid #1c7ff2;font-size:14px;line-height:20px;color:#333;'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'<strong style="color:#1c7ff2">What this means for you:</strong> {s["callout"]}</div>'
                )

            stories_html += "</div>"

        oh_html = render_other_headlines_for_section(title, tiered_items, links_by_id, used_ids)
        stories_html += oh_html

        if not stories_html:
            continue

        html += (
            f'\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
            f'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
            f'\n  <div style="padding:15px 15px 0">'
            f'\n    <p style="color:#1c7ff2;margin:0 0 12px;font-size:13px;font-weight:700;'
            f'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">{emoji} {title}</p>'
            f'\n  </div>'
            f'\n  <div style="padding:0 15px 15px">{stories_html}</div>'
            f'\n</div>'
        )

    return html, used_ids


def build_everything_else(links_by_id, used_ids, clusters_by_item_id=None, tiered_items=None):
    """Render up to MAX_EVERYTHING_ELSE items globally, ranked by tier then score.

    Tier 1 overflow (items capped out of featured) ranks first, then tier 2
    overflow (capped out of Other Headlines), then tier 3. Items the triage
    dropped (tier 0) and items it never scored are excluded.
    """
    clusters_by_item_id = clusters_by_item_id or {}
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
    top = candidates[:MAX_EVERYTHING_ELSE]
    if not top:
        return ""

    items_html = ""
    for _tier, _neg_score, _lid, l in top:
        words = l["title"].split(" ")
        link_words = " ".join(words[:4])
        remaining = " ".join(words[4:])
        linked_part = (
            f'<a href="{l["link"]}" style="color:#333;font-weight:400;'
            f'text-decoration:underline;text-decoration-color:#1c7ff2;">{link_words}</a>'
            if l["link"] else link_words
        )
        full_line = f"{linked_part} {remaining}" if remaining else linked_part
        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">{full_line}</li>'
        )

    return (
        '\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
        'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
        '\n  <div style="padding:15px 15px 0">'
        '\n    <p style="color:#1c7ff2;margin:0 0 4px;font-size:13px;font-weight:700;'
        'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        '\n  </div>'
        f'\n  <div style="padding:0 15px 15px"><ul style="margin:0;padding-left:20px">{items_html}</ul></div>'
        '\n</div>'
    )


def parse_subject_line(claude_response):
    stripped = claude_response.lstrip()
    first_line, _, rest = stripped.partition("\n")
    if first_line.startswith("SUBJECT:"):
        return first_line[len("SUBJECT:"):].strip(), rest.lstrip()
    return None, claude_response


def build_email_html(claude_response, links_by_id, clusters_by_item_id=None, tiered_items=None):
    clusters_by_item_id = clusters_by_item_id or {}
    toronto_tz  = ZoneInfo("America/Toronto")
    now_toronto = datetime.now(toronto_tz)
    today_long  = now_toronto.strftime("%A, %B %-d, %Y")
    short_date  = now_toronto.strftime("%b %-d")

    parsed_subject, claude_response = parse_subject_line(claude_response)
    if parsed_subject:
        subject = f"{parsed_subject} · {short_date}"
    else:
        subject = f"Quite Frankly · {short_date}"

    if TEST_MODE:
        subject = f"[TEST] {subject}"

    sections_html, used_ids = parse_and_render_sections(
        claude_response, links_by_id, clusters_by_item_id, tiered_items=tiered_items
    )
    everything_else_html    = build_everything_else(
        links_by_id, used_ids, clusters_by_item_id, tiered_items=tiered_items
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4">
<table border="0" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse;background:#f4f4f4">
<tr><td style="padding:20px 10px">
<div style="max-width:670px;margin:0 auto">

  <div style="margin-bottom:10px;border-radius:15px;overflow:hidden;border:1px solid #e6e6e6;font-family:Helvetica,Arial,sans-serif">
    <div style="padding:16px 20px;border-bottom:1px solid #222;background:#1f1f1f;">
      <table border="0" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;padding-right:10px;">
            <img src="https://quitefrank.co/wp-content/uploads/2021/03/favicon.svg" width="28" height="28" style="display:block;border-radius:50%;" alt="Quite Frankly">
          </td>
          <td style="vertical-align:middle;">
            <p style="margin:0;font-size:11px;font-weight:700;letter-spacing:0.12em;text-transform:uppercase;color:#fff;font-family:Helvetica,Arial,sans-serif">Quite Frankly</p>
          </td>
        </tr>
      </table>
    </div>
    <div style="padding:20px 20px 22px;background:#ffffff;">
      <h1 style="margin:0 0 6px;font-size:26px;font-weight:700;color:#1a1a1a;line-height:1.2;font-family:Helvetica,Arial,sans-serif">Here's what matters today.</h1>
      <p style="margin:0;font-size:13px;color:#888;font-family:Helvetica,Arial,sans-serif">{today_long}</p>
    </div>
  </div>

  {sections_html}
  {everything_else_html}

  <div style="margin-top:10px;border-radius:15px;overflow:hidden;background:#E9EBF7;font-family:Helvetica,Arial,sans-serif">
    <div style="padding:15px;font-size:12px;color:#79787d;text-align:center;line-height:20px">
      Generated daily by Quite Frankly &nbsp;·&nbsp; Sources: CBC, Globe and Mail, TechCrunch, UX Collective, BBC, Smashing Magazine, Yahoo Finance, Globe &amp; Mail Finance, r/toronto<br>
      <span style="font-size:11px">Quite Frankly &nbsp;·&nbsp; Toronto, Ontario</span>
    </div>
  </div>

</div>
</td></tr></table>
</body></html>"""

    return html, subject


# ── Email Sending ──────────────────────────────────────────────────────────────

def send_email(html, subject):
    gmail_user     = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Quite Frankly <{SENDER}>"
    msg["To"]      = RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(SENDER, RECIPIENT, msg.as_string())

    print(f"Sent: {subject}")
