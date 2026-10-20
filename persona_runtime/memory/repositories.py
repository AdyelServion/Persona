"""Typed memory repositories."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.db import MEMORY_COLLECTIONS
from persona_runtime.db.time_utils import utcnow
from persona_runtime.exceptions import DatabaseError
from persona_runtime.logging_utils import get_logger

logger = get_logger(__name__)


class MemoryRepository:
    def __init__(self, db: Database):
        self.db = db

    def collection_for(self, memory_type: str):
        name = MEMORY_COLLECTIONS.get(memory_type)
        if not name:
            raise ValueError(f"Unknown memory type: {memory_type}")
        return self.db[name]

    def create_memory(self, memory_type: str, document: dict[str, Any]) -> dict[str, Any]:
        col = self.collection_for(memory_type)
        doc = dict(document)
        doc.setdefault("memory_id", str(uuid4()))
        doc.setdefault("type", memory_type)
        doc.setdefault("status", "active")
        now = utcnow()
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        doc.setdefault("retrieval_count", 0)
        doc.setdefault("last_retrieved_at", None)
        try:
            col.insert_one(doc)
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"Failed to create {memory_type} memory: {exc}") from exc
        return doc

    def update_memory(self, memory_type: str, memory_id: str, updates: dict[str, Any]) -> None:
        col = self.collection_for(memory_type)
        updates = {**updates, "updated_at": utcnow()}
        col.update_one({"memory_id": memory_id}, {"$set": updates})

    def mark_retrieved(self, memory_type: str, memory_id: str) -> None:
        col = self.collection_for(memory_type)
        col.update_one(
            {"memory_id": memory_id},
            {
                "$inc": {"retrieval_count": 1},
                "$set": {"last_retrieved_at": utcnow()},
            },
        )

    def get_active(
        self,
        memory_type: str,
        *,
        persona_id: str,
        user_id: str | None = None,
        other_person_id: str | None = None,
        conversation_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        col = self.collection_for(memory_type)
        q: dict[str, Any] = {"persona_id": persona_id, "status": "active"}
        if user_id is not None:
            q["$or"] = [
                {"scope": "persona"},
                {"scope": "user", "user_id": user_id},
                {"user_id": user_id},
                {"user_id": None, "scope": "persona"},
            ]
        if other_person_id is not None:
            q["other_person_id"] = other_person_id
        if conversation_id is not None and memory_type == "working":
            q["conversation_id"] = conversation_id
        try:
            return list(col.find(q).sort("created_at", -1).limit(limit))
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(str(exc)) from exc

    def find_semantic_fact(
        self,
        persona_id: str,
        scope: str,
        subject: str,
        predicate: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        q: dict[str, Any] = {
            "persona_id": persona_id,
            "scope": scope,
            "subject": subject,
            "predicate": predicate,
            "status": "active",
        }
        if user_id:
            q["user_id"] = user_id
        return self.collection_for("semantic").find_one(q)

    def supersede_semantic(self, old_memory_id: str, new_doc: dict[str, Any]) -> dict[str, Any]:
        self.update_memory("semantic", old_memory_id, {"status": "superseded"})
        history = new_doc.setdefault("history", [])
        history.append({"superseded_memory_id": old_memory_id, "at": utcnow().isoformat()})
        return self.create_memory("semantic", new_doc)

    def list_all_active_for_user(self, persona_id: str, user_id: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for mtype in MEMORY_COLLECTIONS:
            if mtype == "working":
                continue
            try:
                for mem in self.get_active(mtype, persona_id=persona_id, user_id=user_id, limit=50):
                    # Strict relationship privacy: relationship-scoped memories only if other is user
                    if mem.get("scope") == "relationship":
                        if mem.get("other_person_id") not in {None, user_id}:
                            continue
                    results.append({**mem, "_memory_type": mtype})
            except DatabaseError:
                logger.exception("memory_list_failed type=%s", mtype)
        return results
