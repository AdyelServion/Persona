"""Deterministic response strategy for batched inbox messages."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.life.activities import get_activity

STRATEGIES = (
    "RESPOND_TO_ALL",
    "RESPOND_TO_LATEST",
    "RESPOND_TO_GROUP",
    "ACKNOWLEDGE_LATEST",
    "IGNORE_LOW_VALUE_MESSAGES",
    "WAIT_FOR_MORE_CONTEXT",
    "DEFER_RESPONSE",
)

_SUPERSEDE = re.compile(
    r"\b(?:never\s*mind|nvm|actually[, ]|ignore that|forget (?:that|it)|cancel that)\b",
    re.I,
)
_LOW_VALUE = re.compile(r"^(?:hey+|hi+|hello|yo|sup|ok|okay|k|thanks|thx|lol|haha)\W*$", re.I)
_QUESTION = re.compile(r"\?")


def classify_priority(content: str) -> str:
    text = (content or "").strip().lower()
    if not text:
        return "low"
    if any(p in text for p in ("right now", "urgent", "emergency", "call me now", "asap")):
        return "urgent"
    if any(p in text for p in ("really bad", "awful day", "terrified", "panic", "crying", "scared")):
        return "emotionally_important"
    if any(p in text for p in ("need to tell you", "important", "worried", "need your help")):
        return "important"
    if _LOW_VALUE.match(text) or len(text) < 8:
        return "low"
    return "normal"


def _related(a: str, b: str) -> bool:
    ta = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    tb = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    stop = {"a", "the", "you", "are", "is", "to", "i", "me", "my", "do", "did", "what", "how"}
    ta -= stop
    tb -= stop
    if not ta or not tb:
        return True  # short greetings cluster together
    return bool(ta & tb) or abs(len(ta) - len(tb)) <= 2


def choose_response_strategy(
    *,
    messages: list[dict[str, Any]],
    activity_key: str,
    availability: float,
    strategy_hint: str | None = None,
) -> dict[str, Any]:
    """Pick a strategy and mark which message ids are included / superseded / ignored."""
    params = get_activity(activity_key)
    msgs = list(messages or [])
    if not msgs:
        return {
            "strategy": "DEFER_RESPONSE",
            "include_ids": [],
            "superseded_ids": [],
            "ignored_ids": [],
            "reason": "no_messages",
        }

    # A stored DEFER_RESPONSE hint only means "wait until due". Once the job
    # is claimed, decide from *current* availability — otherwise Sarah types
    # and never replies (sticky defer loop).
    currently_blocked = bool(
        params.sleeping or params.availability < 0.12 or availability < 0.12
    )
    if strategy_hint == "ACKNOWLEDGE_LATEST" or currently_blocked:
        priorities = [m.get("priority") or "normal" for m in msgs]
        if strategy_hint == "ACKNOWLEDGE_LATEST" or any(
            p in {"urgent", "important", "emotionally_important"} for p in priorities
        ):
            latest = msgs[-1]
            return {
                "strategy": "ACKNOWLEDGE_LATEST",
                "include_ids": [latest["message_id"]],
                "superseded_ids": [],
                "ignored_ids": [m["message_id"] for m in msgs[:-1]],
                "reason": "busy_acknowledgement",
                "busy_ack": True,
            }
        if currently_blocked:
            return {
                "strategy": "DEFER_RESPONSE",
                "include_ids": [m["message_id"] for m in msgs],
                "superseded_ids": [],
                "ignored_ids": [],
                "reason": "unavailable",
                "busy_ack": False,
            }

    superseded: list[str] = []
    ignored: list[str] = []
    include: list[str] = []

    # Detect supersession: later message cancels earlier intent
    for i, m in enumerate(msgs):
        content = m.get("content") or ""
        if i > 0 and _SUPERSEDE.search(content):
            # supersede previous non-superseded
            for j in range(i - 1, -1, -1):
                prev = msgs[j]
                if prev["message_id"] not in superseded:
                    superseded.append(prev["message_id"])
                    break

    active = [m for m in msgs if m["message_id"] not in superseded]

    # Low-value only trail before a real message
    if len(active) >= 2:
        last = active[-1]
        if not _LOW_VALUE.match((last.get("content") or "").strip()):
            for m in active[:-1]:
                if _LOW_VALUE.match((m.get("content") or "").strip()):
                    # still include in group response — mark as low but include
                    pass

    if len(active) == 1:
        strategy = "RESPOND_TO_LATEST"
        include = [active[0]["message_id"]]
    else:
        contents = [m.get("content") or "" for m in active]
        all_related = all(_related(contents[i], contents[i + 1]) for i in range(len(contents) - 1))
        questions = sum(1 for c in contents if _QUESTION.search(c))
        if all_related and questions <= 1:
            strategy = "RESPOND_TO_GROUP"
            include = [m["message_id"] for m in active]
        elif questions >= 2 and not all_related:
            strategy = "RESPOND_TO_ALL"
            include = [m["message_id"] for m in active]
        elif superseded:
            strategy = "RESPOND_TO_LATEST"
            include = [active[-1]["message_id"]]
            for m in active[:-1]:
                if m["message_id"] not in include:
                    ignored.append(m["message_id"])
        else:
            strategy = "RESPOND_TO_GROUP"
            include = [m["message_id"] for m in active]

    # Anything not included and not superseded is ignored
    for m in msgs:
        mid = m["message_id"]
        if mid not in include and mid not in superseded and mid not in ignored:
            if _LOW_VALUE.match((m.get("content") or "").strip()) and strategy == "RESPOND_TO_LATEST":
                ignored.append(mid)
            elif mid not in include:
                # still part of group unless explicitly ignored
                if strategy in {"RESPOND_TO_GROUP", "RESPOND_TO_ALL"} and mid not in superseded:
                    if mid not in include:
                        include.append(mid)

    return {
        "strategy": strategy,
        "include_ids": include,
        "superseded_ids": superseded,
        "ignored_ids": ignored,
        "reason": "planned",
        "busy_ack": False,
    }
