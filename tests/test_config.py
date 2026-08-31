import config
from config import _weekday_feeds, FEEDS_WEEKDAY

TECH_SOURCES = {"TechCrunch", "Hacker News", "Simon Willison", "Stratechery"}


def test_tech_feeds_excluded_when_parked():
    feeds = _weekday_feeds(tech_enabled=False)
    sources = {f["source"] for f in feeds}
    assert not (sources & TECH_SOURCES), "no tech source should be fetched when parked"
    # Non-tech weekday feeds survive untouched.
    assert "CBC" in sources
    assert "BBC" in sources
    assert "NYT The Daily" in sources


def test_tech_feeds_restored_when_enabled():
    feeds = _weekday_feeds(tech_enabled=True)
    sources = {f["source"] for f in feeds}
    assert TECH_SOURCES <= sources, "flipping the flag restores every tech feed"


def test_exported_feeds_reflect_default_flag():
    # FEEDS_WEEKDAY is composed once at import from the module-level flag.
    exported = {f["source"] for f in FEEDS_WEEKDAY}
    if config.TECH_AI_ENABLED:
        assert TECH_SOURCES <= exported
    else:
        assert not (exported & TECH_SOURCES)


# ---- doc.cc intake (Fix 4) ----

def test_doc_cc_feed_is_wired_into_saturday_strategic():
    from config import FEEDS_SATURDAY_STRATEGIC
    urls = [f["url"] for f in FEEDS_SATURDAY_STRATEGIC]
    assert any("doc.cc" in u for u in urls)


def test_doc_cc_feed_shares_the_ux_collective_source_name():
    """Folded under one source name so per-source caps treat them as one
    publisher instead of letting doc.cc dodge the cap as fake diversity."""
    from config import FEEDS_SATURDAY_STRATEGIC
    doc = [f for f in FEEDS_SATURDAY_STRATEGIC if "doc.cc" in f["url"]]
    assert doc and all(f["source"] == "UX Collective" for f in doc)
