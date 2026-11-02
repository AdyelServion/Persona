"""User-wise memory taxonomy and service (scope = user_id + persona_id).

Facts about a real user live in the existing typed collections (mostly SemanticMemories)
with category / memory_key / temporal metadata. Nothing here ever reads another user's docs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, get_args

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES, MEMORY_COLLECTIONS
from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.logging_utils import get_logger
from persona_runtime.memory.schemas import MemoryCandidate, MemoryCategory, Temporal

logger = get_logger(__name__)

CATEGORIES: tuple[str, ...] = get_args(MemoryCategory)
TEMPORALS: tuple[str, ...] = get_args(Temporal)
TEMPORARY_TTL_HOURS = 6


@dataclass(frozen=True)
class KeySpec:
    memory_key: str
    category: str
    single: bool


# predicate -> taxonomy. Single-valued keys supersede; multi-valued keys accumulate.
KEY_SPECS: dict[str, KeySpec] = {
    "name": KeySpec("user.name", "profile", True),
    "preferred_name": KeySpec("user.name", "profile", True),
    "occupation": KeySpec("user.occupation", "profile", True),
    "employer": KeySpec("user.employer", "profile", True),
    "industry": KeySpec("user.industry", "profile", True),
    "education": KeySpec("user.education", "profile", True),
    "lives_in": KeySpec("user.location", "profile", True),
    "location": KeySpec("user.location", "profile", True),
    "owns_car": KeySpec("user.car", "profile", True),
    "hobby": KeySpec("user.hobby", "hobby", False),
    "interest": KeySpec("user.interest", "interest", False),
    "supports_team": KeySpec("user.team", "interest", True),
    "music_preference": KeySpec("user.music", "preference", False),
    "favourite_food": KeySpec("user.favourite_food", "preference", False),
    "favorite_food": KeySpec("user.favourite_food", "preference", False),
    "dislikes": KeySpec("user.dislike", "preference", False),
    "morning_drink": KeySpec("user.morning_drink", "preference", True),
    "weekend_preference": KeySpec("user.weekend_activity", "lifestyle", False),
    "routine": KeySpec("user.routine", "lifestyle", False),
    "has_upcoming_event": KeySpec("user.upcoming_event", "event", False),
    "plan": KeySpec("user.plan", "plan", False),
    "messaging_boundary": KeySpec("user.messaging_boundary", "interaction_pref", False),
    "communication_preference": KeySpec("user.communication_preference", "interaction_pref", False),
}

CATEGORY_ALIASES = {
    "hobbies": "hobby",
    "interests": "interest",
    "preferences": "preference",
    "events": "event",
    "plans": "plan",
    "basic": "profile",
    "personal": "profile",
    "relationship": "interaction_pref",
    "interaction": "interaction_pref",
    "thread": "open_thread",
}

# Words in a query that hint which category is relevant (retrieval boost)
CATEGORY_HINTS: dict[str, tuple[str, ...]] = {
    "profile": ("name", "call", "job", "work", "live", "based", "from", "car", "drive"),
    "hobby": ("hobby", "hobbies", "free", "time", "photo", "photography", "game", "gaming", "play"),
    "interest": ("team", "match", "into", "interest", "support"),
    "lifestyle": ("weekend", "weekends", "morning", "routine", "evening", "after"),
    "preference": ("favourite", "favorite", "music", "food", "drink", "coffee", "tea", "like"),
    "event": ("presentation", "interview", "exam", "trip", "holiday", "birthday", "went", "go"),
    "plan": ("plan", "plans", "planning", "next", "tomorrow"),
    "interaction_pref": ("message", "messages", "busy", "text"),
}

_TEMPORARY_WORDS = re.compile(r"\b(?:right now|at the moment|currently|just now)\b")


def spec_for(cand: MemoryCandidate) -> KeySpec | None:
    pred = (cand.predicate or "").strip().lower()
    if pred in KEY_SPECS:
        return KEY_SPECS[pred]
    if cand.memory_key:
        for spec in KEY_SPECS.values():
            if spec.memory_key == cand.memory_key:
                return spec
    return None


def normalize_value(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def enrich_candidate(cand: MemoryCandidate) -> MemoryCandidate:
    """Fill category / memory_key / temporal; never trust free-form labels blindly."""
    c = cand.model_copy()
    spec = spec_for(c) if (c.subject or "user") == "user" else None
    if spec:
        c.memory_key = spec.memory_key
        c.category = spec.category
    elif c.memory_key and not c.memory_key.startswith("user."):
        c.memory_key = f"user.{c.memory_key}"

    cat = (c.category or "").strip().lower()
    cat = CATEGORY_ALIASES.get(cat, cat)
    if cat not in CATEGORIES:
        if c.memory_type == "episodic" and (c.occurs_at or c.horizon in {"upcoming", "awaiting_outcome"}):
            cat = "event"
        elif c.memory_type in {"episodic", "emotional"}:
            cat = "conversation"
        else:
            cat = None  # type: ignore[assignment]
    c.category = cat or None

    temporal = (c.temporal or "").strip().lower()
    if temporal not in TEMPORALS:
        if c.memory_type == "working":
            temporal = "temporary"
        elif c.horizon == "upcoming" or (c.occurs_at and c.outcome_known is False and c.horizon != "awaiting_outcome"):
            temporal = "planned"
        elif c.horizon == "resolved" or c.outcome_known is True:
            temporal = "completed"
        elif _TEMPORARY_WORDS.search((c.fact or c.event_description or "").lower()) and c.predicate not in KEY_SPECS:
            temporal = "temporary"
        else:
            temporal = "stable"
    c.temporal = temporal
    if c.category in {"event", "plan"} and c.temporal == "stable" and c.horizon == "upcoming":
        c.temporal = "planned"

    status = (c.interest_status or "").strip().lower()
    c.interest_status = status if status in {"current", "former"} else (
        "current" if c.category in {"hobby", "interest"} else None
    )

    if c.temporal == "temporary" and c.valid_until is None:
        c.valid_until = utcnow() + timedelta(hours=TEMPORARY_TTL_HOURS)
    return c


def memory_status_label(mem: dict[str, Any]) -> str:
    """How the response planner should treat a memory (never present uncertain as confirmed)."""
    if mem.get("status") == "superseded":
        return "outdated"
    temporal = mem.get("temporal") or "stable"
    if temporal == "temporary":
        return "temporary_state"
    if mem.get("interest_status") == "former":
        return "former_interest"
    horizon = mem.get("horizon")
    if horizon == "awaiting_outcome":
        return "past_event_outcome_unknown"
    if temporal == "planned" or horizon == "upcoming":
        return "future_plan"
    if temporal == "completed" or horizon == "resolved":
        return "completed_event"
    if float(mem.get("confidence") or 0.5) < 0.6:
        return "inferred_unconfirmed"
    return "user_provided_fact"


def category_boost(query_tokens: set[str], mem: dict[str, Any]) -> float:
    cat = mem.get("category")
    if not cat:
        return 0.0
    hints = CATEGORY_HINTS.get(cat, ())
    return 0.35 if any(h in query_tokens for h in hints) else 0.0


class UserMemoryService:
    """Read/delete operations over one user's memories with this persona."""

    def __init__(self, db: Database):
        self.db = db

    def _user_query(self, persona_id: str, user_id: str) -> dict[str, Any]:
        return {"persona_id": persona_id, "user_id": user_id, "scope": {"$in": ["user", None]}}

    def list_for_user(self, persona_id: str, user_id: str, *, include_working: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for mtype, col_name in MEMORY_COLLECTIONS.items():
            if mtype == "working" and not include_working:
                continue
            q = {**self._user_query(persona_id, user_id), "status": "active"}
            for doc in self.db[col_name].find(q).sort("created_at", -1).limit(200):
                out.append(self._public(doc, mtype))
        return out

    @staticmethod
    def _public(doc: dict[str, Any], mtype: str) -> dict[str, Any]:
        created = doc.get("created_at")
        return {
            "memory_id": doc.get("memory_id"),
            "memory_type": mtype,
            "category": doc.get("category"),
            "memory_key": doc.get("memory_key"),
            "value": doc.get("object"),
            "text": doc.get("fact") or doc.get("event_description") or doc.get("pattern"),
            "temporal": doc.get("temporal"),
            "interest_status": doc.get("interest_status"),
            "status_label": memory_status_label(doc),
            "confidence": doc.get("confidence"),
            "source_conversation_id": doc.get("source_conversation_id") or doc.get("conversation_id"),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        }

    def profile_card(self, persona_id: str, user_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """Compact 'known about this user' facts: stable, current, highest value first."""
        col = self.db[MEMORY_COLLECTIONS["semantic"]]
        q = {
            **self._user_query(persona_id, user_id),
            "status": "active",
            "subject": "user",
        }
        docs = [
            d
            for d in col.find(q).limit(200)
            if (d.get("temporal") or "stable") != "temporary" and d.get("interest_status") != "former"
        ]
        docs.sort(
            key=lambda d: (
                1 if d.get("category") == "profile" else 0,
                float(d.get("importance") or 0.5),
                str(d.get("updated_at") or ""),
            ),
            reverse=True,
        )
        seen_single: set[str] = set()
        card: list[dict[str, Any]] = []
        for d in docs:
            key = d.get("memory_key") or d.get("predicate") or ""
            spec = KEY_SPECS.get(str(d.get("predicate") or ""))
            if spec and spec.single:
                if key in seen_single:
                    continue
                seen_single.add(key)
            card.append({**d, "_memory_type": "semantic", "status_label": memory_status_label(d)})
            if len(card) >= limit:
                break
        return card

    def coverage(self, persona_id: str, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {c: 0 for c in CATEGORIES}
        for mtype in ("semantic", "episodic"):
            col = self.db[MEMORY_COLLECTIONS[mtype]]
            for d in col.find({**self._user_query(persona_id, user_id), "status": "active"}).limit(300):
                cat = d.get("category")
                if cat in counts:
                    counts[cat] += 1
        return counts

    def known_values(self, persona_id: str, user_id: str, memory_key: str) -> list[str]:
        col = self.db[MEMORY_COLLECTIONS["semantic"]]
        q = {**self._user_query(persona_id, user_id), "status": "active", "memory_key": memory_key}
        return [str(d.get("object") or "") for d in col.find(q).limit(50) if d.get("object")]

    def delete(self, persona_id: str, user_id: str, memory_id: str) -> bool:
        """Soft-delete one of the caller's memories and scrub derived conversation state."""
        for mtype, col_name in MEMORY_COLLECTIONS.items():
            col = self.db[col_name]
            doc = col.find_one({"memory_id": memory_id, "persona_id": persona_id, "user_id": user_id})
            if not doc:
                continue
            if doc.get("scope") not in {"user", None}:
                return False
            now = utcnow()
            col.update_one(
                {"memory_id": memory_id, "user_id": user_id},
                {"$set": {"status": "deleted", "deleted_at": now, "updated_at": now}},
            )
            self._scrub_contexts(persona_id, user_id, doc)
            self.db[COLLECTION_NAMES["events"]].insert_one(
                {
                    "event_type": "memory_deleted",
                    "user_id": user_id,
                    "persona_id": persona_id,
                    "memory_id": memory_id,
                    "memory_type": mtype,
                    "created_at": now,
                }
            )
            return True
        return False

    def _scrub_contexts(self, persona_id: str, user_id: str, doc: dict[str, Any]) -> None:
        needle = normalize_value(doc.get("object") or "")
        pred = doc.get("predicate")
        ctx_col = self.db[COLLECTION_NAMES["conversation_contexts"]]
        for ctx in ctx_col.find({"persona_id": persona_id, "user_id": user_id}):
            facts = [
                f
                for f in (ctx.get("user_facts_this_conversation") or [])
                if not (
                    isinstance(f, dict)
                    and (
                        (pred and f.get("predicate") == pred and normalize_value(f.get("object")) == needle)
                        or (needle and needle in normalize_value(f.get("object")))
                    )
                )
            ]
            summary = ctx.get("recent_summary") or ""
            if needle and needle in summary.lower():
                summary = ""
            ctx_col.update_one(
                {"_id": ctx["_id"]},
                {"$set": {"user_facts_this_conversation": facts, "recent_summary": summary}},
            )


def is_expired(mem: dict[str, Any], now=None) -> bool:
    until = mem.get("valid_until")
    if until is None:
        return False
    try:
        return ensure_utc(until) <= ensure_utc(now or utcnow())
    except Exception:  # noqa: BLE001
        return False
