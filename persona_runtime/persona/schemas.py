"""Persona schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class PersonaRoot(BaseModel):
    persona_id: str
    display_name: str
    doc_type: Literal["root"] = "root"
    source_files: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SubcategoryDocument(BaseModel):
    persona_id: str
    doc_type: Literal["subcategory"] = "subcategory"
    category: str
    subcategory: str
    subcategory_key: str
    content_raw: str
    content_structured: dict[str, Any] | list[Any] | str | None = None
    hierarchy: list[str] = Field(default_factory=list)
    source_filename: str
    source: str = "markdown"
    generated: bool = False
    canonical: bool = True
    generation_model: str | None = None
    generation_prompt_id: str | None = None
    generation_prompt_text: str | None = None
    source_categories: list[str] = Field(default_factory=list)
    consistency_checked: bool = False
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CanonicalFact(BaseModel):
    persona_id: str
    doc_type: Literal["canonical_fact"] = "canonical_fact"
    fact_id: str | None = None
    subject: str
    predicate: str
    object: str
    time: dict[str, Any] | None = None
    forbidden_recency_phrases: list[str] = Field(default_factory=list)
    evidence_subcategory_id: str | None = None
    source: str = "seed"
    confidence: float = 1.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
