"""Deterministic tests for the authoritative persona clock."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from persona_runtime.db.time_utils import set_clock
from persona_runtime.life.clock import PersonaClock, clock_snapshot
from persona_runtime.state.repositories import activity_for_now


@pytest.fixture(autouse=True)
def _clear_clock():
    set_clock(None)
    yield
    set_clock(None)


def test_snapshot_utc_local_weekday_and_timezone():
    # Wednesday 2026-10-14 14:30 UTC = 15:30 Europe/London (BST ends late Oct)
    fixed = datetime(2026, 10, 14, 14, 30, 0, tzinfo=timezone.utc)
    set_clock(lambda: fixed)
    snap = clock_snapshot(tz_name="Europe/London")
    assert snap.timezone == "Europe/London"
    assert snap.utc_now == fixed
    assert snap.local_date.isoformat() == "2026-10-14"
    assert snap.weekday == "Wednesday"
    assert snap.weekday_index == 2
    assert snap.is_weekend is False
    assert snap.local_time == "15:30"
    assert snap.to_dict()["authoritative"] is True


def test_midnight_rollover_changes_local_date_and_weekday():
    # Just before midnight London on a Thursday
    before = datetime(2026, 10, 15, 22, 59, 0, tzinfo=timezone.utc)  # 23:59 BST
    set_clock(lambda: before)
    snap_before = PersonaClock("Europe/London").snapshot()
    assert snap_before.local_date.isoformat() == "2026-10-15"
    assert snap_before.weekday == "Thursday"

    after = before + timedelta(minutes=2)  # 00:01 Friday local
    set_clock(lambda: after)
    snap_after = PersonaClock("Europe/London").snapshot()
    assert snap_after.local_date.isoformat() == "2026-10-16"
    assert snap_after.weekday == "Friday"
    assert snap_after.weekday_index == 4


def test_weekend_flag():
    saturday = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    set_clock(lambda: saturday)
    snap = clock_snapshot()
    assert snap.is_weekend is True
    assert snap.weekday == "Saturday"


def test_elapsed_since():
    now = datetime(2026, 10, 14, 16, 0, 0, tzinfo=timezone.utc)
    set_clock(lambda: now)
    snap = clock_snapshot()
    earlier = now - timedelta(minutes=45)
    assert snap.elapsed_seconds_since(earlier) == 45 * 60
    assert snap.elapsed_since(None) is None


def test_activity_for_now_uses_injected_clock():
    # Tuesday 10:00 London → working
    fixed = datetime(2026, 10, 13, 9, 0, 0, tzinfo=timezone.utc)  # 10:00 BST
    set_clock(lambda: fixed)
    snap = activity_for_now("Europe/London")
    assert snap["current_activity"] == "working"
    assert snap["local_hour"] == 10
    assert snap["weekday"] == 1
