import json
import os
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_feed_xml():
    return (FIXTURES / "sample_feed.xml").read_text()


@pytest.fixture
def sample_format_response():
    return (FIXTURES / "sample_format_response.md").read_text()


def _make_tool_use_block(tool_input: dict):
    block = type("ToolBlock", (), {})()
    block.type = "tool_use"
    block.name = "emit_triage"
    block.input = tool_input
    return block


def _make_text_block(text: str):
    block = type("TextBlock", (), {})()
    block.type = "text"
    block.text = text
    return block


@pytest.fixture
def fake_anthropic_client(monkeypatch, sample_format_response):
    triage_payload = json.loads((FIXTURES / "sample_triage_response.json").read_text())
    triage_tool_input = {
        "items": [
            {
                "id": it["id"],
                "tier": it["tier"],
                "section": it["section"],
                "cluster_id": it["cluster_id"],
                "cross_source_coverage": it["scores"]["cross_source_coverage"],
                "personal_relevance": it["scores"]["personal_relevance"],
                "section_fit": it["scores"]["section_fit"],
                "promotion_to_worth_knowing": it["promotion_to_worth_knowing"],
            }
            for it in triage_payload["items"]
        ],
        "clusters": triage_payload["clusters"],
    }

    class FakeMessage:
        def __init__(self, blocks):
            self.content = blocks

    triage_response = FakeMessage([_make_tool_use_block(triage_tool_input)])
    format_response = FakeMessage([_make_text_block(sample_format_response)])
    responses = iter([triage_response, format_response])

    class FakeMessages:
        def create(self, **kwargs):
            return next(responses)

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: FakeClient())
    return FakeClient()
