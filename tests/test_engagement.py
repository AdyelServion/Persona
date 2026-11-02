"""Deterministic tests for conversational engagement (no live LLM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from persona_runtime.api.main import _public_metadata
from persona_runtime.conversation.dates import occurs_at_datetime, parse_relative_date
from persona_runtime.conversation.engagement import select_strategy
from persona_runtime.conversation.proactive import evaluate_proactive_policy
from persona_runtime.conversation.topics import (
    apply_topic_turn,
    detect_declined_topic,
    detect_proactive_opt_out,
)
from persona_runtime.conversation.voice import select_tone
from persona_runtime.graph.bubbles import is_fragment_bubble, merge_fragment_bubbles
from persona_runtime.memory.retrieval import MemoryRetriever
from persona_runtime.memory.schemas import MemoryCandidate


def test_onboarding_asks_where_they_live_then_one_basic_at_a_time():
    how = select_strategy(
        understanding={
            "speech_act": "acknowledgement",
            "topic": "opening",
            "importance": "low",
            "emotional_intensity": "low",
        },
        conversation_context={
            "onboarding_step": "how_are_you",
            "recent_moves": ["ASK"],
            "style_profile": {"response_length": "short", "question_tolerance": 0.2},
        },
        incoming_message="I'm good thanks",
    )
    assert how["onboarding_step"] == "lives_in"
    assert how["should_ask_question"] is True
    assert "where they live" in how["followup_hint"]

    work = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "location",
            "importance": "medium",
            "emotional_intensity": "low",
        },
        conversation_context={
            "onboarding_step": "lives_in",
            "recent_moves": ["ASK", "ASK"],
            "style_profile": {},
            "user_facts_this_conversation": [{"predicate": "lives_in", "object": "Leeds"}],
        },
        incoming_message="I live in Leeds",
    )
    assert work["onboarding_step"] == "occupation"
    assert work["should_ask_question"] is True
    assert "day to day" in work["followup_hint"]

    hobby = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "everyday",
            "importance": "medium",
            "emotional_intensity": "low",
        },
        conversation_context={
            "onboarding_step": "occupation",
            "recent_moves": ["ASK", "ASK"],
            "style_profile": {},
            "user_facts_this_conversation": [{"predicate": "occupation", "object": "nurse"}],
        },
        incoming_message="I'm a nurse",
    )
    assert hobby["onboarding_step"] == "hobby"
    assert hobby["should_ask_question"] is True

    done = select_strategy(
        understanding={
            "speech_act": "acknowledgement",
            "topic": "hobbies",
            "importance": "low",
            "emotional_intensity": "low",
        },
        conversation_context={
            "onboarding_step": "hobby",
            "recent_moves": ["ASK", "ASK"],
            "style_profile": {},
        },
        incoming_message="Mostly chess",
    )
    assert done["onboarding_step"] == "done"
    assert done["should_ask_question"] is False


def test_onboarding_stops_when_declined_and_pauses_for_a_direct_question():
    declined = select_strategy(
        understanding={
            "speech_act": "acknowledgement",
            "topic": "location",
            "importance": "low",
            "emotional_intensity": "low",
        },
        conversation_context={"onboarding_step": "lives_in", "recent_moves": [], "style_profile": {}},
        incoming_message="I'd rather not talk about that",
    )
    assert declined["onboarding_step"] == "done"
    assert declined["should_ask_question"] is False

    asked = select_strategy(
        understanding={
            "speech_act": "question",
            "requires_information": True,
            "topic": "lunch",
            "importance": "medium",
            "emotional_intensity": "low",
            "questions": [{"slot": "meal_now", "text": "What are you having for lunch?"}],
        },
        conversation_context={"onboarding_step": "how_are_you", "recent_moves": [], "style_profile": {}},
        incoming_message="What are you having for lunch?",
    )
    assert asked["strategy"] == "direct_answer"
    assert "onboarding_step" not in asked


def test_humanize_text_drops_dashes_and_keeps_hyphenated_words():
    from persona_runtime.graph.bubbles import humanize_text, messages_state_update
    from persona_runtime.graph.nodes import generate_response
    from persona_runtime.prompts.registry import PROMPT_SEEDS

    assert humanize_text("programming—any recent projects") == "programming, any recent projects"
    assert humanize_text("Hey — how's your day going?") == "Hey, how's your day going?"
    assert humanize_text("beach – mountain") == "beach, mountain"
    assert humanize_text("Hey -- how's your day going?") == "Hey, how's your day going?"
    assert humanize_text("movie-at-home") == "movie-at-home"
    packed = messages_state_update(["Hey — how's your day?"])
    assert "—" not in packed["generated_response"]
    assert " -- " not in packed["generated_response"]

    busy = generate_response(
        {"busy_ack": True, "persona_state": {"current_state": {"current_activity": "meeting"}}},
        None,
    )
    assert "—" not in busy["generated_response"]
    assert "–" not in busy["generated_response"]
    assert " -- " not in busy["generated_response"]
    assert "meeting" in busy["generated_response"].lower()

    opening = next(seed for seed in PROMPT_SEEDS if seed["name"] == "opening_generation")
    assert opening["version"] == 8
    assert "em dash" in opening["system_prompt_template"].lower()


def test_opener_style_follows_interests_and_rejects_the_script():
    from persona_runtime.conversation.engagement import (
        fallback_opener,
        is_robotic_opener,
        opener_style,
    )

    travel = opener_style("Adeel Ahmed", ["travel"])
    programming = opener_style("Daniyal Muzammil", ["programming"])
    first = opener_style("Adeel Ahmed", [])
    assert travel["categories"] == ["travel"]
    assert travel["first_name"] == "Adeel"
    assert any("travel" in line.lower() or "visited" in line.lower() for line in travel["examples"])
    assert programming["categories"] == ["hobbies"]
    assert programming["first_name"] == "Daniyal"
    assert first["categories"] == ["first_time"]
    assert any("day going" in line.lower() for line in first["examples"])
    assert is_robotic_opener("Hey Daniyal Muzammil. You mentioned programming — how are you?")
    assert is_robotic_opener("Hey Adeel. Still into photography? How are you?")
    assert not is_robotic_opener("Hey! How's your day going so far?")
    fallback = fallback_opener(travel, "user-a")[0]
    assert fallback in travel["examples"]
    assert not is_robotic_opener(fallback)


def test_signup_interests_skip_the_hobby_question():
    done = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "everyday",
            "importance": "medium",
            "emotional_intensity": "low",
        },
        conversation_context={
            "onboarding_step": "occupation",
            "signup_interests": ["photography"],
            "recent_moves": ["ASK", "ASK"],
            "style_profile": {},
        },
        incoming_message="I'm a nurse",
    )
    assert done["onboarding_step"] == "done"
    assert done["should_ask_question"] is False


def test_opening_plan_asks_only_how_they_are():
    from persona_runtime.graph.context_builder import build_prompt_context
    from persona_runtime.graph.nodes import response_plan

    state = {
        "event_type": "conversation_start",
        "user_id": "user-adeel",
        "user_context": {
            "display_name": "Adeel",
            "profile": {"display_name": "Adeel", "interests": ["photography"]},
        },
        "understanding": {"speech_act": "greeting", "topic": "opening"},
        "behaviour_plan": {
            "conversational_move": "ASK",
            "allowed_moves": ["ASK", "REACT"],
            "warmth": 0.6,
            "engagement": {
                "strategy": "answer_plus_followup",
                "should_ask_question": True,
            },
        },
        "engagement_brief": {
            "strategy": "answer_plus_followup",
            "should_ask_question": True,
        },
        "conversation_context": {},
        "persona_state": {
            "current_state": {
                "current_activity": "working",
                "current_task": "monthly financial reporting",
                "current_location": "office",
            }
        },
        "retrieved_memories": [],
        "allowed_evidence_ids": [],
    }
    out = response_plan(state, None)
    plan = out["response_plan"]
    points = " ".join(plan["talking_points"])
    assert plan["should_ask_question"] is True
    assert plan["onboarding_step"] == "how_are_you"
    assert plan["opener_style"]["categories"] == ["hobbies"]
    assert "photography" in plan["opener_style"]["interests"]
    assert "write a natural opener" in points
    assert "financial reporting" not in points.lower()
    prompt = build_prompt_context({**state, "response_plan": plan})
    assert "CURRENT_STATE" not in prompt
    assert "financial reporting" not in prompt.lower()
    assert "photography" in prompt.lower()
    assert "use this opener exactly" not in prompt.lower()


def test_lunch_question_direct_answer_no_followup():
    brief = select_strategy(
        understanding={
            "speech_act": "question",
            "requires_information": True,
            "topic": "lunch",
            "importance": "medium",
            "emotional_intensity": "low",
            "questions": [{"slot": "meal_now", "text": "What are you having for lunch?"}],
        },
        conversation_context={"recent_moves": [], "style_profile": {}},
        incoming_message="What are you having for lunch?",
    )
    assert brief["strategy"] == "direct_answer"
    assert brief["should_ask_question"] is False
    assert "ASK" not in brief["allowed_moves"]


def test_travelling_disclosure_may_followup_or_share():
    brief = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "travel",
            "importance": "medium",
            "emotional_intensity": "low",
            "requires_information": False,
        },
        conversation_context={
            "recent_moves": [],
            "style_profile": {"response_length": "medium", "question_tolerance": 0.6},
        },
        incoming_message="I like travelling.",
        voice_tone={"tone": "curious"},
    )
    assert brief["strategy"] in {"answer_plus_followup", "relevant_self_disclosure"}
    if brief["strategy"] == "answer_plus_followup":
        assert brief["should_ask_question"] is True
        assert brief["followup_hint"]


def test_terrible_day_blocks_fresh_topic():
    brief = select_strategy(
        understanding={
            "speech_act": "emotional_statement",
            "topic": "work",
            "importance": "high",
            "emotional_intensity": "high",
            "user_emotion": "frustrated",
        },
        conversation_context={"recent_moves": [], "open_threads": [], "style_profile": {}},
        incoming_message="I had a terrible day.",
    )
    assert brief["strategy"] == "empathize"
    assert brief["strategy"] != "fresh_topic"
    assert "CHANGE_TOPIC" not in brief["allowed_moves"]


def test_topic_switch_follows_user():
    conv = {
        "current_topic": "work",
        "previous_topics": [],
        "open_threads": [],
        "declined_topics": [],
        "style_profile": {},
    }
    updates = apply_topic_turn(
        conv,
        understanding={"topic": "music", "speech_act": "self_disclosure", "importance": "medium"},
        incoming="I've been listening to a lot of jazz lately",
    )
    assert updates["current_topic"] == "music"
    assert "work" in updates["previous_topics"]
    assert any(t.get("topic") == "work" for t in updates["open_threads"])


def test_third_consecutive_question_blocked():
    brief = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "hobbies",
            "importance": "medium",
            "emotional_intensity": "low",
        },
        conversation_context={
            "recent_moves": ["ASK", "ASK"],
            "style_profile": {"question_tolerance": 0.8},
        },
        incoming_message="I also like cooking.",
    )
    assert brief["should_ask_question"] is False
    assert "ASK" not in brief["allowed_moves"]
    assert "ask_streak" in brief["notes"] or brief["ask_streak"] >= 2


def test_driving_test_awaiting_outcome_not_passed(ingested_db):
    from persona_runtime.memory.repositories import MemoryRepository

    repo = MemoryRepository(ingested_db)
    past = datetime.now(timezone.utc) - timedelta(days=2)
    doc = repo.create_memory(
        "episodic",
        {
            "persona_id": "sarah_taylor_001",
            "user_id": "engage-user",
            "scope": "user",
            "event_description": "I'm taking my driving test next Friday.",
            "importance": 0.85,
            "confidence": 0.9,
            "occurs_at": past,
            "horizon": "upcoming",
            "outcome_known": False,
        },
    )
    retriever = MemoryRetriever(repo)
    due = retriever.due_followups(
        persona_id="sarah_taylor_001",
        user_id="engage-user",
        now=datetime.now(timezone.utc),
    )
    assert due
    assert due[0]["memory_id"] == doc["memory_id"]
    assert due[0]["horizon"] == "awaiting_outcome"
    assert due[0].get("outcome_known") is not True

    # Engagement on greeting may surface the follow-up without inventing pass/fail
    brief = select_strategy(
        understanding={
            "speech_act": "greeting",
            "topic": "general",
            "importance": "low",
            "emotional_intensity": "low",
        },
        conversation_context={"recent_moves": [], "style_profile": {"question_tolerance": 0.6}},
        due_followups=due,
        incoming_message="Hey",
        event_type="user_message",
    )
    assert brief["strategy"] == "continue_earlier_topic"
    assert "passed" not in (brief.get("followup_hint") or "").lower()


def test_proactive_disabled_and_opt_out_block_resume():
    settings = SimpleNamespace(
        proactive_outbound_enabled=False,
        proactive_min_interval_hours=12.0,
        proactive_max_per_day=1,
    )
    denied = evaluate_proactive_policy(
        situation="user_resumed",
        settings=settings,
        conversation_context={"proactive_opt_out": False},
        persona_state={"current_state": {"availability": 0.8, "sleeping": False}},
    )
    assert denied["allow_outbound"] is False
    assert denied.get("use_engagement_in_reply") is True

    opted = evaluate_proactive_policy(
        situation="user_resumed",
        settings=SimpleNamespace(
            proactive_outbound_enabled=True,
            proactive_min_interval_hours=12.0,
            proactive_max_per_day=1,
        ),
        conversation_context={"proactive_opt_out": True},
        persona_state={"current_state": {"availability": 0.8, "sleeping": False}},
    )
    assert opted["allow_outbound"] is False
    assert opted["situation"] == "user_opted_out"


def test_fragment_bubble_detected_and_merged():
    assert is_fragment_bubble("Wait,")
    assert is_fragment_bubble("Wait")
    merged = merge_fragment_bubbles(["Wait,", "you drove all the way there?"])
    assert len(merged) == 1
    assert "drove" in merged[0].lower()
    natural = merge_fragment_bubbles(
        ["Wait, you drove all the way there?", "How long did it take you?"]
    )
    assert len(natural) == 2


def test_voice_tone_supportive_for_hard_day():
    tone = select_tone(
        understanding={
            "speech_act": "emotional_statement",
            "emotional_intensity": "high",
            "user_emotion": "sad",
            "importance": "high",
        },
        incoming_message="Work was awful today.",
    )
    assert tone["tone"] == "supportive"


def test_declined_topic_and_opt_out_detection():
    assert detect_declined_topic("I don't want to talk about that", "exes") == "exes"
    assert detect_proactive_opt_out("Please don't message me")


def test_relative_date_next_friday():
    clock = {"local_date": "2026-10-15"}  # Thursday
    d = parse_relative_date("I'm taking my driving test next Friday", clock=clock)
    assert d is not None
    assert d.isoformat() == "2026-10-16"
    occurs = occurs_at_datetime("driving test tomorrow", clock=clock)
    assert occurs is not None
    assert occurs.date().isoformat() == "2026-10-16"


def test_public_metadata_strips_orchestration():
    public = _public_metadata(
        {
            "behaviour_plan": {"x": 1},
            "response_plan": {"y": 2},
            "understanding": {},
            "bubble_index": 0,
            "bubble_count": 2,
            "request_id": "abc",
        }
    )
    assert "behaviour_plan" not in public
    assert "response_plan" not in public
    assert public["bubble_index"] == 0
    assert public["request_id"] == "abc"


def test_memory_candidate_time_fields():
    when = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
    c = MemoryCandidate(
        memory_type="episodic",
        importance=0.9,
        confidence=0.9,
        event_description="driving test",
        occurs_at=when,
        horizon="upcoming",
        outcome_known=False,
    )
    data = c.model_dump()
    assert data["horizon"] == "upcoming"
    assert data["outcome_known"] is False


def test_short_style_suppresses_questions():
    brief = select_strategy(
        understanding={
            "speech_act": "self_disclosure",
            "topic": "food",
            "importance": "low",
            "emotional_intensity": "low",
        },
        conversation_context={
            "recent_moves": [],
            "style_profile": {"response_length": "short", "question_tolerance": 0.2},
        },
        incoming_message="Cool.",
    )
    assert brief["should_ask_question"] is False
