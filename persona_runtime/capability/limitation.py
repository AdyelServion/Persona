"""Restricted response path when capability is blocked — no main answer generation."""

from __future__ import annotations

import hashlib
from typing import Any

from persona_runtime.capability.validator import capability_fallback_reply


def pick_limitation_line(state: dict[str, Any]) -> str | None:
    """Deterministic casual limitation line for blocked turns."""
    fallback = capability_fallback_reply(state)
    if fallback:
        return fallback
    decision = state.get("capability_decision") or {}
    profile = state.get("capability_profile") or {}
    topic = str(decision.get("limitation_topic") or "generic")
    conv = state.get("conversation_context") or {}
    recent = list(conv.get("recent_capability_declines") or [])
    pool = limitation_template_pool(profile, topic, recent)
    used = {str(r).strip().lower() for r in recent if r}
    fresh = [t for t in pool if t.strip().lower() not in used]
    pool = fresh or pool
    if not pool:
        return None
    msg = state.get("incoming_message") or topic
    seed = f"{msg}|{len(recent)}|{topic}|{len(pool)}"
    idx = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(pool)
    line = pool[idx]
    return line.replace("{topic}", topic)


def emit_limitation_response(state: dict[str, Any]) -> dict[str, Any]:
    """Build a single casual limitation bubble without exposing the user task to the main generator."""
    line = pick_limitation_line(state)
    if not line:
        line = "thats not really something id know much about"
    return {
        "generated_response": line,
        "generated_messages": [{"text": line, "type": "text"}],
        "capability_limitation_path_used": True,
    }


def build_limitation_prompt_context(state: dict[str, Any]) -> dict[str, Any]:
    """Minimal context for optional limitation paraphrase — topic family only, not the request."""
    decision = state.get("capability_decision") or {}
    return {
        "limitation_topic": decision.get("limitation_topic") or "generic",
        "typing_style": (state.get("typing_style") or {}).get("params") or {},
        "recent_declines": list((state.get("conversation_context") or {}).get("recent_capability_declines") or [])[-3:],
    }


def limitation_template_pool(profile: dict[str, Any], topic: str, recent: list[str]) -> list[str]:
    templates = dict(profile.get("limitation_templates") or {})
    pool = list(templates.get(topic) or templates.get("generic") or [])
    pool.extend(list(profile.get("fallback_styles") or []))
    used = {r.lower()[:50] for r in recent if r}
    fresh = [t for t in pool if t.lower() not in used]
    return fresh or pool or ["thats not really something id know much about"]
