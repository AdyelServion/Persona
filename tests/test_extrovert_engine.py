"""Extroverted engagement layer: initiative, topics, discovery, Sarah-led mode, limits."""

from __future__ import annotations

from datetime import timedelta

from persona_runtime.conversation.discovery import discovery_stage, next_discovery_target
from persona_runtime.conversation.extrovert import apply_extrovert_layer, grounded_self_disclosure
from persona_runtime.conversation.personality import DEFAULT_PERSONALITY, load_personality, merge_personality
from persona_runtime.conversation.topic_manager import (
    UserTopicRepository,
    classify_topic,
    engagement_signal,
    suggest_transition,
)
from persona_runtime.db.time_utils import utcnow
from persona_runtime.graph.validator import validate_response
from persona_runtime.scheduling.scheduler import ResponseScheduler

P = merge_personality(None)


def _idle(**over):
    base = {
        "strategy": "simple_response",
        "conversational_move": "ACKNOWLEDGE",
        "allowed_moves": ["ACKNOWLEDGE", "REACT"],
        "should_ask_question": False,
        "ask_streak": 0,
        "notes": "low_stakes",
        "instruction": "",
    }
    return {**base, **over}


def _layer(eng, *, conv=None, card=None, topics=None, coverage=None, speech="acknowledgement", persona_repo=None):
    return apply_extrovert_layer(
        eng,
        user_id="u1",
        persona_id="sarah_taylor_001",
        understanding={"speech_act": speech, "topic": "chat"},
        conversation_context=conv or {},
        personality=P,
        user_topics=topics or [],
        profile_card=card or [],
        coverage=coverage or {},
        persona_repo=persona_repo,
    )


HOBBY_CARD = [
    {
        "memory_id": "m-photo",
        "user_id": "u1",
        "category": "hobby",
        "memory_key": "hobby",
        "predicate": "hobby",
        "object": "photography",
        "fact": "User enjoys photography",
    }
]


def test_personality_caps_questions_and_accepts_overrides(ingested_db):
    assert merge_personality({"max_questions_per_reply": 4})["max_questions_per_reply"] == 1
    assert merge_personality({"initiative": 7})["initiative"] == 1.0
    assert "how about you?" in DEFAULT_PERSONALITY["banned_phrases"]
    from persona_runtime.persona.repositories import PersonaRepository

    repo = PersonaRepository(ingested_db)
    repo.col.insert_one({"persona_id": "sarah_taylor_001", "doc_type": "personality_profile", "params": {"curiosity": 0.2}})
    assert load_personality(repo, "sarah_taylor_001")["curiosity"] == 0.2


def test_onboarding_skips_known_facts_and_is_not_replaced():
    out = _layer(
        _idle(),
        conv={
            "onboarding_step": "how_are_you",
            "recent_moves": [],
            "style_profile": {"response_length": "short", "question_tolerance": 0.2},
        },
        card=[{"memory_key": "user.location", "predicate": "lives_in", "object": "Leeds"}],
    )
    assert out["onboarding_step"] == "occupation"
    assert out["should_ask_question"] is True
    assert "day to day" in out["followup_hint"]
    assert not out.get("transition")


def test_protected_strategies_are_never_overridden():
    for strategy in ("direct_answer", "empathize", "natural_close", "respectful_disagree"):
        out = _layer(_idle(strategy=strategy), card=HOBBY_CARD)
        assert out["strategy"] == strategy
        assert not out.get("transition")


def test_thin_turn_revisits_a_known_interest_with_evidence():
    out = _layer(_idle(), card=HOBBY_CARD)
    assert out["strategy"] == "continue_earlier_topic"
    assert out["should_ask_question"] is True
    assert out["transition"]["evidence_memory_id"] == "m-photo"
    assert "photography" in out["followup_hint"]


def test_no_initiative_right_after_a_question_unless_sarah_led():
    assert _layer(_idle(ask_streak=1), card=HOBBY_CARD)["strategy"] == "simple_response"
    led = _layer(
        _idle(ask_streak=1),
        card=HOBBY_CARD,
        conv={"session_mode": "sarah_led", "sarah_led_turns_left": 2},
    )
    assert led["strategy"] in {"continue_earlier_topic", "fresh_topic"}
    assert led["sarah_led"] is True
    assert _layer(_idle(ask_streak=2), conv={"session_mode": "sarah_led", "sarah_led_turns_left": 2})[
        "strategy"
    ] == "simple_response"


def test_short_style_users_are_not_pushed():
    conv = {"style_profile": {"response_length": "short"}}
    assert _layer(_idle(), card=HOBBY_CARD, conv=conv)["strategy"] == "simple_response"


def test_declined_topics_are_never_suggested():
    topics = [{"topic": "hobbies", "declined": True}]
    out = _layer(_idle(), card=HOBBY_CARD, topics=topics)
    assert out.get("transition", {}).get("topic") != "hobbies"
    for _ in range(5):
        t = suggest_transition(user_id="u1", topics=topics, declined_topics=["music", "sports"])
        assert t and t["topic"] not in {"hobbies", "music", "sports"}


def test_fresh_topic_carries_one_discovery_target_and_respects_gap():
    out = _layer(_idle())
    assert out["strategy"] == "fresh_topic"
    assert out["discovery_target"]["area"] in {"everyday", "hobbies", "weekends"}
    conv = {"last_discovery_turn": 3, "response_history": [{}] * 4}
    assert "discovery_target" not in _layer(_idle(), conv=conv)


def test_discovery_stage_and_targets():
    assert discovery_stage({}) == "getting_to_know"
    assert discovery_stage({"hobby": 2, "profile": 3}) == "building"
    assert discovery_stage({"hobby": 5, "profile": 5}) == "familiar"
    t = next_discovery_target(coverage={}, known_keys={"occupation", "hobby"})
    assert t["area"] == "weekends"
    assert next_discovery_target(coverage={}, known_keys=set(), declined_topics=["everyday", "hobbies", "weekends"]) is None


def test_grounded_self_disclosure_uses_persona_canon(runtime):
    share = grounded_self_disclosure(runtime.persona_repo, runtime.settings.default_persona_id, "food")
    assert share and share["excerpt"]
    assert grounded_self_disclosure(runtime.persona_repo, runtime.settings.default_persona_id, None) is None


def test_topic_repo_tracks_depth_cooldown_and_is_per_user(db):
    repo = UserTopicRepository(db)
    for _ in range(4):
        repo.record_turn("u1", "p", "music", user_text="I love this album so much!", previous_topic="music")
    doc = repo.get("u1", "p", "music")
    assert doc["cooldown_until"] and doc["interest_level"] > 0.5
    repo.mark_declined("u1", "p", "sports")
    assert repo.get("u1", "p", "sports")["declined"] is True
    assert repo.list("u2", "p") == []


def test_topic_classification_and_engagement_signal():
    assert classify_topic("I went to a gig last night, the band was great") == "music"
    assert classify_topic("") is None
    assert engagement_signal("meh") < 0 < engagement_signal("I absolutely love it, honestly it's the best thing ever!")


def test_validator_blocks_bounce_backs_and_double_questions():
    state = {"personality": P, "response_plan": {"should_ask_question": True}}
    assert any(f.startswith("banned_phrase") for f in validate_response(state, "Nice! How about you?").failures)
    assert "too_many_questions" in validate_response(state, "Where was it? Who did you go with?").failures
    assert validate_response(state, "Oh that sounds fun. Who did you go with?").ok


def test_reply_to_outbound_starts_sarah_led_mode(runtime):
    persona_id = runtime.settings.default_persona_id
    user = runtime.user_repo.create(display_name="Alex")
    uid = user["user_id"]
    conv = runtime.conversation_repo.get_or_create(persona_id, uid)
    runtime.proactive_settings_repo.get_or_create(uid, persona_id, enabled=True)
    runtime.proactive_settings_repo.record_outbound(uid, persona_id, outbound_id="ob-1", proactive_type="new_topic")
    sched = ResponseScheduler(
        conversation_repo=runtime.conversation_repo,
        job_repo=runtime.job_repo,
        state_repo=runtime.state_repo,
        relationship_repo=runtime.relationship_repo,
        settings=runtime.settings,
        proactive_settings_repo=runtime.proactive_settings_repo,
        conversation_context_repo=runtime.conversation_context_repo,
    )
    sched.accept_user_message(conversation_id=conv["conversation_id"], persona_id=persona_id, user_id=uid, content="haha yeah")
    ctx = runtime.conversation_context_repo.get(conv["conversation_id"])
    assert ctx["session_mode"] == "sarah_led"
    assert ctx["sarah_led_turns_left"] == runtime.settings.sarah_led_turns
    prefs = runtime.proactive_settings_repo.get(uid, persona_id)
    assert prefs["unanswered_outbound_id"] is None


def test_graph_turn_records_topics_and_counts_down_sarah_led(runtime):
    persona_id = runtime.settings.default_persona_id
    uid = runtime.user_repo.create(display_name="Jo")["user_id"]
    conv = runtime.conversation_repo.get_or_create(persona_id, uid)
    cid = conv["conversation_id"]
    runtime.conversation_context_repo.get_or_create(conversation_id=cid, persona_id=persona_id, user_id=uid)
    runtime.conversation_context_repo.update(cid, {"session_mode": "sarah_led", "sarah_led_turns_left": 1})
    text = "I went to a gig last night and the band was amazing"
    msg = runtime.conversation_repo.add_message(conversation_id=cid, sender="user", content=text)
    result = runtime.run(
        event_type="user_message", user_id=uid, conversation_id=cid, incoming_message=text,
        user_message_id=msg["message_id"], pending_messages=[msg],
    )
    assert result.get("personality", {}).get("max_questions_per_reply") == 1
    ctx = runtime.conversation_context_repo.get(cid)
    assert ctx["sarah_led_turns_left"] == 0 and ctx["session_mode"] == "normal"
    assert runtime.topic_repo.get(uid, persona_id, "music") is not None
    assert runtime.topic_repo.list("someone-else", persona_id) == []


def test_revisit_skips_recently_discussed_topic():
    now = utcnow()
    topics = [{"topic": "hobbies", "last_discussed_at": now - timedelta(hours=1), "times_discussed": 3}]
    t = suggest_transition(user_id="u1", topics=topics, profile_card=HOBBY_CARD, now=now)
    assert t and not (t["kind"] == "revisit" and t["topic"] == "hobbies")
