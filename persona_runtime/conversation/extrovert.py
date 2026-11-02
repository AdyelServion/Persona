"""Extroverted engagement layer applied on top of the base engagement brief.

The base brief (engagement.select_strategy) decides what the turn *needs* (answer,
empathy, close...). This layer only adds initiative on turns that leave room for it:
keeping a thin conversation alive, revisiting a known interest, opening a fresh topic,
one discovery target, and grounded self-disclosure. It never overrides answers,
empathy, closings or disagreement, and never adds a second question.
"""

from __future__ import annotations

from typing import Any

from persona_runtime.conversation.discovery import discovery_stage, next_discovery_target
from persona_runtime.conversation.engagement import known_onboarding_keys, stamp_onboarding_brief
from persona_runtime.conversation.topic_manager import TOPIC_CATALOGUE, suggest_transition

PROTECTED_STRATEGIES = {"direct_answer", "empathize", "natural_close", "respectful_disagree"}
IDLE_STRATEGIES = {"simple_response", "playful_reaction", "relevant_self_disclosure"}


def sarah_led_active(conv: dict[str, Any] | None) -> bool:
    conv = conv or {}
    return conv.get("session_mode") == "sarah_led" and int(conv.get("sarah_led_turns_left") or 0) > 0


def _turn_index(conv: dict[str, Any]) -> int:
    return len(conv.get("response_history") or [])


def _short_style(conv: dict[str, Any]) -> bool:
    style = conv.get("style_profile") or {}
    return style.get("response_length") == "short" or float(
        style.get("question_tolerance") if style.get("question_tolerance") is not None else 0.55
    ) < 0.4


def grounded_self_disclosure(persona_repo: Any, persona_id: str, topic: str | None) -> dict[str, Any] | None:
    """A canonical Preferences entry related to the topic, so Sarah shares real canon only."""
    if not topic or persona_repo is None:
        return None
    keywords = [topic] + list(TOPIC_CATALOGUE.get(topic, {}).get("keywords", ()))[:6]
    try:
        matches = persona_repo.find_subcategories_by_keywords(persona_id, "Preferences", keywords)
    except Exception:  # noqa: BLE001
        return None
    for sub in matches or []:
        text = str(sub.get("content_raw") or "").strip()
        if text:
            return {
                "subcategory": sub.get("subcategory"),
                "excerpt": text[:240],
                "rule": "share at most one short line of this, in your own words; do not embellish",
            }
    return None


def apply_extrovert_layer(
    engagement: dict[str, Any],
    *,
    user_id: str,
    persona_id: str,
    understanding: dict[str, Any] | None,
    conversation_context: dict[str, Any] | None,
    personality: dict[str, Any],
    user_topics: list[dict[str, Any]] | None,
    profile_card: list[dict[str, Any]] | None,
    coverage: dict[str, int] | None,
    persona_repo: Any = None,
    event_type: str = "user_message",
) -> dict[str, Any]:
    eng = dict(engagement or {})
    conv = conversation_context or {}
    understanding = understanding or {}
    notes = [n for n in str(eng.get("notes") or "").split(";") if n]
    if event_type != "user_message":
        return eng
    strategy = eng.get("strategy") or "simple_response"
    if strategy in PROTECTED_STRATEGIES:
        return eng

    led = sarah_led_active(conv)
    ask_streak = int(eng.get("ask_streak") or 0)
    can_ask = ask_streak < int(personality.get("ask_streak_limit", 2)) and not _short_style(conv)
    declined = list(conv.get("declined_topics") or []) + [
        t["topic"] for t in (user_topics or []) if t.get("declined")
    ]
    recent = [conv.get("current_topic") or ""] + list(conv.get("previous_topics") or [])[-3:]
    current_topic = understanding.get("topic") or conv.get("current_topic") or ""
    topic_doc = next((t for t in (user_topics or []) if t.get("topic") == current_topic), {})
    exhausted = int(topic_doc.get("explored_depth") or 0) >= int(personality.get("topic_depth_before_switch", 3))
    initiative = float(personality.get("initiative", 0.7))

    speech = understanding.get("speech_act") or ""
    eng = stamp_onboarding_brief(
        eng,
        conv,
        known_keys=known_onboarding_keys(conv, profile_card),
        declined_topics=declined,
        speech_act=speech,
        incoming_message=str(understanding.get("text") or ""),
    )
    if eng.get("onboarding_active"):
        topic_for_share = eng.get("topic") or current_topic
        if float(personality.get("self_disclosure_rate", 0.5)) >= 0.4 and topic_for_share in TOPIC_CATALOGUE:
            share = grounded_self_disclosure(persona_repo, persona_id, topic_for_share)
            if share:
                eng["self_disclosure"] = share
                eng["should_self_disclose"] = True
        eng["discovery_stage"] = discovery_stage(coverage)
        eng["sarah_led"] = led
        if eng.get("followup_hint") and eng.get("should_ask_question"):
            eng["instruction"] = (
                str(eng.get("instruction") or "")
                + " React to what they said first. One question only."
            ).strip()
        return eng

    thin_turn = speech in {"acknowledgement", "continuation"} or exhausted
    wants_initiative = led or (ask_streak == 0 and thin_turn and initiative >= 0.6)

    # 1. Keep a thin conversation alive instead of letting it die on "ok"/"nice"
    if strategy in IDLE_STRATEGIES and can_ask and wants_initiative:
        transition = suggest_transition(
            user_id=user_id,
            topics=list(user_topics or []),
            profile_card=profile_card,
            declined_topics=declined,
            recent_topics=[r for r in recent if r],
        )
        if transition:
            revisit = transition["kind"] == "revisit"
            eng.update(
                {
                    "strategy": "continue_earlier_topic" if revisit else "fresh_topic",
                    "allowed_strategies": ["continue_earlier_topic" if revisit else "fresh_topic"],
                    "conversational_move": "ASK" if revisit else "CHANGE_TOPIC",
                    "allowed_moves": ["ASK", "CHANGE_TOPIC", "SHARE", "REACT"],
                    "should_ask_question": True,
                    "topic": transition["topic"],
                    "followup_hint": transition["hint"],
                    "transition": transition,
                }
            )
            notes.append("extrovert_transition" + (":sarah_led" if led else ""))

    # 2. One discovery target, only where a question is already happening
    if eng.get("should_ask_question") and eng.get("strategy") in {"fresh_topic", "answer_plus_followup", "continue_earlier_topic"}:
        last_disc = conv.get("last_discovery_turn")
        gap = int(personality.get("discovery_min_turn_gap", 2))
        if last_disc is None or _turn_index(conv) - int(last_disc) >= gap:
            known = {str(c.get("memory_key") or c.get("predicate") or "") for c in (profile_card or [])}
            target = next_discovery_target(
                coverage=coverage, known_keys=known, declined_topics=declined, recent_topics=None
            )
            if target and eng.get("strategy") == "fresh_topic" and not eng.get("transition", {}).get("subject"):
                eng["discovery_target"] = target
                eng["topic"] = target["area"]
                eng["followup_hint"] = f"casually find out {target['hint']}"
                notes.append(f"discovery:{target['area']}")

    # 3. Reciprocal, grounded self-disclosure on the active topic
    topic_for_share = eng.get("topic") or current_topic
    if float(personality.get("self_disclosure_rate", 0.5)) >= 0.4 and topic_for_share in TOPIC_CATALOGUE:
        share = grounded_self_disclosure(persona_repo, persona_id, topic_for_share)
        if share:
            eng["self_disclosure"] = share
            eng["should_self_disclose"] = True

    eng["discovery_stage"] = discovery_stage(coverage)
    eng["sarah_led"] = led
    eng["notes"] = ";".join(notes)
    if eng.get("followup_hint") and eng.get("should_ask_question"):
        eng["instruction"] = (
            str(eng.get("instruction") or "")
            + f" Lead the conversation: {eng['followup_hint']}. One question at most,"
            " and add your own take or a short related share so it isn't an interview."
        ).strip()
    return eng
