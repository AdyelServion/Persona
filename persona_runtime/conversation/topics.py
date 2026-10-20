"""Lightweight conversation topic state and style adaptation."""

from __future__ import annotations

import re
from typing import Any


def default_style_profile() -> dict[str, Any]:
    return {
        "response_length": "medium",  # short | medium | detailed
        "tone_preference": "balanced",  # playful | serious | balanced
        "question_tolerance": 0.55,  # 0–1, lower = fewer questions from Sarah
        "emoji_rate": 0.35,
        "depth_interest": 0.5,
        "personal_topics_ok": True,
        "samples": 0,
    }


DECLINE_PATTERNS = (
    r"\bi don'?t want to (talk|discuss|go into)\b",
    r"\bcan we (not|skip|change)\b",
    r"\bplease stop (asking|talking)\b",
    r"\bi'?d rather not (talk|discuss)\b",
    r"\bdon'?t (ask|talk) about\b",
    r"\bchange (the )?subject\b",
)

OPT_OUT_PATTERNS = (
    r"\bdon'?t (message|text|contact) me\b",
    r"\bstop (messaging|texting) me\b",
    r"\bleave me alone\b",
    r"\bno (more )?proactive\b",
    r"\bdon'?t (message|text) (me )?(first|unless)\b",
)


def detect_declined_topic(text: str, current_topic: str = "") -> str | None:
    lower = (text or "").lower().strip()
    if not lower:
        return None
    if any(re.search(p, lower) for p in DECLINE_PATTERNS):
        return (current_topic or "current").strip() or "current"
    return None


def detect_proactive_opt_out(text: str) -> bool:
    lower = (text or "").lower().strip()
    return bool(lower and any(re.search(p, lower) for p in OPT_OUT_PATTERNS))


def _update_style_profile(
    profile: dict[str, Any],
    *,
    incoming: str,
    understanding: dict[str, Any],
) -> dict[str, Any]:
    out = {**default_style_profile(), **(profile or {})}
    samples = int(out.get("samples") or 0) + 1
    words = len((incoming or "").split())
    # Exponential-ish blend toward observed style
    alpha = min(0.35, 1.0 / max(samples, 1))

    if words <= 5:
        target_len = "short"
        q_tol = 0.35
    elif words >= 40:
        target_len = "detailed"
        q_tol = 0.65
    else:
        target_len = "medium"
        q_tol = float(out.get("question_tolerance") or 0.55)

    length_map = {"short": 0.0, "medium": 0.5, "detailed": 1.0}
    cur = length_map.get(str(out.get("response_length") or "medium"), 0.5)
    blended = cur * (1 - alpha) + length_map[target_len] * alpha
    if blended < 0.33:
        out["response_length"] = "short"
    elif blended > 0.66:
        out["response_length"] = "detailed"
    else:
        out["response_length"] = "medium"

    out["question_tolerance"] = round(
        float(out.get("question_tolerance") or 0.55) * (1 - alpha) + q_tol * alpha, 3
    )

    emoji_count = sum(1 for ch in incoming if ord(ch) > 0x1F300 or ch in "😂😅😊🙂😉")
    emoji_obs = min(1.0, emoji_count / max(words, 1) * 4)
    out["emoji_rate"] = round(
        float(out.get("emoji_rate") or 0.35) * (1 - alpha) + emoji_obs * alpha, 3
    )

    intensity = (understanding.get("emotional_intensity") or "low").lower()
    importance = (understanding.get("importance") or "medium").lower()
    if intensity in {"medium", "high"} or importance == "high":
        depth_obs = 0.75
    elif words <= 5:
        depth_obs = 0.3
    else:
        depth_obs = 0.5
    out["depth_interest"] = round(
        float(out.get("depth_interest") or 0.5) * (1 - alpha) + depth_obs * alpha, 3
    )

    speech = understanding.get("speech_act") or ""
    lower = (incoming or "").lower()
    if any(k in lower for k in ("😂", "lol", "haha", "joke")):
        out["tone_preference"] = "playful"
    elif speech == "emotional_statement" or intensity == "high":
        out["tone_preference"] = "serious"

    if detect_declined_topic(incoming, understanding.get("topic") or ""):
        out["personal_topics_ok"] = False

    out["samples"] = samples
    return out


def apply_topic_turn(
    conv: dict[str, Any],
    *,
    understanding: dict[str, Any],
    incoming: str,
    reply: str = "",
    engagement_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ConversationContext field updates for topic/style state."""
    topic = (understanding.get("topic") or conv.get("current_topic") or "").strip()
    previous = list(conv.get("previous_topics") or [])
    open_threads = list(conv.get("open_threads") or [])
    declined = list(conv.get("declined_topics") or [])
    last_topic = (conv.get("current_topic") or "").strip()
    last_transition = conv.get("last_transition") or ""

    if last_topic and topic and last_topic != topic:
        if last_topic not in previous:
            previous.append(last_topic)
        # Park previous topic as open thread if it had unfinished substance
        if last_topic not in {t.get("topic") for t in open_threads if isinstance(t, dict)}:
            open_threads.append(
                {
                    "topic": last_topic,
                    "unknown": "user_changed_subject",
                    "source": "topic_switch",
                }
            )
        last_transition = f"{last_topic}->{topic}"

    declined_hit = detect_declined_topic(incoming, topic or last_topic)
    if declined_hit and declined_hit not in declined:
        declined.append(declined_hit)
        open_threads = [
            t for t in open_threads if not (isinstance(t, dict) and t.get("topic") == declined_hit)
        ]

    # Drop open thread when user returns to that topic
    if topic:
        open_threads = [
            t for t in open_threads if not (isinstance(t, dict) and t.get("topic") == topic)
        ]

    brief = engagement_brief or {}
    if brief.get("park_thread") and isinstance(brief["park_thread"], dict):
        pt = brief["park_thread"]
        if pt.get("topic") and pt["topic"] not in {
            t.get("topic") for t in open_threads if isinstance(t, dict)
        }:
            open_threads.append(pt)

    if brief.get("resolve_thread_topic"):
        rt = brief["resolve_thread_topic"]
        open_threads = [
            t for t in open_threads if not (isinstance(t, dict) and t.get("topic") == rt)
        ]

    style = _update_style_profile(
        conv.get("style_profile") or {},
        incoming=incoming,
        understanding=understanding,
    )

    updates: dict[str, Any] = {
        "current_topic": topic,
        "previous_topics": previous[-10:],
        "open_threads": open_threads[-8:],
        "declined_topics": declined[-20:],
        "last_transition": last_transition,
        "style_profile": style,
    }
    if detect_proactive_opt_out(incoming):
        updates["proactive_opt_out"] = True
    return updates
