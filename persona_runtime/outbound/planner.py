"""Proactive outbound planner: scan opted-in users, schedule and execute outreach.

Flow: scan() on the worker tick → evaluate_outbound gates → select_trigger → one
idempotent ResponseJob (event_type="proactive"). The worker later calls execute(job),
which re-checks ownership and every gate, runs the graph with
event_type="proactive_outreach", persists 1–N bubbles under one outbound_id and
delivers them. One outbound event counts once toward caps, and nothing else is sent
until the user replies.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.life.activities import get_activity
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.logging_utils import get_logger, log_event
from persona_runtime.outbound.briefs import fallback_messages
from persona_runtime.outbound.delivery import DeliveryAdapter, get_delivery
from persona_runtime.outbound.policy import evaluate_outbound, unanswered_expired
from persona_runtime.outbound.triggers import event_subject, select_trigger

logger = get_logger(__name__)

RESUME_MIN_IDLE_HOURS = 3


def cancel_pending_proactive(runtime, user_id: str, *, reason: str) -> int:
    cancelled = 0
    for job in runtime.job_repo.open_proactive_for_user(user_id):
        if job.get("status") == "scheduled" and runtime.job_repo.cancel(job["job_id"], reason=reason):
            cancelled += 1
            runtime.conversation_repo.record_event(
                "proactive_cancelled",
                {"user_id": user_id, "job_id": job["job_id"], "reason": reason},
            )
    return cancelled


class ProactivePlanner:
    def __init__(
        self,
        *,
        runtime,
        settings=None,
        delivery: DeliveryAdapter | None = None,
        persona_id: str | None = None,
    ):
        self.runtime = runtime
        self.settings = settings or runtime.settings
        self.delivery = delivery or get_delivery(self.settings, runtime.conversation_repo)
        self.persona_id = persona_id or self.settings.default_persona_id
        self.life = LifeSimulator(runtime.state_repo, tz_name=self.settings.timezone)

    # ------------------------------------------------------------------ helpers

    def _event(self, name: str, payload: dict[str, Any]) -> None:
        try:
            self.runtime.conversation_repo.record_event(name, payload)
        except Exception:  # noqa: BLE001
            pass
        log_event(logger, name, **{k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool))})

    def _primary_conversation(self, user_id: str) -> dict[str, Any]:
        return self.runtime.conversation_repo.get_or_create(self.persona_id, user_id)

    def _decision(self, settings_doc, now, proactive_type=None, *, exclude_job_id=None, ignore_quiet=False):
        open_jobs = [
            j
            for j in self.runtime.job_repo.open_proactive_for_user(settings_doc["user_id"])
            if j.get("job_id") != exclude_job_id
        ]
        return evaluate_outbound(
            settings_doc=settings_doc,
            app_settings=self.settings,
            now=now,
            proactive_type=proactive_type,
            open_proactive_jobs=len(open_jobs),
            ignore_quiet_hours=ignore_quiet,
        )

    def _current_life_state(self, now: datetime) -> dict[str, Any]:
        """Sarah's real current activity/availability — never pretend she's relaxing."""
        try:
            self.life.advance_if_needed(self.persona_id, now=now)
            doc = self.runtime.state_repo.get_state(self.persona_id)
            return dict(doc.get("current_state") or {})
        except Exception:  # noqa: BLE001
            return {}

    def _due_followups(self, user_id: str, now: datetime) -> list[dict[str, Any]]:
        try:
            return self.runtime.services.memory_retriever.due_followups(
                persona_id=self.persona_id, user_id=user_id, now=now, tz_name=self.settings.timezone
            )
        except Exception:  # noqa: BLE001
            return []

    def _build_brief(self, trigger: dict[str, Any], *, current_state: dict[str, Any] | None = None) -> dict[str, Any]:
        max_bubbles = max(1, min(3, int(self.settings.proactive_max_bubbles)))
        bubbles = 1 if trigger["proactive_type"] == "weekend_followup" and not trigger.get("subject") else 2
        current = current_state or {}
        brief = {
            **trigger,
            "outbound_id": str(uuid4()),
            "max_bubbles": min(max_bubbles, max(bubbles, 1)),
            "current_activity": current.get("current_activity") or "relaxing",
        }
        brief["fallback_messages"] = fallback_messages(brief)
        return brief

    def _create_job(
        self,
        *,
        user_id: str,
        conv: dict[str, Any],
        brief: dict[str, Any],
        local_now: datetime,
        now: datetime,
        current_state: dict[str, Any] | None = None,
    ):
        current = current_state or {}
        activity_key = current.get("current_activity") or brief.get("current_activity") or "relaxing"
        params = get_activity(activity_key)
        availability = float(
            current.get("availability") if current.get("availability") is not None else params.availability
        )
        key = f"{user_id}:{brief['proactive_type']}:{brief.get('idempotency_subject')}:{local_now.date().isoformat()}"
        job = self.runtime.job_repo.create_idempotent(
            {
                "persona_id": self.persona_id,
                "conversation_id": conv["conversation_id"],
                "user_id": user_id,
                "message_ids": [],
                "scheduled_for": now,
                "read_at": now,
                "activity_at_schedule": activity_key,
                "availability_at_schedule": availability,
                "reason": f"proactive:{brief['proactive_type']}",
                "strategy": "RESPOND_TO_LATEST",
                "event_type": "proactive",
                "proactive_type": brief["proactive_type"],
                "proactive_brief": brief,
                "outbound_id": brief["outbound_id"],
                "idempotency_key": key,
                "expires_at": now + timedelta(hours=float(self.settings.proactive_job_ttl_hours)),
            }
        )
        return job, key

    # ------------------------------------------------------------------ scan

    def expire_unanswered(self, now: datetime | None = None) -> int:
        now = ensure_utc(now or utcnow())
        expired = 0
        repo = self.runtime.proactive_settings_repo
        for doc in repo.list_enabled(self.persona_id):
            if unanswered_expired(doc, now):
                updated = repo.record_ignored(doc["user_id"], self.persona_id)
                expired += 1
                self._event(
                    "proactive_ignored",
                    {
                        "user_id": doc["user_id"],
                        "outbound_id": doc.get("unanswered_outbound_id"),
                        "auto_paused": not updated.get("enabled"),
                    },
                )
        return expired

    def scan(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = ensure_utc(now or utcnow())
        if not self.settings.proactive_outbound_enabled:
            return []
        self.expire_unanswered(now)
        outcomes = []
        for doc in self.runtime.proactive_settings_repo.list_enabled(self.persona_id):
            try:
                outcomes.append(self.evaluate_user(doc["user_id"], now=now))
            except Exception as exc:  # noqa: BLE001
                logger.warning("proactive_evaluate_failed user=%s: %s", doc.get("user_id"), exc)
        return outcomes

    def evaluate_user(self, user_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        now = ensure_utc(now or utcnow())
        repo = self.runtime.proactive_settings_repo
        settings_doc = repo.get(user_id, self.persona_id)
        if not settings_doc:
            return {"user_id": user_id, "scheduled": False, "reason": "not_opted_in"}
        decision = self._decision(settings_doc, now)
        if not decision.allow:
            return {"user_id": user_id, "scheduled": False, "reason": decision.reason}

        conv = self._primary_conversation(user_id)
        if self.runtime.job_repo.get_open_for_conversation(conv["conversation_id"]):
            return {"user_id": user_id, "scheduled": False, "reason": "conversation_busy"}
        if self.runtime.conversation_repo.count_messages(conv["conversation_id"]) == 0:
            return {"user_id": user_id, "scheduled": False, "reason": "no_conversation_yet"}
        ctx = self.runtime.conversation_context_repo.get(conv["conversation_id"]) or {}
        if ctx.get("proactive_opt_out"):
            repo.opt_out(user_id, self.persona_id, reason="conversation_request")
            return {"user_id": user_id, "scheduled": False, "reason": "not_opted_in"}

        trigger = select_trigger(
            user_id=user_id,
            persona_id=self.persona_id,
            now=now,
            local_now=decision.local_now or now,
            settings_doc=settings_doc,
            profile_card=self.runtime.user_memory.profile_card(self.persona_id, user_id, limit=20),
            due_followups=self._due_followups(user_id, now),
            conversation_context=ctx,
            user_topics=self.runtime.topic_repo.list(user_id, self.persona_id),
            last_message_at=conv.get("last_message_at"),
        )
        if not trigger:
            return {"user_id": user_id, "scheduled": False, "reason": "no_grounded_reason"}
        type_decision = self._decision(settings_doc, now, trigger["proactive_type"])
        if not type_decision.allow:
            return {"user_id": user_id, "scheduled": False, "reason": type_decision.reason}

        current_state = self._current_life_state(now)
        brief = self._build_brief(trigger, current_state=current_state)
        job, key = self._create_job(
            user_id=user_id,
            conv=conv,
            brief=brief,
            local_now=decision.local_now or now,
            now=now,
            current_state=current_state,
        )
        if not job:
            return {"user_id": user_id, "scheduled": False, "reason": "duplicate", "idempotency_key": key}
        self._event(
            "proactive_scheduled",
            {
                "user_id": user_id,
                "conversation_id": conv["conversation_id"],
                "job_id": job["job_id"],
                "proactive_type": brief["proactive_type"],
                "topic": brief.get("topic"),
            },
        )
        return {"user_id": user_id, "scheduled": True, "reason": "scheduled", "job": job}

    # ------------------------------------------------------------------ resume

    def on_user_resumed(self, conv: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """User opened the chat after a gap: maybe one returning-user greeting (opted-in only)."""
        now = ensure_utc(now or utcnow())
        user_id = conv["user_id"]
        base = {"job": None, "situation": "user_resumed", "use_engagement_in_reply": True}
        last = conv.get("last_message_at")
        if self.runtime.conversation_repo.count_messages(conv["conversation_id"]) == 0:
            return {**base, "reason": "no_history"}
        if last and now - ensure_utc(last) < timedelta(hours=RESUME_MIN_IDLE_HOURS):
            return {**base, "reason": "recent_activity"}
        if self.runtime.job_repo.get_open_for_conversation(conv["conversation_id"]):
            return {**base, "reason": "already_scheduled"}
        settings_doc = self.runtime.proactive_settings_repo.get(user_id, conv["persona_id"])
        decision = self._decision(settings_doc or {"user_id": user_id}, now, "returning_user_greeting", ignore_quiet=True)
        if not decision.allow:
            return {**base, "reason": decision.reason}

        due = [d for d in self._due_followups(user_id, now) if d.get("user_id") == user_id]
        ctx = self.runtime.conversation_context_repo.get(conv["conversation_id"]) or {}
        if due:
            subject = event_subject(due[0].get("event_description") or due[0].get("fact") or "")
            trigger = {
                "proactive_type": "event_followup",
                "topic": "everyday",
                "subject": subject,
                "hint": f"welcome them back and ask how {subject} went — don't assume the outcome",
                "talking_points": ["warm welcome back", "ask how it went"],
                "evidence_memory_ids": [due[0].get("memory_id")],
                "idempotency_subject": f"event:{due[0].get('memory_id')}",
            }
        else:
            subject = ctx.get("current_topic") or None
            trigger = {
                "proactive_type": "returning_user_greeting",
                "topic": subject or "everyday",
                "subject": None,
                "hint": "welcome them back casually and ask one light question; reference the last topic only if natural",
                "talking_points": ["casual welcome back"],
                "evidence_memory_ids": [],
                "idempotency_subject": "resume",
            }
        current_state = self._current_life_state(now)
        brief = self._build_brief(trigger, current_state=current_state)
        job, _ = self._create_job(
            user_id=user_id,
            conv=conv,
            brief=brief,
            local_now=decision.local_now or now,
            now=now,
            current_state=current_state,
        )
        if not job:
            return {**base, "reason": "duplicate"}
        self._event(
            "proactive_scheduled",
            {"user_id": user_id, "job_id": job["job_id"], "proactive_type": brief["proactive_type"], "via": "resume"},
        )
        return {**base, "job": job, "reason": "resume_scheduled", "use_engagement_in_reply": False}

    # ------------------------------------------------------------------ execute

    def execute(self, job: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """Run one claimed proactive job. Returns {sent: bool, reason, message_ids}."""
        now = ensure_utc(now or utcnow())
        user_id = job.get("user_id")
        conv = self.runtime.conversation_repo.get(job["conversation_id"]) or {}
        if not user_id or conv.get("user_id") != user_id:
            self._event("proactive_blocked", {"job_id": job["job_id"], "reason": "ownership_mismatch"})
            return {"sent": False, "reason": "ownership_mismatch"}
        expires = job.get("expires_at")
        if expires and ensure_utc(expires) <= now:
            return {"sent": False, "reason": "expired"}
        brief = dict(job.get("proactive_brief") or {})
        settings_doc = self.runtime.proactive_settings_repo.get(user_id, job["persona_id"])
        via_resume = brief.get("idempotency_subject") == "resume" or brief.get("proactive_type") == "returning_user_greeting"
        decision = self._decision(
            settings_doc or {"user_id": user_id},
            now,
            brief.get("proactive_type"),
            exclude_job_id=job["job_id"],
            ignore_quiet=via_resume,
        )
        if not decision.allow:
            self._event("proactive_suppressed", {"job_id": job["job_id"], "user_id": user_id, "reason": decision.reason})
            return {"sent": False, "reason": decision.reason}
        if self.runtime.conversation_repo.pending_user_messages(job["conversation_id"]):
            return {"sent": False, "reason": "user_spoke_first"}

        result = self.runtime.run(
            event_type="proactive_outreach",
            persona_id=job["persona_id"],
            user_id=user_id,
            conversation_id=job["conversation_id"],
            incoming_message="",
            request_id=job["job_id"],
            response_job=job,
            proactive_brief=brief,
        )
        message_ids = list(result.get("assistant_message_ids") or [])
        if not message_ids:
            for text in brief.get("fallback_messages") or fallback_messages(brief):
                msg = self.runtime.conversation_repo.add_message(
                    conversation_id=job["conversation_id"],
                    sender="assistant",
                    content=text,
                    metadata={"fallback": "proactive", "response_job_id": job["job_id"]},
                    message_type="proactive",
                    proactive_type=brief.get("proactive_type"),
                    outbound_id=brief.get("outbound_id"),
                )
                message_ids.append(msg["message_id"])
        self.delivery.deliver(
            user_id=user_id,
            conversation_id=job["conversation_id"],
            message_ids=message_ids,
            proactive_type=brief.get("proactive_type") or "",
        )
        self.runtime.proactive_settings_repo.record_outbound(
            user_id,
            job["persona_id"],
            outbound_id=brief.get("outbound_id") or job["job_id"],
            proactive_type=brief.get("proactive_type") or "new_topic",
            topic=(brief.get("history_key") or brief.get("subject") or brief.get("topic")),
            now=now,
        )
        self._event(
            "proactive_sent",
            {
                "user_id": user_id,
                "conversation_id": job["conversation_id"],
                "outbound_id": brief.get("outbound_id"),
                "proactive_type": brief.get("proactive_type"),
                "bubbles": len(message_ids),
            },
        )
        return {"sent": True, "reason": "sent", "message_ids": message_ids}
