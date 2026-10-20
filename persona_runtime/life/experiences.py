"""Simulated experience events for open activity windows (meals and future slots)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from uuid import uuid4

from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.life.activities import EXPERIENCE_SLOT_CATALOGS, experience_slots_for


def _stable_choice(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(options)
    return options[idx]


def window_key(persona_id: str, activity: str, started_at: datetime | None) -> str:
    start = ensure_utc(started_at or utcnow()).isoformat()
    return f"{persona_id}:{activity}:{start}"


def find_open_event(
    events: list[dict[str, Any]],
    *,
    slot: str,
    activity: str | None = None,
) -> dict[str, Any] | None:
    for ev in reversed(events or []):
        if ev.get("slot") != slot:
            continue
        if ev.get("ended_at"):
            continue
        if activity and ev.get("activity") != activity:
            continue
        return ev
    return None


def find_event_for_window(
    events: list[dict[str, Any]],
    *,
    slot: str,
    window: str,
) -> dict[str, Any] | None:
    for ev in events or []:
        if ev.get("slot") == slot and ev.get("window_key") == window:
            return ev
    return None


def find_past_events(
    events: list[dict[str, Any]],
    *,
    slot: str | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ev in events or []:
        if slot and ev.get("slot") != slot:
            continue
        started = ev.get("started_at")
        if started is None:
            continue
        started_dt = ensure_utc(started)
        if before and started_dt >= ensure_utc(before):
            continue
        if after and started_dt < ensure_utc(after):
            continue
        out.append(ev)
    return out


def materialize_experience(
    *,
    persona_id: str,
    activity: str,
    slot: str,
    started_at: datetime | None,
    expected_end_at: datetime | None,
    existing_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Create or reuse a simulated experience for the open activity window.

    Returns None when the activity does not declare the slot or catalog is empty.
    """
    declared = experience_slots_for(activity)
    if slot not in declared:
        return None
    catalog = EXPERIENCE_SLOT_CATALOGS.get(slot) or []
    if not catalog:
        return None

    events = list(existing_events or [])
    window = window_key(persona_id, activity, started_at)
    existing = find_event_for_window(events, slot=slot, window=window)
    if existing:
        return existing

    open_ev = find_open_event(events, slot=slot, activity=activity)
    if open_ev and open_ev.get("window_key") == window:
        return open_ev

    value = _stable_choice(f"{window}:{slot}", list(catalog))
    now = utcnow()
    event = {
        "event_id": str(uuid4()),
        "slot": slot,
        "value": value,
        "status": "simulated",
        "activity": activity,
        "window_key": window,
        "started_at": ensure_utc(started_at or now),
        "ended_at": None,
        "expected_end_at": ensure_utc(expected_end_at) if expected_end_at else None,
        "timeline_event_id": None,
        "source": "life_simulator",
        "created_at": now,
    }
    return event


def close_open_experiences(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    old_activity: str | None = None,
) -> list[dict[str, Any]]:
    """Mark open events as ended when the activity window closes."""
    moment = ensure_utc(now or utcnow())
    updated: list[dict[str, Any]] = []
    for ev in events or []:
        item = dict(ev)
        if item.get("ended_at"):
            updated.append(item)
            continue
        if old_activity and item.get("activity") != old_activity:
            updated.append(item)
            continue
        item["ended_at"] = moment
        updated.append(item)
    return updated


def resolve_experience_for_slot(
    *,
    persona_id: str,
    state_doc: dict[str, Any],
    slot: str,
    state_repo: Any | None = None,
) -> dict[str, Any] | None:
    """Ensure an experience exists for the current open window and persist it."""
    current = (state_doc or {}).get("current_state") or {}
    activity = current.get("current_activity") or ""
    events = list((state_doc or {}).get("experience_events") or [])
    event = materialize_experience(
        persona_id=persona_id,
        activity=activity,
        slot=slot,
        started_at=current.get("activity_started_at"),
        expected_end_at=current.get("activity_expected_end_at"),
        existing_events=events,
    )
    if not event:
        return None
    # Attach active timeline event id when available
    if not event.get("timeline_event_id") and current.get("active_event_id"):
        event = dict(event)
        event["timeline_event_id"] = current.get("active_event_id")
    # Persist if new or newly linked
    existing = next((e for e in events if e.get("event_id") == event.get("event_id")), None)
    if existing is None:
        events.append(event)
        if state_repo is not None:
            state_repo.set_experience_events(persona_id, events)
    elif existing.get("timeline_event_id") != event.get("timeline_event_id"):
        for i, e in enumerate(events):
            if e.get("event_id") == event.get("event_id"):
                events[i] = event
                break
        if state_repo is not None:
            state_repo.set_experience_events(persona_id, events)
    return event
