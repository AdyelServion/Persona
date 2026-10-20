"""Conversation engagement engine — one strategy per turn, not a checklist."""

from __future__ import annotations

from typing import Any, Literal

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
    }:
        allow_life_aside = True

    if ask_streak >= 2:
        allow_ask = False
        notes.append("ask_streak_block")

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
