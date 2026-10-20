"""Persistent daily life plan and activity transitions."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

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
from persona_runtime.life.experiences import close_open_experiences
from persona_runtime.logging_utils import get_logger

logger = get_logger(__name__)


def _assign_workday_task(
    *,
    persona_id: str,
    activity_key: str,
    state: dict[str, Any],
    seed: str,
) -> dict[str, Any]:
    """Keep today's project/task through lunch/meetings; clear after leaving work."""
    if keeps_workday_task(activity_key):
        if state.get("current_task") and state.get("current_project"):
            return {
                "current_task": state.get("current_task"),
                "task_detail": state.get("task_detail"),
                "current_project": state.get("current_project"),
            }
        if state.get("current_task"):
            task = pick_work_task(_stable_rng(persona_id, seed))
            return {
                "current_task": state.get("current_task"),
                "task_detail": state.get("task_detail") or task["task_detail"],
                "current_project": state.get("current_project") or task.get("current_project"),
            }
        task = pick_work_task(_stable_rng(persona_id, seed))
        return {
            "current_task": task["current_task"],
            "task_detail": task["task_detail"],
            "current_project": task.get("current_project"),
        }
    return {"current_task": None, "task_detail": None, "current_project": None}


def _enrich_location_fields(
    fields: dict[str, Any],
    *,
    state: dict[str, Any],
    params: Any,
    next_activity: str | None,
) -> dict[str, Any]:
    loc_type = location_type_for(params.location, params.key)
    fields["location_type"] = loc_type
    old_loc = state.get("current_location")
    new_loc = fields.get("current_location") or params.location
    if old_loc and old_loc != new_loc:
        fields["last_location"] = old_loc
    elif state.get("last_location"):
        fields["last_location"] = state.get("last_location")
    else:
        fields["last_location"] = new_loc
    fields["next_planned_activity"] = next_activity_phrase(next_activity)
    return fields


# (local hour, minute, activity_key) weekday template
_WEEKDAY_TEMPLATE: list[tuple[int, int, str]] = [
    (7, 0, "waking_up"),
    (7, 30, "breakfast"),
    (8, 15, "commuting"),
    (9, 0, "working"),
    (10, 30, "meeting"),
    (11, 15, "working"),
    (12, 30, "lunch"),
    (13, 15, "working"),
    (17, 30, "commuting"),
    (18, 15, "gym"),
    (19, 30, "cooking"),
    (20, 15, "eating"),
    (20, 45, "personal_time"),
    (23, 30, "sleeping"),
]

_WEEKEND_TEMPLATE: list[tuple[int, int, str]] = [
    (9, 0, "waking_up"),
    (9, 30, "breakfast"),
    (10, 30, "relaxing"),
    (12, 30, "eating"),
    (14, 0, "shopping"),
    (16, 0, "with_friends"),
    (19, 0, "cooking"),
    (19, 45, "eating"),
    (20, 30, "personal_time"),
    (23, 45, "sleeping"),
]


def _stable_rng(persona_id: str, date_str: str) -> random.Random:
    seed = int(hashlib.sha256(f"{persona_id}:{date_str}".encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def build_daily_plan(
    *,
    persona_id: str,
    local_now: datetime,
    tz_name: str = "Europe/London",
) -> list[dict[str, Any]]:
    """Build a varied day plan anchored to local midnight."""
    tz = ZoneInfo(tz_name)
    local_date = local_now.astimezone(tz).date()
    date_str = local_date.isoformat()
    rng = _stable_rng(persona_id, date_str)
    weekday = local_date.weekday()
    template = list(_WEEKEND_TEMPLATE if weekday >= 5 else _WEEKDAY_TEMPLATE)

    # Variations (stable per day)
    skip_gym = rng.random() < 0.25 and weekday < 5
    meeting_overrun = rng.randint(0, 25) if weekday < 5 else 0
    lunch_extra = rng.choice([0, 0, 10, 15])
    early_finish = rng.random() < 0.15 and weekday < 5

    blocks: list[dict[str, Any]] = []
    midnight = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tz)

    for i, (hour, minute, activity) in enumerate(template):
        act = activity
        if skip_gym and act == "gym":
            act = "commuting"  # go home instead
        start_local = midnight + timedelta(hours=hour, minutes=minute)
        if early_finish and act == "working" and hour >= 14:
            # finish a bit early — shift later blocks
            start_local -= timedelta(minutes=20)

        # end = next block start, or typical duration
        if i + 1 < len(template):
            nh, nm, _ = template[i + 1]
            end_local = midnight + timedelta(hours=nh, minutes=nm)
            if early_finish and nh >= 14:
                end_local -= timedelta(minutes=20)
        else:
            # sleep until next morning ~7am
            end_local = midnight + timedelta(days=1, hours=7)

        if act == "meeting" and meeting_overrun:
            end_local += timedelta(minutes=meeting_overrun)
        if act == "lunch" and lunch_extra:
            end_local += timedelta(minutes=lunch_extra)

        params = get_activity(act)
        blocks.append(
            {
                "activity": act,
                "location": params.location,
                "start_at": ensure_utc(start_local),
                "end_at": ensure_utc(end_local),
            }
        )

    # Fix overlapping ends after overrun
    for i in range(len(blocks) - 1):
        if blocks[i]["end_at"] > blocks[i + 1]["start_at"]:
            blocks[i + 1]["start_at"] = blocks[i]["end_at"]
            if blocks[i + 1]["end_at"] <= blocks[i + 1]["start_at"]:
                params = get_activity(blocks[i + 1]["activity"])
                blocks[i + 1]["end_at"] = blocks[i + 1]["start_at"] + timedelta(
                    minutes=params.typical_duration_minutes
                )

    return blocks


def block_for_time(plan: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    now = ensure_utc(now)
    for block in plan:
        if ensure_utc(block["start_at"]) <= now < ensure_utc(block["end_at"]):
            return block
    if plan:
        # before first or after last
        if now < ensure_utc(plan[0]["start_at"]):
            return plan[-1]  # previous day's sleep conceptually
        return plan[-1]
    return None


def on_activity_transition(
    *,
    persona_id: str,
    old_activity: str | None,
    new_activity: str,
    now: datetime,
    state_repo: Any | None = None,
) -> list[dict[str, Any]]:
    """Close open experience events for the previous activity window."""
    logger.debug(
        "life_transition persona=%s %s -> %s at %s",
        persona_id,
        old_activity,
        new_activity,
        now.isoformat(),
    )
    if state_repo is not None and old_activity and old_activity != new_activity:
        events = state_repo.get_experience_events(persona_id)
        closed = close_open_experiences(
            events, now=now, old_activity=old_activity
        )
        state_repo.set_experience_events(persona_id, closed)
    return []


class LifeSimulator:
    """Advances and persists Sarah's independent life state via TimelineEngine."""

    def __init__(
        self,
        state_repo: Any,
        tz_name: str = "Europe/London",
        *,
        timeline_repo: Any | None = None,
        commute_mode: str = "public_transport",
    ):
        self.state_repo = state_repo
        self.tz_name = tz_name
        self.commute_mode = commute_mode
        self._timeline_repo = timeline_repo
        self._engine: Any | None = None

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        from persona_runtime.life.timeline import TimelineEngine, TimelineRepository

        repo = self._timeline_repo
        if repo is None:
            db = self.state_repo.col.database
            repo = TimelineRepository(db)
            self._timeline_repo = repo
        self._engine = TimelineEngine(
            self.state_repo,
            repo,
            tz_name=self.tz_name,
            commute_mode=self.commute_mode,
        )
        return self._engine

    @property
    def timeline_repo(self) -> Any:
        self._get_engine()
        return self._timeline_repo

    def ensure_life_state(self, persona_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Ensure day's timeline exists and advance world state to ``now``."""
        result = self._get_engine().advance(persona_id, now=now)
        return result.get("persona_state") or self.state_repo.get_state(persona_id)

    def advance_if_needed(self, persona_id: str, now: datetime | None = None) -> dict[str, Any]:
        """Re-evaluate timeline; call on every worker tick / hydrate."""
        return self.ensure_life_state(persona_id, now=now)

    def advance_with_meta(
        self, persona_id: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Like advance_if_needed but returns transitions and state_version."""
        return self._get_engine().advance(persona_id, now=now)

    def force_activity(
        self,
        persona_id: str,
        activity: str,
        *,
        duration_minutes: float = 60,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Test/helper: pin an activity until expected end (survives plan refresh)."""
        now = ensure_utc(now or utcnow())
        params = get_activity(activity)
        end = now + timedelta(minutes=duration_minutes)
        fields = activity_to_state_fields(params)
        fields["situation"] = situation_for_activity(params.key)
        next_act = "working" if keeps_workday_task(params.key) else "relaxing"
        if params.key in {"meeting", "lunch", "coffee_break"}:
            next_act = "working"
        doc = self.state_repo.get_state(persona_id)
        prior = dict(doc.get("current_state") or {})
        old_activity = prior.get("current_activity")
        if old_activity and old_activity != params.key:
            on_activity_transition(
                persona_id=persona_id,
                old_activity=old_activity,
                new_activity=params.key,
                now=now,
                state_repo=self.state_repo,
            )
        fields.update(
            _assign_workday_task(
                persona_id=persona_id,
                activity_key=params.key,
                state=prior,
                seed=f"pin:{activity}:{end.isoformat()}",
            )
        )
        fields.update(
            {
                "activity_started_at": now,
                "activity_expected_end_at": end,
                "next_activity": next_act,
                "next_activity_at": end,
                "last_activity_change": now,
            }
        )
        _enrich_location_fields(
            fields, state=prior, params=params, next_activity=next_act
        )
        # Pin overrides daily plan until end
        self.state_repo.col.update_one(
            {"persona_id": persona_id},
            {
                "$set": {
                    "activity_pin": {
                        "activity": activity,
                        "until": end,
                        "location": params.location,
                    },
                    "updated_at": now,
                }
            },
            upsert=False,
        )
        # Ensure document exists
        self.state_repo.get_state(persona_id)
        self.state_repo.col.update_one(
            {"persona_id": persona_id},
            {
                "$set": {
                    "activity_pin": {
                        "activity": activity,
                        "until": end,
                        "location": params.location,
                    },
                }
            },
        )
        return self.state_repo.apply_updates(persona_id, fields)

    def current_snapshot(self, persona_id: str) -> dict[str, Any]:
        doc = self.state_repo.get_state(persona_id)
        return dict(doc.get("current_state") or {})
