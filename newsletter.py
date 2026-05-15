#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

from config import SECTION_MAP
from pipeline import fetch_all_feeds, deduplicate
from formatting import call_formatter, build_email_html, send_email


def main():
    print("Fetching feeds...")
    all_items = fetch_all_feeds()
    print(f"Total raw items: {len(all_items)}")

    print("Deduplicating...")
    items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}")

    headlines = "\n".join(
        f"[#{idx}] [{SECTION_MAP.get(i['source'], i['source'])}] {i['title']} | Source: {i['source']}"
        for idx, i in enumerate(items)
    )
    links_by_id = {idx: i for idx, i in enumerate(items)}

    print("Calling Claude API...")
    claude_response = call_formatter(headlines)

    print("Building HTML...")
    html, subject = build_email_html(claude_response, links_by_id)

    print("Sending email...")
    send_email(html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
