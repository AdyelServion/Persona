"""Grounding against timeline clock, transport facts, and multi-question continuity."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from persona_runtime.db.time_utils import set_clock
from persona_runtime.graph.grounding import (
    build_answer_plan,
    fallback_messages_from_answer_plan,
    retrieve_fact_for_question,
    retrieve_facts,
)
from persona_runtime.graph.questions import classify_slot, extract_questions
from persona_runtime.graph.validator import validate_response
from persona_runtime.life.clock import clock_snapshot
from persona_runtime.life.timeline import TimelineEngine, TimelineRepository
from persona_runtime.persona.constants import TRANSPORT_PROFILE
from persona_runtime.state.repositories import PersonaStateRepository


PERSONA = "sarah_taylor_001"


@pytest.fixture(autouse=True)
def _clear_clock():
    set_clock(None)
    yield
    set_clock(None)


@pytest.fixture()
def advanced(db):
    state_repo = PersonaStateRepository(db)
    state_repo.ensure_default_state(PERSONA)
    tl = TimelineRepository(db)
    eng = TimelineEngine(state_repo, tl)
    # Wednesday 10:00 London
    fixed = datetime(2026, 10, 14, 9, 0, 0, tzinfo=timezone.utc)
    set_clock(lambda: fixed)
    eng.advance(PERSONA)
    return state_repo, tl, eng, fixed


def test_slot_classification_time_presence_leave_transport():
    assert classify_slot("What time is it?") == "time_now"
    assert classify_slot("Are you still at the office?") == "still_at_office"
    assert classify_slot("What time will you leave work?") == "leave_work"
    assert classify_slot("When will you get home?") == "arrive_home"
    assert classify_slot("Do you have a car?") == "transport"
    assert classify_slot("How do you commute to work?") == "transport"


def test_time_now_from_authoritative_clock(advanced):
    state_repo, tl, eng, fixed = advanced
    doc = state_repo.get_state(PERSONA)
    clock = clock_snapshot(tz_name="Europe/London")
    q = extract_questions("What time is it?")[0]
    fact = retrieve_fact_for_question(
        q,
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
        clock=clock,
    )
    assert fact.status == "established"
    assert fact.value["weekday"] == "Wednesday"
    assert fact.value["local_time"] == clock.local_time
    assert fact.source == "clock:authoritative"


def test_still_at_office_uses_current_state(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    q = extract_questions("Are you still at the office?")[0]
    fact = retrieve_fact_for_question(
        q, persona_id=PERSONA, persona_state=doc, timeline_repo=tl
    )
    assert fact.status == "established"
    assert fact.value["at_office"] is True


def test_leave_work_and_arrive_home_are_simulated(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    leave = retrieve_fact_for_question(
        extract_questions("What time will you leave work?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    assert leave.status == "simulated"
    assert leave.value.get("uncertain") is True
    assert leave.event_id

    arrive = retrieve_fact_for_question(
        extract_questions("When will you get home?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    assert arrive.status == "simulated"
    assert arrive.value.get("uncertain") is True
    assert "give or take" in (arrive.value.get("phrase") or "").lower() or arrive.value.get(
        "commute_minutes"
    )


def test_transport_no_personal_car(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    fact = retrieve_fact_for_question(
        extract_questions("Do you have a car?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    assert fact.status == "established"
    assert fact.value["owns_personal_vehicle"] is False
    assert fact.value["commute_mode"] == "public_transport"
    # Company vehicle is a separate field — must not overwrite ownership
    assert TRANSPORT_PROFILE["owns_personal_vehicle"] is False
    assert TRANSPORT_PROFILE.get("company_vehicle_access") is None


def test_personal_car_claim_does_not_overwrite_fact():
    # Validator path for reply — personal car claim is rejected
    state = {
        "generated_response": "Yeah I just hop in my car and drive in",
        "response_plan": {"answers": []},
        "understanding": {},
        "behaviour_plan": {},
        "conversation_context": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "persona_state": {"current_state": {}},
        "clock_snapshot": {"weekday": "Wednesday"},
    }
    result = validate_response(state, state["generated_response"])
    assert any("owns_personal_vehicle" in f for f in result.failures)


def test_past_unknown_without_completed_yesterday(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    fact = retrieve_fact_for_question(
        extract_questions("What did you do yesterday?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    # No yesterday timeline completed yet
    assert fact.status == "unknown"


def test_past_from_completed_yesterday(db):
    state_repo = PersonaStateRepository(db)
    state_repo.ensure_default_state(PERSONA)
    tl = TimelineRepository(db)
    eng = TimelineEngine(state_repo, tl)
    # Advance through a full Wednesday
    wed = datetime(2026, 10, 14, 18, 0, 0, tzinfo=timezone.utc)
    set_clock(lambda: wed)
    eng.advance(PERSONA)
    # Jump to Thursday morning
    thu = datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc)
    set_clock(lambda: thu)
    eng.advance(PERSONA)
    doc = state_repo.get_state(PERSONA)
    fact = retrieve_fact_for_question(
        extract_questions("What did you do yesterday?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
        clock=clock_snapshot(),
    )
    assert fact.status == "simulated"
    assert fact.value.get("local_date") == "2026-10-14"
    assert fact.event_id


def test_repeated_leave_work_same_event_id(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    a = retrieve_fact_for_question(
        extract_questions("What time will you leave work?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    b = retrieve_fact_for_question(
        extract_questions("What time will you leave work?")[0],
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
    )
    assert a.event_id == b.event_id


def test_multiple_questions_bubbles_agree(advanced):
    state_repo, tl, _, _ = advanced
    doc = state_repo.get_state(PERSONA)
    text = "Are you still at the office? When will you get home?"
    qs = extract_questions(text)
    assert [q.slot for q in qs] == ["still_at_office", "arrive_home"]
    facts = retrieve_facts(
        qs,
        persona_id=PERSONA,
        persona_state=doc,
        timeline_repo=tl,
        clock=clock_snapshot(),
    )
    plan = build_answer_plan(qs, facts)
    bubbles = fallback_messages_from_answer_plan(plan)
    assert len(bubbles) == 2
    # First bubble about office; second about home arrival — no personal car invent
    joined = " ".join(bubbles).lower()
    assert "car" not in joined or "don't" in joined or "dont" in joined


def test_company_vehicle_separate_from_personal():
    """Company Ford Focus access must not flip owns_personal_vehicle."""
    profile = dict(TRANSPORT_PROFILE)
    profile["company_vehicle_access"] = "Ford Focus"
    assert profile["owns_personal_vehicle"] is False
    assert profile["company_vehicle_access"] == "Ford Focus"
    assert profile["commute_mode"] == "public_transport"
