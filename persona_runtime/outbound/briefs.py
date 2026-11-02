"""Proactive brief → engagement plan and deterministic grounded fallback bubbles."""

from __future__ import annotations

from typing import Any

from persona_runtime.life.activities import get_activity

TOPIC_QUESTIONS: dict[str, str] = {
    "work": "What does a normal day look like for you at the moment?",
    "hobbies": "What do you usually get up to when you've got a free evening?",
    "music": "Do you listen to music while you work, or do you need silence?",
    "movies": "Watched anything good lately?",
    "sports": "Do you follow any sport, or not really your thing?",
    "travel": "Is there anywhere you've always wanted to visit?",
    "food": "What's the best thing you've eaten recently?",
    "weekends": "What does a usual weekend look like for you?",
    "lifestyle": "Are you more of a morning person or a night owl?",
    "fitness": "Do you do anything to stay active, or is that a sore subject 😄",
    "technology": "Is there an app you genuinely couldn't live without?",
    "cars": "Do you actually enjoy driving, or is it just a way to get places?",
    "everyday": "How's your week been treating you?",
    "social_media": "What kind of stuff do you actually enjoy seeing online?",
}

FOLLOWUP_STRATEGY = {
    "event_followup",
    "hobby_followup",
    "interest_followup",
    "weekend_followup",
    "conversation_resumption",
    "returning_user_greeting",
}


def proactive_engagement(brief: dict[str, Any]) -> dict[str, Any]:
    ptype = brief.get("proactive_type") or "new_topic"
    strategy = "continue_earlier_topic" if ptype in FOLLOWUP_STRATEGY else "fresh_topic"
    hint = str(brief.get("hint") or "")
    # Sarah is still genuinely busy/occupied in the life sim — let her say so briefly
    # ("quick one before my meeting...") when that activity naturally allows it.
    activity_key = str(brief.get("current_activity") or "relaxing")
    allow_life_aside = bool(get_activity(activity_key).may_mention)
    return {
        "strategy": strategy,
        "allowed_strategies": [strategy],
        "conversational_move": "ASK",
        "allowed_moves": ["ASK", "SHARE", "REACT", "CHANGE_TOPIC"],
        "should_ask_question": True,
        "should_self_disclose": ptype == "new_topic",
        "allow_life_aside": allow_life_aside,
        "tone": "casual",
        "topic": brief.get("topic"),
        "followup_hint": hint,
        "topic_priority": ["stored_user_fact", "shared_interest", "general_starter"],
        "ask_streak": 0,
        "declined_topics": [],
        "open_threads": [],
        "park_thread": None,
        "due_followup_ids": list(brief.get("evidence_memory_ids") or [])[:3],
        "notes": f"proactive:{ptype}",
        "instruction": (
            f"Sarah is starting this conversation ({ptype}). {hint} "
            "Keep it light and specific; at most one question across all bubbles; "
            "no guilt, no pressure, no invented details."
        ),
    }


def brief_from_prompt_context(context: str) -> dict[str, Any]:
    """Recover the PROACTIVE_BRIEF section from a built prompt (used by fake LLMs in tests/QA)."""
    import json
    import re

    m = re.search(r"=== PROACTIVE_BRIEF[^\n]*\n", context)
    if not m:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(context[m.end():])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    data["max_bubbles"] = data.pop("MAX_BUBBLES", 2)
    return data


def fallback_messages(brief: dict[str, Any]) -> list[str]:
    """Deterministic, grounded bubbles with exactly one question. Used when generation fails."""
    ptype = brief.get("proactive_type") or "new_topic"
    subject = str(brief.get("subject") or "").strip()
    topic = str(brief.get("topic") or "everyday")
    if ptype == "event_followup" and subject:
        msgs = [f"hey, i remembered you had {subject}", "how did it go?"]
    elif ptype == "hobby_followup" and subject:
        msgs = [f"random thought, {subject} popped into my head earlier", "have you had any time for it lately?"]
    elif ptype == "interest_followup" and subject:
        msgs = [f"Hey, I was thinking about {subject} earlier", "Been into it much lately?"]
    elif ptype == "weekend_followup":
        msgs = ["hey, how was your weekend?"]
        if subject:
            msgs = ["hey, hope the weekend was a good one", f"did you get any {subject} in?"]
    elif ptype == "conversation_resumption" and subject:
        msgs = [f"Hey, I was still thinking about what you said about {subject}", "Did anything come of it?"]
    elif ptype == "returning_user_greeting":
        msgs = ["hey, good to see you back"]
        msgs.append(f"how's {subject} going?" if subject else "how's your week been going?")
    else:
        msgs = ["hey, random question", TOPIC_QUESTIONS.get(topic, TOPIC_QUESTIONS["everyday"])]
    max_bubbles = max(1, int(brief.get("max_bubbles") or 2))
    if len(msgs) > max_bubbles:
        msgs = [" ".join(msgs[: len(msgs) - max_bubbles + 1])] + msgs[len(msgs) - max_bubbles + 1 :]
    return msgs
