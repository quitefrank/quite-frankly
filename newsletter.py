#!/usr/bin/env python3
"""
Quite Frankly - Daily Newsletter
Fetches RSS feeds, summarizes via Claude API, delivers to Gmail.
"""

import json
import os
import re
import smtplib
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import anthropic
import feedparser

# ── Config ─────────────────────────────────────────────────────────────────────

RECIPIENT = "suarez.milan@gmail.com"
SENDER = "frank@quitefrank.co"
SEEN_LINKS_FILE = "seen_links.json"
SEVEN_DAYS_S = 7 * 24 * 60 * 60

FEEDS = [
    {"url": "https://www.cbc.ca/cmlink/rss-canada-toronto",                                               "source": "CBC"},
    {"url": "https://www.theglobeandmail.com/arc/outboundfeeds/rss/category/canada/toronto/",             "source": "Globe & Mail"},
    {"url": "https://feeds.feedburner.com/TechCrunch",                                                    "source": "TechCrunch"},
    {"url": "https://uxdesign.cc/feed",                                                                   "source": "UX Collective"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                               "source": "BBC"},
    {"url": "https://www.smashingmagazine.com/feed/",                                                     "source": "Smashing Magazine"},
    {"url": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^IXIC&region=US&lang=en-US", "source": "Yahoo Finance"},
    {"url": "https://globeandmail.com/arc/outboundfeeds/rss/category/investing/",                         "source": "Globe & Mail Finance"},
    {"url": "https://www.reddit.com/r/toronto/top.rss?t=day",                                            "source": "r/toronto"},
    {"url": "https://www.reddit.com/r/canadahousing/top.rss?t=day",                                      "source": "r/canadahousing"},
]

SECTION_MAP = {
    "CBC":                 "Canada & Toronto",
    "Globe & Mail":        "Toronto Housing",
    "TechCrunch":          "Tech & AI",
    "UX Collective":       "Design & Product",
    "Smashing Magazine":   "Design & Product",
    "BBC":                 "US & Global",
    "Yahoo Finance":       "Finance & Markets",
    "Globe & Mail Finance":"Finance & Markets",
    "r/toronto":           "Canada & Toronto",
    "r/canadahousing":     "Toronto Housing",
}

SECTION_EMOJIS = {
    "Canada & Toronto": "🇨🇦",
    "Toronto Housing":  "🏠",
    "Tech & AI":        "💻",
    "Design & Product": "🎨",
    "Finance & Markets":"📈",
    "US & Global":      "🌍",
    "Everything Else":  "📋",
}

SOURCE_FAVICONS = {
    "CBC":                 "https://www.google.com/s2/favicons?domain=cbc.ca&sz=64",
    "Globe & Mail":        "https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "TechCrunch":          "https://www.google.com/s2/favicons?domain=techcrunch.com&sz=64",
    "UX Collective":       "https://www.google.com/s2/favicons?domain=uxdesign.cc&sz=64",
    "Smashing Magazine":   "https://www.google.com/s2/favicons?domain=smashingmagazine.com&sz=64",
    "BBC":                 "https://www.google.com/s2/favicons?domain=bbc.com&sz=64",
    "Yahoo Finance":       "https://www.google.com/s2/favicons?domain=finance.yahoo.com&sz=64",
    "Globe & Mail Finance":"https://www.google.com/s2/favicons?domain=theglobeandmail.com&sz=64",
    "r/toronto":           "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
    "r/canadahousing":     "https://www.google.com/s2/favicons?domain=reddit.com&sz=64",
}

SYSTEM_PROMPT = """You are a daily briefing editor. Follow this format exactly. Here is an example of one correctly formatted section:

## Canada & Toronto

**Ontario tables renter protection bill**
The Ford government introduced legislation Thursday that would cap above-guideline rent increases. The bill also aims to speed up Landlord and Tenant Board hearings. Advocates say the move is overdue given vacancy rates hitting a 10-year low in Toronto.

This is a significant development for renters across the province, particularly in Toronto where affordability has been a growing concern. The legislation is expected to face pushback from landlord associations who argue the caps will discourage new rental construction at a time when supply is critically needed.
Source: CBC

**TTC adds late night service for World Cup**
The TTC announced extended hours and express shuttles to handle World Cup crowds this summer. Service will run until 3am on match nights across key corridors. The city expects over 2 million visitors during the tournament.

The expanded service represents one of the largest single-event transit deployments in TTC history. Officials say the investment will also serve as a test case for permanent late-night service expansion that transit advocates have long demanded.
Source: CBC

Now write all 6 sections following this exact format. Each story must have a bold headline on its own line, then exactly 2 paragraphs of 3 to 4 sentences each, then Source: on its own line. The two paragraphs must be separated by a blank line. After each individual story in any section, if the story is relevant to Frank's life, add this on its own line:
What this means for you: [one specific sentence written directly to Frank, starting with You or with the subject of the insight, never starting with his name. Only include this if there is a genuine connection to his work as a product designer, his Leslieville condo, his investments, his freelance work, or his life in Toronto. Skip it if the story has no clear personal relevance.]

CRITICAL RULES YOU MUST FOLLOW:
1. Every headline in the provided list is pre-labelled with a section in brackets, for example [Canada & Toronto] or [Tech & AI]. You must place each story in the section that matches its label exactly. Never move a story to a different section.
2. For Canada & Toronto, Toronto Housing, Tech & AI, and Design & Product: write exactly 2 full stories per section. If fewer than 2 stories are labelled for a section, write only the ones available.
3. For Finance & Markets and US & Global: write exactly 1 full story per section. Then add an Other Headlines subsection with all remaining stories labelled for that section.
4. The Other Headlines subsection must follow this exact format:
### Other Headlines
- **First few words of headline**: one sentence summary of the story. Source: [source name]
5. Never reassign, promote, or recategorize any story. The section label is final.
6. Never invent stories. Use only the real headlines provided.

Write these 6 sections in this order:
## Canada & Toronto
## Toronto Housing
## Tech & AI
## Design & Product
## Finance & Markets
## US & Global

After all 6 sections, add a final section using exactly this format:

## Everything Else

- **First few words of headline**: one sentence summary of the story.

Include every headline from the provided list that was NOT used as a featured story or Other Headlines item in the 6 sections above. Include all of them, do not skip any."""


# ── RSS Fetching ───────────────────────────────────────────────────────────────

def extract_image(entry):
    if hasattr(entry, "media_content") and entry.media_content:
        for m in entry.media_content:
            url = m.get("url", "")
            if m.get("type", "").startswith("image") or url.lower().endswith(("jpg", "jpeg", "png", "webp")):
                return url

    if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
        return entry.media_thumbnail[0].get("url", "")

    if hasattr(entry, "enclosures") and entry.enclosures:
        for enc in entry.enclosures:
            if enc.get("type", "").startswith("image"):
                return enc.get("href", enc.get("url", ""))

    summary = getattr(entry, "summary", "") or ""
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)

    return ""


def fetch_feed(feed_config):
    items = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; QuiteFramkly/1.0)"}
        parsed = feedparser.parse(feed_config["url"], request_headers=headers)
        for entry in parsed.entries[:10]:
            link  = getattr(entry, "link",  "") or ""
            title = getattr(entry, "title", "") or ""
            summary = re.sub(r"<[^>]+>", "", getattr(entry, "summary", "") or "").strip()
            if title and link:
                items.append({
                    "title":   title,
                    "link":    link,
                    "snippet": summary[:300],
                    "image":   extract_image(entry),
                    "source":  feed_config["source"],
                })
    except Exception as e:
        print(f"  Error fetching {feed_config['source']}: {e}")
    return items


def fetch_all_feeds():
    all_items = []
    for feed_config in FEEDS:
        items = fetch_feed(feed_config)
        print(f"  {feed_config['source']}: {len(items)} items")
        all_items.extend(items)
        time.sleep(0.5)
    return all_items


# ── Deduplication ──────────────────────────────────────────────────────────────

def load_seen_links():
    if os.path.exists(SEEN_LINKS_FILE):
        with open(SEEN_LINKS_FILE) as f:
            return json.load(f)
    return {}


def save_seen_links(seen):
    with open(SEEN_LINKS_FILE, "w") as f:
        json.dump(seen, f, indent=2)


def deduplicate(items):
    seen = load_seen_links()
    now  = time.time()
    seen = {url: ts for url, ts in seen.items() if now - ts < SEVEN_DAYS_S}

    fresh = [i for i in items if i["link"] not in seen]

    if not fresh:
        print("  All items seen before - using full list (likely a test run)")
        fresh = items

    for item in fresh:
        seen[item["link"]] = now

    save_seen_links(seen)
    return fresh


# ── Claude API ─────────────────────────────────────────────────────────────────

def call_claude(headlines_text):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = (
        "Here are today's real headlines from my RSS feeds. Use ONLY these real stories:\n\n"
        + headlines_text
        + "\n\nGenerate my daily briefing following the exact format specified."
    )
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


# ── HTML Formatting ────────────────────────────────────────────────────────────

def source_with_favicon(source_name, article_link=None):
    favicon = SOURCE_FAVICONS.get(
        source_name,
        f"https://www.google.com/s2/favicons?domain={source_name}&sz=64",
    )
    img = (
        f'<img src="{favicon}" width="16" height="16" '
        f'style="width:16px;height:16px;vertical-align:middle;margin-right:4px;border-radius:3px;display:inline-block">'
    )
    if article_link:
        return (
            f'{img}<a href="{article_link}" '
            f'style="color:#1c7ff2;text-decoration:none;vertical-align:middle;font-size:12px;">{source_name}</a>'
        )
    return f'{img}<span style="vertical-align:middle;font-size:12px;color:#999;">{source_name}</span>'


def find_article_data(headline, links):
    h = headline.lower()[:30]
    for l in links:
        t = l["title"].lower()[:30]
        if h in l["title"].lower() or l["title"].lower()[:30] in h:
            return {"link": l["link"], "image": l["image"]}
    return {"link": None, "image": None}


def render_other_headlines(other_lines, links, used_headlines):
    items_html = ""
    for line in other_lines[:3]:
        cleaned = re.sub(r"^-\s*", "", line).strip()
        m = re.match(r"^\*\*(.*?)\*\*:?\s*(.*?)(?:\s*Source:\s*(.*))?$", cleaned)
        if not m:
            continue

        linked_words = m.group(1).strip()
        summary      = m.group(2).strip()
        lw_lower     = linked_words.lower()[:25]

        article_link_obj = next(
            (l for l in links if lw_lower in l["title"].lower() or l["title"].lower()[:25] in lw_lower),
            None,
        )

        used_headlines.add(linked_words.lower()[:40])
        if article_link_obj:
            used_headlines.add(article_link_obj["title"].lower()[:40])

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


def parse_and_render_sections(text, links):
    used_headlines = set()
    blocks = re.split(r"\n## ", text)
    html   = ""

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
                current_story = {"headline": line[2:-2], "body": [], "source": "", "callout": ""}
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

        stories_html = ""

        if not stories and not other_headline_lines:
            stories_html = (
                '<p style="margin:0;font-size:14px;color:#999;'
                'font-family:Helvetica,Arial,sans-serif;font-style:italic">No stories available today.</p>'
            )

        for i, s in enumerate(stories):
            border       = "" if i == len(stories) - 1 else "border-bottom:1px solid #f0f0f0;padding-bottom:16px;margin-bottom:16px;"
            article_data = find_article_data(s["headline"], links)
            article_link = article_data["link"]
            article_image= article_data["image"]

            used_headlines.add(s["headline"].lower()[:40])
            matched = next(
                (l for l in links if l["title"].lower()[:30] in s["headline"].lower()
                 or s["headline"].lower()[:30] in l["title"].lower()),
                None,
            )
            if matched:
                used_headlines.add(matched["title"].lower()[:40])

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

            if s["source"]:
                stories_html += (
                    f'<p style="margin:0 0 10px;font-size:12px;color:#999;'
                    f'font-family:Helvetica,Arial,sans-serif">'
                    f'{source_with_favicon(s["source"], article_link)}</p>'
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
            stories_html += render_other_headlines(other_headline_lines, links, used_headlines)

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

    return html, used_headlines


def build_everything_else(links, used_headlines):
    grouped = {}
    for l in links:
        title_key = l["title"].lower()[:40]
        is_used = any(
            title_key[:30] in used or used[:30] in title_key
            for used in used_headlines
        )
        if is_used:
            continue
        section = SECTION_MAP.get(l["source"], l["source"])
        grouped.setdefault(section, []).append(l)

    section_order = [
        "Canada & Toronto", "Toronto Housing", "Tech & AI",
        "Design & Product", "Finance & Markets", "US & Global",
    ]
    inner_html = ""

    for section in section_order:
        section_links = grouped.get(section, [])
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


def build_email_html(claude_response, links):
    toronto_tz  = ZoneInfo("America/Toronto")
    now_toronto = datetime.now(toronto_tz)
    today_long  = now_toronto.strftime("%A, %B %-d, %Y")
    subject_date= now_toronto.strftime("%a, %b %-d, %Y")
    subject     = f"Quite Frankly - {subject_date}"

    sections_html, used_headlines = parse_and_render_sections(claude_response, links)
    everything_else_html          = build_everything_else(links, used_headlines)

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


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("Fetching feeds...")
    all_items = fetch_all_feeds()
    print(f"Total raw items: {len(all_items)}")

    print("Deduplicating...")
    items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}")

    headlines = "\n".join(
        f"[{SECTION_MAP.get(i['source'], i['source'])}] {i['title']} | Source: {i['source']}"
        for i in items
    )

    links = [
        {"title": i["title"], "link": i["link"], "source": i["source"], "image": i["image"]}
        for i in items
    ]

    print("Calling Claude API...")
    claude_response = call_claude(headlines)

    print("Building HTML...")
    html, subject = build_email_html(claude_response, links)

    print("Sending email...")
    send_email(html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
