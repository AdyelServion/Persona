"""Persona markdown ingestion into MongoDB Identity collection."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.db.time_utils import utcnow
from persona_runtime.logging_utils import get_logger, log_event
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.persona.constants import (
    DEFAULT_PERSONA_ID,
    DEFAULT_PERSONA_NAME,
    NAMED_RELATIONSHIPS,
    SEED_CANONICAL_FACTS,
    TOP_LEVEL_CATEGORIES,
)
from persona_runtime.persona.loader.parser import (
    discover_persona_files,
    extract_timeline_events,
    parse_persona_file,
    sanitize_for_mongo,
)
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.persona.schemas import CanonicalFact, SubcategoryDocument
from persona_runtime.relationships.repositories import RelationshipRepository
from persona_runtime.state.repositories import PersonaStateRepository

logger = get_logger(__name__)


class PersonaIngestionService:
    def __init__(self, db: Database, persona_id: str = DEFAULT_PERSONA_ID):
        self.db = db
        self.persona_id = persona_id
        self.persona_repo = PersonaRepository(db)
        self.memory_repo = MemoryRepository(db)
        self.relationship_repo = RelationshipRepository(db)
        self.state_repo = PersonaStateRepository(db)

    def ingest(self, source_dir: Path) -> dict[str, Any]:
        files = discover_persona_files(source_dir)
        source_meta: list[dict[str, Any]] = []
        subcategory_count = 0
        biography_text = ""

        for path, category in files:
            parsed = parse_persona_file(path, category)
            source_meta.append(
                {
                    "filename": parsed.filename,
                    "category": category,
                    "hash": parsed.file_hash,
                    "section_count": len(parsed.sections),
                }
            )
            if category == "Biography":
                biography_text = parsed.full_text

            for section in parsed.sections:
                doc = SubcategoryDocument(
                    persona_id=self.persona_id,
                    category=category,
                    subcategory=section.title,
                    subcategory_key=section.subcategory_key,
                    content_raw=section.content_raw,
                    content_structured=sanitize_for_mongo(section.content_structured)
                    if section.content_structured is not None
                    else None,
                    hierarchy=[category, section.title],
                    source_filename=parsed.filename,
                    source="markdown",
                    generated=False,
                    canonical=True,
                    consistency_checked=True,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
                self.persona_repo.upsert_subcategory(doc)
                subcategory_count += 1

        self.persona_repo.upsert_root(
            persona_id=self.persona_id,
            display_name=DEFAULT_PERSONA_NAME,
            source_files=source_meta,
        )

        for fact in SEED_CANONICAL_FACTS:
            self.persona_repo.upsert_canonical_fact(
                CanonicalFact(
                    persona_id=self.persona_id,
                    fact_id=fact.get("fact_id"),
                    subject=fact["subject"],
                    predicate=fact["predicate"],
                    object=fact["object"],
                    time=fact.get("time"),
                    forbidden_recency_phrases=list(fact.get("forbidden_recency_phrases") or []),
                    source="seed",
                    confidence=1.0,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )

        life_events = extract_timeline_events(biography_text) if biography_text else []
        existing_life = self.memory_repo.get_active(
            "life_event", persona_id=self.persona_id, limit=1
        )
        if not existing_life:
            for event in life_events:
                self.memory_repo.create_memory(
                    memory_type="life_event",
                    document={
                        "memory_id": str(uuid4()),
                        "persona_id": self.persona_id,
                        "scope": "persona",
                        "user_id": None,
                        "other_person_id": None,
                        "type": "life_event",
                        "event_description": event.get("event"),
                        "year": event.get("year"),
                        "age": event.get("age"),
                        "category": event.get("category"),
                        "significance": float(event.get("importance", 0.5)),
                        "emotional_impact": event.get("emotional_impact"),
                        "importance": float(event.get("importance", 0.5)),
                        "confidence": 1.0,
                        "source": "markdown",
                        "status": "active",
                        "source_message_ids": [],
                        "created_at": utcnow(),
                        "updated_at": utcnow(),
                        "retrieval_count": 0,
                        "last_retrieved_at": None,
                    },
                )
                self.memory_repo.create_memory(
                    memory_type="autobiographical",
                    document={
                        "memory_id": str(uuid4()),
                        "persona_id": self.persona_id,
                        "scope": "persona",
                        "user_id": None,
                        "type": "autobiographical",
                        "event_description": event.get("event"),
                        "year": event.get("year"),
                        "age": event.get("age"),
                        "importance": float(event.get("importance", 0.5)),
                        "confidence": 1.0,
                        "source": "markdown",
                        "status": "active",
                        "source_message_ids": [],
                        "created_at": utcnow(),
                        "updated_at": utcnow(),
                        "retrieval_count": 0,
                        "last_retrieved_at": None,
                    },
                )

        for rel in NAMED_RELATIONSHIPS:
            self.relationship_repo.upsert_relationship(
                persona_id=self.persona_id,
                other_person_id=rel["other_person_id"],
                data={**rel, "shared_experiences": 0, "meaningful_interactions": 0},
            )

        categories = self.persona_repo.categories_present(self.persona_id)
        missing = [c for c in TOP_LEVEL_CATEGORIES if c not in categories]

        self.state_repo.ensure_default_state(self.persona_id)

        result = {
            "persona_id": self.persona_id,
            "subcategory_count": subcategory_count,
            "source_files": source_meta,
            "categories": sorted(categories),
            "missing_categories": missing,
            "life_events_seeded": len(life_events),
            "canonical_facts": len(SEED_CANONICAL_FACTS),
        }
        log_event(
            logger,
            "persona_ingestion_complete",
            persona_id=self.persona_id,
            subcategory_count=subcategory_count,
            life_events_seeded=len(life_events),
        )
        return result
