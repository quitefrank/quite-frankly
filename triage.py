"""Pass-1 Claude triage: score, tier, and cluster items."""

from __future__ import annotations

import json
import os
import re

import anthropic

from prompts import TRIAGE_SYSTEM_PROMPT


def call_triage(headlines_text: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16000,
        system=TRIAGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": headlines_text}],
    )
    return message.content[0].text


def parse_triage_response(raw: str) -> tuple[list[dict], dict[str, dict]]:
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
    return "Here are today's headlines:\n\n" + "\n".join(lines)
