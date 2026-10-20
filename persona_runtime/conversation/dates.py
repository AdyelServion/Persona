"""Relative date parsing against persona local clock — no external dependency."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _local_today(clock: dict[str, Any] | None, tz_name: str = "Europe/London") -> date:
    if clock and clock.get("local_date"):
        try:
            return date.fromisoformat(str(clock["local_date"])[:10])
        except ValueError:
            pass
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    return datetime.now(tz).date()


def parse_relative_date(
    text: str,
    *,
    clock: dict[str, Any] | None = None,
    tz_name: str = "Europe/London",
) -> date | None:
    """Parse tomorrow / next Friday / this Saturday / in N days from text."""
    lower = (text or "").lower()
    today = _local_today(clock, tz_name)

    if re.search(r"\btomorrow\b", lower):
        return today + timedelta(days=1)
    if re.search(r"\btoday\b", lower):
        return today
    m = re.search(r"\bin\s+(\d+)\s+days?\b", lower)
    if m:
        return today + timedelta(days=int(m.group(1)))

    m = re.search(
        r"\b(?:next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        lower,
    )
    if m:
        target = WEEKDAYS[m.group(1)]
        days_ahead = (target - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7 if m.group(0).startswith("next") else 0
        elif "next" in m.group(0) and days_ahead < 7:
            # "next Friday" from a Friday → +7; from Thursday → +1 is fine as upcoming
            pass
        if "next" in m.group(0) and days_ahead == 0:
            days_ahead = 7
        return today + timedelta(days=days_ahead if days_ahead else 7)

    for name, wd in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lower):
            days_ahead = (wd - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return today + timedelta(days=days_ahead)
    return None


def occurs_at_datetime(
    text: str,
    *,
    clock: dict[str, Any] | None = None,
    tz_name: str = "Europe/London",
) -> datetime | None:
    d = parse_relative_date(text, clock=clock, tz_name=tz_name)
    if d is None:
        return None
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    # Default midday local for vague day references
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=tz)
