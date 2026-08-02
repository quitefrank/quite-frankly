"""Pass-1 Claude triage: score, tier, and cluster items.

Uses Anthropic tool-use structured output so the model cannot return
items missing required fields. Falls back to JSON parsing if tool use
isn't available on the chosen model.
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

import anthropic

from config import REDDIT_SUBREDDITS
from prompts import build_triage_system_prompt, triage_sections
from traction import fetch_hn_traction, fetch_reddit_traction


MAX_TRIAGE_INPUT_ITEMS = 120


def build_triage_tool(is_design_edition: bool = True) -> dict:
    """The triage structured-output tool. The section enum is the hard gate:
    a section the model cannot emit is a section that cannot render. It gates
    both ways — weekday editions drop "Design & Product", design editions drop
    the six news sections — so an item the model wants to reclassify falls back
    to its feed-origin section instead. See prompts.triage_sections."""
    return {
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
                                "enum": triage_sections(is_design_edition),
                            },
                            "cluster_id": {"type": "string"},
                            "cross_source_coverage": {"type": "integer", "minimum": 1},
                            "personal_relevance": {"type": "integer", "minimum": 0, "maximum": 3},
                            "section_fit": {"type": "string", "enum": ["good", "weak", "none"]},
                        },
                        "required": ["id", "tier", "section", "cluster_id", "cross_source_coverage", "personal_relevance", "section_fit"],
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


# Back-compat constant for direct importers. call_triage builds its own tool
# per edition, so nothing in the pipeline reads this.
TRIAGE_TOOL = build_triage_tool()


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


def call_triage(items: list[dict], is_design_edition: bool = True) -> tuple[list[dict], dict[str, dict]]:
    """Run the triage pass and return (tiered_items, clusters_by_id).

    Uses tool-use structured output so required fields are guaranteed.

    is_design_edition selects the section menu the model may assign from. Pass
    False on weekday editions (the design feeds aren't fetched, so a stray
    weekday source shouldn't be reclassified into a thin one-item design
    section) and True on weekend editions (the pool is design feeds only, so a
    news section can only appear by reclassification).
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_message = build_triage_user_message(items)
    # Stream the response. At max_tokens=32000 the SDK refuses a non-streaming
    # request ("Streaming is required for operations that may take longer than
    # 10 minutes"), which silently dropped triage into the legacy fallback and
    # shipped editions with no Everything Else. get_final_message() reassembles
    # the same Message (tool_use included) the interpreter expects.
    with client.messages.stream(
        model="claude-sonnet-4-6",
        # 32k (up from 16k) buys headroom now that the og:description snippet
        # backfill makes the prompt denser. A full 120-item weekday load plus
        # its clusters can approach the old ceiling; truncation there returned
        # an empty tool call and shipped a blank edition (the June 8 incident).
        max_tokens=32000,
        system=build_triage_system_prompt(is_design_edition),
        tools=[build_triage_tool(is_design_edition)],
        tool_choice={"type": "tool", "name": "emit_triage"},
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        message = stream.get_final_message()
    return _interpret_triage_message(message, input_count=len(items))


def _interpret_triage_message(message, input_count: int) -> tuple[list[dict], dict[str, dict]]:
    """Turn the raw API message into (tiered_items, clusters_by_id).

    Raises RuntimeError (which newsletter.py catches to fall back to the legacy
    single-pass formatter) when:
      - the emit_triage tool call is absent, or
      - triage returns zero usable items for a non-empty input. An empty result
        is only legitimate when nothing was sent in; a 120-in/0-out result means
        the model truncated or derailed, and shipping it produces a blank
        "No major stories today" edition. The stop_reason is surfaced so a
        max_tokens truncation is visible in the CI log.
    """
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_triage":
            items, clusters = _shape_tool_output(block.input)
            if input_count > 0 and not items:
                stop = getattr(message, "stop_reason", None)
                raise RuntimeError(
                    f"Triage returned 0 items for {input_count} input item(s) "
                    f"(stop_reason={stop}); falling back to legacy formatter"
                )
            return items, clusters
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
        })
    if dropped:
        print(f"  Triage: dropped {dropped} malformed item(s) from tool output")
    if raw_items and not items:
        raise RuntimeError(
            f"Triage returned {len(raw_items)} items, all malformed; "
            "falling back to legacy formatter"
        )
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
        snippet = (i.get("snippet") or "").strip()
        # The snippet is the only place differently-worded headlines about
        # the same story share vocabulary (the same people, company, event),
        # so it's what lets triage cluster cross-publisher duplicates. Cap at
        # 200 chars to keep the prompt tractable across ~120 items.
        snippet_part = f" — {snippet[:200]}" if snippet else ""
        lines.append(
            f"[#{i['id']}] [{i.get('section_label', '?')}] {i['title']} "
            f"| Source: {i['source']}{snippet_part}"
        )
    return "Here are today's headlines. Call emit_triage with one entry per item:\n\n" + "\n".join(lines)


# ---- Phase 2 traction-aware tier scoring ----

# Reddit's anonymous rate limit is ~60 req/min. With up to 7 subreddits per
# item + 1 HN call, 5 concurrent workers keeps burst rate under that ceiling.
# (Weekend design editions search the 6-entry DESIGN_SUBREDDITS, strictly fewer.)
TRACTION_MAX_WORKERS = 5


SECTION_FIT_SCORE = {"good": 1, "weak": 0, "none": -1}


def reddit_bonus(reddit: dict) -> int:
    if reddit.get("score", 0) >= 1000 or reddit.get("subreddit_hits", 0) >= 2:
        return 2
    if reddit.get("score", 0) >= 200:
        return 1
    return 0


def hn_bonus(hn: dict) -> int:
    return 1 if hn.get("points", 0) >= 200 else 0


def compute_phase2_tier(item: dict) -> int:
    scores = item.get("scores", {})
    base = (
        scores.get("cross_source_coverage", 0) * 3
        + scores.get("personal_relevance", 0) * 2
        + SECTION_FIT_SCORE.get(scores.get("section_fit", "none"), 0)
    )
    total = base + reddit_bonus(item.get("reddit", {})) + hn_bonus(item.get("hn", {}))
    if total >= 6:
        return 1
    if total >= 3:
        return 2
    if total >= 1:
        return 3
    return 0


def _attach_one(item: dict, link: str, subreddits: list) -> None:
    item["reddit"] = fetch_reddit_traction(link, subreddits)
    item["hn"] = fetch_hn_traction(link)


def attach_traction(items: list[dict], links_by_id: dict, subreddits: list = None) -> list[dict]:
    """Attach Reddit + HN traction to each item, in parallel across items.

    Each worker handles one item's full traction (one search per configured
    subreddit + 1 HN query, ~800ms total). With TRACTION_MAX_WORKERS=5 the burst rate to
    Reddit stays under the anonymous 60 req/min ceiling.
    """
    subreddits = subreddits if subreddits is not None else REDDIT_SUBREDDITS
    work = []
    for item in items:
        link = links_by_id.get(item["id"], {}).get("link", "")
        if not link:
            continue
        work.append((item, link))
    if not work:
        return items
    with ThreadPoolExecutor(max_workers=TRACTION_MAX_WORKERS) as executor:
        list(executor.map(lambda pair: _attach_one(pair[0], pair[1], subreddits), work))
    return items


def apply_phase2_tier(items: list[dict], links_by_id: dict, design_edition: bool = False) -> list[dict]:
    """Overwrite each item's tier using the Phase 2 traction-aware formula.

    Mutates items in place. If the Reddit/HN fetch raises (network outage,
    library error), log and return items unchanged so the email still ships
    with Claude's original tier assignments.
    """
    from config import DESIGN_SUBREDDITS
    subreddits = DESIGN_SUBREDDITS if design_edition else REDDIT_SUBREDDITS
    try:
        attach_traction(items, links_by_id, subreddits)
    except Exception as e:
        print(f"  Phase 2: attach_traction failed ({e}); keeping Claude tiers.", flush=True)
        return items
    for item in items:
        item["tier"] = compute_phase2_tier(item)
    return items


def enrich_cluster_metrics(items: list[dict], links_by_id: dict) -> list[dict]:
    """Set each item's cluster_size and cross_source_coverage from real cluster
    membership, replacing the LLM's self-reported cross_source_coverage guess.

    cluster_size = number of items sharing the cluster_id.
    cross_source_coverage = number of DISTINCT sources in the cluster (min 1).
    Items with an empty cluster_id are singletons (size 1, coverage 1).

    Mutates items in place. MUST run after call_triage and before
    apply_phase2_tier, so compute_phase2_tier reads the corrected coverage
    (which it weights x3) instead of the model's estimate.
    """
    by_cluster: dict[str, list[dict]] = {}
    for it in items:
        cid = it.get("cluster_id") or ""
        if not cid:
            it["cluster_size"] = 1
            it.setdefault("scores", {})["cross_source_coverage"] = 1
            continue
        by_cluster.setdefault(cid, []).append(it)
    for members in by_cluster.values():
        size = len(members)
        sources = {
            links_by_id.get(m["id"], {}).get("source", "") for m in members
        }
        sources.discard("")
        coverage = max(len(sources), 1)
        for it in members:
            it["cluster_size"] = size
            it.setdefault("scores", {})["cross_source_coverage"] = coverage
    return items
