"""Pick a grounded reason for Sarah to message first. No reason → no message.

Priority: an event whose outcome is unknown, an unfinished thread, the weekend (if the
user told her about weekend habits), a known hobby, a known interest, then a fresh topic.
Every followup is grounded in this user's own stored memories.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from persona_runtime.conversation.topic_manager import classify_topic, suggest_transition
from persona_runtime.db.time_utils import ensure_utc

EVENT_WORDS = (
    "driving test",
    "interview",
    "presentation",
    "exam",
    "flight",
    "holiday",
    "appointment",
    "match",
    "trip",
    "date",
)
TOPIC_REPEAT_DAYS = 3
RESUMPTION_MIN_IDLE_HOURS = 12


def event_subject(text: str) -> str:
    lower = (text or "").lower()
    for word in EVENT_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            return f"your {word}"
    return "that thing you had coming up"


def _recent_subjects(settings_doc: dict[str, Any], now: datetime) -> set[str]:
    out: set[str] = set()
    for h in settings_doc.get("topic_history") or []:
        if not isinstance(h, dict) or not h.get("at"):
            continue
        try:
            if ensure_utc(now) - ensure_utc(h["at"]) < timedelta(days=TOPIC_REPEAT_DAYS):
                out.add(str(h.get("topic") or "").lower())
        except Exception:  # noqa: BLE001
            continue
    return out


def _is_weekend_window(local_now: datetime) -> bool:
    wd = local_now.weekday()
    return (wd == 5 and local_now.hour >= 15) or wd == 6 or (wd == 0 and local_now.hour < 13)


def select_trigger(
    *,
    user_id: str,
    persona_id: str,
    now: datetime,
    local_now: datetime,
    settings_doc: dict[str, Any],
    profile_card: list[dict[str, Any]],
    due_followups: list[dict[str, Any]],
    conversation_context: dict[str, Any] | None,
    user_topics: list[dict[str, Any]],
    last_message_at: datetime | None,
) -> dict[str, Any] | None:
    muted = set(settings_doc.get("muted_types") or [])
    recent = _recent_subjects(settings_doc, now)
    ctx = conversation_context or {}
    declined = {str(d).lower() for d in (ctx.get("declined_topics") or [])} | {
        t["topic"] for t in user_topics if t.get("declined")
    }

    def allowed(ptype: str, topic: str | None, subject: str | None) -> bool:
        if ptype in muted:
            return False
        if topic and topic.lower() in declined:
            return False
        key = (subject or topic or "").lower()
        return not (key and key in recent)

    # 1. Event follow-up: something happened and Sarah doesn't know how it went
    for mem in due_followups:
        if mem.get("user_id") != user_id:
            continue
        subject = event_subject(mem.get("event_description") or mem.get("fact") or "")
        if allowed("event_followup", "everyday", subject):
            return {
                "proactive_type": "event_followup",
                "topic": classify_topic(mem.get("event_description") or "") or "everyday",
                "subject": subject,
                "hint": f"ask how {subject} went — do not assume or invent the outcome",
                "talking_points": ["one warm line", "ask how it went"],
                "evidence_memory_ids": [mem.get("memory_id")],
                "idempotency_subject": f"event:{mem.get('memory_id')}",
            }

    # 2. Conversation resumption: an unfinished thread from a while ago
    idle = last_message_at is None or ensure_utc(now) - ensure_utc(last_message_at) >= timedelta(
        hours=RESUMPTION_MIN_IDLE_HOURS
    )
    if idle:
        for thread in ctx.get("open_threads") or []:
            if not isinstance(thread, dict) or not thread.get("topic"):
                continue
            topic = str(thread["topic"])
            if allowed("conversation_resumption", topic, topic):
                return {
                    "proactive_type": "conversation_resumption",
                    "topic": topic,
                    "subject": topic,
                    "hint": f"pick the earlier conversation about {topic} back up; don't invent new details",
                    "talking_points": ["reference the earlier thread", "one light question"],
                    "evidence_memory_ids": [],
                    "idempotency_subject": f"thread:{topic}",
                }

    by_key: dict[str, list[dict[str, Any]]] = {}
    for mem in profile_card:
        if mem.get("user_id") != user_id or mem.get("interest_status") == "former":
            continue
        by_key.setdefault(str(mem.get("memory_key") or mem.get("predicate") or ""), []).append(mem)

    # 3. Weekend follow-up, only if the user shared weekend habits
    if _is_weekend_window(local_now) and by_key.get("weekend_preference"):
        mem = by_key["weekend_preference"][0]
        subject = str(mem.get("object") or "").strip()
        iso_week = local_now.isocalendar()
        week_key = f"weekend:{iso_week[0]}-{iso_week[1]}"
        if allowed("weekend_followup", "weekends", week_key):
            return {
                "history_key": week_key,
                "proactive_type": "weekend_followup",
                "topic": "weekends",
                "subject": subject or None,
                "hint": "ask casually about their weekend, referencing their usual weekend habit",
                "talking_points": ["light weekend check-in"],
                "evidence_memory_ids": [mem.get("memory_id")],
                "idempotency_subject": f"weekend:{iso_week[0]}-{iso_week[1]}",
            }

    # 4. Hobby, then 5. interest follow-ups (grounded in stored facts)
    for ptype, keys in (
        ("hobby_followup", ("hobby",)),
        ("interest_followup", ("interest", "music_preference", "supports_team", "favourite_food")),
    ):
        for key in keys:
            for mem in by_key.get(key, []):
                subject = str(mem.get("object") or "").strip()
                if not subject:
                    continue
                topic = classify_topic(f"{subject} {mem.get('fact') or ''}") or "hobbies"
                if not allowed(ptype, topic, subject):
                    continue
                hint = f"bring up {subject} naturally — something they told you about"
                if key == "supports_team":
                    hint = (
                        f"ask if they've been following {subject} lately; do NOT claim any match, "
                        "result or news happened"
                    )
                return {
                    "proactive_type": ptype,
                    "topic": topic,
                    "subject": subject,
                    "hint": hint,
                    "talking_points": ["casual opener", "one specific question"],
                    "evidence_memory_ids": [mem.get("memory_id")],
                    "idempotency_subject": f"{key}:{subject.lower()}",
                }

    # 6. Fresh topic to discover something new
    if "new_topic" not in muted:
        transition = suggest_transition(
            user_id=user_id,
            topics=user_topics,
            profile_card=[],
            declined_topics=list(declined),
            recent_topics=list(recent),
            now=now,
        )
        if transition and transition.get("kind") == "fresh":
            return {
                "proactive_type": "new_topic",
                "topic": transition["topic"],
                "subject": None,
                "hint": transition["hint"],
                "talking_points": ["casual, curious opener", "share a tiny grounded take of your own if natural"],
                "evidence_memory_ids": [],
                "idempotency_subject": f"topic:{transition['topic']}",
            }
    return None
