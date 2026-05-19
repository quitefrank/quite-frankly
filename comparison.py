"""Phase 1.5 shadow scoring and comparison-log writing.

Runs after the production triage pass and email send. For each item, fetches
free traction signals from Reddit + HN, recomputes a Phase-2 tier with those
signals weighted in, and writes a daily `comparison/YYYY-MM-DD.json` capturing
what Phase 1 actually sent versus what Phase 2 would have promoted/demoted.

Failures are isolated: a Reddit outage, a single missing link, or a JSON write
error must not block the live email. The orchestrator wraps shadow_score in a
try/except for that reason.
"""

import html
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from config import REDDIT_SUBREDDITS
from traction import fetch_hn_traction, fetch_reddit_traction


# Reddit's anonymous rate limit is ~60 req/min. With 7 subreddits per item +
# 1 HN call, 5 concurrent workers keeps burst rate under that ceiling.
TRACTION_MAX_WORKERS = 5


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


def _attach_one(item: dict, link: str) -> None:
    item["reddit"] = fetch_reddit_traction(link, REDDIT_SUBREDDITS)
    item["hn"] = fetch_hn_traction(link)


def attach_traction(items: list[dict], links_by_id: dict) -> list[dict]:
    """Attach Reddit + HN traction to each item, in parallel across items.

    Each worker handles one item's full traction (7 subreddit searches + 1 HN
    query, ~800ms total). With TRACTION_MAX_WORKERS=5 the burst rate to
    Reddit stays under the anonymous 60 req/min ceiling.
    """
    work = []
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        work.append((item, link))
    if not work:
        return items
    with ThreadPoolExecutor(max_workers=TRACTION_MAX_WORKERS) as executor:
        list(executor.map(lambda pair: _attach_one(*pair), work))
    return items


def shadow_score(items: list[dict], links_by_id: dict) -> list[dict]:
    enriched = attach_traction([dict(i) for i in items], links_by_id)
    for item in enriched:
        item["tier"] = compute_phase2_tier(item)
    return enriched


def _delta_entry(item_id, p1, p2):
    return {
        "id": item_id,
        "from": p1["tier"],
        "to": p2["tier"],
        "headline": p1.get("headline", "") or p1.get("title", ""),
        "source": p1.get("source", ""),
        "section": p1.get("section", ""),
        "link": p1.get("link", ""),
    }


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
            promoted.append(_delta_entry(item_id, p1, p2))
        elif p2["tier"] > p1["tier"]:
            demoted.append(_delta_entry(item_id, p1, p2))

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


def summarize_week(comparison_dir: Path, week_start: str, week_end: str) -> dict:
    comparison_dir = Path(comparison_dir)
    start = date.fromisoformat(week_start)
    end = date.fromisoformat(week_end)

    promotions = 0
    demotions = 0
    promoted_samples: list[dict] = []
    demoted_samples: list[dict] = []
    days_with_data = 0

    d = start
    while d <= end:
        f = comparison_dir / f"{d.isoformat()}.json"
        if f.exists():
            days_with_data += 1
            log = json.loads(f.read_text())
            day_promoted = log.get("deltas", {}).get("promoted_by_phase2", [])
            day_demoted = log.get("deltas", {}).get("demoted_by_phase2", [])
            promotions += len(day_promoted)
            demotions += len(day_demoted)
            promoted_samples.extend(day_promoted)
            demoted_samples.extend(day_demoted)
        d += timedelta(days=1)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "days_with_data": days_with_data,
        "total_promotions": promotions,
        "total_demotions": demotions,
        "promoted_samples": promoted_samples[:5],
        "demoted_samples": demoted_samples[:5],
    }


def _render_sample(sample: dict) -> str:
    source = html.escape(sample.get("source") or "Unknown source")
    headline = html.escape(sample.get("headline") or f"Item #{sample.get('id', '?')}")
    link = sample.get("link") or ""
    tier_from = sample.get("from", "?")
    tier_to = sample.get("to", "?")
    headline_html = (
        f'<a href="{html.escape(link, quote=True)}" style="color:#1a73e8;text-decoration:none">{headline}</a>'
        if link else headline
    )
    return (
        f"<li><strong>{source}</strong> · {headline_html} "
        f"<span style='color:#888'>(tier {tier_from} → tier {tier_to})</span></li>"
    )


def build_weekly_digest_html(summary: dict) -> tuple[str, str]:
    subject = f"📊 Phase 2 shadow digest · week of {summary['week_start']}"
    days = summary.get("days_with_data", 0)
    promoted = summary.get("promoted_samples", [])
    demoted = summary.get("demoted_samples", [])

    if days == 0:
        body = f"""
            <p>Week of {summary['week_start']} to {summary['week_end']}. No comparison data yet.</p>
            <p>Shadow scoring writes the first log on the next weekday run. Check back next Sunday.</p>
        """
    else:
        promoted_block = (
            "<h3 style='margin-top:24px'>Top swap-ins (Phase 2 would have featured)</h3>"
            f"<ul>{''.join(_render_sample(s) for s in promoted)}</ul>"
            if promoted else ""
        )
        demoted_block = (
            "<h3 style='margin-top:24px'>Top swap-outs (Phase 2 would have demoted)</h3>"
            f"<ul>{''.join(_render_sample(s) for s in demoted)}</ul>"
            if demoted else ""
        )
        body = f"""
            <p>Week of {summary['week_start']} to {summary['week_end']}. Comparison data: {days} day(s).</p>
            <p>Phase 2 weighed Reddit and Hacker News traction on top of the existing scoring. If it had been live this week:</p>
            <ul>
              <li><strong>{summary['total_promotions']}</strong> items promoted to a higher tier.</li>
              <li><strong>{summary['total_demotions']}</strong> items demoted.</li>
            </ul>
            {promoted_block}
            {demoted_block}
            <p style="color:#888;font-size:13px;margin-top:32px">
              Decide whether to promote Phase 2 into production tier scoring after 2 to 3 weeks of this data.
            </p>
        """

    html = f"""<html><body style="font-family:Helvetica,Arial,sans-serif;padding:24px;max-width:640px;color:#222">
<h2 style="margin:0 0 8px 0">Phase 2 shadow evaluation</h2>
{body}
</body></html>"""
    return html, subject
