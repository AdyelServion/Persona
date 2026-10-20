"""Authoritative persona clock — never ask the LLM for date or time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from persona_runtime.db.time_utils import ensure_utc, utcnow

DEFAULT_PERSONA_TIMEZONE = "Europe/London"

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


@dataclass(frozen=True)
class ClockSnapshot:
    """Validated time snapshot injected into every conversation request."""

    utc_now: datetime
    local_now: datetime
    timezone: str
    local_date: date
    weekday: str
    weekday_index: int  # 0=Monday … 6=Sunday
    local_time: str  # HH:MM
    is_weekend: bool

    def elapsed_since(self, moment: datetime | None) -> timedelta | None:
        if moment is None:
            return None
        return ensure_utc(self.utc_now) - ensure_utc(moment)

    def elapsed_seconds_since(self, moment: datetime | None) -> float | None:
        delta = self.elapsed_since(moment)
        if delta is None:
            return None
        return delta.total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "utc_now": self.utc_now.isoformat(),
            "local_now": self.local_now.isoformat(),
            "timezone": self.timezone,
            "local_date": self.local_date.isoformat(),
            "weekday": self.weekday,
            "weekday_index": self.weekday_index,
            "local_time": self.local_time,
            "is_weekend": self.is_weekend,
            "authoritative": True,
        }


class PersonaClock:
    """Supplies timezone-aware snapshots. Uses the injectable ``utcnow`` clock."""

    def __init__(self, tz_name: str = DEFAULT_PERSONA_TIMEZONE):
        self.tz_name = tz_name or DEFAULT_PERSONA_TIMEZONE
        self._tz = ZoneInfo(self.tz_name)

    def snapshot(self, now: datetime | None = None) -> ClockSnapshot:
        utc = ensure_utc(now or utcnow())
        local = utc.astimezone(self._tz)
        local_date = local.date()
        weekday_index = local_date.weekday()
        return ClockSnapshot(
            utc_now=utc,
            local_now=local,
            timezone=self.tz_name,
            local_date=local_date,
            weekday=_WEEKDAYS[weekday_index],
            weekday_index=weekday_index,
            local_time=local.strftime("%H:%M"),
            is_weekend=weekday_index >= 5,
        )


def clock_snapshot(
    *,
    tz_name: str = DEFAULT_PERSONA_TIMEZONE,
    now: datetime | None = None,
) -> ClockSnapshot:
    return PersonaClock(tz_name=tz_name).snapshot(now=now)
