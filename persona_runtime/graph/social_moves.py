"""Deterministic social-move policy for Sarah's conversational behaviour.

LLM plans may only pick a move from allowed_moves; the policy default wins
when the model returns a forbidden move (especially ASK/SUPPORT).
"""

from __future__ import annotations

from typing import Any, Literal

ConversationalMove = Literal[
    "ACKNOWLEDGE",
    "REACT",
    "ASK",
    "SHARE",
    "JOKE",
    "AGREE",
    "DISAGREE",
    "CLARIFY",
    "SUPPORT",
    "CHANGE_TOPIC",
    "CONTINUE",
    "END_CONVERSATION",
    "WAIT",
]

ALL_MOVES: tuple[ConversationalMove, ...] = (
    "ACKNOWLEDGE",
    "REACT",
    "ASK",
    "SHARE",
    "JOKE",
    "AGREE",
    "DISAGREE",
    "CLARIFY",
    "SUPPORT",
    "CHANGE_TOPIC",
    "CONTINUE",
    "END_CONVERSATION",
    "WAIT",
)

# Talking points that describe a help/availability offer — banned from plans
HELP_OFFER_PHRASES = (
    "offer to listen",
    "invite them to share",
    "offer help",
    "offer assistance",
    "be available",
    "here to listen",
    "here to help",
    "feel free to share",
    "let them know you're available",
    "support them by offering",
    "invite further sharing",
)


def _recent_ask_streak(recent_moves: list[str]) -> int:
    streak = 0
    for m in reversed(recent_moves or []):
        if m == "ASK":
            streak += 1
        else:
            break
    return streak


def select_move(
    *,
    understanding: dict[str, Any],
    persona_state: dict[str, Any] | None = None,
    relationship_state: dict[str, Any] | None = None,
    recent_moves: list[str] | None = None,
    preference_conflict: bool = False,
) -> dict[str, Any]:
    """Return {conversational_move, allowed_moves, ask_question, notes}."""
    speech = (understanding.get("speech_act") or "").strip()
    importance = (understanding.get("importance") or "medium").lower()
    intensity = (understanding.get("emotional_intensity") or "low").lower()
    current = (persona_state or {}).get("current_state") or persona_state or {}
    energy = float(current.get("energy", 0.7))
    availability = float(current.get("availability", 0.5))
    stage = (relationship_state or {}).get("relationship_stage") or "new_contact"
    recent = list(recent_moves or [])
    ask_streak = _recent_ask_streak(recent)

    allowed: list[ConversationalMove]
    chosen: ConversationalMove
    notes = f"speech={speech};importance={importance};intensity={intensity}"

    if speech == "conversation_closing":
        allowed = ["END_CONVERSATION", "ACKNOWLEDGE"]
        chosen = "END_CONVERSATION"
    elif energy < 0.35 and intensity == "low" and importance == "low":
        allowed = ["WAIT", "ACKNOWLEDGE", "REACT"]
        chosen = "WAIT" if availability < 0.35 else "ACKNOWLEDGE"
        notes += ";low_energy"
    elif speech == "acknowledgement" or (
        speech == "continuation" and importance == "low" and intensity == "low"
    ):
        allowed = ["ACKNOWLEDGE", "REACT", "CONTINUE", "JOKE"]
        if ask_streak < 2 and importance == "low":
            # Soft topical curiosity allowed, but never the default
            allowed.append("ASK")
        # SUPPORT never allowed on low-stakes acknowledgements
        chosen = "REACT" if (understanding.get("topic") or "") not in {"", "general", "continuation"} else "ACKNOWLEDGE"
        notes += ";low_stakes_ack"
    elif speech == "self_disclosure":
        allowed = ["REACT", "SHARE", "CONTINUE", "JOKE", "AGREE"]
        if ask_streak < 2:
            allowed.append("ASK")
        if preference_conflict:
            allowed.append("DISAGREE")
        chosen = "REACT"
        notes += ";self_disclosure"
    elif speech == "emotional_statement":
        allowed = ["REACT", "CLARIFY", "ACKNOWLEDGE"]
        close_enough = stage in {"friend", "close_friend", "partner", "family"} or float(
            (relationship_state or {}).get("trust", 0) or 0
        ) >= 0.55
        if intensity in {"medium", "high"} and close_enough:
            allowed.append("SUPPORT")
            chosen = "SUPPORT" if intensity == "high" else "CLARIFY"
        else:
            chosen = "CLARIFY" if intensity != "low" else "REACT"
        notes += ";emotional"
    elif speech == "greeting":
        allowed = ["ACKNOWLEDGE", "REACT", "ASK", "SHARE"]
        chosen = "REACT"
    elif speech == "question":
        allowed = ["REACT", "SHARE", "ACKNOWLEDGE", "CLARIFY", "CONTINUE"]
        if ask_streak < 2:
            allowed.append("ASK")
        chosen = "SHARE" if understanding.get("requires_information") else "REACT"
    elif speech == "disagreement":
        allowed = ["REACT", "CLARIFY", "AGREE", "CONTINUE"]
        if preference_conflict:
            allowed.append("DISAGREE")
        chosen = "CLARIFY"
    elif speech == "request":
        # Practical request — respond, don't default to emotional SUPPORT
        allowed = ["REACT", "CLARIFY", "SHARE", "CONTINUE", "ACKNOWLEDGE"]
        if intensity in {"medium", "high"}:
            allowed.append("SUPPORT")
        chosen = "REACT"
    else:
        allowed = ["REACT", "CONTINUE", "ACKNOWLEDGE", "JOKE", "SHARE"]
        if ask_streak < 2:
            allowed.append("ASK")
        chosen = "REACT"

    ask_question = chosen in {"ASK", "CLARIFY"}
    return {
        "conversational_move": chosen,
        "allowed_moves": allowed,
        "ask_question": ask_question,
        "notes": notes,
    }


def constrain_move(
    proposed: str | None,
    *,
    policy: dict[str, Any],
) -> ConversationalMove:
    """Keep LLM proposal only if it is in allowed_moves; else use policy default."""
    allowed = list(policy.get("allowed_moves") or [])
    default: ConversationalMove = policy.get("conversational_move") or "REACT"  # type: ignore[assignment]
    if not proposed:
        return default
    move = str(proposed).strip().upper().replace(" ", "_")
    # Normalise common aliases
    aliases = {
        "ACK": "ACKNOWLEDGE",
        "ACKNOWLEDGEMENT": "ACKNOWLEDGE",
        "RESPONSE": "REACT",
        "LISTEN": "ACKNOWLEDGE",
        "ENGAGE": "REACT",
        "GREET": "REACT",
        "CLOSE": "END_CONVERSATION",
        "SUPPORTIVE": "SUPPORT",
    }
    move = aliases.get(move, move)
    if move in allowed:
        return move  # type: ignore[return-value]
    # Explicitly reject SUPPORT/ASK when not allowed
    return default


def talking_points_for_move(
    move: ConversationalMove,
    *,
    understanding: dict[str, Any],
) -> list[str]:
    topic = understanding.get("topic") or "current topic"
    speech = understanding.get("speech_act") or ""
    mapping: dict[str, list[str]] = {
        "ACKNOWLEDGE": ["brief natural acknowledgement", f"stay on {topic}"],
        "REACT": [f"react to what was said about {topic}", "show a personal reaction"],
        "ASK": [f"one natural follow-up on {topic}", "no biography dump"],
        "SHARE": ["share a short personal reaction or preference", "do not reopen suppressed biography"],
        "JOKE": ["light observational remark", "keep it brief"],
        "AGREE": ["agree briefly with a concrete reason"],
        "DISAGREE": ["offer a mild differing preference consistent with Sarah"],
        "CLARIFY": ["ask what happened / what they mean"],
        "SUPPORT": ["respond to the specific feeling with a concrete reaction", "no availability offer"],
        "CHANGE_TOPIC": ["shift gently to something Sarah finds interesting"],
        "CONTINUE": [f"continue the thread on {topic}"],
        "END_CONVERSATION": ["warm short closing"],
        "WAIT": ["short acknowledgement; do not extend the conversation"],
    }
    points = list(mapping.get(move, ["respond naturally"]))
    if speech == "acknowledgement":
        points = [p for p in points if "biography" not in p.lower()] or points
    return points


def plan_has_help_offer(talking_points: list[str] | None) -> bool:
    joined = " ".join(talking_points or []).lower()
    return any(p in joined for p in HELP_OFFER_PHRASES)


def apply_plan_humanity_gate(plan: dict[str, Any], *, policy: dict[str, Any], understanding: dict[str, Any]) -> dict[str, Any]:
    """Rewrite plan before generation if move/talking points violate social policy."""
    plan = dict(plan)
    move = constrain_move(plan.get("conversational_move") or policy.get("conversational_move"), policy=policy)
    plan["conversational_move"] = move
    plan["allowed_moves"] = list(policy.get("allowed_moves") or [])
    plan["should_offer_help"] = False

    if move not in {"ASK", "CLARIFY"}:
        plan["should_ask_question"] = False
    else:
        plan["should_ask_question"] = True

    if move != "SHARE":
        # SHARE may keep disclose_fact_ids from disclosure tracker; others clear new disclosure intent
        if move in {"ACKNOWLEDGE", "REACT", "CONTINUE", "JOKE", "WAIT", "END_CONVERSATION"}:
            plan["should_self_disclose"] = False

    if plan_has_help_offer(plan.get("talking_points")) or not plan.get("talking_points"):
        plan["talking_points"] = talking_points_for_move(move, understanding=understanding)

    importance = (understanding.get("importance") or "medium").lower()
    speech = understanding.get("speech_act") or ""
    if speech == "acknowledgement" or importance == "low":
        plan["response_length"] = "short"
        plan["length"] = "short"

    return plan
