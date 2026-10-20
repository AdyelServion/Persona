"""Conversation and message persistence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow
from persona_runtime.life.strategy import classify_priority


class ConversationRepository:
    def __init__(self, db: Database):
        self.conversations = db[COLLECTION_NAMES["conversations"]]
        self.messages = db[COLLECTION_NAMES["messages"]]
        self.events = db[COLLECTION_NAMES["events"]]

    def get_or_create(self, persona_id: str, user_id: str) -> dict[str, Any]:
        existing = self.conversations.find_one(
            {"persona_id": persona_id, "user_id": user_id, "status": "active"}
        )
        if existing:
            return existing
        now = utcnow()
        doc = {
            "conversation_id": str(uuid4()),
            "persona_id": persona_id,
            "user_id": user_id,
            "status": "active",
            "next_sequence": 0,
            "created_at": now,
            "updated_at": now,
        }
        self.conversations.insert_one(doc)
        return doc

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        return self.conversations.find_one({"conversation_id": conversation_id})

    def touch(self, conversation_id: str) -> None:
        self.conversations.update_one(
            {"conversation_id": conversation_id},
            {"$set": {"updated_at": utcnow()}},
        )

    def next_sequence(self, conversation_id: str) -> int:
        result = self.conversations.find_one_and_update(
            {"conversation_id": conversation_id},
            {"$inc": {"next_sequence": 1}, "$set": {"updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise ValueError(f"Conversation not found: {conversation_id}")
        return int(result.get("next_sequence") or 1)

    def add_message(
        self,
        *,
        conversation_id: str,
        sender: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        priority: str | None = None,
        response_job_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        sequence = self.next_sequence(conversation_id)
        if sender == "user":
            msg_status = status or "received"
            msg_priority = priority or classify_priority(content)
        else:
            msg_status = status or "answered"
            msg_priority = priority or "normal"

        doc = {
            "message_id": str(uuid4()),
            "conversation_id": conversation_id,
            "sender": sender,
            "content": content,
            "timestamp": now,
            "created_at": now,
            "sequence": sequence,
            "status": msg_status,
            "priority": msg_priority,
            "read_at": None,
            "answered_at": now if sender == "assistant" else None,
            "response_job_id": response_job_id,
            "metadata": metadata or {},
        }
        self.messages.insert_one(doc)
        self.touch(conversation_id)
        return doc

    def update_message(self, message_id: str, updates: dict[str, Any]) -> None:
        self.messages.update_one({"message_id": message_id}, {"$set": updates})

    def update_messages(self, message_ids: list[str], updates: dict[str, Any]) -> None:
        if not message_ids:
            return
        self.messages.update_many({"message_id": {"$in": message_ids}}, {"$set": updates})

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        return self.messages.find_one({"message_id": message_id})

    def get_messages_by_ids(self, message_ids: list[str]) -> list[dict[str, Any]]:
        if not message_ids:
            return []
        docs = list(self.messages.find({"message_id": {"$in": message_ids}}))
        order = {mid: i for i, mid in enumerate(message_ids)}
        docs.sort(key=lambda d: order.get(d["message_id"], 10**9))
        return docs

    def list_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        after_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"conversation_id": conversation_id}
        if after_sequence is not None:
            query["sequence"] = {"$gt": int(after_sequence)}
        return list(self.messages.find(query).sort("sequence", 1).limit(limit))

    def recent_messages(self, conversation_id: str, limit: int = 12) -> list[dict[str, Any]]:
        msgs = list(
            self.messages.find({"conversation_id": conversation_id})
            .sort("sequence", -1)
            .limit(limit)
        )
        return list(reversed(msgs))

    def pending_user_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        return list(
            self.messages.find(
                {
                    "conversation_id": conversation_id,
                    "sender": "user",
                    "status": {
                        "$in": [
                            "received",
                            "unread",
                            "read",
                            "pending_response",
                        ]
                    },
                }
            ).sort("sequence", 1)
        )

    def count_messages(self, conversation_id: str) -> int:
        return self.messages.count_documents({"conversation_id": conversation_id})

    def record_event(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        doc = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "created_at": utcnow(),
            **payload,
        }
        self.events.insert_one(doc)
        return doc

    def inbox_projection(self, conversation_id: str) -> dict[str, Any]:
        msgs = list(
            self.messages.find({"conversation_id": conversation_id, "sender": "user"}).sort(
                "sequence", 1
            )
        )
        buckets: dict[str, list[str]] = {
            "unread": [],
            "pending": [],
            "read": [],
            "included": [],
            "answered": [],
        }
        for m in msgs:
            st = m.get("status") or ""
            mid = m["message_id"]
            if st in {"received", "unread"}:
                buckets["unread"].append(mid)
            if st in {"received", "unread", "read", "pending_response"}:
                buckets["pending"].append(mid)
            if st == "read":
                buckets["read"].append(mid)
            if st == "included_in_response":
                buckets["included"].append(mid)
            if st in {"answered", "ignored", "superseded"}:
                buckets["answered"].append(mid)
        return {"conversation_id": conversation_id, **buckets}
