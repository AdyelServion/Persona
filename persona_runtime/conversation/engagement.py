"""Conversation engagement engine — one strategy per turn, not a checklist."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from persona_runtime.conversation.topics import detect_declined_topic
from persona_runtime.graph.social_moves import ConversationalMove

Strategy = Literal[
    "direct_answer",
    "answer_plus_observation",
    "answer_plus_followup",
    "empathize",
    "playful_reaction",
    "relevant_self_disclosure",
    "continue_earlier_topic",
    "fresh_topic",
    "share_opinion",
    "respectful_disagree",
    "natural_close",
    "simple_response",
]

STRATEGY_TO_MOVES: dict[str, list[ConversationalMove]] = {
    "direct_answer": ["SHARE", "REACT", "ACKNOWLEDGE", "CONTINUE"],
    "answer_plus_observation": ["SHARE", "REACT", "CONTINUE"],
    "answer_plus_followup": ["SHARE", "ASK", "REACT", "CLARIFY"],
    "empathize": ["SUPPORT", "REACT", "CLARIFY", "ACKNOWLEDGE"],
    "playful_reaction": ["JOKE", "REACT", "ACKNOWLEDGE"],
    "relevant_self_disclosure": ["SHARE", "REACT", "CONTINUE", "AGREE"],
    "continue_earlier_topic": ["CONTINUE", "ASK", "REACT", "SHARE"],
    "fresh_topic": ["CHANGE_TOPIC", "ASK", "SHARE", "REACT"],
    "share_opinion": ["SHARE", "AGREE", "DISAGREE", "REACT"],
    "respectful_disagree": ["DISAGREE", "CLARIFY", "REACT"],
    "natural_close": ["END_CONVERSATION", "ACKNOWLEDGE"],
    "simple_response": ["ACKNOWLEDGE", "REACT", "CONTINUE", "WAIT"],
}


def _ask_streak(recent_moves: list[str]) -> int:
    streak = 0
    for m in reversed(recent_moves or []):
        if str(m).upper() in {"ASK", "CLARIFY"}:
            streak += 1
        else:
            break
    return streak


def _has_factual_question(understanding: dict[str, Any]) -> bool:
    if understanding.get("requires_information"):
        return True
    questions = list(understanding.get("questions") or [])
    for q in questions:
        slot = (q.get("slot") or "none").lower()
        if slot not in {"none", "follow_up", ""}:
            return True
    speech = understanding.get("speech_act") or ""
    return speech == "question" and bool(understanding.get("requires_information", True))


def _is_emotional_difficult(understanding: dict[str, Any], text: str) -> bool:
    intensity = (understanding.get("emotional_intensity") or "low").lower()
    speech = understanding.get("speech_act") or ""
    emotion = (understanding.get("user_emotion") or "").lower()
    lower = (text or "").lower()
    hard = any(
        k in lower
        for k in (
            "terrible",
            "awful",
            "horrible",
            "worst",
            "devastat",
            "heartbroken",
            "fired",
            "broke up",
            "anxiety",
            "depressed",
            "stressed out",
        )
    )
    if speech == "emotional_statement" and (intensity in {"medium", "high"} or hard):
        return True
    if hard:
        return True
    if any(k in emotion for k in ("sad", "frustrat", "angry", "upset", "stress")):
        return intensity != "low" or hard
    return False


def _style_wants_short(style: dict[str, Any]) -> bool:
    return (style or {}).get("response_length") == "short"


# Asked one per reply after Sarah's "how are you?" opener. Not the full discovery catalogue.
_ONBOARDING_AFTER = (
    (
        "lives_in",
        ("lives_in", "location", "user.location"),
        "location",
        "acknowledge what they just said, then ask where they live",
    ),
    (
        "occupation",
        ("occupation", "user.occupation"),
        "everyday",
        "react to their answer, then ask what they do day to day (work or study)",
    ),
    (
        "hobby",
        ("hobby", "interest", "user.hobby", "user.interest"),
        "hobbies",
        "react briefly, then ask what they enjoy doing in their free time",
    ),
)
_ONBOARDING_ORDER = ("how_are_you", "lives_in", "occupation", "hobby")
_ONBOARDING_PAUSE = {"direct_answer", "empathize", "natural_close", "respectful_disagree"}
_ROBOTIC_OPENER = re.compile(r"\byou mentioned\b|\bstill into\b", re.I)

# Tone examples for a first chat. The model writes its own line; these are not a script.
_OPENER_EXAMPLES: dict[str, tuple[str, ...]] = {
    "first_time": (
        "Hey! How's your day going so far?",
        "Hey there! What's keeping you busy today?",
        "Hii! Glad we finally got to chat. How are you?",
        "So, tell me something interesting about yourself!",
        "Hey! Are you having a productive day or one of those lazy ones?",
        "Random question: are you more of an indoor person or someone who loves going out?",
        "What's something you genuinely enjoy doing when you have free time?",
        "Hey! What's been the best part of your week so far?",
        "Let's start with something interesting. What's one thing you're really passionate about?",
        "Hey! What do you usually get up to when you're not working?",
    ),
    "hobbies": (
        "So, what do you usually do for fun?",
        "Are you into photography, gaming, sports, or something completely different?",
        "What's a hobby you could spend hours doing without getting bored?",
        "Do you enjoy trying new things, or do you prefer sticking to your usual interests?",
        "What's something you've always wanted to learn?",
        "What's one interest people might not guess about you?",
        "Have you picked up any new hobbies recently?",
    ),
    "lifestyle": (
        "Are you a morning person or a night owl?",
        "What does a normal weekend look like for you?",
        "Do you prefer going out with friends or having a quiet evening at home?",
        "What's your ideal way to spend a free Sunday?",
        "Do you enjoy spontaneous plans, or do you like everything organized?",
        "What's usually the first thing you do when you get home after work?",
        "Coffee, tea, or neither?",
    ),
    "work": (
        "What do you do when you're not busy exploring this app?",
        "Do you actually enjoy your work, or is it more of a means to an end?",
        "What does a typical working day look like for you?",
        "How did you end up in your current field?",
        "What's the most interesting part of your job?",
        "What do you usually do to unwind after a particularly busy day?",
    ),
    "travel": (
        "Are you someone who loves travelling?",
        "What's the best place you've ever visited?",
        "If you could travel anywhere next month, where would you go?",
        "More into relaxing beach holidays or adventurous mountain trips?",
        "Do you prefer travelling with friends or exploring somewhere on your own?",
        "What's one destination on your bucket list?",
        "Have you ever taken a completely unplanned trip?",
    ),
    "entertainment": (
        "What kind of music has been on repeat for you lately?",
        "What's the last really good movie you watched?",
        "Are you into series?",
        "Do you prefer comedy, thrillers, or something more emotional?",
        "What's an artist you could listen to all day?",
        "Are you a cinema person or more of a movie-at-home person?",
        "What's a show you think everyone should watch at least once?",
    ),
}
_CATEGORY_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("travel", ("travel", "travelling", "traveling", "trip", "holiday", "beach", "mountain", "adventure")),
    ("entertainment", ("music", "movie", "movies", "film", "series", "cinema", "song")),
    ("work", ("career", "job", "work")),
    ("lifestyle", ("weekend", "coffee", "tea", "morning", "night owl", "going out", "sunday")),
    ("hobbies", ("photography", "gaming", "game", "sport", "programming", "coding", "reading", "cooking", "hobby")),
)


def _stable_index(user_id: str, count: int, salt: str) -> int:
    if count <= 1:
        return 0
    digest = hashlib.sha256(f"{user_id}:{salt}".encode()).hexdigest()
    return int(digest[:8], 16) % count


def _clean_interests(interests: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in interests or []:
        text = " ".join(str(raw or "").split())
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


def _category_for_interest(interest: str) -> str:
    low = interest.lower()
    for category, keys in _CATEGORY_KEYS:
        for key in keys:
            if " " in key:
                if key in low:
                    return category
            elif re.search(rf"\b{re.escape(key)}\b", low):
                return category
    return "hobbies"


def opener_style(name: str | None, interests: list[str] | None) -> dict[str, Any]:
    """Pick example questions that match signup interests. Examples are tone, not a script."""
    first = " ".join(str(name or "").split()).split(" ")[0] if str(name or "").strip() else ""
    cleaned = _clean_interests(interests)
    if not cleaned:
        categories = ["first_time"]
    else:
        categories = []
        for interest in cleaned:
            category = _category_for_interest(interest)
            if category not in categories:
                categories.append(category)
    examples: list[str] = []
    for category in categories:
        examples.extend(_OPENER_EXAMPLES[category])
    return {
        "first_name": first,
        "interests": cleaned,
        "categories": categories,
        "examples": examples,
    }


def is_robotic_opener(text: str) -> bool:
    return bool(_ROBOTIC_OPENER.search(text or ""))


def fallback_opener(style: dict[str, Any], user_id: str | None) -> list[str]:
    """One human example from the matched group when generation fails or sounds scripted."""
    examples = list(style.get("examples") or _OPENER_EXAMPLES["first_time"])
    return [examples[_stable_index(str(user_id or ""), len(examples), "fallback")]]


def signup_from_state(state: dict[str, Any]) -> tuple[str, list[str]]:
    """Display name and interests collected when this chat was created."""
    ctx = state.get("user_context") or {}
    profile = ctx.get("profile") if isinstance(ctx.get("profile"), dict) else {}
    name = str(ctx.get("display_name") or profile.get("display_name") or "").strip()
    raw = profile.get("interests") or []
    interests = [" ".join(str(item).split()) for item in raw if str(item).strip()]
    if not interests:
        sources = list(state.get("social_context") or []) + list(ctx.get("authorized_context") or [])
        for item in sources:
            if isinstance(item, dict) and item.get("kind") == "self_declared_interest" and item.get("value"):
                interests.append(" ".join(str(item["value"]).split()))
    return name, interests


def known_onboarding_keys(
    conversation_context: dict[str, Any] | None,
    profile_card: list[dict[str, Any]] | None = None,
) -> set[str]:
    known: set[str] = set()
    conv = conversation_context or {}
    for fact in conv.get("user_facts_this_conversation") or []:
        if not isinstance(fact, dict):
            continue
        for field in ("predicate", "memory_key"):
            if fact.get(field):
                known.add(str(fact[field]).lower())
    for card in profile_card or []:
        if not isinstance(card, dict):
            continue
        for field in ("predicate", "memory_key"):
            if card.get(field):
                known.add(str(card[field]).lower())
    if conv.get("signup_interests"):
        # The opener already used a signup interest, so don't ask "what do you enjoy" next.
        known.update({"hobby", "interest", "user.hobby", "user.interest"})
    return known


def onboarding_followup(
    conversation_context: dict[str, Any] | None,
    *,
    known_keys: set[str] | None = None,
    declined_topics: list[str] | None = None,
    speech_act: str = "",
    strategy: str = "",
    incoming_message: str = "",
) -> dict[str, Any] | None:
    """Next getting-to-know-you question, or a finish marker. None if this chat is not onboarding."""
    conv = conversation_context or {}
    current = conv.get("onboarding_step")
    if current in (None, "", "done"):
        return None
    if speech_act == "conversation_closing" or detect_declined_topic(incoming_message, str(current)):
        return {"onboarding_step": "done", "onboarding_active": False, "finish_only": True}
    if strategy in _ONBOARDING_PAUSE:
        return None
    try:
        asked_idx = _ONBOARDING_ORDER.index(str(current))
    except ValueError:
        return {"onboarding_step": "done", "onboarding_active": False, "finish_only": True}

    known = {k.lower() for k in (known_keys or set()) if k}
    declined = [str(d).lower() for d in (declined_topics or []) if d]
    for step, keys, topic, hint in _ONBOARDING_AFTER:
        if _ONBOARDING_ORDER.index(step) <= asked_idx:
            continue
        if any(k.lower() in known for k in keys):
            continue
        if any(topic == d or topic in d or d in topic for d in declined):
            continue
        return {
            "onboarding_step": step,
            "onboarding_active": True,
            "followup_hint": hint,
            "topic": topic,
            "strategy": "answer_plus_followup",
        }
    return {"onboarding_step": "done", "onboarding_active": False, "finish_only": True}


def _topic_declined(topic: str, declined: list[str]) -> bool:
    if not topic:
        return False
    t = topic.lower()
    return any(t == d.lower() or t in d.lower() or d.lower() in t for d in declined)


def select_strategy(
    *,
    understanding: dict[str, Any],
    conversation_context: dict[str, Any] | None = None,
    persona_state: dict[str, Any] | None = None,
    retrieved_memories: list[dict[str, Any]] | None = None,
    due_followups: list[dict[str, Any]] | None = None,
    incoming_message: str = "",
    voice_tone: dict[str, Any] | None = None,
    event_type: str = "user_message",
) -> dict[str, Any]:
    """Return engagement brief: strategy, allowed moves, ask/disclose flags, topic hint."""
    conv = conversation_context or {}
    understanding = understanding or {}
    speech = (understanding.get("speech_act") or "").strip()
    recent_moves = list(conv.get("recent_moves") or [])
    ask_streak = _ask_streak(recent_moves)
    style = conv.get("style_profile") or {}
    declined = list(conv.get("declined_topics") or [])
    open_threads = [
        t for t in (conv.get("open_threads") or []) if isinstance(t, dict) and t.get("topic")
    ]
    topic = (understanding.get("topic") or conv.get("current_topic") or "").strip()
    current = (persona_state or {}).get("current_state") or persona_state or {}
    activity = (current.get("current_activity") or "").lower()
    tone = (voice_tone or {}).get("tone") or "casual"
    short_style = _style_wants_short(style)
    q_tol = float(style.get("question_tolerance") if style.get("question_tolerance") is not None else 0.55)
    allow_ask = ask_streak < 2 and q_tol >= 0.4 and not short_style
    factual = _has_factual_question(understanding)
    emotional = _is_emotional_difficult(understanding, incoming_message)
    due = list(due_followups or [])

    strategy: Strategy
    allow_life_aside = False
    topic_hint = topic
    followup_hint = ""
    park_thread = None
    notes: list[str] = []

    # 1. Closing
    if speech == "conversation_closing":
        strategy = "natural_close"
        allow_ask = False
        notes.append("closing")

    # 2. Emotional / difficult — acknowledge first, never fresh topic
    elif emotional:
        strategy = "empathize"
        allow_ask = allow_ask and intensity_allows_clarify(understanding)
        notes.append("emotional_first")

    # 3. Direct factual question — answer first, no follow-up question on meal/slots
    elif factual:
        strategy = "direct_answer"
        allow_ask = False
        notes.append("factual_direct")

    # 4. Disagreement
    elif speech == "disagreement":
        strategy = "respectful_disagree"
        allow_ask = False
        notes.append("disagree")

    # 5. Self-disclosure — react + optional specific follow-up or self-share
    elif speech == "self_disclosure":
        if allow_ask:
            strategy = "answer_plus_followup"
            followup_hint = f"one specific question about {topic or 'what they shared'}"
        else:
            strategy = "relevant_self_disclosure"
        notes.append("self_disclosure")

    # 6. Short acknowledgements
    elif speech in {"acknowledgement", "continuation"} and (
        understanding.get("importance") or "medium"
    ).lower() == "low":
        if short_style or ask_streak >= 1:
            strategy = "simple_response"
            allow_ask = False
        elif open_threads and allow_ask and not _topic_declined(
            str(open_threads[0].get("topic") or ""), declined
        ):
            strategy = "continue_earlier_topic"
            topic_hint = str(open_threads[0].get("topic") or topic)
            followup_hint = "gently return to open thread if natural"
        elif tone == "playful":
            strategy = "playful_reaction"
            allow_ask = False
        else:
            strategy = "simple_response"
            allow_ask = False
        notes.append("low_stakes")

    # 7. Greeting / conversation start / resume with due or grounded memory follow-up
    elif speech == "greeting" or event_type == "conversation_start":
        mem_hook = _memory_followup_hook(retrieved_memories or [], due)
        # Memory check-ins are allowed even when style_profile leans short — keep the
        # reply brief, but do not suppress the only natural follow-up.
        if due and ask_streak < 2:
            strategy = "continue_earlier_topic"
            allow_ask = True
            followup_hint = (
                f"ask how it went without inventing the outcome: "
                f"{(due[0].get('event_description') or due[0].get('fact') or '')[:120]}"
            )
            topic_hint = "due_followup"
            notes.append("due_followup")
        elif mem_hook and ask_streak < 2:
            strategy = "continue_earlier_topic"
            allow_ask = True
            followup_hint = mem_hook
            topic_hint = "memory_followup"
            notes.append("memory_followup")
        else:
            strategy = "playful_reaction" if tone == "playful" else "simple_response"
            allow_ask = bool(allow_ask and event_type == "conversation_start")
            notes.append("greeting")

    # 8. Opinion / preference questions from user (non-factual slot)
    elif speech == "question":
        strategy = "share_opinion" if not factual else "direct_answer"
        allow_ask = False
        notes.append("user_question")

    # 9. Default: continue current topic; optional initiative when thread is thin
    else:
        if due and allow_ask and speech in {"greeting", "acknowledgement", "continuation", ""}:
            strategy = "continue_earlier_topic"
            followup_hint = "due memory follow-up without inventing outcome"
            notes.append("due_memory")
        elif topic and not _topic_declined(topic, declined):
            if allow_ask and speech in {"answer", "continuation", "unclear"}:
                strategy = "answer_plus_followup"
                followup_hint = f"specific follow-up on {topic}"
            else:
                strategy = "relevant_self_disclosure" if allow_ask is False else "simple_response"
            notes.append("stay_on_topic")
        elif open_threads:
            ot = open_threads[0]
            if _topic_declined(str(ot.get("topic") or ""), declined):
                strategy = "simple_response"
                allow_ask = False
            else:
                strategy = "continue_earlier_topic"
                topic_hint = str(ot.get("topic") or "")
                allow_ask = allow_ask
            notes.append("open_thread")
        else:
            # Fresh topic only when conversation is idle and not emotional
            strategy = "fresh_topic" if allow_ask and not short_style else "simple_response"
            allow_ask = strategy == "fresh_topic"
            notes.append("fresh_or_simple")

    # Block fresh topic on declined topics and emotional turns
    if strategy == "fresh_topic" and (emotional or _topic_declined(topic_hint, declined)):
        strategy = "simple_response"
        allow_ask = False
        notes.append("fresh_blocked")

    # Short style: force compact, no questions — keep memory/due follow-ups
    if short_style and strategy not in {"direct_answer", "empathize", "natural_close"}:
        memory_followup = "due_followup" in notes or "memory_followup" in notes
        if strategy == "fresh_topic" or (
            strategy in {"answer_plus_followup", "continue_earlier_topic"} and not memory_followup
        ):
            strategy = "simple_response"
            allow_ask = False
            notes.append("short_style")
        elif memory_followup:
            notes.append("short_style_kept_memory_followup")

    # Life aside: only when strategy allows and activity is a natural transition
    if strategy in {
        "answer_plus_observation",
        "relevant_self_disclosure",
        "fresh_topic",
        "playful_reaction",
    } and activity in {
        "commuting",
        "commute_home",
        "leaving_office",
        "arriving_home",
        "relaxing",
        "having_lunch",
        "having_dinner",
        "cooking",
        "working",
        "meeting",
        "deep_work",
        "gym",
        "with_friends",
        "family_call",
    }:
        allow_life_aside = True

    if ask_streak >= 2:
        allow_ask = False
        notes.append("ask_streak_block")

    onboarding_fields: dict[str, Any] = {}
    obo = onboarding_followup(
        conv,
        known_keys=known_onboarding_keys(conv),
        declined_topics=declined,
        speech_act=speech,
        strategy=strategy,
        incoming_message=incoming_message,
    )
    if obo and obo.get("onboarding_active"):
        strategy = "answer_plus_followup"
        allow_ask = True
        followup_hint = str(obo["followup_hint"])
        topic_hint = str(obo["topic"])
        notes.append(f"onboarding:{obo['onboarding_step']}")
        onboarding_fields = {
            "onboarding_step": obo["onboarding_step"],
            "onboarding_active": True,
        }
    elif obo and obo.get("finish_only"):
        notes.append("onboarding:done")
        onboarding_fields = {"onboarding_step": "done", "onboarding_active": False}

    allowed_moves = list(STRATEGY_TO_MOVES.get(strategy, ["REACT", "ACKNOWLEDGE"]))
    if not allow_ask:
        allowed_moves = [m for m in allowed_moves if m not in {"ASK", "CLARIFY"}]
        if not allowed_moves:
            allowed_moves = ["REACT", "ACKNOWLEDGE", "CONTINUE"]

    # Map strategy to primary social move
    primary_move = allowed_moves[0]
    if strategy == "empathize":
        primary_move = "SUPPORT" if "SUPPORT" in allowed_moves else "REACT"
    elif strategy == "direct_answer":
        primary_move = "SHARE"
    elif strategy in {"answer_plus_followup", "continue_earlier_topic"} and allow_ask:
        primary_move = "ASK" if "ASK" in allowed_moves else allowed_moves[0]
    elif strategy == "fresh_topic":
        primary_move = "CHANGE_TOPIC"
    elif strategy == "natural_close":
        primary_move = "END_CONVERSATION"
    elif strategy == "playful_reaction":
        primary_move = "JOKE" if "JOKE" in allowed_moves else "REACT"
    elif strategy == "relevant_self_disclosure":
        primary_move = "SHARE"
    elif strategy == "respectful_disagree":
        primary_move = "DISAGREE"
    elif strategy == "simple_response":
        primary_move = "ACKNOWLEDGE" if speech == "acknowledgement" else "REACT"

    should_ask = allow_ask and primary_move in {"ASK", "CLARIFY"}
    should_self_disclose = strategy in {
        "relevant_self_disclosure",
        "answer_plus_observation",
        "share_opinion",
        "direct_answer",
    }

    # Topic priority note for prompts
    topic_priority = [
        "latest_user_message",
        "active_or_unresolved_thread",
        "stored_user_fact",
        "shared_interest",
        "timeline_supported_aside" if allow_life_aside else None,
        "persona_interest",
        "general_starter",
    ]
    topic_priority = [p for p in topic_priority if p]

    return {
        "strategy": strategy,
        "allowed_strategies": [strategy],  # hard constraint: one strategy
        "conversational_move": primary_move,
        "allowed_moves": allowed_moves,
        "should_ask_question": should_ask,
        "should_self_disclose": should_self_disclose,
        "allow_life_aside": allow_life_aside,
        "tone": tone,
        "topic": topic_hint,
        "followup_hint": followup_hint,
        "topic_priority": topic_priority,
        "ask_streak": ask_streak,
        "declined_topics": declined,
        "open_threads": open_threads[:3],
        "park_thread": park_thread,
        "due_followup_ids": [d.get("memory_id") for d in due if d.get("memory_id")][:3],
        "notes": ";".join(notes),
        "instruction": _brief_instruction(
            strategy=strategy,
            should_ask=should_ask,
            followup_hint=followup_hint,
            allow_life_aside=allow_life_aside,
            tone=tone,
            topic=topic_hint,
        ),
        **onboarding_fields,
    }


def intensity_allows_clarify(understanding: dict[str, Any]) -> bool:
    intensity = (understanding.get("emotional_intensity") or "low").lower()
    return intensity in {"medium", "high"}


def _memory_followup_hook(
    memories: list[dict[str, Any]],
    due: list[dict[str, Any]],
) -> str:
    """Return a follow-up hint when retrieved memories support a natural check-in."""
    if due:
        return ""
    for mem in memories:
        text = (
            (mem.get("event_description") or mem.get("fact") or mem.get("object") or "")
        ).lower()
        if not text:
            continue
        if mem.get("predicate") == "has_upcoming_event" or any(
            k in text for k in ("interview", "driving test", "presentation", "exam")
        ):
            horizon = mem.get("horizon") or ""
            if horizon == "awaiting_outcome":
                return "ask how it went — do not invent the outcome"
            if horizon == "upcoming" or "tomorrow" in text or "next" in text:
                return "wish them luck or ask a light question about the upcoming event"
            return "reference this memory naturally if evidence allows; do not invent details"
    return ""


def stamp_onboarding_brief(
    brief: dict[str, Any],
    conversation_context: dict[str, Any] | None,
    *,
    known_keys: set[str] | None = None,
    declined_topics: list[str] | None = None,
    speech_act: str = "",
    incoming_message: str = "",
) -> dict[str, Any]:
    """Re-apply onboarding once profile facts are known. Active onboarding wins over other initiative."""
    obo = onboarding_followup(
        conversation_context,
        known_keys=known_keys,
        declined_topics=declined_topics,
        speech_act=speech_act,
        strategy=str((brief or {}).get("strategy") or ""),
        incoming_message=incoming_message,
    )
    if brief.get("onboarding_step") == "done" and not brief.get("onboarding_active"):
        return brief
    if not obo:
        return brief
    eng = dict(brief)
    if obo.get("finish_only"):
        eng["onboarding_step"] = "done"
        eng["onboarding_active"] = False
        if brief.get("onboarding_active"):
            eng["should_ask_question"] = False
            eng["followup_hint"] = ""
            eng["strategy"] = "simple_response"
            eng["conversational_move"] = "REACT"
            eng["instruction"] = _brief_instruction(
                strategy="simple_response",
                should_ask=False,
                followup_hint="",
                allow_life_aside=bool(brief.get("allow_life_aside")),
                tone=str(brief.get("tone") or "casual"),
                topic=str(brief.get("topic") or ""),
            )
        return eng
    hint = str(obo["followup_hint"])
    topic = str(obo["topic"])
    eng.update(
        {
            "strategy": "answer_plus_followup",
            "allowed_strategies": ["answer_plus_followup"],
            "should_ask_question": True,
            "conversational_move": "ASK",
            "allowed_moves": ["ASK", "REACT", "SHARE"],
            "followup_hint": hint,
            "topic": topic,
            "onboarding_step": obo["onboarding_step"],
            "onboarding_active": True,
        }
    )
    notes = [n for n in str(eng.get("notes") or "").split(";") if n and not n.startswith("onboarding:")]
    notes.append(f"onboarding:{obo['onboarding_step']}")
    eng["notes"] = ";".join(notes)
    eng["instruction"] = _brief_instruction(
        strategy="answer_plus_followup",
        should_ask=True,
        followup_hint=hint,
        allow_life_aside=False,
        tone=str(brief.get("tone") or "casual"),
        topic=topic,
    )
    return eng


def _brief_instruction(
    *,
    strategy: str,
    should_ask: bool,
    followup_hint: str,
    allow_life_aside: bool,
    tone: str,
    topic: str,
) -> str:
    parts = [
        f"Engagement strategy: {strategy}.",
        f"Tone: {tone}.",
        "Answer the user's primary point first.",
    ]
    if should_ask:
        parts.append(
            f"At most one specific follow-up question"
            + (f" ({followup_hint})" if followup_hint else "")
            + ". No generic 'how about you' / 'tell me more'."
        )
    else:
        parts.append("Do not ask a question.")
    if allow_life_aside:
        parts.append(
            "You may add one short life aside only if the current activity supports it."
        )
    else:
        parts.append("Do not insert a schedule or life update.")
    if topic:
        parts.append(f"Stay relevant to topic: {topic}.")
    parts.append("Do not interview the user. Do not manufacture dependency or guilt.")
    return " ".join(parts)


def merge_engagement_into_policy(
    social_policy: dict[str, Any],
    engagement: dict[str, Any],
) -> dict[str, Any]:
    """Intersect social-move policy with engagement brief."""
    policy = dict(social_policy or {})
    eng_allowed = set(engagement.get("allowed_moves") or [])
    policy_allowed = list(policy.get("allowed_moves") or [])
    if eng_allowed and policy_allowed:
        intersect = [m for m in policy_allowed if m in eng_allowed]
        # Keep engagement moves that social policy also allows; if empty, prefer engagement
        # but still strip ASK/SUPPORT if social policy forbids them
        if not intersect:
            intersect = [
                m
                for m in engagement.get("allowed_moves") or []
                if m in policy_allowed
                or (m not in {"ASK", "CLARIFY", "SUPPORT"} or m in policy_allowed)
            ]
            # Stricter: only moves present in either but ASK only if both allow
            social_set = set(policy_allowed)
            intersect = [m for m in (engagement.get("allowed_moves") or []) if m in social_set]
        if not intersect:
            intersect = [m for m in policy_allowed if m not in {"ASK", "CLARIFY"}] or policy_allowed
        policy["allowed_moves"] = intersect
    elif eng_allowed:
        policy["allowed_moves"] = list(eng_allowed)

    move = engagement.get("conversational_move")
    allowed = set(policy.get("allowed_moves") or [])
    if move and move in allowed:
        policy["conversational_move"] = move
    elif policy.get("conversational_move") not in allowed and allowed:
        policy["conversational_move"] = next(iter(allowed))

    policy["ask_question"] = bool(engagement.get("should_ask_question")) and policy.get(
        "conversational_move"
    ) in {"ASK", "CLARIFY"}
    policy["engagement_strategy"] = engagement.get("strategy")
    policy["engagement"] = engagement
    return policy
