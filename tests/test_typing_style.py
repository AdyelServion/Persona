"""Typing-style config, emoji enforcement, and prompt rules. No live model."""

from __future__ import annotations

from persona_runtime.conversation.typing_style import (
    SARAH_TYPING_STYLE,
    load_typing_style,
    merge_typing_style,
    typos_allowed_for_turn,
    typing_style_brief,
)
from persona_runtime.graph.bubbles import contains_emoji, messages_state_update, strip_emojis
from persona_runtime.graph.nodes import generate_response
from persona_runtime.graph.validator import deterministic_fallback_reply, validate_response
from persona_runtime.outbound.briefs import fallback_messages
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.prompts.registry import PROMPT_SEEDS
from persona_runtime.qa.typing_style_score import score_reply


def test_sarah_style_merges_and_rejects_unknown_slang():
    merged = merge_typing_style({**SARAH_TYPING_STYLE, "slang_intensity": "shouting", "intentional_typo_rate": 4})
    assert merged["style"] == "casual_gen_z"
    assert merged["emoji_enabled"] is False
    assert merged["slang_intensity"] == "none"
    assert merged["intentional_typo_rate"] == 1.0
    assert merged["max_intentional_typos_per_message"] == 1
    assert merge_typing_style(None)["emoji_enabled"] is True


def test_typing_style_seeded_and_not_overwritten(ingested_db):
    repo = PersonaRepository(ingested_db)
    loaded = load_typing_style(repo, "sarah_taylor_001")
    assert loaded is not None
    assert loaded["emoji_enabled"] is False
    assert loaded["intentional_typo_rate"] == 0.12
    repo.upsert_typing_style("sarah_taylor_001", {"style": "neutral", "emoji_enabled": True}, overwrite=False)
    again = load_typing_style(repo, "sarah_taylor_001")
    assert again is not None
    assert again["style"] == "casual_gen_z"
    assert again["emoji_enabled"] is False


def test_missing_document_loads_nothing(ingested_db):
    repo = PersonaRepository(ingested_db)
    assert load_typing_style(repo, "someone_else") is None


def test_strip_removes_emoji_and_keeps_words():
    assert strip_emojis("hahaha that's actually funny 😂") == "hahaha that's actually funny"
    assert strip_emojis("sounds good to me ❤️") == "sounds good to me"
    assert not contains_emoji(strip_emojis("oh really? 😊"))
    packed = messages_state_update(
        ["oh nice 😊", "😂"],
        typing_style=SARAH_TYPING_STYLE,
    )
    assert packed["generated_messages"] == [{"text": "oh nice", "type": "text"}]
    assert "😊" not in packed["generated_response"]
    untouched = messages_state_update(["oh nice 😊"])
    assert "😊" in untouched["generated_response"]


def test_typos_blocked_on_facts_and_allowed_on_chat():
    style = SARAH_TYPING_STYLE
    chat = typos_allowed_for_turn(style, {"incoming_message": "you like coffee?"})
    assert chat is True
    calc = typos_allowed_for_turn(style, {"incoming_message": "what is 15% of 200?"})
    assert calc is False
    code = typos_allowed_for_turn(
        style,
        {
            "incoming_message": "can you write c++ code for me?",
            "capability_decision": {"classification": {"request_type": "produce_artifact", "domain": "programming"}},
        },
    )
    assert code is False
    place = typos_allowed_for_turn(
        style,
        {
            "incoming_message": "where do you live?",
            "understanding": {"question_target": "permanent_identity"},
        },
    )
    assert place is False
    brief = typing_style_brief(style, {"incoming_message": "you like coffee?"})
    assert brief["typos_allowed"] is True
    assert brief["emoji_enabled"] is False


def test_generation_prompts_forbid_emoji_and_defer_to_style():
    wanted = {
        "response_generation": 11,
        "response_repair": 10,
        "opening_generation": 8,
        "proactive_generation": 3,
    }
    for seed in PROMPT_SEEDS:
        if seed["name"] not in wanted:
            continue
        text = seed["system_prompt_template"].lower()
        assert seed["version"] == wanted[seed["name"]]
        assert "typing_style" in text
        assert "emoji_enabled false" in text
        assert "light emoji" not in text
        assert "em dash" in text


def test_canned_sarah_lines_have_no_emoji():
    busy = generate_response(
        {
            "busy_ack": True,
            "persona_state": {"current_state": {"current_activity": "meeting"}},
            "typing_style": SARAH_TYPING_STYLE,
        },
        None,
    )
    assert not contains_emoji(busy["generated_response"])
    assert "meeting" in busy["generated_response"].lower()
    for kind in ("event_followup", "hobby_followup", "returning_user_greeting", "new_topic"):
        text = " ".join(fallback_messages({"proactive_type": kind, "subject": "photography", "topic": "everyday"}))
        assert not contains_emoji(text)
    reply = deterministic_fallback_reply(
        {
            "understanding": {"speech_act": "acknowledgement", "topic": "career"},
            "response_plan": {"should_ask_question": True, "conversational_move": "REACT"},
            "behaviour_plan": {},
            "conversation_context": {},
            "persona_state": {},
        }
    )
    assert not contains_emoji(reply)
    assert "—" not in reply


def test_validator_flags_emoji_only_when_style_disables_them():
    state = {
        "typing_style": SARAH_TYPING_STYLE,
        "understanding": {"speech_act": "acknowledgement"},
        "response_plan": {"should_ask_question": False},
        "behaviour_plan": {},
        "conversation_context": {},
        "persona_state": {},
        "relationship_state": {"relationship_stage": "new_contact"},
        "incoming_message": "nice",
    }
    failed = validate_response(state, "yeah thats funny 😂")
    assert "emoji_present" in failed.failures
    clean = validate_response({**state, "typing_style": None}, "yeah thats funny 😂")
    assert "emoji_present" not in clean.failures


def test_score_does_not_pass_formal_prose_or_stacked_slang():
    formal = score_reply("I am currently working on a financial report.", emoji=False)
    assert formal["natural"] == "Fail"
    assert formal["overall"] == "Fail"
    stacked = score_reply("heyyy lol ngl fr thats so cool tbh", emoji=False)
    assert stacked["slang"] == "Fail"
    plain = score_reply("yeah i kinda get what you mean", emoji=False)
    assert plain["overall"] == "Pass"
    assert plain["typo"] == "Not Applicable"
    slipped = score_reply("yeah thats definately interesting", emoji=False)
    assert slipped["typo"] == "Pass"
    assert score_reply("nice 😂", emoji=True)["emoji"] == "Yes"
