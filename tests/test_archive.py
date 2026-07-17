import json
import archive
from config import FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL


def test_load_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "nope.json"))
    assert archive.load() == {}


def test_save_then_load_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE_FILE", str(tmp_path / "a.json"))
    archive.save({"k": {"title": "t"}})
    assert archive.load() == {"k": {"title": "t"}}


def test_design_feeds_and_source_sets_cover_all_nine():
    # DESIGN_FEEDS is the union of the two weekend feed sets.
    assert archive.DESIGN_FEEDS == FEEDS_SATURDAY_STRATEGIC + FEEDS_SUNDAY_VISUAL
    assert archive.STRATEGIC_SOURCES == {f["source"] for f in FEEDS_SATURDAY_STRATEGIC}
    assert archive.VISUAL_SOURCES == {f["source"] for f in FEEDS_SUNDAY_VISUAL}
    assert len(archive.STRATEGIC_SOURCES | archive.VISUAL_SOURCES) == 9
