"""Persistent response job repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow


OPEN_STATUSES = ("scheduled", "running")


class ResponseJobRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["response_jobs"]]

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"job_id": job_id})

    def get_open_for_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        return self.col.find_one(
            {"conversation_id": conversation_id, "status": {"$in": list(OPEN_STATUSES)}}
        )

    def create(self, doc: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "job_id": doc.get("job_id") or str(uuid4()),
            "persona_id": doc["persona_id"],
            "conversation_id": doc["conversation_id"],
            "message_ids": list(doc.get("message_ids") or []),
            "status": doc.get("status") or "scheduled",
            "scheduled_for": doc["scheduled_for"],
            "created_at": doc.get("created_at") or utcnow(),
            "started_at": None,
            "completed_at": None,
            "activity_at_schedule": doc.get("activity_at_schedule"),
            "availability_at_schedule": doc.get("availability_at_schedule"),
            "reason": doc.get("reason"),
            "strategy": doc.get("strategy"),
            "read_at": doc.get("read_at"),
            "lock_token": None,
            "locked_by": None,
            "attempt_count": 0,
            "error": None,
            "event_type": doc.get("event_type") or "user_message",
            "follow_up_of": doc.get("follow_up_of"),
            "busy_ack": bool(doc.get("busy_ack")),
        }
        self.col.insert_one(payload)
        return payload

    def append_messages(
        self,
        job_id: str,
        message_ids: list[str],
        *,
        scheduled_for: Any | None = None,
        strategy: str | None = None,
        reason: str | None = None,
        read_at: Any | None = None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {}
        if scheduled_for is not None:
            updates["scheduled_for"] = scheduled_for
        if strategy is not None:
            updates["strategy"] = strategy
        if reason is not None:
            updates["reason"] = reason
        if read_at is not None:
            updates["read_at"] = read_at
        ops: dict[str, Any] = {"$addToSet": {"message_ids": {"$each": message_ids}}}
        if updates:
            ops["$set"] = updates
        return self.col.find_one_and_update(
            {"job_id": job_id, "status": "scheduled"},
            ops,
            return_document=ReturnDocument.AFTER,
        )

    def claim_due(self, worker_id: str, now=None) -> dict[str, Any] | None:
        from persona_runtime.db.time_utils import ensure_utc

        now = ensure_utc(now or utcnow())
        lock_token = str(uuid4())
        # Prefer atomic claim; mongomock may store naive datetimes so also scan
        claimed = self.col.find_one_and_update(
            {"status": "scheduled", "scheduled_for": {"$lte": now}},
            {
                "$set": {
                    "status": "running",
                    "started_at": now,
                    "lock_token": lock_token,
                    "locked_by": worker_id,
                },
                "$inc": {"attempt_count": 1},
            },
            return_document=ReturnDocument.AFTER,
        )
        if claimed:
            return claimed
        # Fallback for naive/aware mismatch in tests
        for job in self.col.find({"status": "scheduled"}):
            scheduled = job.get("scheduled_for")
            if scheduled is None:
                continue
            try:
                if ensure_utc(scheduled) <= now:
                    return self.col.find_one_and_update(
                        {"job_id": job["job_id"], "status": "scheduled"},
                        {
                            "$set": {
                                "status": "running",
                                "started_at": now,
                                "lock_token": lock_token,
                                "locked_by": worker_id,
                            },
                            "$inc": {"attempt_count": 1},
                        },
                        return_document=ReturnDocument.AFTER,
                    )
            except Exception:  # noqa: BLE001
                continue
        return None

    def reschedule(
        self,
        job_id: str,
        lock_token: str,
        *,
        scheduled_for,
        reason: str,
        activity: str | None = None,
        availability: float | None = None,
        strategy: str | None = None,
        read_at=None,
    ) -> dict[str, Any] | None:
        updates: dict[str, Any] = {
            "status": "scheduled",
            "scheduled_for": scheduled_for,
            "reason": reason,
            "started_at": None,
            "lock_token": None,
            "locked_by": None,
        }
        if activity is not None:
            updates["activity_at_schedule"] = activity
        if availability is not None:
            updates["availability_at_schedule"] = availability
        if strategy is not None:
            updates["strategy"] = strategy
        if read_at is not None:
            updates["read_at"] = read_at
        return self.col.find_one_and_update(
            {"job_id": job_id, "lock_token": lock_token, "status": "running"},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )

    def complete(self, job_id: str, lock_token: str, *, strategy: str | None = None) -> None:
        updates: dict[str, Any] = {
            "status": "completed",
            "completed_at": utcnow(),
            "lock_token": None,
            "locked_by": None,
        }
        if strategy is not None:
            updates["strategy"] = strategy
        self.col.update_one(
            {"job_id": job_id, "lock_token": lock_token},
            {"$set": updates},
        )

    def fail(self, job_id: str, lock_token: str, error: str) -> None:
        self.col.update_one(
            {"job_id": job_id, "lock_token": lock_token},
            {
                "$set": {
                    "status": "failed",
                    "error": error,
                    "completed_at": utcnow(),
                    "lock_token": None,
                    "locked_by": None,
                }
            },
        )

    def mark_strategy(self, job_id: str, strategy: str) -> None:
        self.col.update_one({"job_id": job_id}, {"$set": {"strategy": strategy}})

    def count_open(self, conversation_id: str) -> int:
        return self.col.count_documents(
            {"conversation_id": conversation_id, "status": {"$in": list(OPEN_STATUSES)}}
        )

    def list_for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        return list(self.col.find({"conversation_id": conversation_id}).sort("created_at", 1))
