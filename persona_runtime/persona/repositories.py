"""Persona identity repository."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo.collection import Collection
from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow
from persona_runtime.exceptions import DatabaseError, PersonaNotFoundError
from persona_runtime.persona.constants import DEFAULT_PERSONA_ID
from persona_runtime.persona.schemas import CanonicalFact, SubcategoryDocument


class PersonaRepository:
    def __init__(self, db: Database):
        self.db = db
        self.col: Collection = db[COLLECTION_NAMES["identity"]]

    def upsert_root(self, persona_id: str, display_name: str, source_files: list[dict], version: int = 1) -> dict:
        now = utcnow()
        doc = {
            "persona_id": persona_id,
            "doc_type": "root",
            "category": "_root",
            "subcategory_key": "_root",
            "display_name": display_name,
            "source_files": source_files,
            "version": version,
            "updated_at": now,
        }
        existing = self.col.find_one({"persona_id": persona_id, "doc_type": "root"})
        if existing:
            self.col.update_one({"_id": existing["_id"]}, {"$set": doc})
        else:
            doc["created_at"] = now
            self.col.insert_one(doc)
        return doc

    def upsert_subcategory(self, sub: SubcategoryDocument | dict[str, Any]) -> dict[str, Any]:
        data = sub.model_dump() if isinstance(sub, SubcategoryDocument) else dict(sub)
        now = utcnow()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        data.setdefault("doc_type", "subcategory")
        filter_q = {
            "persona_id": data["persona_id"],
            "doc_type": "subcategory",
            "category": data["category"],
            "subcategory_key": data["subcategory_key"],
        }
        existing = self.col.find_one(filter_q)
        if existing:
            data["created_at"] = existing.get("created_at", now)
            data["version"] = int(existing.get("version", 1)) + (0 if not data.get("generated") else 0)
            self.col.update_one({"_id": existing["_id"]}, {"$set": data})
            data["_id"] = existing["_id"]
        else:
            data.setdefault("subcategory_id", str(uuid4()))
            result = self.col.insert_one(data)
            data["_id"] = result.inserted_id
        return data

    def get_root(self, persona_id: str = DEFAULT_PERSONA_ID) -> dict[str, Any]:
        doc = self.col.find_one({"persona_id": persona_id, "doc_type": "root"})
        if not doc:
            raise PersonaNotFoundError(f"Persona root not found: {persona_id}")
        return doc

    def list_subcategories(self, persona_id: str, category: str | None = None) -> list[dict[str, Any]]:
        q: dict[str, Any] = {"persona_id": persona_id, "doc_type": "subcategory"}
        if category:
            q["category"] = category
        return list(self.col.find(q))

    def get_subcategory(self, persona_id: str, category: str, subcategory_key: str) -> dict[str, Any] | None:
        return self.col.find_one(
            {
                "persona_id": persona_id,
                "doc_type": "subcategory",
                "category": category,
                "subcategory_key": subcategory_key,
            }
        )

    def find_subcategories_by_keywords(
        self, persona_id: str, category: str, keywords: list[str]
    ) -> list[dict[str, Any]]:
        subs = self.list_subcategories(persona_id, category)
        if not keywords:
            return subs[:5]
        scored: list[tuple[float, dict]] = []
        for sub in subs:
            hay = f"{sub.get('subcategory', '')} {sub.get('content_raw', '')}".lower()
            score = sum(1.0 for kw in keywords if kw.lower() in hay)
            if score > 0:
                scored.append((score, sub))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored]

    def upsert_canonical_fact(self, fact: CanonicalFact | dict[str, Any]) -> dict[str, Any]:
        data = fact.model_dump() if isinstance(fact, CanonicalFact) else dict(fact)
        now = utcnow()
        data.setdefault("created_at", now)
        data["updated_at"] = now
        data.setdefault("doc_type", "canonical_fact")
        data.setdefault("category", "_facts")
        data["subcategory_key"] = f"fact_{data['subject']}_{data['predicate']}_{data['object']}"[:120]
        filter_q = {
            "persona_id": data["persona_id"],
            "doc_type": "canonical_fact",
            "subject": data["subject"],
            "predicate": data["predicate"],
            "object": data["object"],
        }
        existing = self.col.find_one(filter_q)
        if existing:
            self.col.update_one({"_id": existing["_id"]}, {"$set": data})
            data["_id"] = existing["_id"]
        else:
            result = self.col.insert_one(data)
            data["_id"] = result.inserted_id
        return data

    def list_canonical_facts(self, persona_id: str) -> list[dict[str, Any]]:
        return list(self.col.find({"persona_id": persona_id, "doc_type": "canonical_fact"}))

    def categories_present(self, persona_id: str) -> set[str]:
        return set(self.col.distinct("category", {"persona_id": persona_id, "doc_type": "subcategory"}))

    def get_identity_card(self, persona_id: str) -> dict[str, Any]:
        """Compact identity snapshot for prompts."""
        identity_subs = self.list_subcategories(persona_id, "Identity")
        card = {
            "persona_id": persona_id,
            "display_name": "Sarah Taylor",
            "fictional": True,
            "snippets": [],
        }
        try:
            root = self.get_root(persona_id)
            card["display_name"] = root.get("display_name", card["display_name"])
        except PersonaNotFoundError:
            pass
        for sub in identity_subs[:6]:
            card["snippets"].append(
                {
                    "subcategory": sub.get("subcategory"),
                    "excerpt": (sub.get("content_raw") or "")[:800],
                }
            )
        return card

    def health_check(self) -> bool:
        try:
            self.col.find_one({}, projection={"_id": 1})
            return True
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(str(exc)) from exc
