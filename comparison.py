"""Phase 1.5 shadow scoring and comparison-log writing.

Runs after the production triage pass and email send. For each item, fetches
free traction signals from Reddit + HN, recomputes a Phase-2 tier with those
signals weighted in, and writes a daily `comparison/YYYY-MM-DD.json` capturing
what Phase 1 actually sent versus what Phase 2 would have promoted/demoted.

Failures are isolated: a Reddit outage, a single missing link, or a JSON write
error must not block the live email. The orchestrator wraps shadow_score in a
try/except for that reason.
"""

import json
from pathlib import Path

from config import REDDIT_SUBREDDITS
from traction import fetch_hn_traction, fetch_reddit_traction


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}


def compute_phase2_tier(item: dict) -> int:
    scores = item.get("scores", {})
    base = (
        scores.get("cross_source_coverage", 0) * 3
        + scores.get("personal_relevance", 0) * 2
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "none"), 0)
    )

    reddit = item.get("reddit", {})
    if reddit.get("score", 0) >= 1000 or reddit.get("subreddit_hits", 0) >= 2:
        reddit_bonus = 2
    elif reddit.get("score", 0) >= 200:
        reddit_bonus = 1
    else:
        reddit_bonus = 0

    hn = item.get("hn", {})
    hn_bonus = 1 if hn.get("points", 0) >= 200 else 0

    total = base + reddit_bonus + hn_bonus
    if total >= 6:
        return 1
    if total >= 3:
        return 2
    if total >= 1:
        return 3
    return 0


def attach_traction(items: list[dict], links_by_id: dict) -> list[dict]:
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        item["reddit"] = fetch_reddit_traction(link, REDDIT_SUBREDDITS)
        item["hn"] = fetch_hn_traction(link)
    return items


def shadow_score(items: list[dict], links_by_id: dict) -> list[dict]:
    enriched = attach_traction([dict(i) for i in items], links_by_id)
    for item in enriched:
        item["tier"] = compute_phase2_tier(item)
    return enriched


def build_comparison_log(date_str: str, mode: str, phase1: list[dict], phase2: list[dict]) -> dict:
    by_id_p1 = {i["id"]: i for i in phase1}
    by_id_p2 = {i["id"]: i for i in phase2}

    promoted = []
    demoted = []
    for item_id, p2 in by_id_p2.items():
        p1 = by_id_p1.get(item_id)
        if not p1:
            continue
        if p2["tier"] < p1["tier"] and p2["tier"] > 0:
            promoted.append({"id": item_id, "from": p1["tier"], "to": p2["tier"]})
        elif p2["tier"] > p1["tier"]:
            demoted.append({"id": item_id, "from": p1["tier"], "to": p2["tier"]})

    return {
        "date": date_str,
        "mode": mode,
        "phase1": phase1,
        "phase2_shadow": phase2,
        "deltas": {
            "promoted_by_phase2": promoted,
            "demoted_by_phase2": demoted,
        },
    }


def write_comparison_log(log: dict, base_dir: Path) -> None:
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    out = base_dir / f"{log['date']}.json"
    out.write_text(json.dumps(log, indent=2))
