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
