"""Current reality layers: now-questions vs permanent identity."""

from __future__ import annotations

from persona_runtime.graph.fact_tracker import (
    compute_disclosure_plan,
    user_asks_about_fact,
)
from persona_runtime.graph.bubbles import (
    join_messages,
    normalize_generated_messages,
)
from persona_runtime.graph.reality import (
    build_world_state,
    classify_question_target,
    classify_question_targets,
    world_state_fallback_messages,
    world_state_fallback_reply,
)
from persona_runtime.graph.understanding import classify_message_deterministic
from persona_runtime.graph.validator import deterministic_fallback_reply, validate_response
from persona_runtime.life.simulator import LifeSimulator


BIO_MARKERS = (
    "management accountant",
    "accounting and finance",
    "living in manchester",
    "been living in manchester",
)

TRANSCRIPT_BURST = [
    "so what's your zodic sign ?",
    "where are you right now ?",
    "and what are you currently working on ?",
    "are you at home ?",
    "where is your office ?",
]


def _run_user(runtime, *, user_id: str, conversation_id: str, text: str):
    msg = runtime.conversation_repo.add_message(
        conversation_id=conversation_id, sender="user", content=text
    )
    return runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id=user_id,
        conversation_id=conversation_id,
        incoming_message=text,
        user_message_id=msg["message_id"],
    )


def test_you_work_not_matched_inside_working():
    assert user_asks_about_fact("so what are you working on ?", "PERSONA_FACT_OCCUPATION") is False
    assert classify_question_target("so what are you working on ?") == "current_task"
    assert classify_question_target("what do you do?") == "permanent_identity"
    assert classify_question_target("So where are you at this time ?") == "location_now"
    assert classify_question_target("where do you live?") == "permanent_identity"
    assert classify_question_target("where is your office ?") == "office_location"
    assert classify_question_target("are you at home ?") == "at_home"
    assert classify_question_target("so what's your zodic sign ?") == "zodiac"
    assert classify_question_target("where is your office ?") != "habit"
    assert classify_question_target("whats your favorite dish ?") == "habit"
    assert classify_question_target("what's your favourite food?") == "habit"


FAVORITE_THEN_DOING = [
    "whats your favorite dish ?",
    "what are you doing right now ?",
]


def test_favorite_dish_then_doing_keeps_user_order():
    targets = classify_question_targets(
        "\n".join(FAVORITE_THEN_DOING),
        pending_messages=FAVORITE_THEN_DOING,
    )
    assert targets == ["habit", "activity_now"]

    u = classify_message_deterministic(
        "\n".join(FAVORITE_THEN_DOING),
        pending_messages=[{"content": m} for m in FAVORITE_THEN_DOING],
    )
    assert u is not None
    assert u.question_targets == ["habit", "activity_now"]
    assert u.topic == "preferences"


def test_activity_now_lunch_fallback_omits_desk_task():
    world = {
        "date": "2026-10-12",
        "time": "12:40",
        "location": "Manchester Finance Office",
        "location_type": "office",
        "activity": "lunch",
        "current_task": "monthly financial reporting",
        "task_detail": (
            "checking the revenue figures and making sure everything "
            "reconciles before the report goes out"
        ),
        "current_project": "Monthly Financial Reporting",
        "situation": "at the office, having lunch",
        "availability": "available_for_chat",
        "next_planned_activity": "get back to my desk",
    }
    activity_reply = world_state_fallback_reply(
        "activity_now", world=world, targets=["activity_now"]
    ).lower()
    assert "lunch" in activity_reply
    assert "financial reporting" not in activity_reply
    assert "revenue" not in activity_reply

    messages = world_state_fallback_messages(
        "habit", world=world, targets=["habit", "activity_now"]
    )
    assert len(messages) == 2
    joined = "\n".join(messages).lower()
    # Habit fallback is topic-agnostic; food is only for food preference via answer_plan
    assert "lunch" in joined
    assert "financial reporting" not in joined
    assert "revenue" not in joined


def test_where_are_you_is_not_lives_in_fact():
    assert user_asks_about_fact("where are you right now?", "PERSONA_FACT_LIVES_IN") is False
    assert user_asks_about_fact("where do you live?", "PERSONA_FACT_LIVES_IN") is True


def test_working_on_disclosure_suppresses_biography():
    understanding = {
        "speech_act": "question",
        "topic": "current_situation",
        "question_target": "current_task",
        "requires_information": True,
    }
    plan = compute_disclosure_plan(
        understanding=understanding,
        facts_shared_by_sarah=[],
        incoming_message="what are you working on?",
    )
    assert plan["disclose_fact_ids"] == []
    assert "PERSONA_FACT_OCCUPATION" in plan["suppressed_fact_ids"]


def test_what_do_you_do_still_discloses_occupation():
    understanding = {
        "speech_act": "question",
        "topic": "sarah_career",
        "question_target": "permanent_identity",
        "requires_information": True,
    }
    plan = compute_disclosure_plan(
        understanding=understanding,
        facts_shared_by_sarah=[],
        incoming_message="what do you do?",
    )
    assert "PERSONA_FACT_OCCUPATION" in plan["disclose_fact_ids"]


def test_deterministic_classification_working_on():
    u = classify_message_deterministic("so what are you working on ?")
    assert u is not None
    assert u.question_target == "current_task"
    assert u.topic == "current_situation"
    assert u.speech_act == "question"


def test_follow_up_after_current_task():
    u = classify_message_deterministic(
        "Sounds boring 😂",
        last_question_target="current_task",
    )
    assert u is not None
    assert u.question_target == "follow_up"


def test_world_state_fallback_uses_task():
    world = {
        "location": "office",
        "activity": "working",
        "current_task": "monthly financial reporting",
        "task_detail": "checking the numbers and making sure everything reconciles",
        "situation": "at the office at my desk",
        "availability": "available_for_chat",
    }
    reply = world_state_fallback_reply("current_task", world=world).lower()
    assert "monthly financial reporting" in reply
    assert "management accountant" not in reply


def test_validator_rejects_biography_on_now_question():
    state = {
        "understanding": {"question_target": "location_now", "speech_act": "question"},
        "response_plan": {"question_target": "location_now", "disclose_fact_ids": [], "suppressed_fact_ids": []},
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_location": "office",
                "situation": "at the office at my desk",
            }
        },
        "behaviour_plan": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "incoming_message": "where are you right now?",
    }
    result = validate_response(
        state,
        "I'm currently out with friends, enjoying some time in the city.",
    )
    assert not result.ok
    assert any("unsupported_activity_claim" in f or "unsupported_location_claim" in f for f in result.failures)

    bio = validate_response(
        state,
        "I'm a Management Accountant. I studied Accounting and Finance. I've been living in Manchester for a few years now.",
    )
    assert "biography_instead_of_now" in bio.failures


def test_fallback_for_now_not_biography():
    state = {
        "understanding": {"question_target": "current_task", "speech_act": "question"},
        "response_plan": {
            "question_target": "current_task",
            "disclose_fact_ids": ["PERSONA_FACT_OCCUPATION"],  # should be ignored
            "world_state": {
                "location": "office",
                "activity": "working",
                "current_task": "monthly financial reporting",
                "task_detail": "checking the numbers",
                "situation": "at the office at my desk",
            },
        },
        "conversation_context": {},
        "persona_state": {"current_state": {"current_activity": "working"}},
        "behaviour_plan": {},
    }
    reply = deterministic_fallback_reply(state).lower()
    assert "monthly financial reporting" in reply
    for marker in BIO_MARKERS:
        assert marker not in reply


def test_work_block_persists_stable_task(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    state1 = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]
    assert state1["current_activity"] == "working"
    assert state1["current_location"] == "office"
    assert state1.get("current_task")
    assert state1.get("situation")
    task = state1["current_task"]

    # Same pin window — task must stay
    life.advance_if_needed("sarah_taylor_001")
    state2 = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]
    assert state2["current_task"] == task


def test_where_are_you_stable_and_not_friends_while_working(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    user_id = "reality-where-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]

    r1 = _run_user(runtime, user_id=user_id, conversation_id=cid, text="So where are you at this time ?")
    reply1 = (r1.get("generated_response") or "").lower()
    assert r1.get("understanding", {}).get("question_target") == "location_now"
    assert "office" in reply1 or "desk" in reply1
    assert "out with friends" not in reply1
    for marker in BIO_MARKERS:
        assert marker not in reply1

    r2 = _run_user(runtime, user_id=user_id, conversation_id=cid, text="So where are you at this time ?")
    reply2 = (r2.get("generated_response") or "").lower()
    assert "office" in reply2 or "desk" in reply2
    assert "out with friends" not in reply2


def test_working_on_answers_task_not_biography(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    task = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]["current_task"]
    user_id = "reality-task-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]

    r1 = _run_user(runtime, user_id=user_id, conversation_id=cid, text="so what are you working on ?")
    reply1 = (r1.get("generated_response") or "").lower()
    assert r1.get("understanding", {}).get("question_target") == "current_task"
    assert task.lower() in reply1
    for marker in BIO_MARKERS:
        assert marker not in reply1
    assert (r1.get("response_plan") or {}).get("disclose_fact_ids") == []

    r2 = _run_user(runtime, user_id=user_id, conversation_id=cid, text="Sounds boring 😂")
    reply2 = (r2.get("generated_response") or "").lower()
    assert r2.get("understanding", {}).get("question_target") == "follow_up"
    for marker in BIO_MARKERS:
        assert marker not in reply2
    # Stay on the task / situation thread
    assert task.lower() in reply2 or "moment" in reply2 or "haha" in reply2


def test_what_do_you_do_still_discloses_job(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    user_id = "reality-job-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]

    r1 = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="what do you do ?",
    )
    reply1 = (r1.get("generated_response") or "").lower()
    assert r1.get("understanding", {}).get("question_target") == "permanent_identity"
    assert "management accountant" in reply1


def test_transcript_burst_targets_not_only_location():
    joined = "\n".join(TRANSCRIPT_BURST)
    targets = classify_question_targets(joined, pending_messages=TRANSCRIPT_BURST)
    assert "zodiac" in targets
    assert "location_now" in targets
    assert "current_task" in targets
    assert "at_home" in targets
    assert "office_location" in targets
    assert targets != ["location_now"]

    u = classify_message_deterministic(
        joined,
        pending_messages=[{"content": m} for m in TRANSCRIPT_BURST],
    )
    assert u is not None
    assert set(u.question_targets) >= {
        "zodiac",
        "location_now",
        "current_task",
        "at_home",
        "office_location",
    }


def test_office_question_not_habit_only():
    assert classify_question_target("where is your office located ?") == "office_location"
    world = build_world_state(
        {
            "current_activity": "lunch",
            "current_location": "office",
            "location_type": "office",
            "situation": "at the office, having lunch",
            "current_task": "monthly financial reporting",
            "current_project": "Monthly Financial Reporting",
            "next_activity": "working",
            "next_planned_activity": "get back to my desk",
        }
    )
    reply = world_state_fallback_reply(
        "office_location", world=world, targets=["office_location"]
    ).lower()
    assert "alderbrook" in reply or "northbridge" in reply
    assert "usually work from an office" not in reply


def test_lunch_keeps_workday_task_and_named_world_state(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    working = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]
    task = working["current_task"]
    project = working.get("current_project")
    assert task
    assert project

    life.force_activity("sarah_taylor_001", "lunch", duration_minutes=45)
    lunch = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]
    assert lunch["current_activity"] == "lunch"
    assert lunch["current_location"] == "office"
    assert lunch["current_task"] == task
    assert lunch.get("current_project") == project
    assert "near work" not in (lunch.get("situation") or "").lower()

    world = build_world_state(lunch)
    assert world["location_type"] == "office"
    assert "manchester finance office" in (world["location"] or "").lower()
    assert world["current_task"] == task
    assert world.get("current_project") == project
    assert world.get("date")
    assert world.get("time")


def test_transcript_burst_fallback_covers_layers():
    world = {
        "date": "2026-10-07",
        "time": "12:45",
        "location": "Manchester Finance Office",
        "location_type": "office",
        "activity": "lunch",
        "current_task": "monthly financial reporting",
        "task_detail": (
            "checking the revenue figures and making sure everything "
            "reconciles before the report goes out"
        ),
        "current_project": "Monthly Financial Reporting",
        "situation": "at the office, having lunch",
        "availability": "available_for_chat",
        "next_planned_activity": "get back to my desk",
    }
    targets = [
        "zodiac",
        "location_now",
        "at_home",
        "office_location",
        "current_task",
    ]
    messages = world_state_fallback_messages(
        "location_now", world=world, targets=targets
    )
    assert len(messages) == len(targets)
    reply = world_state_fallback_reply(
        "location_now", world=world, targets=targets
    ).lower()
    assert "aries" in reply
    assert "office" in reply or "lunch" in reply
    assert "monthly financial reporting" in reply or "revenue" in reply
    assert "nope" in reply or "not" in reply or "work" in reply
    assert "alderbrook" in reply or "northbridge" in reply
    assert "usually work from an office" not in reply


def test_normalize_splits_combined_multi_target_into_bubbles():
    world = {
        "location": "Manchester Finance Office",
        "location_type": "office",
        "activity": "working",
        "current_task": "monthly financial reporting",
        "task_detail": "comparing budget against actuals",
        "current_project": "Monthly Financial Reporting",
        "situation": "at the office, at my desk",
    }
    targets = ["zodiac", "location_now", "current_task"]
    state = {
        "understanding": {
            "question_target": "zodiac",
            "question_targets": targets,
        },
        "response_plan": {"world_state": world, "question_targets": targets},
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_location": "office",
                "current_task": "monthly financial reporting",
            }
        },
    }
    combined = (
        "I'm an Aries. I'm at the office right now. "
        "I'm comparing the budget against the actuals at the moment."
    )
    texts = normalize_generated_messages([combined], state)
    assert len(texts) == 3
    joined = join_messages(texts).lower()
    assert "aries" in joined
    assert "office" in joined or "desk" in joined
    assert "monthly financial reporting" in joined or "budget" in joined or "actuals" in joined


def test_normalize_keeps_single_location_bubble():
    state = {
        "understanding": {
            "question_target": "location_now",
            "question_targets": ["location_now"],
        },
        "response_plan": {},
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_location": "office",
            }
        },
    }
    texts = normalize_generated_messages(["I'm at the office right now."], state)
    assert len(texts) == 1
    assert "office" in texts[0].lower()


def test_validator_rejects_internal_persona_data():
    state = {
        "understanding": {
            "question_target": "location_now",
            "question_targets": ["location_now"],
            "speech_act": "question",
        },
        "response_plan": {
            "question_target": "location_now",
            "question_targets": ["location_now"],
            "disclose_fact_ids": [],
            "suppressed_fact_ids": [],
        },
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_location": "office",
            }
        },
        "behaviour_plan": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "incoming_message": "where are you?",
    }
    bad = validate_response(state, "My world state says I'm at the office.")
    assert "exposes_internal_persona_data" in bad.failures
    bad2 = validate_response(state, "I retrieved that from my memory — I'm at work.")
    assert "exposes_internal_persona_data" in bad2.failures


def test_multi_question_persists_one_message_per_target(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    user_id = "bubble-burst-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    pending = []
    for text in TRANSCRIPT_BURST:
        msg = runtime.conversation_repo.add_message(
            conversation_id=cid, sender="user", content=text
        )
        pending.append(msg)

    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id=user_id,
        conversation_id=cid,
        incoming_message="\n".join(TRANSCRIPT_BURST),
        user_message_id=pending[-1]["message_id"],
        pending_messages=pending,
        response_strategy="RESPOND_TO_GROUP",
    )
    targets = list((result.get("understanding") or {}).get("question_targets") or [])
    assert len(targets) >= 3
    generated = list(result.get("generated_messages") or [])
    assert len(generated) == len(targets)
    assistant = [
        m
        for m in runtime.conversation_repo.list_messages(cid)
        if m.get("sender") == "assistant"
    ]
    assert len(assistant) == len(generated)
    joined = (result.get("generated_response") or "").lower()
    assert "aries" in joined
    assert "office" in joined or "desk" in joined


def test_office_location_runtime_reply(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    user_id = "reality-office-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]

    r1 = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="where is your office ?",
    )
    reply1 = (r1.get("generated_response") or "").lower()
    assert r1.get("understanding", {}).get("question_target") == "office_location"
    assert "alderbrook" in reply1 or "northbridge" in reply1
    assert "usually work from an office" not in reply1


def test_validator_rejects_habit_as_office_answer():
    state = {
        "understanding": {
            "question_target": "office_location",
            "question_targets": ["office_location"],
            "speech_act": "question",
        },
        "response_plan": {
            "question_target": "office_location",
            "question_targets": ["office_location"],
            "disclose_fact_ids": ["PERSONA_FACT_OFFICE"],
            "suppressed_fact_ids": [],
        },
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_location": "office",
            }
        },
        "behaviour_plan": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "incoming_message": "where is your office ?",
    }
    bad = validate_response(
        state,
        "I usually work from an office. It's a great environment for focusing on my tasks.",
    )
    assert "habit_instead_of_office_location" in bad.failures

    good = validate_response(
        state,
        "It's in Manchester city centre. I work for Northbridge Financial Group, "
        "and our finance office is at 18 Alderbrook Square.",
    )
    assert "habit_instead_of_office_location" not in good.failures


def test_favorite_dish_then_doing_runtime_bubbles(runtime):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=120)
    life.force_activity("sarah_taylor_001", "lunch", duration_minutes=45)
    user_id = "favorite-dish-doing-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    pending = []
    for text in FAVORITE_THEN_DOING:
        msg = runtime.conversation_repo.add_message(
            conversation_id=cid, sender="user", content=text
        )
        pending.append(msg)

    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id=user_id,
        conversation_id=cid,
        incoming_message="\n".join(FAVORITE_THEN_DOING),
        user_message_id=pending[-1]["message_id"],
        pending_messages=pending,
        response_strategy="RESPOND_TO_GROUP",
    )
    targets = list((result.get("understanding") or {}).get("question_targets") or [])
    assert targets == ["habit", "activity_now"]
    generated = list(result.get("generated_messages") or [])
    assert len(generated) == 2
    joined = (result.get("generated_response") or "").lower()
    assert "pasta" in joined or "italian" in joined or "risotto" in joined
    assert "lunch" in joined
    assert "financial reporting" not in joined
    assert "revenue" not in joined
    assistant = [
        m
        for m in runtime.conversation_repo.list_messages(cid)
        if m.get("sender") == "assistant"
    ]
    assert len(assistant) == 2
