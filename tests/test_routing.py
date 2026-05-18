from datetime import date
from routing import Mode, get_mode, get_feeds_for_mode


def test_monday_is_weekend_catchup():
    assert get_mode(date(2026, 5, 18)) == Mode.MONDAY_CATCHUP


def test_tuesday_through_friday_is_daily():
    for d in [date(2026, 5, 19), date(2026, 5, 20), date(2026, 5, 21), date(2026, 5, 22)]:
        assert get_mode(d) == Mode.WEEKDAY_DAILY


def test_saturday_is_strategic_design():
    assert get_mode(date(2026, 5, 23)) == Mode.SATURDAY_STRATEGIC


def test_sunday_is_visual_design():
    assert get_mode(date(2026, 5, 24)) == Mode.SUNDAY_VISUAL


def test_weekday_pool_excludes_design_feeds():
    feeds = get_feeds_for_mode(Mode.WEEKDAY_DAILY)
    sources = [f["source"] for f in feeds]
    assert "Design Milk" not in sources
    assert "Hypebeast" not in sources
    assert "UX Collective" not in sources


def test_saturday_pool_is_strategic_design_only():
    feeds = get_feeds_for_mode(Mode.SATURDAY_STRATEGIC)
    sources = [f["source"] for f in feeds]
    assert "UX Collective" in sources
    assert "Lenny's Newsletter" in sources
    assert "Hypebeast" not in sources
    assert "CBC" not in sources


def test_sunday_pool_is_visual_design_only():
    feeds = get_feeds_for_mode(Mode.SUNDAY_VISUAL)
    sources = [f["source"] for f in feeds]
    assert "Design Milk" in sources
    assert "Codrops" in sources
    assert "Lenny's Newsletter" not in sources
