"""Accept user messages and maintain one response job per conversation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from persona_runtime.db.time_utils import ensure_utc, to_iso, utcnow
from persona_runtime.life.activities import get_activity
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.life.strategy import classify_priority
from persona_runtime.life.timing import compute_response_schedule
from persona_runtime.logging_utils import get_logger, log_event

logger = get_logger(__name__)

# Availability threshold for "spare time" (relaxing, coffee, TV, etc.)
SPARE_TIME_AVAILABILITY = 0.7
# How recently Sarah must have replied for idle Online status
RECENT_EXCHANGE_SECONDS = 180.0


class ResponseScheduler:
    def __init__(
        self,
        *,
        conversation_repo,
        job_repo,
        state_repo,
        relationship_repo,
        settings,
        life_simulator: LifeSimulator | None = None,
    ):
        self.conversation_repo = conversation_repo
        self.job_repo = job_repo
        self.state_repo = state_repo
        self.relationship_repo = relationship_repo
        self.settings = settings
        self.life = life_simulator or LifeSimulator(state_repo, tz_name=settings.timezone)

    def accept_user_message(
        self,
        *,
        conversation_id: str,
        persona_id: str,
        user_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        priority = classify_priority(content)
        self.life.advance_if_needed(persona_id, now=now)
        state_doc = self.state_repo.get_state(persona_id)
        current = dict(state_doc.get("current_state") or {})

        msg = self.conversation_repo.add_message(
            conversation_id=conversation_id,
            sender="user",
            content=content,
            metadata=metadata or {},
            status="pending_response",
            priority=priority,
        )

        open_job = self.job_repo.get_open_for_conversation(conversation_id)
        if open_job and open_job.get("status") == "running":
            # Generation already started — leave for next cycle
            log_event(
                logger,
                "message_queued_next_cycle",
                conversation_id=conversation_id,
                message_id=msg["message_id"],
                running_job_id=open_job.get("job_id"),
            )
            return {
                "message": msg,
                "job": open_job,
                "status": "received",
                "deferred_to_next_cycle": True,
            }

        if open_job and open_job.get("status") == "scheduled":
            # Append; maybe pull schedule earlier for urgency
            updates: dict[str, Any] = {}
            if priority in {"urgent", "emotionally_important", "important"}:
                rel = self.relationship_repo.get_or_create_user_relationship(persona_id, user_id)
                schedule = compute_response_schedule(
                    activity_key=current.get("current_activity") or "relaxing",
                    availability=float(current.get("availability") or 0.5),
                    priority=priority,
                    relationship_stage=rel.get("relationship_stage") or "new_contact",
                    now=now,
                    activity_expected_end_at=current.get("activity_expected_end_at"),
                    batch_window_seconds=self.settings.batch_window_min_seconds,
                    time_scale=self.settings.life_time_scale,
                    seed=open_job["job_id"] + ":" + priority,
                )
                if schedule["scheduled_for"] < open_job.get("scheduled_for"):
                    updates["scheduled_for"] = schedule["scheduled_for"]
                    updates["reason"] = schedule["reason"]
                    updates["read_at"] = schedule["read_at"]
                    updates["strategy"] = schedule.get("strategy_hint")

            job = self.job_repo.append_messages(
                open_job["job_id"],
                [msg["message_id"]],
                scheduled_for=updates.get("scheduled_for"),
                strategy=updates.get("strategy"),
                reason=updates.get("reason"),
                read_at=updates.get("read_at"),
            ) or open_job
            self.conversation_repo.update_message(
                msg["message_id"], {"response_job_id": job["job_id"]}
            )
            log_event(
                logger,
                "response_job_appended",
                conversation_id=conversation_id,
                job_id=job["job_id"],
                message_id=msg["message_id"],
                message_count=len(job.get("message_ids") or []),
            )
            return {"message": msg, "job": job, "status": "received"}

        # Create new job
        rel = self.relationship_repo.get_or_create_user_relationship(persona_id, user_id)
        seed = f"{conversation_id}:{msg['message_id']}"
        schedule = compute_response_schedule(
            activity_key=current.get("current_activity") or "relaxing",
            availability=float(current.get("availability") or 0.5),
            priority=priority,
            relationship_stage=rel.get("relationship_stage") or "new_contact",
            now=now,
            activity_expected_end_at=current.get("activity_expected_end_at"),
            batch_window_seconds=self.settings.batch_window_min_seconds,
            time_scale=self.settings.life_time_scale,
            seed=seed,
        )
        job = self.job_repo.create(
            {
                "persona_id": persona_id,
                "conversation_id": conversation_id,
                "message_ids": [msg["message_id"]],
                "scheduled_for": schedule["scheduled_for"],
                "read_at": schedule["read_at"],
                "activity_at_schedule": schedule["activity"],
                "availability_at_schedule": schedule["availability"],
                "reason": schedule["reason"],
                "strategy": schedule.get("strategy_hint"),
                "event_type": "user_message",
            }
        )
        self.conversation_repo.update_message(
            msg["message_id"], {"response_job_id": job["job_id"]}
        )
        log_event(
            logger,
            "response_job_created",
            conversation_id=conversation_id,
            job_id=job["job_id"],
            scheduled_for=str(schedule["scheduled_for"]),
            activity=schedule["activity"],
            reason=schedule["reason"],
            message_received_at=str(msg.get("created_at")),
        )
        return {"message": msg, "job": job, "status": "received"}

    def schedule_opening(
        self,
        *,
        conversation_id: str,
        persona_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        if self.conversation_repo.count_messages(conversation_id) > 0:
            return None
        if self.job_repo.get_open_for_conversation(conversation_id):
            return None
        now = utcnow()
        self.life.advance_if_needed(persona_id, now=now)
        # Opening can be relatively quick when available
        delay = max(1.0, 3.0 * self.settings.life_time_scale)
        job = self.job_repo.create(
            {
                "persona_id": persona_id,
                "conversation_id": conversation_id,
                "message_ids": [],
                "scheduled_for": now + timedelta(seconds=delay),
                "read_at": now,
                "activity_at_schedule": "relaxing",
                "availability_at_schedule": 0.85,
                "reason": "conversation_opening",
                "strategy": "RESPOND_TO_LATEST",
                "event_type": "conversation_start",
            }
        )
        return job

    def schedule_resume(
        self,
        *,
        conversation_id: str,
        persona_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        """Schedule at most one proactive message when the user resumes the chat.

        Caller must enforce proactive permission policy first.
        """
        if self.job_repo.get_open_for_conversation(conversation_id):
            return None
        now = utcnow()
        self.life.advance_if_needed(persona_id, now=now)
        state_doc = self.state_repo.get_state(persona_id)
        current = dict(state_doc.get("current_state") or {})
        delay = max(2.0, 5.0 * self.settings.life_time_scale)
        job = self.job_repo.create(
            {
                "persona_id": persona_id,
                "conversation_id": conversation_id,
                "message_ids": [],
                "scheduled_for": now + timedelta(seconds=delay),
                "read_at": now,
                "activity_at_schedule": current.get("current_activity") or "relaxing",
                "availability_at_schedule": float(current.get("availability") or 0.7),
                "reason": "conversation_resume",
                "strategy": "RESPOND_TO_LATEST",
                "event_type": "conversation_start",
                "user_id": user_id,
            }
        )
        log_event(
            logger,
            "resume_job_created",
            conversation_id=conversation_id,
            job_id=job["job_id"],
        )
        return job

    @staticmethod
    def is_spare_time(current: dict[str, Any]) -> bool:
        """True when Sarah has free attention for continuous chat."""
        if current.get("sleeping"):
            return False
        activity_key = current.get("current_activity") or "relaxing"
        params = get_activity(activity_key)
        if params.busy or params.sleeping:
            return False
        avail = float(current.get("availability") if current.get("availability") is not None else params.availability)
        if avail < SPARE_TIME_AVAILABILITY:
            return False
        return True

    def _recent_assistant_exchange(self, conversation_id: str, now) -> bool:
        msgs = self.conversation_repo.recent_messages(conversation_id, limit=8)
        for m in reversed(msgs):
            if m.get("sender") != "assistant":
                continue
            ts = m.get("answered_at") or m.get("timestamp") or m.get("created_at")
            if ts is None:
                return False
            return (ensure_utc(now) - ensure_utc(ts)).total_seconds() <= RECENT_EXCHANGE_SECONDS
        return False

    def presence_snapshot(self, conversation_id: str, persona_id: str) -> dict[str, Any]:
        """Presence + schedule for chat UI countdown / Online gating."""
        from persona_runtime.life.timing import activity_label

        now = utcnow()
        self.life.advance_if_needed(persona_id, now=now)
        state = self.state_repo.get_state(persona_id)
        current = dict(state.get("current_state") or {})
        spare = self.is_spare_time(current)
        job = self.job_repo.get_open_for_conversation(conversation_id)

        activity = (
            (job or {}).get("activity_at_schedule")
            or current.get("current_activity")
            or "relaxing"
        )
        reason = (job or {}).get("reason")
        label = activity_label(activity)

        scheduled_for = None
        if job and job.get("scheduled_for") is not None:
            scheduled_for = to_iso(ensure_utc(job["scheduled_for"]))

        def _base(**extra: Any) -> dict[str, Any]:
            payload = {
                "spare_time": spare,
                "activity": activity,
                "activity_label": label,
                "reason": reason,
            }
            payload.update(extra)
            return payload

        if job and job.get("status") == "running":
            presence = "online" if spare else "replying"
            return _base(
                presence=presence,
                scheduled_for=None,
            )

        if job and job.get("status") == "scheduled":
            return _base(
                presence="waiting",
                scheduled_for=scheduled_for,
            )

        # Idle — no open job
        reason = None
        if spare and self._recent_assistant_exchange(conversation_id, now):
            return _base(
                presence="online",
                scheduled_for=None,
                reason=None,
            )

        avail = float(current.get("availability") or 0.0)
        if current.get("sleeping") or avail <= 0.1:
            return _base(
                presence="away",
                scheduled_for=None,
                reason=None,
                spare_time=False,
            )

        return _base(
            presence="none",
            scheduled_for=None,
            reason=None,
        )

    def presence_for(self, conversation_id: str, persona_id: str) -> str:
        return self.presence_snapshot(conversation_id, persona_id)["presence"]
