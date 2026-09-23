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


def test_triage_prompt_does_not_ask_for_tier_or_coverage():
    # Removed 2026-09-22. apply_phase2_tier and enrich_cluster_metrics
    # overwrite tier and cross_source_coverage from traction and real cluster
    # membership, so every token the model spent on them was discarded. They
    # were ~35% of the per-item output payload and part of the June 8
    # truncation that shipped a blank edition.
    #
    # The cross-cluster entity dedup rule went with them: it demoted the
    # weaker of two clusters sharing 2+ protagonists, expressed entirely in
    # tiers, and that demotion was already being overwritten in production.
    # If that behaviour is wanted for real it belongs in code after
    # apply_phase2_tier, reading cluster canonical_headlines.
    from prompts import TRIAGE_SYSTEM_PROMPT
    prompt = TRIAGE_SYSTEM_PROMPT.lower()
    assert "tier mapping" not in prompt
    assert "cross_source_coverage" not in prompt
    assert "- tier (" not in prompt, "Triage must not be asked to emit a tier"


def test_triage_sections_drops_design_on_weekday():
    # Design & Product is the weekend edition's signature. On weekday editions
    # its feeds aren't fetched, so the only way an item lands there is the LLM
    # reclassifying a weekday source (Simon Willison writing about writing, say).
    # Dropping it from the weekday menu forces such items to their feed-origin
    # section instead.
    import config
    from prompts import TRIAGE_SECTIONS, triage_sections
    weekday = triage_sections(is_design_edition=False)
    assert "Design & Product" not in weekday
    # Every other section survives the gate untouched, in menu order. Tech & AI
    # is subject to its own park flag and is asserted separately below.
    expected = [s for s in TRIAGE_SECTIONS if s != "Design & Product"]
    if not config.TECH_AI_ENABLED:
        expected = [s for s in expected if s != "Tech & AI"]
    assert weekday == expected
    assert "Finance & Markets" in weekday


def test_triage_sections_is_design_only_on_weekend():
    # The mirror image of the weekday gate. Every weekend feed maps to
    # "Design & Product" in SECTION_MAP, so a news section can only reach a
    # design edition by reclassification — which is how a Sidebar link-blog
    # post about fake startup revenue rendered a Finance & Markets card on the
    # 2026-08-02 Sunday edition. Leaving the news sections off the weekend menu
    # forces every item back to its feed-origin section.
    from prompts import triage_sections
    assert triage_sections(is_design_edition=True) == ["Design & Product"]


def test_triage_sections_drops_tech_ai_when_parked(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", False)
    weekday = triage_sections(is_design_edition=False)
    assert "Tech & AI" not in weekday
    assert "Design & Product" not in weekday
    # The tech gate never touches the weekend menu, which is design-only.
    assert triage_sections(is_design_edition=True) == ["Design & Product"]


def test_triage_sections_restores_tech_ai_when_enabled(monkeypatch):
    import config
    from prompts import triage_sections
    monkeypatch.setattr(config, "TECH_AI_ENABLED", True)
    assert "Tech & AI" in triage_sections(is_design_edition=False)
    assert "Tech & AI" not in triage_sections(is_design_edition=True)


def test_build_triage_system_prompt_gates_sections_both_ways():
    from prompts import build_triage_system_prompt
    weekend = build_triage_system_prompt(is_design_edition=True)
    weekday = build_triage_system_prompt(is_design_edition=False)
    assert "Design & Product" in weekend
    assert "Design & Product" not in weekday
    # The weekend prompt must not offer a news section the model can defect to.
    for section in ("Canada & Toronto", "Toronto Housing", "Finance & Markets",
                    "US & Global", "Today in the World"):
        assert f'"{section}"' not in weekend, f"{section} leaked into the design-edition menu"
        assert f'"{section}"' in weekday


def test_triage_system_prompt_default_includes_design():
    # Back-compat: the module-level constant keeps all seven sections so any
    # caller that imports it directly (and the weekend path) is unchanged.
    from prompts import TRIAGE_SYSTEM_PROMPT
    assert "Design & Product" in TRIAGE_SYSTEM_PROMPT
