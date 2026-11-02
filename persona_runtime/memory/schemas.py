"""Memory schemas and typed collections."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

MemoryType = Literal[
    "episodic",
    "semantic",
    "emotional",
    "relationship",
    "procedural",
    "working",
    "autobiographical",
    "life_event",
    "no_memory",
]

MemoryHorizon = Literal["timeless", "upcoming", "awaiting_outcome", "resolved"]

MemoryCategory = Literal[
    "profile",
    "interest",
    "hobby",
    "lifestyle",
    "preference",
    "event",
    "plan",
    "conversation",
    "interaction_pref",
    "open_thread",
]

# stable: lasting fact/habit; temporary: current state only; planned: future; completed: happened
Temporal = Literal["stable", "temporary", "planned", "completed"]


class MemoryCandidate(BaseModel):
    memory_type: MemoryType
    importance: float = 0.0
    confidence: float = 0.5
    event_description: str | None = None
    fact: str | None = None
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    emotional_label: str | None = None
    intensity: float | None = None
    pattern: str | None = None
    other_person_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    is_correction: bool = False
    occurs_at: datetime | None = None
    horizon: MemoryHorizon | None = None
    outcome_known: bool | None = None
    # Free-form on input (LLM output varies); normalized by user_memory.enrich_candidate
    category: str | None = None
    memory_key: str | None = None
    temporal: str | None = None
    interest_status: str | None = None
    valid_until: datetime | None = None


class MemoryExtractionResult(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)

    @classmethod
    def model_validate_lenient(cls, data: Any) -> "MemoryExtractionResult":
        """Drop malformed candidates instead of failing the whole extraction."""
        items = (data or {}).get("candidates") if isinstance(data, dict) else None
        good: list[MemoryCandidate] = []
        for item in items or []:
            try:
                good.append(MemoryCandidate.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
        return cls(candidates=good)
