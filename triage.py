"""Pass-1 Claude triage: score, tier, and cluster items.

Uses Anthropic tool-use structured output so the model cannot return
items missing required fields. Falls back to JSON parsing if tool use
isn't available on the chosen model.
"""

from __future__ import annotations

import json
import os
import re

import anthropic

from prompts import TRIAGE_SYSTEM_PROMPT


MAX_TRIAGE_INPUT_ITEMS = 120


TRIAGE_TOOL = {
    "name": "emit_triage",
    "description": "Emit the full triage result for today's headlines. Every input item must appear exactly once in 'items'.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "The exact [#N] id from the input headline."},
                        "tier": {"type": "integer", "enum": [0, 1, 2, 3]},
                        "section": {
                            "type": "string",
                            "enum": [
                                "Canada & Toronto",
                                "Toronto Housing",
                                "Tech & AI",
                                "Design & Product",
                                "Finance & Markets",
                                "US & Global",
                                "Today in the World",
                            ],
                        },
                        "cluster_id": {"type": "string"},
                        "cross_source_coverage": {"type": "integer", "minimum": 1},
                        "personal_relevance": {"type": "integer", "minimum": 0, "maximum": 3},
                        "section_fit": {"type": "string", "enum": ["good", "weak", "none"]},
                        "promotion_to_today_in_the_world": {"type": "boolean"},
                    },
                    "required": ["id", "tier", "section", "cluster_id", "cross_source_coverage", "personal_relevance", "section_fit", "promotion_to_today_in_the_world"],
                },
            },
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "primary_source": {"type": "string"},
                        "also_in": {"type": "array", "items": {"type": "string"}},
                        "canonical_headline": {"type": "string"},
                    },
                    "required": ["id", "primary_source", "also_in", "canonical_headline"],
                },
            },
        },
        "required": ["items", "clusters"],
    },
}


def cap_items(items: list[dict], cap: int = MAX_TRIAGE_INPUT_ITEMS) -> list[dict]:
    """Limit items going into triage to keep the output schema tractable.

    Round-robins by source so no single high-volume feed crowds out everyone.
    """
    if len(items) <= cap:
        return items
    by_source: dict[str, list[dict]] = {}
    for item in items:
        by_source.setdefault(item["source"], []).append(item)
    queues = list(by_source.values())
    out: list[dict] = []
    idx = 0
    while len(out) < cap and any(queues):
        q = queues[idx % len(queues)]
        if q:
            out.append(q.pop(0))
        idx += 1
        if all(not q for q in queues):
            break
    return out[:cap]


def call_triage(items: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Run the triage pass and return (tiered_items, clusters_by_id).

    Uses tool-use structured output so required fields are guaranteed.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = build_triage_user_message(items)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        system=TRIAGE_SYSTEM_PROMPT,
        tools=[TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "emit_triage"},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_triage":
            return _shape_tool_output(block.input)
    raise RuntimeError("Triage tool call missing from response")


def _shape_tool_output(payload: dict) -> tuple[list[dict], dict[str, dict]]:
    raw_items = payload.get("items", [])
    raw_clusters = payload.get("clusters", [])
    items: list[dict] = []
    dropped = 0
    for it in raw_items:
        if "id" not in it or "tier" not in it or "section" not in it:
            dropped += 1
            continue
        items.append({
            "id": it["id"],
            "tier": it["tier"],
            "section": it["section"],
            "cluster_id": it.get("cluster_id", ""),
            "scores": {
                "cross_source_coverage": it.get("cross_source_coverage", 1),
                "personal_relevance": it.get("personal_relevance", 0),
                "section_fit": it.get("section_fit", "weak"),
            },
            "promotion_to_today_in_the_world": it.get("promotion_to_today_in_the_world", False),
        })
    if dropped:
        print(f"  Triage: dropped {dropped} malformed item(s) from tool output")
    clusters = {c["id"]: c for c in raw_clusters if "id" in c}
    return items, clusters


def parse_triage_response(raw: str) -> tuple[list[dict], dict[str, dict]]:
    """Legacy text-JSON parser, kept for tests. Production uses call_triage."""
    cleaned = re.sub(r"^```(json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE)
    data = json.loads(cleaned)
    items = data.get("items", [])
    clusters_list = data.get("clusters", [])
    clusters = {c["id"]: c for c in clusters_list}
    return items, clusters


def select_items_by_tier(items: list[dict], tier: int) -> list[dict]:
    return [i for i in items if i.get("tier") == tier]


def build_triage_user_message(items: list[dict]) -> str:
    lines = []
    for i in items:
        lines.append(f"[#{i['id']}] [{i.get('section_label', '?')}] {i['title']} | Source: {i['source']}")
    return "Here are today's headlines. Call emit_triage with one entry per item:\n\n" + "\n".join(lines)


# ---- Phase 2 traction-aware tier scoring ----

from concurrent.futures import ThreadPoolExecutor

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
