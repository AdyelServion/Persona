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
            {"persona_id": persona_id, "user_id": user_id, "status": "active"},
            sort=[("created_at", 1)],
        )
        if existing:
            return existing
        return self.create(persona_id, user_id)

    def create(
        self,
        persona_id: str,
        user_id: str,
        *,
        title: str | None = None,
        conversation_type: str = "primary",
    ) -> dict[str, Any]:
        now = utcnow()
        doc = {
            "conversation_id": str(uuid4()),
            "persona_id": persona_id,
            "user_id": user_id,
            "title": title or "Chat with Sarah",
            "conversation_type": conversation_type,
            "status": "active",
            "next_sequence": 0,
            "last_read_sequence": 0,
            "last_message_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self.conversations.insert_one(doc)
        return doc

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        return self.conversations.find_one({"conversation_id": conversation_id})

    def get_owned(self, conversation_id: str, user_id: str) -> dict[str, Any] | None:
        """Return the conversation only when it belongs to user_id."""
        if not conversation_id or not user_id:
            return None
        return self.conversations.find_one({"conversation_id": conversation_id, "user_id": user_id})

    def list_for_user(self, user_id: str, persona_id: str | None = None) -> list[dict[str, Any]]:
        q: dict[str, Any] = {"user_id": user_id, "status": {"$ne": "deleted"}}
        if persona_id:
            q["persona_id"] = persona_id
        docs = list(self.conversations.find(q))
        docs.sort(
            key=lambda d: (d.get("last_message_at") or d.get("created_at") or utcnow()),
            reverse=True,
        )
        return docs

    def mark_read(self, conversation_id: str, user_id: str, sequence: int | None = None) -> int:
        conv = self.get_owned(conversation_id, user_id)
        if not conv:
            return 0
        if sequence is None:
            sequence = int(conv.get("next_sequence") or 0)
        sequence = min(int(sequence), int(conv.get("next_sequence") or 0))
        if sequence > int(conv.get("last_read_sequence") or 0):
            self.conversations.update_one(
                {"conversation_id": conversation_id, "user_id": user_id},
                {"$set": {"last_read_sequence": sequence}},
            )
            now = utcnow()
            self.messages.update_many(
                {
                    "conversation_id": conversation_id,
                    "sender": "assistant",
                    "sequence": {"$lte": sequence},
                    "read_at": None,
                },
                {"$set": {"read_at": now, "delivery_status": "read"}},
            )
        return sequence

    def unread_count(self, conv: dict[str, Any]) -> int:
        return self.messages.count_documents(
            {
                "conversation_id": conv["conversation_id"],
                "sender": "assistant",
                "sequence": {"$gt": int(conv.get("last_read_sequence") or 0)},
            }
        )

    def last_message(self, conversation_id: str) -> dict[str, Any] | None:
        return self.messages.find_one({"conversation_id": conversation_id}, sort=[("sequence", -1)])

    def touch(self, conversation_id: str) -> None:
        self.conversations.update_one(
            {"conversation_id": conversation_id},
            {"$set": {"updated_at": utcnow()}},
        )

    def next_sequence(self, conversation_id: str) -> int:
        return int(self._advance(conversation_id).get("next_sequence") or 1)

    def _advance(self, conversation_id: str) -> dict[str, Any]:
        now = utcnow()
        result = self.conversations.find_one_and_update(
            {"conversation_id": conversation_id},
            {"$inc": {"next_sequence": 1}, "$set": {"updated_at": now, "last_message_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise ValueError(f"Conversation not found: {conversation_id}")
        return result

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
        message_type: str | None = None,
        proactive_type: str | None = None,
        outbound_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        conv = self._advance(conversation_id)
        sequence = int(conv.get("next_sequence") or 1)
        owner_id = conv.get("user_id")
        if sender == "user":
            msg_status = status or "received"
            msg_priority = priority or classify_priority(content)
        else:
            msg_status = status or "answered"
            msg_priority = priority or "normal"

        doc = {
            "message_id": str(uuid4()),
            "conversation_id": conversation_id,
            "user_id": owner_id,
            "sender": sender,
            "sender_id": owner_id if sender == "user" else conv.get("persona_id"),
            "message_type": message_type or ("user" if sender == "user" else "reply"),
            "proactive_type": proactive_type,
            "outbound_id": outbound_id,
            "delivery_status": "delivered",
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
