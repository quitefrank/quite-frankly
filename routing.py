"""Day-of-week routing for newsletter modes."""

from __future__ import annotations

from datetime import date
from enum import Enum

from config import FEEDS_WEEKDAY, FEEDS_SATURDAY_STRATEGIC, FEEDS_SUNDAY_VISUAL


class Mode(Enum):
    MONDAY_CATCHUP = "monday_catchup"
    WEEKDAY_DAILY = "weekday_daily"
    SATURDAY_STRATEGIC = "saturday_strategic"
    SUNDAY_VISUAL = "sunday_visual"


def get_mode(d: date) -> Mode:
    weekday = d.weekday()
    if weekday == 0:
        return Mode.MONDAY_CATCHUP
    if 1 <= weekday <= 4:
        return Mode.WEEKDAY_DAILY
    if weekday == 5:
        return Mode.SATURDAY_STRATEGIC
    return Mode.SUNDAY_VISUAL


def get_feeds_for_mode(mode: Mode) -> list[dict]:
    if mode in (Mode.MONDAY_CATCHUP, Mode.WEEKDAY_DAILY):
        return FEEDS_WEEKDAY
    if mode == Mode.SATURDAY_STRATEGIC:
        return FEEDS_SATURDAY_STRATEGIC
    return FEEDS_SUNDAY_VISUAL


def is_design_mode(mode: Mode) -> bool:
    return mode in (Mode.SATURDAY_STRATEGIC, Mode.SUNDAY_VISUAL)
