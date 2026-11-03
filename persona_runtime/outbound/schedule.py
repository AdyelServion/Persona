"""Per-user proactive evaluation scheduling (randomized intervals, quiet-hour queue)."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from persona_runtime.db.time_utils import ensure_utc
from persona_runtime.outbound.policy import in_quiet_hours, local_now_for

DEFAULT_INTERVAL_OPTIONS = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60]
ENGAGEMENT_POLICY_VERSION = 2


def interval_options_from_doc(doc: dict[str, Any], app_settings: Any) -> list[int]:
    raw = doc.get("interval_options_minutes")
    if isinstance(raw, list) and raw:
        opts = sorted({int(x) for x in raw if int(x) > 0})
        if opts:
            return opts
    fallback = getattr(app_settings, "proactive_interval_options_minutes", None)
    if isinstance(fallback, list) and fallback:
        return sorted({int(x) for x in fallback if int(x) > 0})
    return list(DEFAULT_INTERVAL_OPTIONS)


def pick_interval_minutes(
    options: list[int],
    *,
    user_id: str,
    now: datetime,
    jitter_ratio: float = 0.15,
) -> tuple[int, float]:
    """Return (base_minutes, jittered_minutes as float)."""
    if not options:
        options = DEFAULT_INTERVAL_OPTIONS
    seed = int(hashlib.sha256(f"{user_id}:{ensure_utc(now).isoformat()}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    base = rng.choice(options)
    jitter = max(0.0, min(0.5, float(jitter_ratio)))
    spread = base * jitter
    delta = rng.uniform(-spread, spread)
    minutes = max(1.0, base + delta)
    return base, minutes


def compute_next_evaluation_at(now: datetime, minutes: float) -> datetime:
    return ensure_utc(now) + timedelta(minutes=float(minutes))


def next_time_after_quiet_hours(
    *,
    local_now: datetime,
    quiet_start: str,
    quiet_end: str,
    jitter_minutes: float = 3.0,
) -> datetime:
    """UTC instant at quiet end (local) plus small jitter."""
    tz = local_now.tzinfo or ZoneInfo("UTC")
    end_h, end_m = (quiet_end or "08:00").split(":")
    end_t = local_now.replace(hour=int(end_h), minute=int(end_m), second=0, microsecond=0)
    if local_now >= end_t:
        end_t = end_t + timedelta(days=1)
    # Convert local end to UTC
    end_local = end_t.replace(tzinfo=tz)
    jitter = random.uniform(0, max(0.0, jitter_minutes))
    return ensure_utc(end_local) + timedelta(minutes=jitter)


def should_queue_for_quiet_hours(
    doc: dict[str, Any],
    app_settings: Any,
    now: datetime,
) -> tuple[bool, datetime | None]:
    if not doc.get("quiet_hours_enabled", True):
        return False, None
    local = local_now_for(doc, now, getattr(app_settings, "timezone", "Europe/London"))
    q_start = doc.get("quiet_start") or app_settings.proactive_quiet_start
    q_end = doc.get("quiet_end") or app_settings.proactive_quiet_end
    if not in_quiet_hours(local, q_start, q_end):
        return False, None
    return True, next_time_after_quiet_hours(local_now=local, quiet_start=q_start, quiet_end=q_end)


def eval_bucket_key(now: datetime, interval_minutes: int) -> str:
    """Floor UTC time to interval for idempotency buckets."""
    ts = ensure_utc(now)
    bucket_min = max(1, int(interval_minutes))
    floored = ts.replace(second=0, microsecond=0)
    minute = (floored.minute // bucket_min) * bucket_min
    floored = floored.replace(minute=minute)
    return floored.isoformat()
