"""Permission policy for proactive / resume messages — no idle messaging loops."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from persona_runtime.db.time_utils import ensure_utc, utcnow

Situation = Literal[
    "user_just_sent_message",
    "user_resumed",
    "awaiting_user_response",
    "outbound_allowed",
    "outbound_disabled",
    "user_opted_out",
    "user_unavailable",
]


def evaluate_proactive_policy(
    *,
    situation: Situation | str,
    settings: Any,
    conversation_context: dict[str, Any] | None = None,
    open_job: dict[str, Any] | None = None,
    persona_state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide whether Sarah may schedule an autonomous outbound message."""
    now = ensure_utc(now or utcnow())
    conv = conversation_context or {}
    current = (persona_state or {}).get("current_state") or persona_state or {}

    enabled = bool(getattr(settings, "proactive_outbound_enabled", False))
    min_hours = float(getattr(settings, "proactive_min_interval_hours", 12.0))
    max_per_day = int(getattr(settings, "proactive_max_per_day", 1))

    reasons: list[str] = []
    allow = False

    if situation == "user_just_sent_message":
        # Normal reply path — not proactive outbound
        return {
            "allow_outbound": False,
            "situation": situation,
            "reason": "user_message_uses_normal_reply_path",
            "use_engagement_in_reply": True,
        }

    if conv.get("proactive_opt_out"):
        return {
            "allow_outbound": False,
            "situation": "user_opted_out",
            "reason": "user_disabled_proactive",
            "use_engagement_in_reply": False,
        }

    if not enabled and situation != "user_resumed":
        return {
            "allow_outbound": False,
            "situation": "outbound_disabled",
            "reason": "PROACTIVE_OUTBOUND_ENABLED=false",
            "use_engagement_in_reply": situation == "user_resumed",
        }

    if current.get("sleeping") or float(current.get("availability") or 0.5) < 0.25:
        return {
            "allow_outbound": False,
            "situation": "user_unavailable",
            "reason": "persona_unavailable",
            "use_engagement_in_reply": False,
        }

    if open_job and open_job.get("status") in {"scheduled", "running"}:
        return {
            "allow_outbound": False,
            "situation": "awaiting_user_response",
            "reason": "open_response_job_exists",
            "use_engagement_in_reply": False,
        }

    # Frequency caps
    last_at = conv.get("last_proactive_at")
    if last_at is not None:
        try:
            last_dt = ensure_utc(last_at)
            if (now - last_dt) < timedelta(hours=min_hours):
                reasons.append("min_interval")
                return {
                    "allow_outbound": False,
                    "situation": situation,
                    "reason": "proactive_min_interval",
                    "use_engagement_in_reply": situation == "user_resumed",
                }
        except Exception:  # noqa: BLE001
            pass

    day_count = int(conv.get("proactive_count_today") or 0)
    day_key = conv.get("proactive_day_key") or ""
    today_key = now.date().isoformat()
    if day_key != today_key:
        day_count = 0
    if day_count >= max_per_day:
        return {
            "allow_outbound": False,
            "situation": situation,
            "reason": "proactive_max_per_day",
            "use_engagement_in_reply": situation == "user_resumed",
        }

    if situation == "user_resumed":
        # Explicit resume: may schedule one message only when outbound enabled
        allow = enabled
        reasons.append("resume_explicit" if enabled else "resume_content_in_reply_only")
        return {
            "allow_outbound": allow,
            "situation": situation,
            "reason": ";".join(reasons) or "resume",
            "use_engagement_in_reply": not allow,
            "proactive_day_key": today_key,
            "proactive_count_today": day_count,
        }

    if situation == "outbound_allowed" and enabled:
        allow = True
        reasons.append("outbound_allowed")

    return {
        "allow_outbound": allow,
        "situation": situation,
        "reason": ";".join(reasons) or ("allowed" if allow else "denied"),
        "use_engagement_in_reply": False,
        "proactive_day_key": today_key,
        "proactive_count_today": day_count,
    }
