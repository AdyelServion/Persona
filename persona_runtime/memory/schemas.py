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


class MemoryExtractionResult(BaseModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list)
