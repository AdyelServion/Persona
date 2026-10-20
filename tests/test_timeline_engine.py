"""Deterministic timeline and world-state advancement tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from persona_runtime.db.time_utils import set_clock
from persona_runtime.life.simulator import LifeSimulator, build_daily_plan
from persona_runtime.life.timeline import TimelineEngine, TimelineRepository
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
