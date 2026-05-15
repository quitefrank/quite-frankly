#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

from datetime import datetime
from zoneinfo import ZoneInfo

from config import SECTION_MAP
from routing import get_mode, get_feeds_for_mode
from pipeline import fetch_all_feeds, deduplicate, assign_ids
from triage import call_triage, parse_triage_response, build_triage_user_message
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email


def main():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    mode = get_mode(today)
    print(f"Mode: {mode.value}")

    feeds = get_feeds_for_mode(mode)
    print("Fetching feeds...")
    all_items = fetch_all_feeds(feeds)
    print(f"Raw items: {len(all_items)}")

    items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}")

    for item in items:
        item["section_label"] = SECTION_MAP.get(item["source"], item["source"])

    links_by_id = assign_ids(items)

    clusters_by_item_id = {}
    try:
        print("Calling triage pass...")
        triage_user = build_triage_user_message(items)
        triage_raw = call_triage(triage_user)
        tiered_items, clusters = parse_triage_response(triage_raw)

        print("Calling format pass...")
        format_input = build_format_input(tiered_items, clusters, links_by_id)
        format_raw = call_formatter(format_input)

        clusters_by_item_id = {
            item["id"]: clusters.get(item["cluster_id"], {})
            for item in tiered_items
        }
    except Exception as e:
        print(f"Triage pipeline failed ({e}); falling back to single-pass format.")
        headlines = "\n".join(
            f"[#{i['id']}] [{i['section_label']}] {i['title']} | Source: {i['source']}"
            for i in items
        )
        format_raw = call_legacy_formatter(headlines)

    print("Building HTML...")
    html, subject = build_email_html(format_raw, links_by_id, clusters_by_item_id)

    print("Sending email...")
    send_email(html, subject)

    print("Done.")


if __name__ == "__main__":
    main()
