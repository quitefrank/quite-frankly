#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


@contextmanager
def _stage(name: str):
    """Print a `[stage] start` / `[stage] done in Xs` pair so the CI log
    reveals where time actually goes (without per-line `flush=True` noise)."""
    print(f"[{name}] start", flush=True)
    start = time.time()
    try:
        yield
    finally:
        print(f"[{name}] done in {time.time() - start:.1f}s", flush=True)

from comparison import (
    build_comparison_log,
    build_weekly_digest_html,
    shadow_score,
    summarize_week,
    write_comparison_log,
)
from config import SECTION_MAP
from routing import Mode, get_mode, get_feeds_for_mode
from pipeline import fetch_all_feeds, deduplicate, assign_ids
from triage import call_triage, cap_items
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email


def main():
    today = datetime.now(ZoneInfo("America/Toronto")).date()
    mode = get_mode(today)
    print(f"Mode: {mode.value}")

    feeds = get_feeds_for_mode(mode)
    with _stage("fetch_feeds"):
        all_items = fetch_all_feeds(feeds)
    print(f"Raw items: {len(all_items)}", flush=True)

    with _stage("deduplicate"):
        items = deduplicate(all_items)
    print(f"Fresh items: {len(items)}", flush=True)

    for item in items:
        item["section_label"] = SECTION_MAP.get(item["source"], item["source"])

    links_by_id = assign_ids(items)

    clusters_by_item_id = {}
    tiered_items = []
    try:
        capped_items = cap_items(items)
        if len(capped_items) < len(items):
            print(f"Capped triage input from {len(items)} to {len(capped_items)} items", flush=True)
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        with _stage("format"):
            format_input = build_format_input(tiered_items, clusters, links_by_id)
            format_raw = call_formatter(format_input)

        clusters_by_item_id = {
            item["id"]: clusters.get(item["cluster_id"], {})
            for item in tiered_items
        }
    except Exception as e:
        print(f"Triage pipeline failed ({e}); falling back to single-pass format.", flush=True)
        headlines = "\n".join(
            f"[#{i['id']}] [{i['section_label']}] {i['title']} | Source: {i['source']}"
            for i in items
        )
        with _stage("format_legacy"):
            format_raw = call_legacy_formatter(headlines)

    with _stage("build_html"):
        html, subject = build_email_html(format_raw, links_by_id, clusters_by_item_id, tiered_items=tiered_items)

    with _stage("send_email"):
        send_email(html, subject)

    if tiered_items:
        print("Running Phase 1.5 shadow scoring...", flush=True)
        try:
            for t in tiered_items:
                src = links_by_id.get(t["id"], {})
                t["headline"] = src.get("title", "")
                t["source"] = src.get("source", "")
                t["link"] = src.get("link", "")
            with _stage("shadow_score"):
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

    if mode == Mode.SUNDAY_VISUAL:
        print("Sending weekly Phase 2 shadow digest...")
        try:
            week_start = (today - timedelta(days=6)).isoformat()
            week_end = today.isoformat()
            summary = summarize_week(Path("comparison"), week_start, week_end)
            digest_html, digest_subject = build_weekly_digest_html(summary)
            send_email(digest_html, digest_subject)
            print(
                f"Digest: {summary['total_promotions']} promotions, "
                f"{summary['total_demotions']} demotions, "
                f"{summary['days_with_data']} day(s) of data"
            )
        except Exception as e:
            print(f"Weekly digest failed: {e}")

    print("Done.")


if __name__ == "__main__":
    main()
