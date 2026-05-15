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


@pytest.fixture
def fake_anthropic_client(monkeypatch, sample_format_response):
    triage_json = (FIXTURES / "sample_triage_response.json").read_text()
    responses = iter([triage_json, sample_format_response])

    class FakeMessage:
        def __init__(self, text):
            self.content = [type("Block", (), {"text": text})()]

    class FakeMessages:
        def create(self, **kwargs):
            return FakeMessage(next(responses))

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: FakeClient())
    return FakeClient()
