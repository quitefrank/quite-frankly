#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from comparison import build_comparison_log, shadow_score, write_comparison_log
from config import SECTION_MAP
from routing import get_mode, get_feeds_for_mode
from pipeline import fetch_all_feeds, deduplicate, assign_ids
from triage import call_triage, cap_items
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
    tiered_items = []
    try:
        capped_items = cap_items(items)
        if len(capped_items) < len(items):
            print(f"Capped triage input from {len(items)} to {len(capped_items)} items")
        print("Calling triage pass...")
        tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters")

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

    if tiered_items:
        print("Running Phase 1.5 shadow scoring...")
        try:
            phase2_items = shadow_score(tiered_items, links_by_id)
            log = build_comparison_log(
                date_str=today.isoformat(),
                mode=mode.value,
                phase1=tiered_items,
                phase2=phase2_items,
            )
            write_comparison_log(log, Path("comparison"))
            promoted = len(log["deltas"]["promoted_by_phase2"])
            demoted = len(log["deltas"]["demoted_by_phase2"])
            print(f"Wrote comparison/{today.isoformat()}.json (+{promoted} promoted, -{demoted} demoted)")
        except Exception as e:
            print(f"Shadow scoring failed: {e}")
    else:
        print("Skipping shadow scoring (no triage output).")

    print("Done.")


if __name__ == "__main__":
    main()
