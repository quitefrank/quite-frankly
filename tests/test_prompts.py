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


def test_triage_prompt_has_cross_cluster_entity_dedup_rule():
    # Two clusters covering different angles of the same protagonists
    # (e.g., a court-case story and a corporate-structure story both
    # starring Musk + Altman) should not both be featured: the lower-
    # scoring cluster is demoted one tier so the reader doesn't see
    # two "duplicate-feeling" stories across sections.
    from prompts import TRIAGE_SYSTEM_PROMPT
    prompt = TRIAGE_SYSTEM_PROMPT.lower()
    assert "dominant entities" in prompt, (
        "Triage prompt must define 'dominant entities' for cross-cluster dedup"
    )
    assert "demote" in prompt, (
        "Triage prompt must instruct the model to demote the weaker cluster"
    )
