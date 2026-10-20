"""Persona dynamic state repository."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow
from persona_runtime.life.activities import get_activity, activity_to_state_fields


def activity_for_now(tz_name: str = "Europe/London") -> dict[str, Any]:
    """Legacy helper kept for tests — prefer LifeSimulator for runtime state.

    Returns a snapshot-like dict without mutating PersonaState.
    Uses the injectable PersonaClock so tests with ``set_clock`` stay deterministic.
    """
    from persona_runtime.life.clock import clock_snapshot

    snap = clock_snapshot(tz_name=tz_name)
    hour = snap.local_now.hour
    weekday = snap.weekday_index
    if weekday >= 5:
        if hour < 10:
            key = "breakfast"
        elif hour < 17:
            key = "with_friends"
        else:
            key = "personal_time"
    else:
        if 7 <= hour < 9:
            key = "commuting"
        elif 9 <= hour < 12:
            key = "working"
        elif 12 <= hour < 14:
            key = "lunch"
        elif 14 <= hour < 17:
            key = "working"
        elif 17 <= hour < 19:
            key = "commuting"
        elif 19 <= hour < 21:
            key = "cooking"
        elif 21 <= hour < 23:
            key = "personal_time"
        else:
            key = "sleeping"
    params = get_activity(key)
    return {
        "current_activity": params.key,
        "current_location": params.location,
        "availability": params.availability,
        "local_hour": hour,
        "weekday": weekday,
    }


_LIFE_KEYS = {
    "current_activity",
    "current_location",
    "availability",
    "focus_level",
    "activity_started_at",
    "activity_expected_end_at",
    "busy",
    "busy_reason",
    "sleeping",
    "next_activity",
    "next_activity_at",
    "last_activity_change",
    "current_task",
    "task_detail",
    "current_project",
    "situation",
    "last_location",
    "location_type",
    "next_planned_activity",
    "active_event_id",
    "last_completed_event_id",
    "next_planned_event_id",
    "transport_mode",
    "current_meal",
    "energy",
    "stress",
    "social_energy",
    "mood",
    "emotion",
    "active_goals",
    "active_fears",
    "conversation_state",
}


class PersonaStateRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["persona_state"]]

    def ensure_default_state(self, persona_id: str, tz_name: str = "Europe/London") -> dict[str, Any]:
        existing = self.col.find_one({"persona_id": persona_id})
        if existing:
            return existing

        # Initial activity from clock — life simulator will persist plan on first tick
        snap = activity_for_now(tz_name)
        params = get_activity(snap["current_activity"])
        life = activity_to_state_fields(params)
        now = utcnow()
        doc = {
            "persona_id": persona_id,
            "current_state": {
                "mood": "neutral_calm",
                "emotion": {"primary": "calm", "intensity": 0.35},
                "energy": 0.70,
                "stress": 0.30,
                "social_energy": 0.60,
                "focus_level": params.attention,
                "current_activity": life["current_activity"],
                "current_location": life["current_location"],
                "availability": life["availability"],
                "busy": life["busy"],
                "busy_reason": life["busy_reason"],
                "sleeping": life["sleeping"],
                "activity_started_at": now,
                "activity_expected_end_at": None,
                "next_activity": None,
                "next_activity_at": None,
                "last_activity_change": now,
                "current_task": None,
                "task_detail": None,
                "current_project": None,
                "situation": None,
                "last_location": None,
                "location_type": None,
                "next_planned_activity": None,
                "active_event_id": None,
                "last_completed_event_id": None,
                "next_planned_event_id": None,
                "transport_mode": None,
                "current_meal": None,
                "active_goals": ["career_growth", "work_life_balance"],
                "active_fears": [],
                "conversation_state": {},
            },
            "baseline": {
                "energy": 0.70,
                "stress": 0.30,
                "social_energy": 0.60,
            },
            "life_plan": [],
            "life_plan_date": None,
            "experience_events": [],
            "state_version": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.col.insert_one(doc)
        return doc

    def get_state(self, persona_id: str) -> dict[str, Any]:
        doc = self.col.find_one({"persona_id": persona_id})
        if not doc:
            return self.ensure_default_state(persona_id)
        return doc

    def set_life_plan(self, persona_id: str, plan: list[dict[str, Any]], date_str: str) -> None:
        self.get_state(persona_id)
        self.col.update_one(
            {"persona_id": persona_id},
            {"$set": {"life_plan": plan, "life_plan_date": date_str, "updated_at": utcnow()}},
        )

    def apply_updates(self, persona_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Apply state updates with clamping. Never touches personality docs."""
        doc = self.get_state(persona_id)
        state = dict(doc.get("current_state") or {})
        for key, value in updates.items():
            if key not in _LIFE_KEYS and key not in {
                "mood",
                "emotion",
                "active_goals",
                "active_fears",
                "conversation_state",
            }:
                continue
            if key in {"energy", "stress", "social_energy", "availability", "focus_level"} and isinstance(
                value, (int, float)
            ):
                state[key] = float(max(0.0, min(1.0, value)))
            elif key in {
                "mood",
                "current_activity",
                "current_location",
                "busy_reason",
                "next_activity",
                "current_task",
                "task_detail",
                "current_project",
                "situation",
                "last_location",
                "location_type",
                "next_planned_activity",
                "active_event_id",
                "last_completed_event_id",
                "next_planned_event_id",
                "transport_mode",
                "current_meal",
            }:
                state[key] = value
            elif key in {"busy", "sleeping"}:
                state[key] = bool(value)
            elif key == "emotion" and isinstance(value, dict):
                state["emotion"] = value
            elif key in {
                "activity_started_at",
                "activity_expected_end_at",
                "next_activity_at",
                "last_activity_change",
            }:
                state[key] = value
            elif key in {"active_goals", "active_fears", "conversation_state"}:
                state[key] = value
        self.col.update_one(
            {"persona_id": persona_id},
            {"$set": {"current_state": state, "updated_at": utcnow()}},
        )
        return self.get_state(persona_id)

    def decay_toward_baseline(self, persona_id: str, hours_elapsed: float) -> dict[str, Any]:
        """Ease energy/stress/social toward baseline. Does NOT overwrite activity."""
        doc = self.get_state(persona_id)
        state = dict(doc.get("current_state") or {})
        baseline = doc.get("baseline") or {}
        factor = min(1.0, max(0.0, hours_elapsed / 24.0))
        for key in ("energy", "stress", "social_energy"):
            current = float(state.get(key, 0.5))
            base = float(baseline.get(key, current))
            state[key] = current + (base - current) * factor * 0.5
        self.col.update_one(
            {"persona_id": persona_id},
            {"$set": {"current_state": state, "updated_at": utcnow()}},
        )
        return self.get_state(persona_id)

    def get_experience_events(self, persona_id: str) -> list[dict[str, Any]]:
        doc = self.get_state(persona_id)
        return list(doc.get("experience_events") or [])

    def set_experience_events(self, persona_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Persist experience log on PersonaState (outside current_state)."""
        self.get_state(persona_id)
        self.col.update_one(
            {"persona_id": persona_id},
            {"$set": {"experience_events": events, "updated_at": utcnow()}},
        )
        return self.get_state(persona_id)

    def append_experience_event(self, persona_id: str, event: dict[str, Any]) -> dict[str, Any]:
        events = self.get_experience_events(persona_id)
        if not any(e.get("event_id") == event.get("event_id") for e in events):
            events.append(event)
        return self.set_experience_events(persona_id, events)
