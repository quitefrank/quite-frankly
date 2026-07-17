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
