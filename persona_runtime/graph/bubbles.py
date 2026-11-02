"""Normalize Sarah replies into short chat bubbles."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.graph.grounding import fallback_messages_from_answer_plan
from persona_runtime.graph.reality import (
    build_world_state,
    world_state_fallback_messages,
)


_DASH_PAUSE = re.compile(r"\s*(?:—|–)\s*")
_DOUBLE_HYPHEN_PAUSE = re.compile(r"\s+--\s+")
# Pictographs, flags, dingbats used as emoji, variation selectors, and ZWJ joins.
_EMOJI = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F02F"
    "\U0001F0A0-\U0001F0FF"
    "\U00002300-\U000023FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "\U0001F3FB-\U0001F3FF"
    "]+",
    flags=re.UNICODE,
)


def contains_emoji(text: str) -> bool:
    return bool(_EMOJI.search(text or ""))


def strip_emojis(text: str) -> str:
    """Remove emoji characters only. Spelling and punctuation stay as generated."""
    cleaned = _EMOJI.sub("", text or "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    return cleaned.strip()


def apply_emoji_policy(texts: list[str], typing_style: dict[str, Any] | None) -> list[str]:
    """Drop emoji when this persona's style disables them. Empty bubbles go away."""
    if not typing_style or typing_style.get("emoji_enabled") is not False:
        return [t for t in texts if t and str(t).strip()]
    kept: list[str] = []
    for item in texts:
        cleaned = strip_emojis(item)
        if cleaned:
            kept.append(cleaned)
    return kept


def humanize_text(text: str) -> str:
    """Texting punctuation. Em dashes and spaced double hyphens become commas."""
    cleaned = _DASH_PAUSE.sub(", ", text or "")
    cleaned = _DOUBLE_HYPHEN_PAUSE.sub(", ", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"(?:,\s*){2,}", ", ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned.lstrip(",").strip()


def _plain(texts: list[str]) -> list[str]:
    return [t for t in (humanize_text(item) for item in texts) if t]


def extract_texts_from_llm_payload(data: dict[str, Any]) -> list[str]:
    """Accept {messages:[{text,type}]} or legacy {reply: string}."""
    raw_messages = data.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        texts: list[str] = []
        for item in raw_messages:
            if isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                text = str(item or "").strip()
            if text:
                texts.append(text)
        if texts:
            return texts

    if "reply" in data:
        reply = str(data.get("reply") or "").strip()
        if reply:
            parts = [p.strip() for p in reply.split("\n") if p.strip()]
            return parts or [reply]
    return []


def pack_message_dicts(texts: list[str]) -> list[dict[str, str]]:
    return [{"text": t, "type": "text"} for t in texts if t and str(t).strip()]


def join_messages(texts: list[str] | list[dict[str, Any]] | None) -> str:
    if not texts:
        return ""
    out: list[str] = []
    for item in texts:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            out.append(text)
    return "\n".join(out)


def _question_targets_from_state(state: dict[str, Any]) -> list[str]:
    understanding = state.get("understanding") or {}
    plan = state.get("response_plan") or {}
    q_target = understanding.get("question_target") or plan.get("question_target") or "none"
    q_targets = list(
        understanding.get("question_targets") or plan.get("question_targets") or []
    )
    if not q_targets and q_target and q_target != "none":
        q_targets = [q_target]
    return [t for t in q_targets if t and t != "none"]


def _questions_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    understanding = state.get("understanding") or {}
    plan = state.get("response_plan") or {}
    questions = list(understanding.get("questions") or plan.get("questions") or [])
    return [q for q in questions if (q.get("slot") or "none") != "none"]


def is_fragment_bubble(text: str) -> bool:
    """True for mechanically split fragments that are not independently readable."""
    t = (text or "").strip()
    if not t:
        return True
    core = t.rstrip(".,!?…").lower()
    # Single dangling connector / incomplete reaction
    if core in {
        "wait",
        "so",
        "and",
        "but",
        "oh",
        "ah",
        "hm",
        "hmm",
        "well",
        "yeah",
    } and len(t.split()) == 1:
        return True
    if t.rstrip().endswith((",", "...")) and len(t.split()) <= 2:
        return True
    return False


def merge_fragment_bubbles(texts: list[str]) -> list[str]:
    """Join fragment bubbles into readable messages."""
    if not texts:
        return []
    out: list[str] = []
    buf = ""
    for t in texts:
        piece = (t or "").strip()
        if not piece:
            continue
        if is_fragment_bubble(piece) or (buf and is_fragment_bubble(buf)):
            buf = f"{buf} {piece}".strip() if buf else piece
            if not is_fragment_bubble(buf):
                out.append(buf)
                buf = ""
            continue
        if buf:
            out.append(buf)
            buf = ""
        out.append(piece)
    if buf:
        # Still a fragment — attach to previous or keep if alone
        if out:
            out[-1] = f"{out[-1]} {buf}".strip()
        else:
            out.append(buf)
    return out


def normalize_generated_messages(
    texts: list[str],
    state: dict[str, Any],
) -> list[str]:
    """Enforce bubble rules; prefer answer-plan fallbacks for multi-question turns."""
    cleaned = [t.strip() for t in texts if t and str(t).strip()]
    cleaned = merge_fragment_bubbles(cleaned)
    targets = _question_targets_from_state(state)
    questions = _questions_from_state(state)
    plan = state.get("response_plan") or {}

    current = (state.get("persona_state") or {}).get("current_state") or {}
    conv = state.get("conversation_context") or {}
    world = plan.get("world_state") or build_world_state(current)
    last_world = conv.get("last_world_snapshot") or {}

    multi_n = max(len(questions), len(targets) if len(targets) > 1 else 0)
    if multi_n > 1:
        if len(cleaned) == multi_n or (
            len(questions) > 1 and len(cleaned) == len(questions)
        ):
            return _plain(cleaned[:5])
        if plan.get("answers"):
            return _plain(fallback_messages_from_answer_plan(plan)[:5])
        primary = targets[0] if targets else "none"
        return _plain(
            world_state_fallback_messages(
                primary,
                world=world if isinstance(world, dict) else build_world_state(current),
                last_world=last_world if isinstance(last_world, dict) else {},
                targets=targets,
            )[:5]
        )

    if not cleaned:
        if plan.get("answers"):
            return _plain(fallback_messages_from_answer_plan(plan)[:3])
        return cleaned

    # Single answer: keep model bubbles (natural continuation), cap at 3
    return _plain(cleaned[:3])


def messages_state_update(
    texts: list[str],
    typing_style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packed = pack_message_dicts(apply_emoji_policy(_plain(list(texts)), typing_style))
    return {
        "generated_messages": packed,
        "generated_response": join_messages(packed),
    }
