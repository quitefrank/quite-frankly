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


def test_triage_sections_gates_design_by_weekday():
    # Design & Product is the weekend edition's signature. On weekday editions
    # its feeds aren't fetched, so the only way an item lands there is the LLM
    # reclassifying a weekday source (Simon Willison writing about writing, say).
    # Dropping it from the weekday menu forces such items to their feed-origin
    # section instead.
    from prompts import triage_sections
    weekend = triage_sections(design_allowed=True)
    weekday = triage_sections(design_allowed=False)
    assert "Design & Product" in weekend
    assert "Design & Product" not in weekday
    # The other six sections survive the gate untouched.
    assert [s for s in weekend if s != "Design & Product"] == weekday


def test_triage_sections_drops_tech_ai_when_parked(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", False)
    weekend = triage_sections(design_allowed=True)
    weekday = triage_sections(design_allowed=False)
    assert "Tech & AI" not in weekend
    assert "Tech & AI" not in weekday
    # Design gate still composes on top of the tech gate.
    assert "Design & Product" in weekend
    assert "Design & Product" not in weekday


def test_triage_sections_restores_tech_ai_when_enabled(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", True)
    assert "Tech & AI" in triage_sections(design_allowed=True)
    assert "Tech & AI" in triage_sections(design_allowed=False)


def test_build_triage_system_prompt_omits_design_on_weekday():
    from prompts import build_triage_system_prompt
    assert "Design & Product" in build_triage_system_prompt(design_allowed=True)
    assert "Design & Product" not in build_triage_system_prompt(design_allowed=False)


def test_triage_system_prompt_default_includes_design():
    # Back-compat: the module-level constant keeps all seven sections so any
    # caller that imports it directly (and the weekend path) is unchanged.
    from prompts import TRIAGE_SYSTEM_PROMPT
    assert "Design & Product" in TRIAGE_SYSTEM_PROMPT
