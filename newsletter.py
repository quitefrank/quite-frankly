#!/usr/bin/env python3
"""Quite Frankly daily newsletter entry point."""

import time
from contextlib import contextmanager
from datetime import datetime
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

from config import SECTION_MAP, TEST_MODE
from routing import Mode, get_mode, get_feeds_for_mode, is_design_mode
from pipeline import fetch_all_feeds, deduplicate, record_seen, assign_ids
from triage import apply_phase2_tier, call_triage, cap_items, enrich_cluster_metrics
from formatting import call_formatter, call_legacy_formatter, build_format_input, build_email_html, send_email, suppressed_cluster_ids, near_duplicate_ids, write_subject_blurbs
from images import resolve_ee_thumbnails


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
    suppressed_ids: set[int] = set()
    try:
        capped_items = cap_items(items)
        if len(capped_items) < len(items):
            print(f"Capped triage input from {len(items)} to {len(capped_items)} items", flush=True)
        with _stage("triage"):
            tiered_items, clusters = call_triage(capped_items)
        print(f"Triage returned {len(tiered_items)} scored items, {len(clusters)} clusters", flush=True)

        enrich_cluster_metrics(tiered_items, links_by_id)

        with _stage("phase2_tier"):
            apply_phase2_tier(tiered_items, links_by_id)
        print("Phase 2 tier reassignment complete.", flush=True)

        suppressed_ids = (
            suppressed_cluster_ids(tiered_items)
            | near_duplicate_ids(tiered_items, links_by_id)
        )
        if suppressed_ids:
            print(f"Cluster suppression: hiding {len(suppressed_ids)} duplicate item(s)", flush=True)

        with _stage("format"):
            format_input = build_format_input(tiered_items, clusters, links_by_id, suppressed_ids)
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
        html, subject, inline_images = build_email_html(
            format_raw, links_by_id, clusters_by_item_id,
            tiered_items=tiered_items, suppressed_ids=suppressed_ids,
            is_design_edition=is_design_mode(mode),
            blurb_writer=write_subject_blurbs,
            thumbnail_resolver=resolve_ee_thumbnails,
        )

    with _stage("send_email"):
        send_email(html, subject, inline_images)

    record_seen(items)

    print("Done.")


if __name__ == "__main__":
    main()
