"""Tests for prompt loading."""


def test_personal_relevance_blurb_loads_and_strips_frontmatter():
    from prompts import PERSONAL_RELEVANCE_BLURB
    assert PERSONAL_RELEVANCE_BLURB, "PERSONAL_RELEVANCE_BLURB is empty"
    assert not PERSONAL_RELEVANCE_BLURB.startswith("---"), \
        "YAML frontmatter should be stripped before reaching Claude"
    assert PERSONAL_RELEVANCE_BLURB.startswith("# Personal Context")


def test_personal_relevance_blurb_contains_required_sections():
    from prompts import PERSONAL_RELEVANCE_BLURB
    # Each of these is load-bearing for triage scoring. Failure means the
    # canonical About Me/personal-context.md was edited in a way that drops
    # a section the triage prompt depends on.
    for section in [
        "## Who I am",
        "## Not elevated",
        "## Scoring guidance",
    ]:
        assert section in PERSONAL_RELEVANCE_BLURB, f"missing section: {section}"


def test_triage_system_prompt_includes_personal_relevance():
    from prompts import TRIAGE_SYSTEM_PROMPT, PERSONAL_RELEVANCE_BLURB
    assert PERSONAL_RELEVANCE_BLURB in TRIAGE_SYSTEM_PROMPT
