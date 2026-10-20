"""Persistent timeline events and deterministic advancement policy."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.life.activities import (
    activity_to_state_fields,
    get_activity,
    keeps_workday_task,
    location_type_for,
    next_activity_phrase,
    pick_work_task,
    situation_for_activity,
)
from persona_runtime.life.clock import PersonaClock
from persona_runtime.life.experiences import close_open_experiences
from persona_runtime.life.transitions import normalize_location, transition_allowed
from persona_runtime.logging_utils import get_logger, log_event

logger = get_logger(__name__)

_COMMUTE_ACTIVITIES = frozenset({"commuting", "travelling"})


def _stable_event_id(persona_id: str, local_date: str, activity: str, start_iso: str) -> str:
    digest = hashlib.sha256(
        f"{persona_id}:{local_date}:{activity}:{start_iso}".encode()
    ).hexdigest()[:24]
    return f"tl_{digest}"


def _stable_rng(persona_id: str, seed: str) -> random.Random:
    n = int(hashlib.sha256(f"{persona_id}:{seed}".encode()).hexdigest()[:16], 16)
    return random.Random(n)


class TimelineRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["timeline_events"]]

    def insert_many_if_absent(self, events: list[dict[str, Any]]) -> int:
        inserted = 0
        for ev in events:
            existing = self.col.find_one({"event_id": ev["event_id"]})
            if existing:
                continue
            self.col.insert_one(ev)
            inserted += 1
        return inserted

    def get_by_id(self, event_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"event_id": event_id})

    def list_for_date(
        self,
        persona_id: str,
        local_date: str,
        *,
        statuses: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"persona_id": persona_id, "local_date": local_date}
        if statuses:
            query["status"] = {"$in": statuses}
        return list(self.col.find(query).sort("scheduled_start", 1))

    def list_planned_and_active(self, persona_id: str) -> list[dict[str, Any]]:
        return list(
            self.col.find(
                {
                    "persona_id": persona_id,
                    "status": {"$in": ["planned", "active"]},
                }
            ).sort("scheduled_start", 1)
        )

    def get_active(self, persona_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"persona_id": persona_id, "status": "active"})

    def list_completed_for_date(self, persona_id: str, local_date: str) -> list[dict[str, Any]]:
        return self.list_for_date(persona_id, local_date, statuses=["completed"])

    def find_next_planned(
        self,
        persona_id: str,
        *,
        after: datetime | None = None,
        activity: str | None = None,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {
            "persona_id": persona_id,
            "status": "planned",
        }
        if after is not None:
            query["scheduled_start"] = {"$gt": ensure_utc(after)}
        if activity:
            query["activity"] = activity
        return self.col.find_one(query, sort=[("scheduled_start", 1)])

    def find_arrive_home_estimate(
        self, persona_id: str, after: datetime
    ) -> dict[str, Any] | None:
        """Next commute whose scheduled_end is the home-arrival estimate."""
        query = {
            "persona_id": persona_id,
            "status": {"$in": ["planned", "active"]},
            "activity": "commuting",
            "scheduled_start": {"$gte": ensure_utc(after) - timedelta(hours=1)},
        }
        candidates = list(self.col.find(query).sort("scheduled_start", 1))
        for c in candidates:
            # Prefer evening commute (end location home via next event)
            return c
        return None

    def try_complete(
        self,
        event_id: str,
        *,
        expected_status: str,
        actual_end: datetime,
        now: datetime,
    ) -> bool:
        result = self.col.update_one(
            {"event_id": event_id, "status": expected_status},
            {
                "$set": {
                    "status": "completed",
                    "actual_end": ensure_utc(actual_end),
                    "updated_at": ensure_utc(now),
                }
            },
        )
        return result.modified_count == 1

    def try_activate(
        self,
        event_id: str,
        *,
        expected_status: str = "planned",
        actual_start: datetime,
        now: datetime,
    ) -> bool:
        result = self.col.update_one(
            {"event_id": event_id, "status": expected_status},
            {
                "$set": {
                    "status": "active",
                    "actual_start": ensure_utc(actual_start),
                    "updated_at": ensure_utc(now),
                }
            },
        )
        return result.modified_count == 1

    def count_for_date(self, persona_id: str, local_date: str) -> int:
        return self.col.count_documents({"persona_id": persona_id, "local_date": local_date})


def blocks_to_timeline_events(
    *,
    persona_id: str,
    blocks: list[dict[str, Any]],
    local_date: str,
    transport_mode: str = "public_transport",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    moment = ensure_utc(now or utcnow())
    events: list[dict[str, Any]] = []
    for block in blocks:
        start = ensure_utc(block["start_at"])
        end = ensure_utc(block["end_at"])
        activity = block["activity"]
        location = block.get("location") or get_activity(activity).location
        event_id = _stable_event_id(persona_id, local_date, activity, start.isoformat())
        transport = transport_mode if activity in _COMMUTE_ACTIVITIES else None
        events.append(
            {
                "event_id": event_id,
                "persona_id": persona_id,
                "event_type": activity,
                "local_date": local_date,
                "scheduled_start": start,
                "scheduled_end": end,
                "actual_start": None,
                "actual_end": None,
                "status": "planned",
                "location": location,
                "location_type": location_type_for(location, activity),
                "activity": activity,
                "task": None,
                "project": None,
                "transport_mode": transport,
                "detail": {},
                "source": "routine_template",
                "created_at": moment,
                "updated_at": moment,
            }
        )
    return events


class TimelineEngine:
    """Ensures daily planned events and advances world state via validated transitions."""

    def __init__(
        self,
        state_repo: Any,
        timeline_repo: TimelineRepository,
        *,
        tz_name: str = "Europe/London",
        commute_mode: str = "public_transport",
    ):
        self.state_repo = state_repo
        self.timeline_repo = timeline_repo
        self.tz_name = tz_name
        self.commute_mode = commute_mode
        self.clock = PersonaClock(tz_name=tz_name)

    def ensure_day_events(
        self,
        persona_id: str,
        *,
        now: datetime | None = None,
        local_date: str | None = None,
    ) -> list[dict[str, Any]]:
        snap = self.clock.snapshot(now=now)
        date_str = local_date or snap.local_date.isoformat()
        existing = self.timeline_repo.list_for_date(persona_id, date_str)
        if existing:
            return existing

        from persona_runtime.life.simulator import build_daily_plan

        if local_date and local_date != snap.local_date.isoformat():
            # Build plan for a specific past/future local date
            y, m, d = (int(x) for x in date_str.split("-"))
            local_noon = datetime(y, m, d, 12, 0, tzinfo=ZoneInfo(self.tz_name))
            plan = build_daily_plan(
                persona_id=persona_id, local_now=local_noon, tz_name=self.tz_name
            )
        else:
            plan = build_daily_plan(
                persona_id=persona_id,
                local_now=snap.local_now,
                tz_name=self.tz_name,
            )
            self.state_repo.set_life_plan(persona_id, plan, date_str)

        events = blocks_to_timeline_events(
            persona_id=persona_id,
            blocks=plan,
            local_date=date_str,
            transport_mode=self.commute_mode,
            now=snap.utc_now,
        )
        self.timeline_repo.insert_many_if_absent(events)
        return self.timeline_repo.list_for_date(persona_id, date_str)

    def advance(
        self,
        persona_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Walk due events; only this method changes event status."""
        snap = self.clock.snapshot(now=now)
        moment = snap.utc_now
        self.ensure_day_events(persona_id, now=moment)

        doc = self.state_repo.get_state(persona_id)
        state = dict(doc.get("current_state") or {})
        version = int(doc.get("state_version") or 0)

        pin = doc.get("activity_pin")
        if pin and pin.get("until"):
            until = ensure_utc(pin["until"])
            if until > moment:
                return self._apply_pin(persona_id, pin, state, moment, version)
            self.state_repo.col.update_one(
                {"persona_id": persona_id}, {"$unset": {"activity_pin": ""}}
            )
            doc = self.state_repo.get_state(persona_id)
            state = dict(doc.get("current_state") or {})
            version = int(doc.get("state_version") or 0)

        transitions: list[dict[str, Any]] = []
        # Catch-up loop: repeatedly activate the earliest due planned event
        # while completing the current active event when a successor is due.
        safety = 0
        while safety < 64:
            safety += 1
            active = self.timeline_repo.get_active(persona_id)
            open_events = self.timeline_repo.list_planned_and_active(persona_id)
            due_planned = [
                e
                for e in open_events
                if e.get("status") == "planned"
                and ensure_utc(e["scheduled_start"]) <= moment
            ]
            if not due_planned:
                break

            nxt = due_planned[0]

            if active is None:
                # Bootstrap: no active timeline event yet — sync onto the schedule
                # without requiring a transition from the legacy default location.
                has_history = bool(state.get("last_completed_event_id")) or bool(
                    state.get("active_event_id")
                )
                if has_history and not self._can_enter(state, nxt):
                    break
                if self.timeline_repo.try_activate(
                    nxt["event_id"],
                    expected_status="planned",
                    actual_start=ensure_utc(nxt["scheduled_start"]),
                    now=moment,
                ):
                    transitions.append(
                        {"event_id": nxt["event_id"], "from": "planned", "to": "active"}
                    )
                    state["current_location"] = nxt.get("location")
                    state["active_event_id"] = nxt["event_id"]
                else:
                    break
                continue

            # Active exists — only complete it when a later due event is ready
            if ensure_utc(nxt["scheduled_start"]) <= ensure_utc(active["scheduled_start"]):
                # Same or earlier planned still open (shouldn't happen) — skip
                break

            if not transition_allowed(active.get("location"), nxt.get("location")):
                log_event(
                    logger,
                    "timeline_transition_blocked",
                    persona_id=persona_id,
                    from_event=active.get("event_id"),
                    to_event=nxt.get("event_id"),
                    from_loc=active.get("location"),
                    to_loc=nxt.get("location"),
                )
                break

            end_at = min(moment, ensure_utc(nxt["scheduled_start"]))
            if not self.timeline_repo.try_complete(
                active["event_id"],
                expected_status="active",
                actual_end=end_at,
                now=moment,
            ):
                break
            transitions.append(
                {"event_id": active["event_id"], "from": "active", "to": "completed"}
            )
            self._close_experiences(
                persona_id, old_activity=active.get("activity"), now=moment
            )
            state["current_location"] = active.get("location")
            state["last_completed_event_id"] = active["event_id"]

            if not self.timeline_repo.try_activate(
                nxt["event_id"],
                expected_status="planned",
                actual_start=ensure_utc(nxt["scheduled_start"]),
                now=moment,
            ):
                break
            transitions.append(
                {"event_id": nxt["event_id"], "from": "planned", "to": "active"}
            )
            state["current_location"] = nxt.get("location")

        true_active = self.timeline_repo.get_active(persona_id)
        return self._sync_world_from_active(
            persona_id,
            active=true_active,
            state=state,
            now=moment,
            version=version,
            transitions=transitions,
        )

    def _can_enter(self, state: dict[str, Any], event: dict[str, Any]) -> bool:
        current = state.get("current_location")
        if not current:
            return True
        return transition_allowed(current, event.get("location"))

    def _close_experiences(
        self, persona_id: str, *, old_activity: str | None, now: datetime
    ) -> None:
        if not old_activity:
            return
        events = self.state_repo.get_experience_events(persona_id)
        closed = close_open_experiences(events, now=now, old_activity=old_activity)
        self.state_repo.set_experience_events(persona_id, closed)

    def _apply_pin(
        self,
        persona_id: str,
        pin: dict[str, Any],
        state: dict[str, Any],
        now: datetime,
        version: int,
    ) -> dict[str, Any]:
        params = get_activity(pin["activity"])
        until = ensure_utc(pin["until"])
        fields = activity_to_state_fields(params)
        fields["situation"] = situation_for_activity(params.key)
        next_act = "working" if keeps_workday_task(params.key) else "relaxing"
        if params.key in {"meeting", "lunch", "coffee_break"}:
            next_act = "working"
        fields.update(self._workday_task(persona_id, params.key, state, f"pin:{params.key}"))
        fields.update(
            {
                "activity_started_at": state.get("activity_started_at") or now,
                "activity_expected_end_at": until,
                "next_activity": next_act,
                "next_activity_at": until,
                "location_type": location_type_for(params.location, params.key),
                "next_planned_activity": next_activity_phrase(next_act),
                "transport_mode": self.commute_mode
                if params.key in _COMMUTE_ACTIVITIES
                else None,
                "active_event_id": state.get("active_event_id"),
            }
        )
        if state.get("current_location") and state.get("current_location") != params.location:
            fields["last_location"] = state.get("current_location")
        return self._cas_apply(persona_id, fields, version, transitions=[], now=now)

    def _workday_task(
        self,
        persona_id: str,
        activity_key: str,
        state: dict[str, Any],
        seed: str,
    ) -> dict[str, Any]:
        if keeps_workday_task(activity_key):
            if state.get("current_task") and state.get("current_project"):
                return {
                    "current_task": state.get("current_task"),
                    "task_detail": state.get("task_detail"),
                    "current_project": state.get("current_project"),
                }
            task = pick_work_task(_stable_rng(persona_id, seed))
            return {
                "current_task": state.get("current_task") or task["current_task"],
                "task_detail": state.get("task_detail") or task["task_detail"],
                "current_project": state.get("current_project")
                or task.get("current_project"),
            }
        return {"current_task": None, "task_detail": None, "current_project": None}

    def _sync_world_from_active(
        self,
        persona_id: str,
        *,
        active: dict[str, Any] | None,
        state: dict[str, Any],
        now: datetime,
        version: int,
        transitions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if active is None:
            params = get_activity("relaxing")
            fields = activity_to_state_fields(params)
            fields.update(
                {
                    "activity_started_at": now,
                    "activity_expected_end_at": now + timedelta(hours=1),
                    "next_activity": None,
                    "next_activity_at": None,
                    "situation": situation_for_activity(params.key),
                    "current_task": None,
                    "task_detail": None,
                    "current_project": None,
                    "location_type": location_type_for(params.location, params.key),
                    "next_planned_activity": None,
                    "active_event_id": None,
                    "transport_mode": None,
                    "current_meal": state.get("current_meal"),
                }
            )
            next_planned = self.timeline_repo.find_next_planned(persona_id, after=now)
            if next_planned:
                fields["next_activity"] = next_planned.get("activity")
                fields["next_activity_at"] = ensure_utc(next_planned["scheduled_start"])
                fields["next_planned_activity"] = next_activity_phrase(
                    next_planned.get("activity")
                )
                fields["next_planned_event_id"] = next_planned.get("event_id")
            if state.get("last_completed_event_id"):
                fields["last_completed_event_id"] = state.get("last_completed_event_id")
            return self._cas_apply(persona_id, fields, version, transitions, now=now)

        params = get_activity(active["activity"])
        fields = activity_to_state_fields(params)
        old_activity = state.get("current_activity")
        fields["activity_started_at"] = ensure_utc(
            active.get("actual_start") or active["scheduled_start"]
        )
        fields["activity_expected_end_at"] = ensure_utc(active["scheduled_end"])
        fields["situation"] = situation_for_activity(params.key)
        fields.update(
            self._workday_task(
                persona_id,
                params.key,
                state,
                f"{active.get('local_date')}:workday",
            )
        )
        if fields.get("current_task"):
            self.timeline_repo.col.update_one(
                {"event_id": active["event_id"]},
                {
                    "$set": {
                        "task": fields.get("current_task"),
                        "project": fields.get("current_project"),
                        "updated_at": now,
                    }
                },
            )

        next_ev = self.timeline_repo.find_next_planned(
            persona_id, after=ensure_utc(active["scheduled_start"])
        )
        next_act = (next_ev or {}).get("activity") or "sleeping"
        fields["next_activity"] = next_act
        fields["next_activity_at"] = (
            ensure_utc(next_ev["scheduled_start"])
            if next_ev
            else ensure_utc(active["scheduled_end"])
        )
        fields["next_planned_activity"] = next_activity_phrase(next_act)
        fields["location_type"] = location_type_for(params.location, params.key)
        fields["active_event_id"] = active["event_id"]
        fields["next_planned_event_id"] = (next_ev or {}).get("event_id")
        fields["transport_mode"] = (
            active.get("transport_mode")
            or (self.commute_mode if params.key in _COMMUTE_ACTIVITIES else None)
        )
        if old_activity and old_activity != params.key:
            fields["last_activity_change"] = now
            if state.get("current_location") and state.get("current_location") != params.location:
                fields["last_location"] = state.get("current_location")
        elif state.get("last_location"):
            fields["last_location"] = state.get("last_location")

        last_completed_id = state.get("last_completed_event_id")
        for t in transitions:
            if t.get("to") == "completed":
                last_completed_id = t.get("event_id")
        if last_completed_id:
            fields["last_completed_event_id"] = last_completed_id

        return self._cas_apply(persona_id, fields, version, transitions, now=now)

    def _cas_apply(
        self,
        persona_id: str,
        fields: dict[str, Any],
        expected_version: int,
        transitions: list[dict[str, Any]],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        doc = self.state_repo.get_state(persona_id)
        current_version = int(doc.get("state_version") or 0)

        if transitions and current_version != expected_version:
            log_event(
                logger,
                "timeline_cas_conflict",
                persona_id=persona_id,
                expected=expected_version,
                actual=current_version,
            )
            return {
                "persona_state": doc,
                "transitions": [],
                "cas_conflict": True,
                "state_version": current_version,
            }

        new_version = current_version + (1 if transitions else 0)
        # Optimistic lock: only bump version if still at expected
        cas = self.state_repo.col.update_one(
            {
                "persona_id": persona_id,
                "$or": [
                    {"state_version": expected_version},
                    {"state_version": {"$exists": False}},
                    {"state_version": None},
                ],
            },
            {"$set": {"state_version": new_version, "updated_at": now}},
        )
        if transitions and cas.matched_count == 0:
            fresh = self.state_repo.get_state(persona_id)
            return {
                "persona_state": fresh,
                "transitions": [],
                "cas_conflict": True,
                "state_version": int(fresh.get("state_version") or 0),
            }

        updated = self.state_repo.apply_updates(persona_id, fields)
        # Ensure version persisted even if apply_updates overwrote updated_at
        self.state_repo.col.update_one(
            {"persona_id": persona_id},
            {"$set": {"state_version": new_version}},
        )
        fresh = self.state_repo.get_state(persona_id)

        log_event(
            logger,
            "timeline_advance",
            persona_id=persona_id,
            state_version=new_version,
            transitions=len(transitions),
            active_event_id=(fresh.get("current_state") or {}).get("active_event_id"),
        )
        return {
            "persona_state": fresh,
            "transitions": transitions,
            "cas_conflict": False,
            "state_version": new_version,
        }
