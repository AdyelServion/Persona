"""Relationship state persistence and gradual updates."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow
from persona_runtime.persona.constants import USER_RELATIONSHIP_INITIAL


NUMERIC_FIELDS = [
    "trust",
    "affection",
    "closeness",
    "familiarity",
    "respect",
    "emotional_safety",
    "reciprocity",
    "reliability",
    "conflict",
    "resentment",
    "uncertainty",
    "dependence",
    "attraction",
    "admiration",
    "communication_frequency",
    "emotional_openness",
]


def clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def derive_stage(familiarity: float, trust: float) -> str:
    score = (familiarity + trust) / 2.0
    if score < 0.15:
        return "unknown"
    if score < 0.30:
        return "familiar"
    if score < 0.50:
        return "acquaintance"
    if score < 0.70:
        return "friendly"
    if score < 0.85:
        return "friend"
    if score < 0.95:
        return "close_friend"
    return "deeply_trusted"


class RelationshipRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["relationships"]]

    def upsert_relationship(
        self,
        persona_id: str,
        other_person_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        now = utcnow()
        existing = self.col.find_one({"persona_id": persona_id, "other_person_id": other_person_id})
        payload = {
            **data,
            "persona_id": persona_id,
            "other_person_id": other_person_id,
            "updated_at": now,
        }
        if existing:
            self.col.update_one({"_id": existing["_id"]}, {"$set": payload})
            return {**existing, **payload}
        payload["relationship_id"] = data.get("relationship_id") or str(uuid4())
        payload["created_at"] = now
        self.col.insert_one(payload)
        return payload

    def get_or_create_user_relationship(self, persona_id: str, user_id: str) -> dict[str, Any]:
        existing = self.col.find_one({"persona_id": persona_id, "other_person_id": user_id})
        if existing:
            return existing
        data = {
            **USER_RELATIONSHIP_INITIAL,
            "display_name": "User",
            "shared_experiences": 0,
            "meaningful_interactions": 0,
        }
        return self.upsert_relationship(persona_id, user_id, data)

    def apply_deltas(
        self,
        persona_id: str,
        other_person_id: str,
        deltas: dict[str, float],
        *,
        max_abs_delta: float = 0.05,
        meaningful: bool = False,
    ) -> dict[str, Any]:
        rel = self.get_or_create_user_relationship(persona_id, other_person_id)
        updates: dict[str, Any] = {}
        for field, delta in deltas.items():
            if field not in NUMERIC_FIELDS:
                continue
            bounded = max(-max_abs_delta, min(max_abs_delta, float(delta)))
            current = float(rel.get(field, 0.0))
            updates[field] = clamp01(current + bounded)
        if meaningful:
            updates["shared_experiences"] = int(rel.get("shared_experiences") or 0) + 1
            updates["meaningful_interactions"] = int(rel.get("meaningful_interactions") or 0) + 1
        familiarity = updates.get("familiarity", rel.get("familiarity", 0))
        trust = updates.get("trust", rel.get("trust", 0))
        updates["relationship_stage"] = derive_stage(float(familiarity), float(trust))
        updates["last_interaction_at"] = utcnow()
        return self.upsert_relationship(persona_id, other_person_id, {**rel, **updates})
