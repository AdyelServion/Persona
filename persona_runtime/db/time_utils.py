"""Shared datetime helpers with an injectable clock for tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

_clock: Callable[[], datetime] | None = None


def utcnow() -> datetime:
    if _clock is not None:
        return _clock()
    return datetime.now(timezone.utc)


def set_clock(fn: Callable[[], datetime] | None) -> None:
    """Inject a clock callable (e.g. for frozen-time tests). Pass None to restore."""
    global _clock
    _clock = fn


def advance_clock(seconds: float) -> datetime:
    """Advance an injected clock by ``seconds``. Requires a mutable clock object.

    Prefer tests that replace the clock with a lambda capturing a mutable list.
    This helper exists for documentation; tests typically set_clock themselves.
    """
    raise RuntimeError("Use set_clock with a mutable datetime holder in tests")


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def ensure_utc(dt: datetime) -> datetime:
    if dt is None:
        raise ValueError("datetime is required")
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def safe_le(a: datetime, b: datetime) -> bool:
    return ensure_utc(a) <= ensure_utc(b)


def safe_ge(a: datetime, b: datetime) -> bool:
    return ensure_utc(a) >= ensure_utc(b)


def add_seconds(dt: datetime, seconds: float) -> datetime:
    return ensure_utc(dt) + timedelta(seconds=seconds)
