"""Universal question grounding: slots, facts, experiences, answer plans."""

from __future__ import annotations

import json
from datetime import timedelta

from persona_runtime.db.time_utils import utcnow
from persona_runtime.graph.bubbles import normalize_generated_messages, pack_message_dicts
from persona_runtime.graph.context_builder import build_prompt_context
from persona_runtime.graph.grounding import (
    build_answer_plan,
    fallback_messages_from_answer_plan,
    retrieve_facts,
    retrieve_fact_for_question,
)
from persona_runtime.graph.questions import (
    attach_questions_to_understanding,
    classify_slot,
    extract_questions,
    preference_kind_from_text,
)
from persona_runtime.graph.validator import validate_response
from persona_runtime.life.experiences import (
    close_open_experiences,
    materialize_experience,
    resolve_experience_for_slot,
)
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.state.repositories import PersonaStateRepository


def _lunch_state(repo: PersonaStateRepository, persona_id: str = "sarah_taylor_001"):
    life = LifeSimulator(repo)
    life.force_activity(persona_id, "lunch", duration_minutes=45)
    return repo.get_state(persona_id)


# --- 1. Direct factual questions ---


def test_occupation_from_canonical_fact(ingested_db):
    qs = extract_questions("What do you do?")
    assert len(qs) == 1
    assert qs[0].slot == "occupation"
    fact = retrieve_fact_for_question(
        qs[0],
        persona_id="sarah_taylor_001",
        persona_state=PersonaStateRepository(ingested_db).get_state("sarah_taylor_001"),
    )
    assert fact.status == "established"
    assert "Management Accountant" in str(fact.value)
    plan = build_answer_plan(qs, [fact])
    assert plan["answers"][0]["can_answer"] is True
    assert plan["answers"][0]["direct_answer"] == "Management Accountant"


# --- 2. Unknown fact ---


def test_unknown_past_event_cannot_answer(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    qs = extract_questions("What did you do yesterday?")
    assert qs[0].slot == "event_past"
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    assert facts[0].status == "unknown"
    plan = build_answer_plan(qs, facts)
    assert plan["answers"][0]["can_answer"] is False
    bubbles = fallback_messages_from_answer_plan(plan)
    joined = " ".join(bubbles).lower()
    assert "chicken sandwich" not in joined
    assert "pasta" not in joined or "blur" in joined or "don't" in joined or "detail" in joined


# --- 3. Activity vs task vs meal ---


def test_activity_task_meal_are_distinct_slots(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    doc = _lunch_state(repo)
    # Keep workday task
    assert (doc.get("current_state") or {}).get("current_activity") == "lunch"

    meal_q = extract_questions("What are you having for lunch?")
    act_q = extract_questions("What are you doing?")
    task_q = extract_questions("What are you working on?")
    assert meal_q[0].slot == "meal_now"
    assert act_q[0].slot == "activity_now"
    assert task_q[0].slot == "task_now"

    meal = retrieve_fact_for_question(
        meal_q[0], persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    doc = repo.get_state("sarah_taylor_001")
    act = retrieve_fact_for_question(
        act_q[0], persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    task = retrieve_fact_for_question(
        task_q[0], persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )

    assert meal.status == "simulated"
    assert meal.value and isinstance(meal.value, str)
    assert act.status == "established"
    assert "lunch" in str(act.value).lower() or "having lunch" in str(act.value).lower()
    assert task.status == "established"
    # Desk task must not be the meal answer
    assert meal.value != (task.value or {}).get("task")
    assert meal.value != (task.value or {}).get("project")


# --- 4. Past vs future ---


def test_past_reads_stored_events_future_reads_plan(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    doc = _lunch_state(repo)
    event = resolve_experience_for_slot(
        persona_id="sarah_taylor_001",
        state_doc=doc,
        slot="meal",
        state_repo=repo,
    )
    assert event is not None

    # Close lunch and move on
    life = LifeSimulator(repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=60)
    doc = repo.get_state("sarah_taylor_001")
    events = doc.get("experience_events") or []
    assert any(e.get("ended_at") for e in events)

    past_q = extract_questions("What did you do yesterday?")
    # Inject a past closed event with older timestamp for yesterday-style retrieval
    past_event = dict(event)
    past_event["started_at"] = utcnow() - timedelta(hours=20)
    past_event["ended_at"] = utcnow() - timedelta(hours=19)
    past_event["event_id"] = "past-test-1"
    events = repo.get_experience_events("sarah_taylor_001")
    events.append(past_event)
    repo.set_experience_events("sarah_taylor_001", events)
    doc = repo.get_state("sarah_taylor_001")

    past_fact = retrieve_fact_for_question(
        past_q[0], persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    assert past_fact.status in {"simulated", "established"}
    assert past_fact.value is not None

    future_q = extract_questions("What are you doing tonight?")
    assert future_q[0].slot == "plan_future"
    future_fact = retrieve_fact_for_question(
        future_q[0], persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    # Routine futures are simulated with uncertainty; meal detail stays unknown
    assert future_fact.status in {"simulated", "unknown"}
    if future_fact.status == "simulated":
        assert (future_fact.value or {}).get("detail_status") == "unknown"
        assert (future_fact.value or {}).get("uncertain") is True


# --- 5. Multiple questions ---


def test_multiple_questions_preserve_order_and_answers(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    _lunch_state(repo)
    text = "whats your favorite dish ?\nwhat are you having for lunch?"
    qs = extract_questions(text, pending_messages=text.split("\n"))
    assert [q.slot for q in qs] == ["preference", "meal_now"]
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    plan = build_answer_plan(qs, facts)
    assert [a["slot"] for a in plan["answers"]] == ["preference", "meal_now"]
    assert plan["answers"][0]["can_answer"] is True
    assert plan["answers"][1]["can_answer"] is True
    assert plan["answers"][0]["direct_answer"] != plan["answers"][1]["direct_answer"]


# --- 6. Follow-up ---


def test_follow_up_uses_last_answer_slots(ingested_db):
    qs = extract_questions(
        "sounds boring 😂",
        last_question_target="activity_now",
        last_answer_slots=["activity_now"],
    )
    assert qs[0].slot == "follow_up"
    assert qs[0].depends_on_previous is True


# --- 7. Repeat question same event ---


def test_repeat_meal_question_same_event(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    doc = _lunch_state(repo)
    q = extract_questions("What are you having for lunch?")[0]
    f1 = retrieve_fact_for_question(
        q, persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    doc = repo.get_state("sarah_taylor_001")
    f2 = retrieve_fact_for_question(
        q, persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    assert f1.event_id and f1.event_id == f2.event_id
    assert f1.value == f2.value


# --- 8. Topic change drops previous slot from allowed ---


def test_topic_change_excludes_previous_slot(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    _lunch_state(repo)
    meal_qs = extract_questions("What are you having for lunch?")
    meal_facts = retrieve_facts(
        meal_qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    meal_plan = build_answer_plan(meal_qs, meal_facts)
    assert "meal_now" in meal_plan["allowed_slots"]

    occ_qs = extract_questions("What do you do?")
    occ_facts = retrieve_facts(
        occ_qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    occ_plan = build_answer_plan(occ_qs, occ_facts)
    assert "occupation" in occ_plan["allowed_slots"]
    assert "meal_now" not in occ_plan["allowed_slots"]
    # Meal catalog phrases should be in must_not or at least not allowed as occupation answer
    assert occ_plan["answers"][0]["direct_answer"] == "Management Accountant"


# --- 9. Consistency after world-state transition ---


def test_meal_not_current_after_transition(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    doc = _lunch_state(repo)
    event = resolve_experience_for_slot(
        persona_id="sarah_taylor_001",
        state_doc=doc,
        slot="meal",
        state_repo=repo,
    )
    meal_value = event["value"]
    life = LifeSimulator(repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=60)
    doc = repo.get_state("sarah_taylor_001")
    closed = [e for e in (doc.get("experience_events") or []) if e.get("event_id") == event["event_id"]]
    assert closed and closed[0].get("ended_at")

    q = extract_questions("What are you having for lunch?")[0]
    fact = retrieve_fact_for_question(
        q, persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    # Not in meal window anymore
    assert fact.status == "unknown"
    assert fact.missing == "not_in_meal_window"
    plan = build_answer_plan([q], [fact])
    bubbles = " ".join(fallback_messages_from_answer_plan(plan)).lower()
    assert meal_value.lower() not in bubbles


# --- 10. Preference vs experience ---


def test_preference_vs_current_meal(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    _lunch_state(repo)
    pref = extract_questions("What's your favourite food?")[0]
    meal = extract_questions("What are you having for lunch?")[0]
    assert pref.slot == "preference"
    assert pref.time_scope == "habitual"
    assert pref.kind == "preference"
    assert meal.slot == "meal_now"
    assert meal.kind == "experience"

    facts = retrieve_facts(
        [pref, meal],
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    assert facts[0].kind == "preference"
    assert facts[0].status == "established"
    assert facts[1].status == "simulated"
    assert facts[0].value != facts[1].value


# --- 11. User memory vs outdated ---


def test_user_memory_active_vs_outdated(ingested_db):
    q = extract_questions("Do you remember what I told you?")[0]
    assert q.slot == "user_memory"
    active = {
        "memory_id": "m1",
        "status": "active",
        "fact": "User works as a teacher",
        "object": "teacher",
    }
    fact = retrieve_fact_for_question(
        q,
        persona_id="sarah_taylor_001",
        persona_state={},
        retrieved_memories=[active],
    )
    assert fact.status == "established"
    assert "teacher" in str(fact.value).lower()

    outdated = retrieve_fact_for_question(
        q,
        persona_id="sarah_taylor_001",
        persona_state={},
        retrieved_memories=[{"memory_id": "m2", "status": "superseded", "fact": "old"}],
    )
    assert outdated.status == "outdated"
    plan = build_answer_plan([q], [outdated])
    assert plan["answers"][0]["can_answer"] is False


# --- 12. Multi-bubble schema ---


def test_multi_bubble_fallback_from_answer_plan(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    _lunch_state(repo)
    qs = extract_questions(
        "whats your favorite dish ?\nwhat are you having for lunch?",
        pending_messages=[
            "whats your favorite dish ?",
            "what are you having for lunch?",
        ],
    )
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    plan = build_answer_plan(qs, facts)
    state = {
        "understanding": {"questions": [q.model_dump() for q in qs], "question_targets": ["habit", "activity_now"]},
        "response_plan": plan,
        "persona_state": repo.get_state("sarah_taylor_001"),
        "conversation_context": {},
    }
    # Wrong bubble count → fallback
    texts = normalize_generated_messages(["one mashed paragraph about everything"], state)
    assert len(texts) == 2
    packed = pack_message_dicts(texts)
    assert all(m["type"] == "text" for m in packed)


# --- 13. No unrelated leakage in generation context ---


def test_lunch_context_excludes_employer_zodiac_family(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    _lunch_state(repo)
    qs = extract_questions("What are you having for lunch?")
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    plan = build_answer_plan(qs, facts)
    state = {
        "understanding": {
            "questions": [q.model_dump() for q in qs],
            "question_target": "activity_now",
            "question_targets": ["activity_now"],
            "speech_act": "question",
            "intent": "ask_persona",
            "topic": "current_situation",
        },
        "response_plan": {**plan, "disclose_fact_ids": [], "suppressed_fact_ids": []},
        "persona_state": repo.get_state("sarah_taylor_001"),
        "conversation_context": {},
        "retrieved_memories": [],
        "allowed_evidence_ids": [],
        "recent_messages": [],
        "incoming_message": "What are you having for lunch?",
    }
    ctx = build_prompt_context(state)
    assert "ANSWER_PLAN" in ctx
    # Concrete employer / zodiac / family / project names must not appear as answer facts
    answers_blob = json.dumps(plan.get("answers") or [])
    assert "Northbridge" not in answers_blob
    assert "Aries" not in answers_blob
    assert "Diane" not in answers_blob
    assert "Northbridge" not in ctx
    assert "Aries" not in ctx
    assert "Diane" not in ctx
    assert "Monthly Financial Reporting" not in ctx
    # Full REALITY dump should be omitted
    assert "=== REALITY (authoritative layers) ===" not in ctx


# --- 14. Unsupported past claims ---


def test_unknown_past_validator_blocks_invented_meal(ingested_db):
    qs = extract_questions("What did you do yesterday?")
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state=PersonaStateRepository(ingested_db).get_state("sarah_taylor_001"),
    )
    plan = build_answer_plan(qs, facts)
    state = {
        "understanding": {
            "questions": [q.model_dump() for q in qs],
            "speech_act": "question",
            "question_targets": [],
        },
        "response_plan": {
            **plan,
            "should_ask_question": False,
            "disclose_fact_ids": [],
            "suppressed_fact_ids": [],
        },
        "persona_state": {
            "current_state": {"current_activity": "working", "current_location": "office"}
        },
        "conversation_context": {},
        "behaviour_plan": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "allowed_evidence_ids": [],
    }
    bad = validate_response(state, "Yesterday I had a chicken sandwich at home.")
    assert not bad.ok
    assert any(
        f.startswith("invented_unknown") or f.startswith("unrelated_context_leak") or "activity" in f
        for f in bad.failures
    )


# --- 15. Contradictory / outdated location ---


def test_stale_location_vs_life_block(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    life = LifeSimulator(repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=60)
    doc = repo.get_state("sarah_taylor_001")
    # Inject stale location field that disagrees with block-derived location_key semantics
    current = dict(doc.get("current_state") or {})
    # Keep activity working/office; mark a companion outdated fact via mismatched raw field
    current["last_location"] = "home"
    repo.apply_updates("sarah_taylor_001", {"last_location": "home"})
    doc = repo.get_state("sarah_taylor_001")
    q = extract_questions("Where are you right now?")[0]
    fact = retrieve_fact_for_question(
        q, persona_id="sarah_taylor_001", persona_state=doc, state_repo=repo
    )
    assert fact.status == "established"
    value = fact.value or {}
    assert value.get("location_type") == "office" or "office" in str(value.get("location") or "").lower()
    assert value.get("at_home") is False


def test_attach_questions_keeps_legacy_targets(ingested_db):
    understanding = {
        "speech_act": "question",
        "intent": "ask_persona",
        "topic": "general",
        "question_target": "none",
        "question_targets": [],
    }
    out = attach_questions_to_understanding(
        understanding,
        message="What are you having for lunch?",
    )
    assert out["questions"][0]["slot"] == "meal_now"
    assert "activity_now" in out["question_targets"]


def test_materialize_deterministic_per_window(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    doc = _lunch_state(repo)
    current = doc["current_state"]
    e1 = materialize_experience(
        persona_id="sarah_taylor_001",
        activity="lunch",
        slot="meal",
        started_at=current["activity_started_at"],
        expected_end_at=current["activity_expected_end_at"],
        existing_events=[],
    )
    e2 = materialize_experience(
        persona_id="sarah_taylor_001",
        activity="lunch",
        slot="meal",
        started_at=current["activity_started_at"],
        expected_end_at=current["activity_expected_end_at"],
        existing_events=[],
    )
    assert e1["value"] == e2["value"]
    assert e1["window_key"] == e2["window_key"]


def test_close_open_experiences_on_transition():
    now = utcnow()
    events = [
        {
            "event_id": "e1",
            "slot": "meal",
            "value": "a chicken sandwich",
            "activity": "lunch",
            "ended_at": None,
            "started_at": now,
        }
    ]
    closed = close_open_experiences(events, now=now + timedelta(minutes=1), old_activity="lunch")
    assert closed[0]["ended_at"] is not None


def test_classify_slot_distinctions():
    assert classify_slot("What are you having for lunch?") == "meal_now"
    assert classify_slot("What are you doing?") == "activity_now"
    assert classify_slot("What are you working on?") == "task_now"
    assert classify_slot("What do you do?") == "occupation"
    assert classify_slot("Where is your office?") == "office"
    assert classify_slot("What are you doing tonight?") == "plan_future"
    assert classify_slot("What did you do yesterday?") == "event_past"
    assert classify_slot("Do you remember what I told you?") == "user_memory"
    assert classify_slot("What's your favourite food?") == "preference"


def test_preference_kind_from_text():
    assert preference_kind_from_text("so whats your favorite hobby ?") == "hobby"
    assert preference_kind_from_text("What's your favourite food?") == "food"
    assert preference_kind_from_text("whats your favorite dish ?") == "food"
    assert preference_kind_from_text("do you like coffee?") == "drink"
    assert preference_kind_from_text("what's your favorite color?") == "unknown"


def test_hobby_preference_not_food(ingested_db):
    """Regression: 'favorite hobby' must not answer with Italian food."""
    repo = PersonaStateRepository(ingested_db)
    qs = extract_questions("so whats your favorite hobby ?")
    assert len(qs) == 1
    assert qs[0].slot == "preference"
    assert qs[0].preference_kind == "hobby"

    fact = retrieve_fact_for_question(
        qs[0],
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    assert fact.status == "established"
    assert fact.source == "habits:favourite_hobbies"
    assert (fact.value or {}).get("habit_id") == "favourite_hobbies"
    assert (fact.value or {}).get("habit_id") != "favourite_food"

    plan = build_answer_plan(qs, [fact])
    assert plan["answers"][0]["can_answer"] is True
    assert plan["answers"][0]["preference_kind"] == "hobby"
    for phrase in ("pasta", "risotto", "italian food"):
        assert phrase in (plan.get("must_not_mention") or [])

    bubbles = " ".join(fallback_messages_from_answer_plan(plan)).lower()
    assert "pasta" not in bubbles
    assert "risotto" not in bubbles
    assert "italian" not in bubbles
    assert any(
        k in bubbles for k in ("cooking", "walking", "reading", "photography")
    )


def test_favourite_food_still_food(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    qs = extract_questions("What's your favourite food?")
    assert qs[0].preference_kind == "food"
    fact = retrieve_fact_for_question(
        qs[0],
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    assert fact.source == "habits:favourite_food"
    plan = build_answer_plan(qs, [fact])
    bubbles = " ".join(fallback_messages_from_answer_plan(plan)).lower()
    assert "pasta" in bubbles or "italian" in bubbles or "risotto" in bubbles


def test_unknown_favourite_does_not_invent_food(ingested_db):
    repo = PersonaStateRepository(ingested_db)
    qs = extract_questions("what's your favorite color?")
    assert qs[0].slot == "preference"
    assert qs[0].preference_kind == "unknown"
    fact = retrieve_fact_for_question(
        qs[0],
        persona_id="sarah_taylor_001",
        persona_state=repo.get_state("sarah_taylor_001"),
        state_repo=repo,
    )
    assert fact.status == "unknown"
    assert fact.missing == "preference_unknown"
    plan = build_answer_plan(qs, [fact])
    assert plan["answers"][0]["can_answer"] is False
    bubbles = " ".join(fallback_messages_from_answer_plan(plan)).lower()
    assert "pasta" not in bubbles
    assert "risotto" not in bubbles
    assert "italian" not in bubbles


def test_validator_rejects_food_answer_for_hobby_question(ingested_db):
    qs = extract_questions("so whats your favorite hobby ?")
    plan = {
        "answers": [
            {
                "slot": "preference",
                "text": qs[0].text,
                "preference_kind": "hobby",
                "can_answer": True,
                "direct_answer": "love cooking new recipes and walking around Manchester",
                "aliases": ["cooking", "walking", "reading", "photography"],
            }
        ],
        "allowed_slots": ["preference"],
        "disclose_fact_ids": [],
        "suppressed_fact_ids": [],
        "must_not_claim": [],
    }
    state = {
        "response_plan": plan,
        "behaviour_plan": {},
        "understanding": {"questions": [qs[0].model_dump()], "question_targets": ["habit"]},
        "conversation_context": {},
        "persona_state": {"current_state": {}},
        "allowed_evidence_ids": [],
    }
    bad = validate_response(
        state,
        "I love Italian food — especially a good pasta or risotto! 🍝",
    )
    assert "preference_topic_mismatch:hobby" in bad.failures

    good = validate_response(
        state,
        "Honestly I love cooking new recipes and walking around Manchester — reading and photography when I get the time.",
    )
    assert "preference_topic_mismatch:hobby" not in good.failures
    assert good.ok or "preference_topic_mismatch:hobby" not in good.failures


def _plan_text(message: str, *, memories: list | None = None, canonical: list | None = None) -> str:
    qs = extract_questions(message)
    facts = retrieve_facts(
        qs,
        persona_id="sarah_taylor_001",
        persona_state={},
        retrieved_memories=memories or [],
        canonical_facts=canonical,
    )
    plan = build_answer_plan(qs, facts)
    return "\n".join(fallback_messages_from_answer_plan(plan))


def test_compound_questions_answer_every_known_slot():
    two = _plan_text("Where do you live, and what do you do for work?")
    assert "Manchester" in two
    assert "Management Accountant" in two

    reordered = _plan_text("What do you do and where do you live?")
    assert "Manchester" in reordered
    assert "Management Accountant" in reordered

    three = _plan_text("Where do you live, what's your job, and what's your zodiac sign?")
    assert "Manchester" in three
    assert "Management Accountant" in three
    assert "Aries" in three

    four = _plan_text("What's your job title, who do you work for, and where is the office?")
    assert "Management Accountant" in four
    assert "Northbridge Financial Group" in four
    assert "Manchester Finance Office" in four
    assert "18 Alderbrook Square" in four

    mixed = _plan_text("Where do you live, what's your favourite planet, and what's your job?")
    assert "Manchester" in mixed
    assert "Management Accountant" in mixed
    assert "not sure" in mixed.lower() or "don't" in mixed.lower() or "haven't" in mixed.lower() or "off the top" in mixed.lower()


def test_hometown_city_and_office_name_are_distinct():
    assert "Sheffield" in _plan_text("Where did you grow up?")
    assert "Manchester" not in _plan_text("Where did you grow up?") or "Sheffield" in _plan_text("Where did you grow up?")
    based = _plan_text("Where are you based?")
    assert "Manchester" in based
    assert "Management Accountant" not in based
    city = _plan_text("Which city do you live in?")
    assert "Manchester" in city
    assert "Management Accountant" not in city
    office = _plan_text("Where is your office?")
    assert "Manchester Finance Office" in office
    assert "18 Alderbrook Square" in office


def test_canonical_fact_override_replaces_seed_city():
    text = _plan_text(
        "Where do you live?",
        canonical=[{"fact_id": "PERSONA_FACT_LIVES_IN", "object": "Leeds"}],
    )
    assert "Leeds" in text
    assert "Manchester" not in text


def test_false_premises_use_canonical_facts():
    city = _plan_text("You live in London, right?")
    assert "Manchester" in city
    assert "London" not in city
    transport = _plan_text("So you drive your own car every day?")
    assert "public transport" in transport.lower() or "don't have my own car" in transport.lower()


def test_user_memory_answers_use_latest_matching_fact():
    memories = [
        {"memory_id": "n1", "status": "active", "scope": "user", "predicate": "name", "object": "Alex", "fact": "User name is Alex", "confidence": 0.9},
        {"memory_id": "c1", "status": "active", "scope": "user", "predicate": "owns_car", "object": "Honda CR-Z", "fact": "User owns a Honda CR-Z", "confidence": 0.9},
        {"memory_id": "d1", "status": "superseded", "scope": "user", "predicate": "morning_drink", "object": "tea", "fact": "User prefers tea in the morning", "confidence": 0.85},
        {"memory_id": "d2", "status": "active", "scope": "user", "predicate": "morning_drink", "object": "coffee", "fact": "User prefers coffee in the morning", "confidence": 0.9},
        {"memory_id": "w1", "status": "active", "scope": "user", "predicate": "weekend_preference", "object": "drives", "fact": "User usually goes for drives on weekends", "confidence": 0.85},
        {"memory_id": "p1", "status": "active", "scope": "user", "predicate": "has_upcoming_event", "object": "presentation", "fact": "User has an important presentation next Friday", "confidence": 0.9},
        {"memory_id": "b1", "status": "active", "scope": "user", "predicate": "messaging_boundary", "object": "busy", "fact": "User does not like being messaged repeatedly when busy", "confidence": 0.9},
    ]
    assert "Honda" in _plan_text("What car do I drive?", memories=memories)
    assert "Jordan" in _plan_text(
        "What's my name?",
        memories=[{**memories[0], "object": "Jordan", "fact": "User name is Jordan"}],
    )
    both = _plan_text("Do you remember my name and my car?", memories=memories)
    assert "Alex" in both and "Honda" in both
    assert "coffee" in _plan_text("What do I prefer in the morning?", memories=memories).lower()
    assert "tea" not in _plan_text("What do I drink in the morning?", memories=memories).lower()
    assert "drives" in _plan_text("What do I usually do on weekends?", memories=memories).lower()
    assert "presentation" in _plan_text("What do I have coming up?", memories=memories).lower()
    assert "busy" in _plan_text("Do I like being messaged a lot when busy?", memories=memories).lower()


def test_stub_speaks_answer_plan_not_hardcoded_alex():
    from persona_runtime.qa.fake_llm import DeterministicQALLM

    stub = DeterministicQALLM()
    user = (
        "=== ANSWER_PLAN ===\n"
        + json.dumps(
            {
                "answers": [
                    {
                        "slot": "user_memory",
                        "can_answer": True,
                        "direct_answer": "name is Jordan",
                    }
                ]
            }
        )
        + "\n=== USER_MESSAGE ===\nWhat's my name?"
    )
    reply = stub(system="Generate a reply in bubbles", user=user)
    text = reply["messages"][0]["text"]
    assert "Jordan" in text
    assert "Alex" not in text

    extraction = stub(
        system="Extract memory candidates from the latest turn",
        user=json.dumps(
            {
                "user_message": "What do I drink in the morning?",
                "assistant_message": "You prefer tea in the morning.",
            }
        ),
    )
    blobs = json.dumps(extraction).lower()
    assert "tea" not in blobs or "no_memory" in blobs
    assert "coffee" not in blobs

