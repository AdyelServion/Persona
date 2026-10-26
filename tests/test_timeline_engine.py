"""Deterministic timeline and world-state advancement tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from persona_runtime.db.time_utils import ensure_utc, set_clock
from persona_runtime.life.simulator import LifeSimulator, build_daily_plan
from persona_runtime.life.timeline import (
    TimelineEngine,
    TimelineRepository,
    blocks_to_timeline_events,
)
from persona_runtime.life.transitions import transition_allowed
from persona_runtime.state.repositories import PersonaStateRepository


PERSONA = "sarah_taylor_001"


@pytest.fixture(autouse=True)
def _clear_clock():
    set_clock(None)
    yield
    set_clock(None)


@pytest.fixture()
def engine(db):
    state_repo = PersonaStateRepository(db)
    state_repo.ensure_default_state(PERSONA)
    tl = TimelineRepository(db)
    return TimelineEngine(state_repo, tl, tz_name="Europe/London"), state_repo, tl


def _set(dt: datetime):
    set_clock(lambda: dt)


def test_transition_rules():
    assert transition_allowed("office", "commute")
    assert transition_allowed("commute", "home")
    assert not transition_allowed("office", "home")
    assert not transition_allowed("gym", "home")
    assert not transition_allowed("home", "city")
    assert transition_allowed("gym", "commute")
    assert transition_allowed("commute", "city")
    assert transition_allowed("home", "home")
    assert transition_allowed("office", "office")


def test_ensure_day_events_idempotent(engine):
    eng, _, tl = engine
    # Wednesday morning
    _set(datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc))  # 09:00 BST
    first = eng.ensure_day_events(PERSONA)
    assert len(first) >= 8
    assert all(e["status"] == "planned" for e in first)
    second = eng.ensure_day_events(PERSONA)
    assert len(second) == len(first)
    assert {e["event_id"] for e in first} == {e["event_id"] for e in second}


def test_planned_stays_planned_until_advance(engine):
    eng, _, tl = engine
    _set(datetime(2026, 10, 14, 8, 0, 0, tzinfo=timezone.utc))
    events = eng.ensure_day_events(PERSONA)
    lunch = next(e for e in events if e["activity"] == "lunch")
    assert lunch["status"] == "planned"
    # Reading without advance leaves status planned
    assert tl.get_by_id(lunch["event_id"])["status"] == "planned"


def test_advance_activates_work_at_office_hours(engine):
    eng, state_repo, tl = engine
    # 10:00 London Wednesday
    _set(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))
    result = eng.advance(PERSONA)
    state = (result["persona_state"].get("current_state") or {})
    assert state["current_activity"] == "working"
    assert state["location_type"] == "office"
    active = tl.get_active(PERSONA)
    assert active is not None
    assert active["activity"] == "working"
    assert active["status"] == "active"
    # Earlier events completed via catch-up
    completed = tl.list_completed_for_date(PERSONA, "2026-10-14")
    assert any(e["activity"] == "commuting" for e in completed)
    assert any(e["activity"] == "waking_up" for e in completed)


def test_lunch_window(engine):
    eng, _, tl = engine
    _set(datetime(2026, 10, 14, 11, 45, 0, tzinfo=timezone.utc))  # 12:45 BST
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] == "lunch"


def test_leave_office_goes_through_commute(engine):
    eng, state_repo, tl = engine
    _set(datetime(2026, 10, 14, 16, 45, 0, tzinfo=timezone.utc))  # 17:45 BST
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] == "commuting"
    state = state_repo.get_state(PERSONA)["current_state"]
    assert state["location_type"] == "transit"
    assert state["transport_mode"] == "public_transport"


def test_home_arrival_after_commute(engine):
    eng, state_repo, tl = engine
    # After evening commute ends (~18:15)
    _set(datetime(2026, 10, 14, 17, 30, 0, tzinfo=timezone.utc))  # 18:30 BST
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] in {"gym", "cooking", "commuting", "eating", "personal_time"}
    # Must have completed a commute
    completed = tl.list_completed_for_date(PERSONA, "2026-10-14")
    assert any(e["activity"] == "commuting" for e in completed)


def test_weekend_template_differs(engine):
    eng, _, tl = engine
    _set(datetime(2026, 10, 17, 11, 0, 0, tzinfo=timezone.utc))  # Saturday
    events = eng.ensure_day_events(PERSONA)
    activities = [e["activity"] for e in events]
    assert "with_friends" in activities or "shopping" in activities or "relaxing" in activities
    assert "meeting" not in activities


def test_session_restart_persists_completed(engine):
    eng, state_repo, tl = engine
    _set(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))
    eng.advance(PERSONA)
    completed_ids = {e["event_id"] for e in tl.list_completed_for_date(PERSONA, "2026-10-14")}
    assert completed_ids
    # New engine instance (session restart)
    eng2 = TimelineEngine(state_repo, tl, tz_name="Europe/London")
    eng2.advance(PERSONA)
    completed2 = {e["event_id"] for e in tl.list_completed_for_date(PERSONA, "2026-10-14")}
    assert completed_ids <= completed2
    active = tl.get_active(PERSONA)
    assert active["activity"] == "working"


def test_cas_conflict_second_advance_noops(engine):
    eng, state_repo, tl = engine
    _set(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))
    r1 = eng.advance(PERSONA)
    assert r1["cas_conflict"] is False
    v1 = r1["state_version"]
    # Same clock again — no new transitions expected (already active)
    r2 = eng.advance(PERSONA)
    assert r2["transitions"] == []
    # Force version mismatch simulation
    state_repo.col.update_one({"persona_id": PERSONA}, {"$set": {"state_version": 999}})
    # Inject fake transitions path by manually calling with stale version via
    # completing an event then advancing — simpler: call _cas_apply with bad version
    fields = {"current_activity": "working"}
    bad = eng._cas_apply(
        PERSONA,
        fields,
        expected_version=0,
        transitions=[{"event_id": "x", "from": "planned", "to": "active"}],
        now=datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc),
    )
    assert bad["cas_conflict"] is True


def test_life_simulator_delegates(db):
    state_repo = PersonaStateRepository(db)
    state_repo.ensure_default_state(PERSONA)
    life = LifeSimulator(state_repo)
    _set(datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc))
    doc = life.ensure_life_state(PERSONA)
    assert doc["current_state"]["current_activity"] == "working"
    assert life.timeline_repo.count_for_date(PERSONA, "2026-10-14") > 0


LONDON = ZoneInfo("Europe/London")


def _london(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LONDON).astimezone(timezone.utc)


def _gym_weekday() -> tuple[datetime, list[dict]]:
    """A weekday whose plan actually includes the gym (some days skip it)."""
    day = datetime(2026, 10, 12, 12, 0, tzinfo=LONDON)
    for _ in range(10):
        plan = build_daily_plan(
            persona_id=PERSONA, local_now=day, tz_name="Europe/London"
        )
        if day.weekday() < 5 and any(block["activity"] == "gym" for block in plan):
            return day, plan
        day += timedelta(days=1)
    raise AssertionError("expected a weekday plan that includes the gym")


def test_plan_inserts_commute_before_illegal_place_change():
    _, plan = _gym_weekday()
    gym_at = next(i for i, block in enumerate(plan) if block["activity"] == "gym")
    assert plan[gym_at + 1]["activity"] == "commuting"
    assert plan[gym_at + 1]["location"] == "commute"
    assert plan[gym_at + 2]["location"] == "home"

    weekend = build_daily_plan(
        persona_id=PERSONA,
        local_now=datetime(2026, 10, 17, 12, 0, tzinfo=LONDON),
        tz_name="Europe/London",
    )
    shop_at = next(i for i, block in enumerate(weekend) if block["activity"] == "shopping")
    assert weekend[shop_at - 1]["activity"] == "commuting"
    assert weekend[shop_at - 1]["location"] == "commute"
    for blocks in (plan, weekend):
        for left, right in zip(blocks, blocks[1:]):
            assert transition_allowed(left["location"], right["location"])
            assert ensure_utc(right["start_at"]) > ensure_utc(left["start_at"])


def test_evening_is_home_after_gym(engine):
    eng, _, tl = engine
    day, _ = _gym_weekday()
    _set(_london(day.year, day.month, day.day, 20, 0))
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] in {"cooking", "eating", "personal_time"}
    assert active["location"] == "home"
    completed = tl.list_completed_for_date(PERSONA, day.date().isoformat())
    gym = next(event for event in completed if event["activity"] == "gym")
    assert any(
        event["activity"] == "commuting"
        and ensure_utc(event["scheduled_start"]) > ensure_utc(gym["scheduled_start"])
        and ensure_utc(event["scheduled_start"]) < ensure_utc(active["scheduled_start"])
        for event in completed
    )


def test_next_morning_is_not_the_gym(engine):
    eng, _, tl = engine
    day, _ = _gym_weekday()
    _set(_london(day.year, day.month, day.day, 18, 30))
    eng.advance(PERSONA)
    assert tl.get_active(PERSONA)["activity"] == "gym"
    nxt = day.date() + timedelta(days=1)
    _set(_london(nxt.year, nxt.month, nxt.day, 9, 0))
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] != "gym"
    assert active["activity"] in {
        "waking_up",
        "breakfast",
        "commuting",
        "working",
        "meeting",
    }


def test_stuck_active_gym_catches_up(engine):
    eng, state_repo, tl = engine
    local_date = "2026-10-14"
    gym_start = datetime(2026, 10, 14, 18, 15, tzinfo=LONDON)
    cook_start = datetime(2026, 10, 14, 19, 30, tzinfo=LONDON)
    cook_end = datetime(2026, 10, 14, 21, 0, tzinfo=LONDON)
    events = blocks_to_timeline_events(
        persona_id=PERSONA,
        blocks=[
            {
                "activity": "gym",
                "location": "gym",
                "start_at": gym_start,
                "end_at": cook_start,
            },
            {
                "activity": "cooking",
                "location": "home",
                "start_at": cook_start,
                "end_at": cook_end,
            },
        ],
        local_date=local_date,
        now=cook_start,
    )
    events[0]["status"] = "active"
    events[0]["actual_start"] = ensure_utc(gym_start)
    tl.insert_many_if_absent(events)
    state_repo.apply_updates(
        PERSONA,
        {
            "current_activity": "gym",
            "current_location": "gym",
            "active_event_id": events[0]["event_id"],
        },
    )
    _set(_london(2026, 10, 14, 20, 0))
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active is not None
    assert active["activity"] != "gym"
    assert active["location"] == "home"
    assert tl.get_by_id(events[0]["event_id"])["status"] == "completed"
    completed = tl.list_completed_for_date(PERSONA, local_date)
    assert any(event["activity"] == "commuting" for event in completed)


def test_weekend_reaches_shopping(engine):
    eng, _, tl = engine
    _set(_london(2026, 10, 17, 15, 0))
    eng.advance(PERSONA)
    active = tl.get_active(PERSONA)
    assert active["activity"] in {"shopping", "with_friends"}
    shopping = next(
        event
        for event in tl.list_for_date(PERSONA, "2026-10-17")
        if event["activity"] == "shopping"
    )
    completed = tl.list_completed_for_date(PERSONA, "2026-10-17")
    assert any(
        event["activity"] == "commuting"
        and ensure_utc(event["scheduled_start"]) < ensure_utc(shopping["scheduled_start"])
        for event in completed
    )
