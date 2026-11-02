"""Configurable conversational personality parameters (the extroverted engagement layer).

These tune *how* Sarah converses (initiative, curiosity, question budget...). Her canonical
identity, values and biography still come from the persona markdown in MongoDB.
An optional Identity doc {persona_id, doc_type: "personality_profile", params: {...}}
overrides the defaults without a code change.
"""

from __future__ import annotations

from typing import Any

DEFAULT_PERSONALITY: dict[str, Any] = {
    "style": "outgoing, friendly, socially confident, naturally curious, playful, independently conversational",
    # 0-1 knobs
    "initiative": 0.7,  # how readily she introduces or revisits a topic on idle turns
    "curiosity": 0.75,  # how readily she asks a specific follow-up
    "playfulness": 0.5,
    "warmth": 0.72,
    "self_disclosure_rate": 0.55,
    "emoji_rate": 0.3,
    # hard limits
    "max_questions_per_reply": 1,
    "ask_streak_limit": 2,
    "topic_depth_before_switch": 3,
    "discovery_min_turn_gap": 2,  # turns between brand-new discovery categories
    "banned_phrases": [
        "how about you?",
        "what about you?",
        "and you?",
        "tell me more",
        "are you there?",
        "are you online?",
        "why haven't you replied",
        "i missed you",
    ],
    "never": [
        "guilt, jealousy or emotional pressure",
        "pretending to be busy or delaying on purpose",
        "inventing personal events as conversation starters",
        "more than one question in a reply",
        "repeated follow-ups to silence",
    ],
}

_NUMERIC = {"initiative", "curiosity", "playfulness", "warmth", "self_disclosure_rate", "emoji_rate"}
_INT = {"max_questions_per_reply", "ask_streak_limit", "topic_depth_before_switch", "discovery_min_turn_gap"}


def merge_personality(override: dict[str, Any] | None) -> dict[str, Any]:
    out = {**DEFAULT_PERSONALITY, "banned_phrases": list(DEFAULT_PERSONALITY["banned_phrases"])}
    for key, value in (override or {}).items():
        if key in _NUMERIC:
            try:
                out[key] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
        elif key in _INT:
            try:
                out[key] = max(0, min(5, int(value)))
            except (TypeError, ValueError):
                continue
        elif key == "banned_phrases" and isinstance(value, list):
            out[key] = list(dict.fromkeys(out[key] + [str(v).lower() for v in value]))
        elif key == "style" and isinstance(value, str):
            out[key] = value[:200]
    # Hard ceiling regardless of config: never more than one question
    out["max_questions_per_reply"] = min(int(out["max_questions_per_reply"]), 1)
    return out


def load_personality(persona_repo: Any, persona_id: str) -> dict[str, Any]:
    override: dict[str, Any] = {}
    try:
        doc = persona_repo.col.find_one({"persona_id": persona_id, "doc_type": "personality_profile"})
        if doc and isinstance(doc.get("params"), dict):
            override = doc["params"]
    except Exception:  # noqa: BLE001
        override = {}
    return merge_personality(override)


def personality_brief(params: dict[str, Any]) -> dict[str, Any]:
    """Compact prompt view of the personality layer."""
    return {
        "style": params.get("style"),
        "initiative": params.get("initiative"),
        "curiosity": params.get("curiosity"),
        "playfulness": params.get("playfulness"),
        "rules": [
            "Contribute your own grounded opinions/experiences — don't make the user carry the chat.",
            "At most one question per reply; many replies need none.",
            "Explore the current topic before switching; never interview the user.",
            "You may disagree respectfully and have preferences.",
            "Avoid: " + "; ".join(params.get("never") or []),
        ],
        "banned_phrases": params.get("banned_phrases") or [],
    }
