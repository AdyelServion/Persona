"""Pre-send validation for proactive outbound messages."""

from __future__ import annotations

import re
from typing import Any

_EMOJI = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
_PRESSURE = (
    "why haven't you",
    "why havent you",
    "are you there",
    "you there",
    "missed you",
    "ignored me",
    "why did you ghost",
    "please reply",
)
_ASSISTANT = (
    "i hope your day is going well",
    "i was wondering whether",
    "as an ai",
    "as a language model",
    "how may i assist",
)


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip(" ?!.,"))


def validate_outbound_draft(
    message: str,
    *,
    asked_questions: list[str] | None = None,
    last_outbound_text: str | None = None,
) -> tuple[bool, str]:
    text = (message or "").strip()
    if not text:
        return False, "empty_message"
    if _EMOJI.search(text):
        return False, "contains_emoji"
    lower = text.lower()
    for phrase in _PRESSURE:
        if phrase in lower:
            return False, "pressuring"
    for phrase in _ASSISTANT:
        if phrase in lower:
            return False, "assistant_speak"
    if len(text.split()) > 35:
        return False, "too_long"
    norm = normalize_question(text)
    for prev in asked_questions or []:
        if normalize_question(prev) == norm:
            return False, "duplicate_question"
    if last_outbound_text and normalize_question(last_outbound_text) == norm:
        return False, "repeat_outbound"
    return True, "ok"


def validate_decision_grounding(
    decision: dict[str, Any],
    *,
    trigger_candidates: list[dict[str, Any]],
    analysis_summary: str,
) -> tuple[bool, str]:
    if not decision.get("should_send"):
        return True, "no_send"
    strategy = str(decision.get("strategy") or "").upper()
    if strategy == "NO_MESSAGE":
        return True, "no_message"
    topic = str(decision.get("topic") or "").lower()
    if not topic and strategy not in {"ASK_CASUAL_QUESTION"}:
        return False, "missing_topic"
    allowed_topics = {str(c.get("topic") or "").lower() for c in trigger_candidates}
    allowed_subjects = {str(c.get("subject") or "").lower() for c in trigger_candidates if c.get("subject")}
    if trigger_candidates and topic and topic not in allowed_topics and not any(topic in s for s in allowed_subjects):
        if strategy != "INTRODUCE_NEW_TOPIC":
            return False, "ungrounded_topic"
    if strategy == "INTRODUCE_NEW_TOPIC" and not any(c.get("proactive_type") == "new_topic" for c in trigger_candidates):
        return False, "new_topic_not_allowed"
    if (
        not analysis_summary
        and strategy in {"CONTINUE_TOPIC", "FOLLOW_UP_MEMORY"}
        and not trigger_candidates
    ):
        return False, "no_context_for_followup"
    return True, "ok"
