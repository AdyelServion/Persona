"""Deterministic analysis of recent conversation before proactive engagement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from persona_runtime.conversation.topic_manager import classify_topic


@dataclass
class ConversationAnalysis:
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    last_user_text: str = ""
    last_assistant_text: str = ""
    open_sarah_question: str | None = None
    open_user_question: str | None = None
    mentioned_hobbies: list[str] = field(default_factory=list)
    mentioned_plans: list[str] = field(default_factory=list)
    last_topic: str | None = None
    topic_completed: bool = False
    user_seems_engaged: bool = True
    repeat_topic_risk: bool = False
    summary: str = ""


_HOBBY_HINTS = (
    "photography",
    "photo",
    "football",
    "gaming",
    "music",
    "hiking",
    "travel",
    "cook",
    "reading",
    "gym",
    "run",
    "cars",
    "paint",
)
_PLAN_HINTS = ("weekend", "tomorrow", "tonight", "trip", "match", "interview", "flight", "holiday", "plan")


def _meaningful(text: str) -> bool:
    t = (text or "").strip()
    return len(t) >= 2 and t.lower() not in {"ok", "k", "yeah", "yep", "lol", "haha", "thanks", "ty"}


def _last_question(text: str) -> str | None:
    if "?" not in (text or ""):
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    for part in reversed(parts):
        if "?" in part:
            return part.strip()
    return text.strip() if "?" in text else None


def analyze_recent_conversation(
    messages: list[dict[str, Any]],
    *,
    conversation_context: dict[str, Any] | None = None,
    limit: int = 10,
) -> ConversationAnalysis:
    limit = max(5, min(10, int(limit)))
    recent = list(messages)[-limit:] if messages else []
    ctx = conversation_context or {}
    analysis = ConversationAnalysis(recent_messages=recent)

    for msg in reversed(recent):
        sender = msg.get("sender")
        text = (msg.get("content") or "").strip()
        if sender == "user" and _meaningful(text) and not analysis.last_user_text:
            analysis.last_user_text = text
        if sender == "assistant" and text and not analysis.last_assistant_text:
            analysis.last_assistant_text = text
        if analysis.last_user_text and analysis.last_assistant_text:
            break

    if recent:
        last = recent[-1]
        if last.get("sender") == "assistant":
            analysis.open_sarah_question = _last_question(last.get("content") or "")
        elif last.get("sender") == "user":
            analysis.open_user_question = _last_question(last.get("content") or "")

    blob = " ".join((m.get("content") or "") for m in recent if m.get("sender") == "user").lower()
    for hint in _HOBBY_HINTS:
        if re.search(rf"\b{re.escape(hint)}\b", blob):
            analysis.mentioned_hobbies.append(hint)
    for hint in _PLAN_HINTS:
        if hint in blob:
            analysis.mentioned_plans.append(hint)

    analysis.last_topic = ctx.get("current_topic") or classify_topic(analysis.last_user_text or blob)
    open_threads = ctx.get("open_threads") or []
    analysis.topic_completed = not open_threads and not analysis.open_user_question
    if analysis.last_user_text:
        words = len(analysis.last_user_text.split())
        analysis.user_seems_engaged = words >= 4 or "?" in analysis.last_user_text
    prev = [str(t).lower() for t in (ctx.get("previous_topics") or [])[-3:]]
    if analysis.last_topic and analysis.last_topic.lower() in prev:
        analysis.repeat_topic_risk = True

    parts = []
    if analysis.last_user_text:
        parts.append(f"User last said: {analysis.last_user_text[:200]}")
    if analysis.open_sarah_question:
        parts.append(f"Sarah's last message had a question still open: {analysis.open_sarah_question[:120]}")
    if analysis.mentioned_hobbies:
        parts.append(f"Hobbies in recent chat: {', '.join(analysis.mentioned_hobbies[:5])}")
    if analysis.mentioned_plans:
        parts.append(f"Plans/events mentioned: {', '.join(analysis.mentioned_plans[:5])}")
    analysis.summary = "; ".join(parts) or "No strong recent context."
    return analysis
