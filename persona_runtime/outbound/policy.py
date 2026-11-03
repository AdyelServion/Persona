"""Permission and frequency gates for proactive outbound messages.

Every gate is evaluated in the user's own timezone. Any failing gate blocks the send;
the first failing gate is returned as the reason so it can be logged and tested.

Quiet hours during *evaluation* are handled by the planner (queue/reschedule), not here,
unless ``check_quiet_hours=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from persona_runtime.db.time_utils import ensure_utc

UNANSWERED_EXPIRY_HOURS = 72


@dataclass
class OutboundDecision:
    allow: bool
    reason: str
    local_now: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"allow": self.allow, "reason": self.reason, "details": self.details}


def _parse_hhmm(value: str, default: str) -> time:
    try:
        hh, mm = (value or default).split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        hh, mm = default.split(":")
        return time(int(hh), int(mm))


def local_now_for(settings_doc: dict[str, Any], now: datetime, fallback_tz: str) -> datetime:
    try:
        tz = ZoneInfo(settings_doc.get("timezone") or fallback_tz)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo(fallback_tz)
    return ensure_utc(now).astimezone(tz)


def in_quiet_hours(local_now: datetime, quiet_start: str, quiet_end: str) -> bool:
    start = _parse_hhmm(quiet_start, "22:00")
    end = _parse_hhmm(quiet_end, "08:00")
    t = local_now.time()
    if start == end:
        return False
    if start < end:
        return start <= t < end
    return t >= start or t < end


def _history_times(settings_doc: dict[str, Any]) -> list[datetime]:
    out = []
    for h in settings_doc.get("outbound_history") or []:
        if isinstance(h, dict) and h.get("at"):
            try:
                out.append(ensure_utc(h["at"]))
            except Exception:  # noqa: BLE001
                continue
    return out


def _min_gap_timedelta(settings_doc: dict[str, Any], app_settings: Any, backoff: int) -> timedelta:
    if int(settings_doc.get("engagement_policy_version") or 0) >= 2:
        gap_min = float(settings_doc.get("min_gap_minutes") or getattr(app_settings, "proactive_min_gap_minutes", 5))
        base = timedelta(minutes=gap_min)
    else:
        gap_hours = float(settings_doc.get("min_gap_hours") or app_settings.proactive_min_gap_hours)
        base = timedelta(hours=gap_hours)
    return base * (2**backoff)


def evaluate_outbound(
    *,
    settings_doc: dict[str, Any] | None,
    app_settings: Any,
    now: datetime,
    proactive_type: str | None = None,
    open_proactive_jobs: int = 0,
    ignore_quiet_hours: bool = False,
    check_quiet_hours: bool = True,
) -> OutboundDecision:
    now = ensure_utc(now)
    if not getattr(app_settings, "proactive_outbound_enabled", False):
        return OutboundDecision(False, "globally_disabled")
    doc = settings_doc or {}
    if not doc or not doc.get("enabled") or not doc.get("opted_in_at"):
        return OutboundDecision(False, "not_opted_in")
    local = local_now_for(doc, now, getattr(app_settings, "timezone", "Europe/London"))

    paused = doc.get("paused_until")
    if paused and ensure_utc(paused) > now:
        return OutboundDecision(False, "paused", local)
    if proactive_type and proactive_type in (doc.get("muted_types") or []):
        return OutboundDecision(False, "type_muted", local)

    max_unanswered = int(doc.get("max_unanswered_outbound_messages") or 1)
    if max_unanswered > 0 and doc.get("unanswered_outbound_id"):
        return OutboundDecision(False, "awaiting_reply", local)

    if open_proactive_jobs > 0:
        return OutboundDecision(False, "already_scheduled", local)

    if (
        check_quiet_hours
        and doc.get("quiet_hours_enabled", True)
        and not ignore_quiet_hours
        and in_quiet_hours(
            local,
            doc.get("quiet_start") or app_settings.proactive_quiet_start,
            doc.get("quiet_end") or app_settings.proactive_quiet_end,
        )
    ):
        return OutboundDecision(False, "quiet_hours", local)

    backoff = int(doc.get("backoff_level") or 0)
    required_gap = _min_gap_timedelta(doc, app_settings, backoff)
    last = doc.get("last_outbound_at")
    if last and now - ensure_utc(last) < required_gap:
        return OutboundDecision(
            False, "backoff" if backoff else "min_gap", local, {"required_gap_seconds": required_gap.total_seconds()}
        )

    times = _history_times(doc)
    if int(doc.get("engagement_policy_version") or 0) >= 2:
        hourly_limit = int(doc.get("hourly_limit") or getattr(app_settings, "proactive_max_per_hour", 2))
        if hourly_limit > 0 and sum(1 for t in times if now - t < timedelta(hours=1)) >= hourly_limit:
            return OutboundDecision(False, "hourly_cap", local)

    daily_limit = int(doc.get("daily_limit") or app_settings.proactive_max_per_day)
    weekly_limit = int(doc.get("weekly_limit") or app_settings.proactive_max_per_week)
    if daily_limit > 0 and sum(1 for t in times if now - t < timedelta(hours=24)) >= daily_limit:
        return OutboundDecision(False, "daily_cap", local)
    if weekly_limit > 0 and sum(1 for t in times if now - t < timedelta(days=7)) >= weekly_limit:
        return OutboundDecision(False, "weekly_cap", local)

    if int(doc.get("engagement_policy_version") or 0) >= 2:
        max_consec = int(
            doc.get("max_consecutive_initiations") or getattr(app_settings, "proactive_max_consecutive_initiations", 3)
        )
        if max_consec > 0 and int(doc.get("consecutive_initiations_without_reply") or 0) >= max_consec:
            return OutboundDecision(False, "consecutive_initiation_cap", local)

    return OutboundDecision(True, "allowed", local)


def unanswered_expired(settings_doc: dict[str, Any], now: datetime) -> bool:
    since = settings_doc.get("unanswered_since")
    if not settings_doc.get("unanswered_outbound_id") or not since:
        return False
    return ensure_utc(now) - ensure_utc(since) >= timedelta(hours=UNANSWERED_EXPIRY_HOURS)
