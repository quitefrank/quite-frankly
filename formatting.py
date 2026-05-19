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
    "Worth Knowing",
]


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}

MAX_FEATURED_PER_SECTION = 2


def _item_score(scores: dict) -> int:
    return (
        scores.get("cross_source_coverage", 0)
        + scores.get("personal_relevance", 0)
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "weak"), 0)
    )


def build_format_input(tiered_items: list[dict], clusters: dict[str, dict], links_by_id: dict[int, dict]) -> str:
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
        })

    for section_buckets in by_section.values():
        for bucket in section_buckets.values():
            bucket.sort(key=lambda x: x["_score"], reverse=True)

    for buckets in by_section.values():
        if buckets["tier_1"]:
            continue
        for fallback_tier in ("tier_2", "tier_3"):
            if buckets[fallback_tier]:
                buckets["tier_1"].append(buckets[fallback_tier].pop(0))
                break

    # Cap featured stories per section. Overflow leaves the JSON entirely;
    # build_everything_else picks them up because they're not in used_ids.
    for buckets in by_section.values():
        if len(buckets["tier_1"]) > MAX_FEATURED_PER_SECTION:
            buckets["tier_1"] = buckets["tier_1"][:MAX_FEATURED_PER_SECTION]

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


def render_other_headlines(other_lines, links_by_id, used_ids, clusters_by_item_id=None):
    clusters_by_item_id = clusters_by_item_id or {}
    items_html = ""
    for line in other_lines[:5]:
        cleaned = re.sub(r"^-\s*", "", line).strip()
        m = re.match(r"^\*\*(.*?)\*\*:?\s*(.*?)(?:\s*Source:\s*(.*))?$", cleaned)
        if not m:
            continue

        linked_words, item_id = extract_id(m.group(1).strip())
        summary               = m.group(2).strip()

        article_link_obj = None
        resolved_id      = None
        if item_id is not None and item_id in links_by_id:
            article_link_obj = links_by_id[item_id]
            resolved_id      = item_id
        else:
            lw_lower = linked_words.lower()[:25]
            for lid, l in links_by_id.items():
                tl = l["title"].lower()
                if lw_lower in tl or tl[:25] in lw_lower:
                    article_link_obj = l
                    resolved_id      = lid
                    break

        if resolved_id is not None:
            used_ids.add(resolved_id)

        if article_link_obj:
            linked_part = (
                f'<a href="{article_link_obj["link"]}" '
                f'style="color:#333;font-weight:400;text-decoration:underline;text-decoration-color:#1c7ff2;">'
                f"{linked_words}</a>"
            )
        else:
            linked_part = linked_words

        items_html += (
            f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:#333;'
            f'font-family:Helvetica,Arial,sans-serif">{linked_part}: {summary}</li>'
        )

    if not items_html:
        return ""

    return (
        '<div style="margin-top:16px;padding-top:14px;border-top:1px solid #f0f0f0;">'
        '<p style="margin:0 0 8px;font-size:12px;font-weight:700;color:#888;'
        'font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.08em">Other Headlines</p>'
        f'<ul style="margin:0;padding-left:20px">{items_html}</ul>'
        "</div>"
    )


def parse_and_render_sections(text, links_by_id, clusters_by_item_id=None):
    clusters_by_item_id = clusters_by_item_id or {}
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

        stories            = []
        current_story      = None
        other_headline_lines = []
        in_other_headlines = False

        for line in lines[1:]:
            line = line.strip()

            if line == "### Other Headlines":
                in_other_headlines = True
                if current_story:
                    stories.append(current_story)
                    current_story = None
                continue

            if in_other_headlines:
                if line.startswith("-"):
                    other_headline_lines.append(line)
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

        if not stories and not other_headline_lines:
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
                    stories_html += (
                        f'<p style="margin:0 0 12px;line-height:22px;font-size:15px;color:#333;'
                        f'font-family:Helvetica,Arial,sans-serif">{p}</p>'
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

        if other_headline_lines:
            stories_html += render_other_headlines(other_headline_lines, links_by_id, used_ids, clusters_by_item_id)

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


def build_everything_else(links_by_id, used_ids, clusters_by_item_id=None):
    clusters_by_item_id = clusters_by_item_id or {}
    grouped = {}
    for lid, l in links_by_id.items():
        if lid in used_ids:
            continue
        section = SECTION_MAP.get(l["source"], l["source"])
        grouped.setdefault(section, []).append(l)

    section_order = [
        "Canada & Toronto", "Toronto Housing", "Tech & AI",
        "Design & Product", "Finance & Markets", "US & Global",
    ]
    inner_html = ""

    for section in section_order:
        section_links = grouped.get(section, [])[:10]
        if not section_links:
            continue
        items = ""
        for l in section_links:
            words       = l["title"].split(" ")
            link_words  = " ".join(words[:4])
            remaining   = " ".join(words[4:])
            linked_part = (
                f'<a href="{l["link"]}" style="color:#333;font-weight:400;'
                f'text-decoration:underline;text-decoration-color:#1c7ff2;">{link_words}</a>'
                if l["link"] else link_words
            )
            full_line = f"{linked_part} {remaining}" if remaining else linked_part
            items += (
                f'<li style="margin-bottom:10px;line-height:22px;font-size:15px;color:#333;'
                f'font-family:Helvetica,Arial,sans-serif">{full_line}</li>'
            )
        inner_html += (
            f'\n    <p style="margin:16px 0 6px;font-size:13px;font-weight:700;color:#1a1a1a;'
            f'font-family:Helvetica,Arial,sans-serif;text-transform:uppercase;letter-spacing:0.05em">'
            f'{section}</p>'
            f'\n    <ul style="margin:0 0 8px;padding-left:20px">{items}</ul>'
        )

    if not inner_html:
        return ""

    return (
        '\n<div style="margin-bottom:10px;border-radius:15px;border:1px solid #e6e6e6;'
        'overflow:hidden;background:#fff;font-family:Helvetica,Arial,sans-serif">'
        '\n  <div style="padding:15px 15px 0">'
        '\n    <p style="color:#1c7ff2;margin:0 0 4px;font-size:13px;font-weight:700;'
        'letter-spacing:0.08em;text-transform:uppercase;line-height:22px">📋 Everything Else</p>'
        '\n  </div>'
        f'\n  <div style="padding:0 15px 15px">{inner_html}</div>'
        '\n</div>'
    )


def parse_subject_line(claude_response):
    stripped = claude_response.lstrip()
    first_line, _, rest = stripped.partition("\n")
    if first_line.startswith("SUBJECT:"):
        return first_line[len("SUBJECT:"):].strip(), rest.lstrip()
    return None, claude_response


def build_email_html(claude_response, links_by_id, clusters_by_item_id=None):
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

    sections_html, used_ids = parse_and_render_sections(claude_response, links_by_id, clusters_by_item_id)
    everything_else_html    = build_everything_else(links_by_id, used_ids, clusters_by_item_id)

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
