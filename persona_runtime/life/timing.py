"""Response delay computation — scheduled once and persisted."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any

from persona_runtime.db.time_utils import ensure_utc
from persona_runtime.life.activities import get_activity


PRIORITY_MODIFIERS = {
    "low": 1.15,
    "normal": 1.0,
    "important": 0.65,
    "emotionally_important": 0.55,
    "urgent": 0.35,
}

# Human-readable labels for countdown UI (activity key -> short phrase)
ACTIVITY_LABELS: dict[str, str] = {
    "sleeping": "Asleep",
    "waking_up": "Waking up",
    "breakfast": "At breakfast",
    "commuting": "Commuting",
    "working": "At work",
    "deep_work": "Deep work",
    "meeting": "In a meeting",
    "lunch": "At lunch",
    "coffee_break": "On a break",
    "gym": "At the gym",
    "shopping": "Out shopping",
    "cooking": "Cooking",
    "eating": "Eating",
    "reading": "Reading",
    "watching_tv": "Watching TV",
    "walking": "Out walking",
    "with_friends": "With friends",
    "family_call": "On a call",
    "relaxing": "Free",
    "personal_time": "Free",
    "running_errands": "Running errands",
    "travelling": "Travelling",
}


def activity_label(activity_key: str | None) -> str:
    key = activity_key or "relaxing"
    if key in ACTIVITY_LABELS:
        return ACTIVITY_LABELS[key]
    params = get_activity(key)
    return ACTIVITY_LABELS.get(params.key, params.key.replace("_", " ").title())


def _rng(seed: str) -> random.Random:
    n = int(hashlib.sha256((seed or "default").encode()).hexdigest()[:12], 16)
    return random.Random(n)


def _sample_delay_minutes(
    rng: random.Random,
    *,
    delay_min: float,
    delay_max: float,
    avail_mod: float,
    attention_mod: float,
    priority_mod: float,
    rel_mod: float,
    toward_late: bool,
) -> float:
    """Sample across the activity delay band (stable RNG), biased by modifiers."""
    lo = float(delay_min)
    hi = float(delay_max)
    if hi < lo:
        hi = lo
    if hi <= lo:
        base = lo
    elif toward_late:
        # Upper half of the band for skip / low engagement
        mid = (lo + hi) / 2.0
        base = rng.uniform(mid, hi)
    else:
        base = rng.uniform(lo, hi)

    delay = base * avail_mod * attention_mod * priority_mod * rel_mod
    return max(lo, min(hi, delay))


def compute_response_schedule(
    *,
    activity_key: str,
    availability: float,
    priority: str,
    relationship_stage: str = "new_contact",
    now: datetime,
    activity_expected_end_at: datetime | None = None,
    batch_window_seconds: float = 15.0,
    time_scale: float = 1.0,
    seed: str = "",
    force_after_busy: bool = False,
) -> dict[str, Any]:
    """Compute when Sarah should respond. Delay is locked by seed once persisted."""
    now = ensure_utc(now)
    params = get_activity(activity_key)
    priority = priority if priority in PRIORITY_MODIFIERS else "normal"
    scale = max(0.001, float(time_scale))
    batch_floor = max(1.0, float(batch_window_seconds) * scale)
    seed_key = seed or f"{activity_key}:{now.isoformat()}"
    rng = _rng(seed_key)

    if params.sleeping:
        wake = activity_expected_end_at or (now + timedelta(hours=7))
        wake = ensure_utc(wake)
        read_at = wake + timedelta(seconds=30 * scale)
        scheduled = max(
            wake + timedelta(minutes=2 * scale),
            now + timedelta(seconds=batch_floor),
        )
        return {
            "scheduled_for": scheduled,
            "read_at": read_at,
            "delay_seconds": (scheduled - now).total_seconds(),
            "reason": "currently_sleeping",
            "activity": params.key,
            "availability": params.availability,
            "strategy_hint": "DEFER_RESPONSE",
            "engaged": False,
        }

    avail = float(availability if availability is not None else params.availability)
    avail_mod = max(0.5, min(8.0, (1.1 - avail) * 2.5 + 0.5))
    attention_mod = 0.7 + 0.6 * float(params.attention)
    priority_mod = PRIORITY_MODIFIERS[priority]
    rel_mod = {
        "new_contact": 1.1,
        "unknown": 1.1,
        "acquaintance": 1.0,
        "familiar": 0.9,
        "close": 0.8,
        "friend": 0.75,
    }.get(relationship_stage or "new_contact", 1.0)

    # Urgent / important always try to engage when interruption is tolerable
    engage_roll = rng.random()
    base_prob = float(params.response_probability)
    if priority in {"urgent", "emotionally_important"}:
        engage_prob = max(base_prob, 0.85)
    elif priority == "important":
        engage_prob = max(base_prob, 0.55)
    else:
        engage_prob = base_prob
    engaged = engage_roll < engage_prob

    end_at = ensure_utc(activity_expected_end_at) if activity_expected_end_at else None
    very_busy = params.availability < 0.15 or params.busy or force_after_busy

    # --- Very busy / forced defer ---
    if very_busy and not engaged:
        delay_minutes = _sample_delay_minutes(
            rng,
            delay_min=params.delay_min_minutes,
            delay_max=params.delay_max_minutes,
            avail_mod=avail_mod,
            attention_mod=attention_mod,
            priority_mod=priority_mod,
            rel_mod=rel_mod,
            toward_late=True,
        )
        delay_seconds = delay_minutes * 60.0 * scale
        if end_at and end_at > now:
            after = end_at + timedelta(seconds=delay_seconds * 0.2)
            scheduled = after
            strategy_hint = "DEFER_RESPONSE"
            reason = f"waiting_until_{params.key}_ends"
        else:
            scheduled = now + timedelta(seconds=max(batch_floor, delay_seconds))
            strategy_hint = "DEFER_RESPONSE"
            reason = f"deferred_{params.key}"
        read_at = (
            end_at + timedelta(seconds=15 * scale)
            if end_at and end_at > now
            else min(scheduled, now + timedelta(seconds=max(5.0 * scale, delay_seconds * 0.35)))
        )
        return {
            "scheduled_for": ensure_utc(scheduled),
            "read_at": ensure_utc(read_at),
            "delay_seconds": (ensure_utc(scheduled) - now).total_seconds(),
            "reason": reason,
            "activity": params.key,
            "availability": avail,
            "strategy_hint": strategy_hint,
            "engaged": False,
        }

    if very_busy and engaged:
        # Busy ack for important interruptions; otherwise still defer after end
        if priority in {"urgent", "emotionally_important", "important"} and params.interruption_tolerance >= 0.05:
            glance = rng.uniform(20.0, 120.0) * scale
            scheduled = now + timedelta(seconds=max(batch_floor, glance))
            read_at = min(scheduled, now + timedelta(seconds=max(5.0 * scale, glance * 0.4)))
            return {
                "scheduled_for": ensure_utc(scheduled),
                "read_at": ensure_utc(read_at),
                "delay_seconds": (ensure_utc(scheduled) - now).total_seconds(),
                "reason": f"busy_ack_{params.key}",
                "activity": params.key,
                "availability": avail,
                "strategy_hint": "ACKNOWLEDGE_LATEST",
                "engaged": True,
            }
        delay_minutes = _sample_delay_minutes(
            rng,
            delay_min=params.delay_min_minutes,
            delay_max=params.delay_max_minutes,
            avail_mod=avail_mod,
            attention_mod=attention_mod,
            priority_mod=priority_mod,
            rel_mod=rel_mod,
            toward_late=True,
        )
        delay_seconds = delay_minutes * 60.0 * scale
        if end_at and end_at > now:
            scheduled = end_at + timedelta(seconds=delay_seconds * 0.2)
            reason = f"waiting_until_{params.key}_ends"
        else:
            scheduled = now + timedelta(seconds=max(batch_floor, delay_seconds))
            reason = f"deferred_{params.key}"
        read_at = (
            end_at + timedelta(seconds=15 * scale)
            if end_at and end_at > now
            else min(scheduled, now + timedelta(seconds=max(5.0 * scale, delay_seconds * 0.35)))
        )
        return {
            "scheduled_for": ensure_utc(scheduled),
            "read_at": ensure_utc(read_at),
            "delay_seconds": (ensure_utc(scheduled) - now).total_seconds(),
            "reason": reason,
            "activity": params.key,
            "availability": avail,
            "strategy_hint": "DEFER_RESPONSE",
            "engaged": False,
        }

    # --- Available / office desk: glance vs later in-band reply ---
    if engaged:
        # Short human glance — tens of seconds to a few minutes (can beat delay_min)
        glance_hi = min(180.0, max(45.0, params.delay_min_minutes * 60.0 * 0.5))
        glance_lo = min(25.0, glance_hi * 0.4)
        glance = rng.uniform(glance_lo, glance_hi) * scale
        # Priority pulls glance earlier
        glance *= priority_mod
        scheduled = now + timedelta(seconds=max(batch_floor, glance))
        read_at = min(scheduled, now + timedelta(seconds=max(5.0 * scale, glance * 0.35)))
        return {
            "scheduled_for": ensure_utc(scheduled),
            "read_at": ensure_utc(read_at),
            "delay_seconds": (ensure_utc(scheduled) - now).total_seconds(),
            "reason": f"glance_while_{params.key}",
            "activity": params.key,
            "availability": avail,
            "strategy_hint": "RESPOND_TO_GROUP",
            "engaged": True,
        }

    # Skip: later reply still within activity band (toward late)
    delay_minutes = _sample_delay_minutes(
        rng,
        delay_min=params.delay_min_minutes,
        delay_max=params.delay_max_minutes,
        avail_mod=avail_mod,
        attention_mod=attention_mod,
        priority_mod=priority_mod,
        rel_mod=rel_mod,
        toward_late=True,
    )
    delay_seconds = delay_minutes * 60.0 * scale
    scheduled = now + timedelta(seconds=max(batch_floor, delay_seconds))
    read_at = min(scheduled, now + timedelta(seconds=max(5.0 * scale, delay_seconds * 0.35)))
    return {
        "scheduled_for": ensure_utc(scheduled),
        "read_at": ensure_utc(read_at),
        "delay_seconds": (ensure_utc(scheduled) - now).total_seconds(),
        "reason": f"later_while_{params.key}",
        "activity": params.key,
        "availability": avail,
        "strategy_hint": "RESPOND_TO_GROUP",
        "engaged": False,
    }
