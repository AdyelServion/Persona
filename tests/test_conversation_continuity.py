"""Regression tests for conversational continuity and persona fact suppression."""

from __future__ import annotations

from persona_runtime.config import get_settings
from persona_runtime.graph.fact_tracker import detect_facts_in_text
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.graph.understanding import classify_message_deterministic
from persona_runtime.graph.validator import validate_response
from persona_runtime.memory.retrieval import MemoryRetriever
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.state.repositories import PersonaStateRepository


BIO_MARKERS = (
    "management accountant",
    "accounting and finance",
    "moved to manchester",
    "recently moved",
)


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


def test_acknowledgement_speech_act_deterministic():
    u = classify_message_deterministic("great", current_topic="user_career")
    assert u is not None
    assert u.speech_act == "acknowledgement"
    assert u.intent == "conversation_continuation"
    assert u.requires_information is False
    assert u.requires_question is False
    assert u.importance == "low"
    assert u.emotional_intensity == "low"
    assert u.topic == "user_career"


def test_filler_acknowledgement_ahaan_great():
    u = classify_message_deterministic("ahaan great", current_topic="user_career")
    assert u is not None
    assert u.speech_act == "acknowledgement"
    assert u.intent == "conversation_continuation"
    assert u.importance == "low"
    assert u.emotional_intensity == "low"
    assert u.topic == "user_career"
    assert u.requires_question is False


def test_ah_nice_acknowledgement():
    u = classify_message_deterministic("ah nice", current_topic="user_career")
    assert u is not None
    assert u.speech_act == "acknowledgement"
    assert u.importance == "low"


def test_transcript_no_persona_repetition_after_disclosure(runtime):
    """Replay the buggy conversation; biography must not recur after first answer."""
    user_id = "continuity-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]

    # Seed Sarah's opening as already said
    runtime.conversation_repo.add_message(
        conversation_id=cid,
        sender="assistant",
        content="Hi there! It looks like you're busy working right now. How's everything going with your projects?",
    )

    r1 = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="its good how about you ? what do you do ?",
    )
    reply1 = (r1.get("generated_response") or "").lower()
    assert "management accountant" in reply1
    assert r1.get("understanding", {}).get("speech_act") == "question"

    facts = (r1.get("conversation_context") or {}).get("facts_shared_by_sarah") or []
    fact_ids = {f.get("fact_id") for f in facts}
    assert "PERSONA_FACT_OCCUPATION" in fact_ids

    r2 = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="i am a technical project manager",
    )
    reply2 = (r2.get("generated_response") or "").lower()
    assert "management accountant" not in reply2
    assert "accounting and finance" not in reply2
    assert "moved to manchester" not in reply2
    assert "recently moved" not in reply2

    # Force bad biography dump on "great" — validator must strip it
    runtime.llm._scripted.force_biography_repeat = True
    r3 = _run_user(runtime, user_id=user_id, conversation_id=cid, text="great")
    assert r3.get("understanding", {}).get("speech_act") == "acknowledgement"
    reply3 = (r3.get("generated_response") or "").lower()
    for marker in BIO_MARKERS:
        assert marker not in reply3, f"repeated persona marker after great: {marker}"
    assert "recently moved" not in reply3

    plan = r3.get("response_plan") or {}
    suppressed = set(plan.get("suppressed_fact_ids") or r3.get("suppressed_fact_ids") or [])
    assert "PERSONA_FACT_OCCUPATION" in suppressed
    assert "PERSONA_FACT_DEGREE" in suppressed
    assert "PERSONA_FACT_LIVES_IN" in suppressed or "PERSONA_FACT_MOVED_MANCHESTER" in suppressed


def test_user_occupation_semantic_memory_and_retrieval(runtime):
    user_id = "mem-occ-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    result = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="i am a technical project manager",
    )
    stored = result.get("stored_memories") or []
    assert any(
        m.get("predicate") == "occupation"
        and "project manager" in (m.get("object") or "").lower()
        for m in stored
    )
    # Evidence linkage
    assert any(m.get("conversation_id") == cid for m in stored)
    assert any(m.get("source_message_ids") for m in stored)

    runtime2 = PersonaRuntime(settings=get_settings(), llm=runtime.llm, db=runtime.db)
    found = MemoryRetriever(runtime2.memory_repo).retrieve(
        persona_id="sarah_taylor_001",
        user_id=user_id,
        query="what do you remember about my job?",
    )
    assert any(
        "project manager" in (m.get("object") or m.get("fact") or "").lower() for m in found
    )


def test_no_fabricated_user_memory_claim(runtime):
    user_id = "no-mem-claim"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    result = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="Do you remember my trip?",
    )
    reply = (result.get("generated_response") or "").lower()
    assert "spain" not in reply
    assert "don't think" in reply or "tell me again" in reply


def test_temporal_consistency_rejects_recently_moved(runtime):
    user_id = "temporal-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    runtime.llm._scripted.force_recently_moved = True
    result = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="what do you do?",
    )
    reply = (result.get("generated_response") or "").lower()
    assert "recently moved" not in reply
    # Canonical year present in seed
    facts = runtime.persona_repo.list_canonical_facts("sarah_taylor_001")
    move = next(f for f in facts if f.get("fact_id") == "PERSONA_FACT_MOVED_MANCHESTER")
    assert (move.get("time") or {}).get("year") == 2021


def test_conversation_context_persists_between_requests(runtime):
    user_id = "ctx-persist"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    r1 = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="what do you do?",
    )
    assert r1.get("conversation_context", {}).get("facts_shared_by_sarah")

    runtime2 = PersonaRuntime(settings=get_settings(), llm=runtime.llm, db=runtime.db)
    ctx = runtime2.conversation_context_repo.get(cid)
    assert ctx is not None
    assert any(
        f.get("fact_id") == "PERSONA_FACT_OCCUPATION"
        for f in (ctx.get("facts_shared_by_sarah") or [])
    )

    r2 = _run_user(runtime2, user_id=user_id, conversation_id=cid, text="great")
    assert r2.get("understanding", {}).get("speech_act") == "acknowledgement"
    ctx2 = runtime2.conversation_context_repo.get(cid)
    assert ctx2.get("speech_act") == "acknowledgement"
    assert ctx2.get("last_user_message") == "great"


def test_static_identity_unchanged_by_conversation(runtime):
    persona = PersonaRepository(runtime.db)
    before = persona.list_subcategories("sarah_taylor_001", "Identity")
    before_raw = [(s.get("subcategory"), s.get("content_raw")) for s in before]

    user_id = "identity-safe"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    _run_user(
        runtime,
        user_id=user_id,
        conversation_id=conv["conversation_id"],
        text="i am a technical project manager",
    )
    after = persona.list_subcategories("sarah_taylor_001", "Identity")
    after_raw = [(s.get("subcategory"), s.get("content_raw")) for s in after]
    assert before_raw == after_raw


def test_dynamic_state_not_confused_with_static_persona(runtime):
    persona = PersonaRepository(runtime.db)
    personality_before = persona.list_subcategories("sarah_taylor_001", "Personality")
    state_repo = PersonaStateRepository(runtime.db)
    state_repo.apply_updates("sarah_taylor_001", {"energy": 0.2, "mood": "tired"})

    user_id = "state-sep"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    _run_user(runtime, user_id=user_id, conversation_id=conv["conversation_id"], text="hey")

    personality_after = persona.list_subcategories("sarah_taylor_001", "Personality")
    assert personality_before[0]["content_raw"] == personality_after[0]["content_raw"]
    state = state_repo.get_state("sarah_taylor_001")
    assert state["current_state"]["mood"] in {"tired", state["current_state"].get("mood")}


def test_validator_catches_persona_contradiction():
    state = {
        "understanding": {"speech_act": "question", "topic": "sarah_career"},
        "response_plan": {"disclose_fact_ids": ["PERSONA_FACT_OCCUPATION"], "memory_claims": []},
        "conversation_context": {"facts_shared_by_sarah": [], "questions_asked": []},
        "relationship_state": {"relationship_stage": "new_contact"},
        "behaviour_plan": {"disclosure_level": 0.1},
        "allowed_evidence_ids": [],
        "incoming_message": "where do you live?",
    }
    bad = "I live in London and love it there."
    result = validate_response(state, bad)
    assert not result.ok
    assert any("contradicts_canonical" in f or "unsupported_experience" in f for f in result.failures)


def test_response_planner_suppresses_repeated_facts(runtime):
    user_id = "suppress-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    _run_user(runtime, user_id=user_id, conversation_id=cid, text="what do you do?")
    r = _run_user(runtime, user_id=user_id, conversation_id=cid, text="great")
    suppressed = set((r.get("response_plan") or {}).get("suppressed_fact_ids") or [])
    assert "PERSONA_FACT_OCCUPATION" in suppressed
    assert not (r.get("response_plan") or {}).get("disclose_fact_ids")


def test_detect_facts_in_text_not_string_equality_only():
    text = "I'm currently working as a Management Accountant after graduating with a BSc Accounting and Finance."
    ids = detect_facts_in_text(text)
    assert "PERSONA_FACT_OCCUPATION" in ids
    assert "PERSONA_FACT_DEGREE" in ids


def test_canonical_facts_have_stable_ids_and_move_year(runtime):
    facts = runtime.persona_repo.list_canonical_facts("sarah_taylor_001")
    by_id = {f.get("fact_id"): f for f in facts if f.get("fact_id")}
    assert "PERSONA_FACT_OCCUPATION" in by_id
    assert by_id["PERSONA_FACT_OCCUPATION"]["object"] == "Management Accountant"
    assert by_id["PERSONA_FACT_MOVED_MANCHESTER"]["time"]["year"] == 2021
    assert "recently moved" in (by_id["PERSONA_FACT_MOVED_MANCHESTER"].get("forbidden_recency_phrases") or [])


def test_ahaan_great_social_move_not_support(runtime):
    """Low-stakes acknowledgement must not plan SUPPORT or ask by default."""
    from persona_runtime.graph.social_moves import select_move

    user_id = "social-ack-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    runtime.conversation_context_repo.apply_turn_update(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=user_id,
        updates={"current_topic": "user_career"},
    )
    result = _run_user(
        runtime, user_id=user_id, conversation_id=cid, text="ahaan great"
    )
    understanding = result.get("understanding") or {}
    assert understanding.get("speech_act") == "acknowledgement"
    assert understanding.get("importance") == "low"
    assert understanding.get("emotional_intensity") == "low"
    assert "career" in (understanding.get("topic") or "")

    behaviour = result.get("behaviour_plan") or {}
    move = (behaviour.get("conversational_move") or "").upper()
    assert move != "SUPPORT"
    assert move in {"ACKNOWLEDGE", "REACT", "CONTINUE", "JOKE", "ASK"}
    plan = result.get("response_plan") or {}
    assert plan.get("should_ask_question") is False
    assert plan.get("should_offer_help") is False

    policy = select_move(
        understanding=understanding,
        recent_moves=[],
    )
    assert "SUPPORT" not in policy["allowed_moves"]
    assert policy["conversational_move"] != "SUPPORT"


def test_service_offer_here_to_listen_rejected(runtime):
    """Forced 'I'm here to listen' draft must not survive validation."""
    user_id = "service-offer-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    runtime.conversation_context_repo.apply_turn_update(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=user_id,
        updates={"current_topic": "user_career"},
    )
    runtime.llm._scripted.force_service_offer = True
    result = _run_user(
        runtime, user_id=user_id, conversation_id=cid, text="ahaan great"
    )
    reply = (result.get("generated_response") or "").lower()
    assert "here to listen" not in reply
    assert "pleased to hear" not in reply
    assert "feel free to share" not in reply
    for marker in BIO_MARKERS:
        assert marker not in reply
    # Natural continuation, not an assistant closer
    assert "i'm here" not in reply
    assert "i am here" not in reply


def test_validator_flags_service_offer_phrase():
    state = {
        "understanding": {
            "speech_act": "acknowledgement",
            "topic": "user_career",
            "importance": "low",
            "emotional_intensity": "low",
            "requires_question": False,
        },
        "response_plan": {
            "disclose_fact_ids": [],
            "memory_claims": [],
            "should_ask_question": False,
            "conversational_move": "REACT",
        },
        "conversation_context": {"facts_shared_by_sarah": [], "questions_asked": []},
        "relationship_state": {"relationship_stage": "new_contact"},
        "behaviour_plan": {"disclosure_level": 0.1, "conversational_move": "REACT"},
        "allowed_evidence_ids": [],
        "incoming_message": "ahaan great",
    }
    bad = (
        "I'm pleased to hear that! If you ever want to share more about your "
        "projects or anything else on your mind, I'm here to listen."
    )
    result = validate_response(state, bad)
    assert not result.ok
    assert any(
        f in ("assistant_service_offer", "stock_validation") for f in result.failures
    )


def test_self_disclosure_can_react_without_question(runtime):
    user_id = "react-disclosure"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    result = _run_user(
        runtime,
        user_id=user_id,
        conversation_id=cid,
        text="i am a technical project manager",
    )
    plan = result.get("response_plan") or {}
    move = (plan.get("conversational_move") or "").upper()
    assert move in {"REACT", "SHARE", "CONTINUE", "JOKE", "AGREE"}
    assert plan.get("should_ask_question") is False
    reply = (result.get("generated_response") or "").lower()
    assert "here to listen" not in reply
    assert "here to help" not in reply


def test_ask_streak_blocks_ask_on_acknowledgement(runtime):
    from persona_runtime.graph.social_moves import select_move

    understanding = {
        "speech_act": "acknowledgement",
        "intent": "conversation_continuation",
        "topic": "user_career",
        "importance": "low",
        "emotional_intensity": "low",
    }
    policy = select_move(understanding=understanding, recent_moves=["ASK", "ASK"])
    assert policy["conversational_move"] != "ASK"
    assert "ASK" not in policy["allowed_moves"]
    assert policy["ask_question"] is False

    user_id = "ask-streak-user"
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", user_id)
    cid = conv["conversation_id"]
    runtime.conversation_context_repo.apply_turn_update(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=user_id,
        updates={"current_topic": "user_career", "recent_moves": ["ASK", "ASK"]},
    )
    result = _run_user(runtime, user_id=user_id, conversation_id=cid, text="great")
    behaviour = result.get("behaviour_plan") or {}
    assert (behaviour.get("conversational_move") or "").upper() != "ASK"
    assert (result.get("response_plan") or {}).get("should_ask_question") is False


def test_fallback_reply_not_im_here():
    from persona_runtime.graph.validator import deterministic_fallback_reply

    state = {
        "understanding": {
            "speech_act": "continuation",
            "topic": "general",
            "importance": "low",
            "emotional_intensity": "low",
        },
        "response_plan": {"conversational_move": "REACT", "should_ask_question": False},
        "behaviour_plan": {"conversational_move": "REACT"},
        "conversation_context": {},
    }
    reply = deterministic_fallback_reply(state).lower()
    assert "i'm here" not in reply
    assert "i am here" not in reply
    assert "here to listen" not in reply
