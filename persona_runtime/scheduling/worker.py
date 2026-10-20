"""Background worker that processes due response jobs."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Any, Callable
from uuid import uuid4

from persona_runtime.db.time_utils import ensure_utc, safe_le, utcnow
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.life.strategy import choose_response_strategy
from persona_runtime.life.timing import compute_response_schedule
from persona_runtime.logging_utils import get_logger, log_event

logger = get_logger(__name__)

# After this many claim/defer cycles, generate anyway (except while sleeping).
MAX_DEFER_ATTEMPTS = 5
# Retry graph failures a few times before permanently failing the job.
MAX_ERROR_ATTEMPTS = 3


class ResponseWorker:
    def __init__(
        self,
        *,
        runtime,
        settings,
        worker_id: str | None = None,
        life_simulator: LifeSimulator | None = None,
    ):
        self.runtime = runtime
        self.settings = settings
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.job_repo = runtime.job_repo
        self.conversation_repo = runtime.conversation_repo
        self.state_repo = runtime.state_repo
        self.relationship_repo = runtime.relationship_repo
        self.life = life_simulator or LifeSimulator(
            self.state_repo, tz_name=settings.timezone
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name=self.worker_id, daemon=True)
        self._thread.start()
        log_event(logger, "response_worker_started", worker_id=self.worker_id)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        log_event(logger, "response_worker_stopped", worker_id=self.worker_id)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.process_due()
            except Exception as exc:  # noqa: BLE001
                logger.exception("worker_tick_failed: %s", exc)
            self._stop.wait(self.settings.response_worker_poll_seconds)

    def process_due(self) -> int:
        """Process life advances + at most one claimed job. Returns jobs processed."""
        now = utcnow()
        # Advance life for default persona (MVP: one persona)
        try:
            self.life.advance_if_needed(self.settings.default_persona_id, now=now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("life_advance_failed: %s", exc)

        job = self.job_repo.claim_due(self.worker_id, now=now)
        if not job:
            return 0
        try:
            self._process_job(job)
            return 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("job_failed job_id=%s: %s", job.get("job_id"), exc)
            self._recover_failed_job(job, str(exc))
            return 0

    def _process_job(self, job: dict[str, Any]) -> None:
        now = utcnow()
        persona_id = job["persona_id"]
        conversation_id = job["conversation_id"]
        lock_token = job["lock_token"]

        self.life.advance_if_needed(persona_id, now=now)
        state_doc = self.state_repo.get_state(persona_id)
        current = dict(state_doc.get("current_state") or {})
        activity = current.get("current_activity") or "relaxing"
        availability = float(current.get("availability") or 0.5)

        # Mark messages read if read_at has passed
        read_at = job.get("read_at")
        if read_at and safe_le(read_at, now):
            self.conversation_repo.update_messages(
                list(job.get("message_ids") or []),
                {"status": "read", "read_at": now},
            )

        # Re-check: still unavailable? Reschedule unless this is a busy-ack job
        end_at = current.get("activity_expected_end_at")
        sleeping = bool(current.get("sleeping"))
        busy_ack = bool(job.get("busy_ack"))
        event_type = job.get("event_type") or "user_message"

        if event_type != "conversation_start" and not busy_ack:
            if sleeping or availability < 0.12:
                # Unless strategy is ACKNOWLEDGE for high priority — recompute
                msgs = self.conversation_repo.get_messages_by_ids(list(job.get("message_ids") or []))
                # Also pick up any pending not yet on the job
                pending = self.conversation_repo.pending_user_messages(conversation_id)
                all_msgs = {m["message_id"]: m for m in msgs}
                for m in pending:
                    all_msgs[m["message_id"]] = m
                message_list = list(all_msgs.values())
                message_list.sort(key=lambda m: m.get("sequence") or 0)

                priorities = [m.get("priority") or "normal" for m in message_list]
                needs_ack = any(
                    p in {"urgent", "important", "emotionally_important"} for p in priorities
                )
                if needs_ack and availability >= 0.05 and not sleeping:
                    # Allow busy ack through
                    pass
                else:
                    schedule = compute_response_schedule(
                        activity_key=activity,
                        availability=availability,
                        priority=max(
                            priorities or ["normal"],
                            key=lambda p: {
                                "urgent": 4,
                                "emotionally_important": 3,
                                "important": 2,
                                "normal": 1,
                                "low": 0,
                            }.get(p, 1),
                        ),
                        now=now,
                        activity_expected_end_at=end_at,
                        batch_window_seconds=self.settings.batch_window_min_seconds,
                        time_scale=self.settings.life_time_scale,
                        seed=job["job_id"] + ":recheck",
                        force_after_busy=True,
                    )
                    if schedule["scheduled_for"] > ensure_utc(now) + timedelta(seconds=2):
                        self.job_repo.reschedule(
                            job["job_id"],
                            lock_token,
                            scheduled_for=schedule["scheduled_for"],
                            reason=schedule["reason"],
                            activity=activity,
                            availability=availability,
                            strategy=schedule.get("strategy_hint"),
                            read_at=schedule["read_at"],
                        )
                        log_event(
                            logger,
                            "response_job_rescheduled",
                            job_id=job["job_id"],
                            reason=schedule["reason"],
                            scheduled_for=str(schedule["scheduled_for"]),
                            current_activity=activity,
                        )
                        return

        # Merge pending messages into batch (except already-running isolation:
        # job.message_ids is authoritative for this claim; also include any that
        # were appended before claim)
        message_ids = list(job.get("message_ids") or [])
        pending = self.conversation_repo.pending_user_messages(conversation_id)
        for m in pending:
            if m["message_id"] not in message_ids:
                # Only include if created before we claimed (or already linked)
                if m.get("response_job_id") in (None, job["job_id"]):
                    message_ids.append(m["message_id"])

        messages = self.conversation_repo.get_messages_by_ids(message_ids)
        # Also refresh job message list from DB in case of race
        fresh = self.job_repo.get(job["job_id"])
        if fresh:
            for mid in fresh.get("message_ids") or []:
                if mid not in message_ids:
                    message_ids.append(mid)
            messages = self.conversation_repo.get_messages_by_ids(message_ids)

        strategy_plan = choose_response_strategy(
            messages=messages,
            activity_key=activity,
            availability=availability,
            strategy_hint=job.get("strategy"),
        )

        attempts = int(job.get("attempt_count") or 0)
        force_reply = attempts >= MAX_DEFER_ATTEMPTS and not sleeping
        if (
            strategy_plan["strategy"] == "DEFER_RESPONSE"
            and not strategy_plan.get("busy_ack")
            and not force_reply
        ):
            schedule = compute_response_schedule(
                activity_key=activity,
                availability=availability,
                priority="normal",
                now=now,
                activity_expected_end_at=end_at,
                batch_window_seconds=self.settings.batch_window_min_seconds,
                time_scale=self.settings.life_time_scale,
                seed=job["job_id"] + ":defer",
                force_after_busy=True,
            )
            if schedule["scheduled_for"] > ensure_utc(now) + timedelta(seconds=2):
                self.job_repo.reschedule(
                    job["job_id"],
                    lock_token,
                    scheduled_for=schedule["scheduled_for"],
                    reason=schedule["reason"],
                    activity=activity,
                    availability=availability,
                    strategy="DEFER_RESPONSE",
                    read_at=schedule["read_at"],
                )
                log_event(
                    logger,
                    "response_job_rescheduled",
                    job_id=job["job_id"],
                    reason=schedule["reason"],
                    scheduled_for=str(schedule["scheduled_for"]),
                    current_activity=activity,
                )
                return
            log_event(
                logger,
                "response_defer_due_now",
                job_id=job["job_id"],
                current_activity=activity,
            )
        elif force_reply and strategy_plan["strategy"] == "DEFER_RESPONSE":
            log_event(
                logger,
                "response_defer_exhausted",
                job_id=job["job_id"],
                attempt_count=attempts,
                current_activity=activity,
            )

        include_ids = strategy_plan.get("include_ids") or [m["message_id"] for m in messages]
        self.conversation_repo.update_messages(
            include_ids, {"status": "included_in_response"}
        )
        for mid in strategy_plan.get("superseded_ids") or []:
            self.conversation_repo.update_message(mid, {"status": "superseded"})
        for mid in strategy_plan.get("ignored_ids") or []:
            self.conversation_repo.update_message(mid, {"status": "ignored"})

        included = [m for m in messages if m["message_id"] in set(include_ids)]
        joined = "\n".join(m.get("content") or "" for m in included)

        log_event(
            logger,
            "response_started",
            job_id=job["job_id"],
            conversation_id=conversation_id,
            current_activity=activity,
            availability=availability,
            response_strategy=strategy_plan["strategy"],
            number_of_batched_messages=len(included),
            response_scheduled_for=str(job.get("scheduled_for")),
            response_started_at=str(now),
        )

        conv = self.conversation_repo.get(conversation_id) or {}
        user_id = conv.get("user_id") or self.settings.default_user_id

        result = self.runtime.run(
            event_type=event_type,
            persona_id=persona_id,
            user_id=user_id,
            conversation_id=conversation_id,
            incoming_message=joined if event_type != "conversation_start" else "",
            user_message_id=include_ids[-1] if include_ids else None,
            request_id=job["job_id"],
            pending_messages=included,
            response_strategy=strategy_plan["strategy"],
            response_job=job,
            busy_ack=bool(strategy_plan.get("busy_ack")),
        )

        if not result.get("assistant_message_id") and event_type != "message_seen":
            fallback = (result.get("generated_response") or "").strip() or "Yeah, fair enough."
            saved = self.conversation_repo.add_message(
                conversation_id=conversation_id,
                sender="assistant",
                content=fallback,
                metadata={
                    "fallback": "missing_assistant_after_run",
                    "response_job_id": job["job_id"],
                },
            )
            result = {**result, "assistant_message_id": saved["message_id"]}
            log_event(
                logger,
                "response_fallback_persisted",
                job_id=job["job_id"],
                conversation_id=conversation_id,
                assistant_message_id=saved["message_id"],
            )

        # Mark answered
        answered_at = utcnow()
        self.conversation_repo.update_messages(
            include_ids,
            {"status": "answered", "answered_at": answered_at},
        )
        # Superseded/ignored stay as marked

        self.job_repo.complete(
            job["job_id"], lock_token, strategy=strategy_plan["strategy"]
        )

        log_event(
            logger,
            "response_completed",
            job_id=job["job_id"],
            conversation_id=conversation_id,
            response_completed_at=str(answered_at),
            assistant_message_id=result.get("assistant_message_id"),
            response_strategy=strategy_plan["strategy"],
            memory_count=len(result.get("stored_memories") or []),
        )

        # If busy ack, schedule follow-up full response after activity ends
        if strategy_plan.get("busy_ack") or strategy_plan["strategy"] == "ACKNOWLEDGE_LATEST":
            # Reload end from state after generation
            state_doc = self.state_repo.get_state(persona_id)
            current = dict(state_doc.get("current_state") or {})
            end_at = current.get("activity_expected_end_at") or end_at
            follow_end = ensure_utc(end_at) if end_at else (now + timedelta(minutes=30))
            for mid in include_ids:
                m = self.conversation_repo.get_message(mid)
                if m and m.get("status") == "answered" and strategy_plan.get("busy_ack"):
                    self.conversation_repo.update_message(
                        mid, {"status": "pending_response", "answered_at": None}
                    )
            remaining = self.conversation_repo.pending_user_messages(conversation_id)
            if remaining and not self.job_repo.get_open_for_conversation(conversation_id):
                scheduled = follow_end + timedelta(seconds=max(30.0, 30.0 * self.settings.life_time_scale))
                if scheduled <= ensure_utc(now):
                    scheduled = ensure_utc(now) + timedelta(seconds=max(30.0, 60.0 * self.settings.life_time_scale))
                follow = self.job_repo.create(
                    {
                        "persona_id": persona_id,
                        "conversation_id": conversation_id,
                        "message_ids": [m["message_id"] for m in remaining],
                        "scheduled_for": scheduled,
                        "read_at": follow_end,
                        "activity_at_schedule": activity,
                        "availability_at_schedule": availability,
                        "reason": f"follow_up_after_{activity}",
                        "strategy": "RESPOND_TO_GROUP",
                        "event_type": "user_message",
                        "follow_up_of": job["job_id"],
                        "busy_ack": False,
                    }
                )
                for m in remaining:
                    self.conversation_repo.update_message(
                        m["message_id"], {"response_job_id": follow["job_id"]}
                    )

        # Schedule next cycle for any pending left without a job
        leftover = self.conversation_repo.pending_user_messages(conversation_id)
        if leftover and not self.job_repo.get_open_for_conversation(conversation_id):
            from persona_runtime.scheduling.scheduler import ResponseScheduler

            sched = ResponseScheduler(
                conversation_repo=self.conversation_repo,
                job_repo=self.job_repo,
                state_repo=self.state_repo,
                relationship_repo=self.relationship_repo,
                settings=self.settings,
                life_simulator=self.life,
            )
            # Re-accept via creating a job for leftovers
            first = leftover[0]
            seed = f"{conversation_id}:leftover:{first['message_id']}"
            schedule = compute_response_schedule(
                activity_key=activity,
                availability=availability,
                priority=first.get("priority") or "normal",
                now=utcnow(),
                activity_expected_end_at=end_at,
                batch_window_seconds=self.settings.batch_window_min_seconds,
                time_scale=self.settings.life_time_scale,
                seed=seed,
            )
            new_job = self.job_repo.create(
                {
                    "persona_id": persona_id,
                    "conversation_id": conversation_id,
                    "message_ids": [m["message_id"] for m in leftover],
                    "scheduled_for": schedule["scheduled_for"],
                    "read_at": schedule["read_at"],
                    "activity_at_schedule": schedule["activity"],
                    "availability_at_schedule": schedule["availability"],
                    "reason": schedule["reason"],
                    "strategy": schedule.get("strategy_hint"),
                    "event_type": "user_message",
                }
            )
            for m in leftover:
                self.conversation_repo.update_message(
                    m["message_id"], {"response_job_id": new_job["job_id"]}
                )

    def _recover_failed_job(self, job: dict[str, Any], error: str) -> None:
        """Retry a crashed job, or fail it and leave a visible fallback bubble."""
        include_ids = list(job.get("message_ids") or [])
        if include_ids:
            self.conversation_repo.update_messages(
                include_ids, {"status": "pending_response"}
            )
        attempts = int(job.get("attempt_count") or 1)
        lock_token = job.get("lock_token")
        if attempts < MAX_ERROR_ATTEMPTS and lock_token:
            delay = max(10.0, 15.0 * attempts)
            self.job_repo.reschedule(
                job["job_id"],
                lock_token,
                scheduled_for=utcnow() + timedelta(seconds=delay),
                reason=f"retry_after_error:{error}"[:180],
                activity=job.get("activity_at_schedule"),
                availability=job.get("availability_at_schedule"),
                strategy=job.get("strategy") or "RESPOND_TO_GROUP",
                read_at=job.get("read_at"),
            )
            log_event(
                logger,
                "response_job_retry_scheduled",
                job_id=job.get("job_id"),
                attempt_count=attempts,
                delay_seconds=delay,
            )
            return
        if lock_token:
            self.job_repo.fail(job["job_id"], lock_token, error)
        try:
            saved = self.conversation_repo.add_message(
                conversation_id=job["conversation_id"],
                sender="assistant",
                content="Sorry — just got distracted. What were you saying?",
                metadata={
                    "fallback": "job_failed",
                    "response_job_id": job.get("job_id"),
                    "error": error[:200],
                },
            )
            if include_ids:
                self.conversation_repo.update_messages(
                    include_ids, {"status": "answered", "answered_at": utcnow()}
                )
            log_event(
                logger,
                "response_fallback_after_fail",
                job_id=job.get("job_id"),
                assistant_message_id=saved["message_id"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fallback_after_fail_failed: %s", exc)
