"""Memory consolidation: extract, dedupe, correct, persist."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from persona_runtime.config import Settings, get_settings
from persona_runtime.db.time_utils import utcnow
from persona_runtime.logging_utils import get_logger
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.memory.retrieval import jaccard, memory_text, tokenize
from persona_runtime.memory.schemas import MemoryCandidate, MemoryExtractionResult

logger = get_logger(__name__)


class MemoryConsolidator:
    def __init__(self, repo: MemoryRepository, settings: Settings | None = None):
        self.repo = repo
        self.settings = settings or get_settings()

    def consolidate(
        self,
        *,
        persona_id: str,
        user_id: str,
        conversation_id: str,
        candidates: list[MemoryCandidate] | MemoryExtractionResult,
    ) -> list[dict[str, Any]]:
        if isinstance(candidates, MemoryExtractionResult):
            items = candidates.candidates
        else:
            items = candidates

        stored: list[dict[str, Any]] = []
        threshold = self.settings.memory_importance_threshold
        dup_thresh = self.settings.memory_jaccard_dup_threshold

        for cand in items:
            if cand.memory_type == "no_memory":
                continue
            if cand.importance < threshold:
                continue

            mtype = cand.memory_type
            if mtype == "working":
                doc = self._candidate_to_doc(cand, persona_id, user_id, conversation_id)
                stored.append(self.repo.create_memory("working", doc))
                continue

            if mtype == "semantic" and cand.subject and cand.predicate:
                existing = self.repo.find_semantic_fact(
                    persona_id=persona_id,
                    scope="user",
                    subject=cand.subject,
                    predicate=cand.predicate,
                    user_id=user_id,
                )
                if existing:
                    same_object = str(cand.object or "") == str(existing.get("object") or "")
                    # A later explicit correction replaces the active value.
                    # An equal-confidence restatement of a different object does not,
                    # so a recall turn cannot resurrect a superseded fact.
                    if cand.is_correction or (
                        not same_object
                        and cand.confidence > float(existing.get("confidence") or 0.5)
                    ):
                        new_doc = self._candidate_to_doc(cand, persona_id, user_id, conversation_id)
                        new_doc["history"] = list(existing.get("history") or [])
                        new_doc["history"].append(
                            {
                                "previous_object": existing.get("object"),
                                "previous_memory_id": existing.get("memory_id"),
                            }
                        )
                        stored.append(self.repo.supersede_semantic(existing["memory_id"], new_doc))
                    else:
                        # Keep stronger fact; append evidence only
                        evidence = list(existing.get("source_message_ids") or [])
                        evidence.extend(cand.source_message_ids)
                        self.repo.update_memory(
                            "semantic",
                            existing["memory_id"],
                            {"source_message_ids": list(dict.fromkeys(evidence))},
                        )
                    continue

            # Dedup by jaccard against same type
            existing_list = self.repo.get_active(mtype, persona_id=persona_id, user_id=user_id, limit=50)
            cand_tokens = tokenize(cand.event_description or cand.fact or cand.pattern or "")
            merged = False
            for ex in existing_list:
                if ex.get("user_id") not in {None, user_id} and mtype not in {"autobiographical", "life_event"}:
                    continue
                if jaccard(cand_tokens, tokenize(memory_text(ex))) >= dup_thresh:
                    evidence = list(ex.get("source_message_ids") or [])
                    evidence.extend(cand.source_message_ids)
                    updates: dict[str, Any] = {
                        "source_message_ids": list(dict.fromkeys(evidence)),
                        "importance": max(float(ex.get("importance") or 0), cand.importance),
                        "confidence": max(float(ex.get("confidence") or 0), cand.confidence),
                    }
                    if cand.event_description:
                        updates["event_description"] = cand.event_description
                    self.repo.update_memory(mtype, ex["memory_id"], updates)
                    merged = True
                    stored.append({**ex, **updates})
                    break
            if merged:
                continue

            doc = self._candidate_to_doc(cand, persona_id, user_id, conversation_id)
            stored.append(self.repo.create_memory(mtype, doc))

        return stored

    def _candidate_to_doc(
        self,
        cand: MemoryCandidate,
        persona_id: str,
        user_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        now = utcnow()
        doc: dict[str, Any] = {
            "memory_id": str(uuid4()),
            "persona_id": persona_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "scope": "user" if cand.memory_type not in {"autobiographical", "life_event"} else "persona",
            "type": cand.memory_type,
            "importance": cand.importance,
            "confidence": cand.confidence,
            "source_message_ids": cand.source_message_ids,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "retrieval_count": 0,
            "last_retrieved_at": None,
            "other_person_id": cand.other_person_id,
        }
        if cand.event_description:
            doc["event_description"] = cand.event_description
        if cand.fact:
            doc["fact"] = cand.fact
        if cand.subject:
            doc["subject"] = cand.subject
        if cand.predicate:
            doc["predicate"] = cand.predicate
        if cand.object:
            doc["object"] = cand.object
        if cand.emotional_label:
            doc["emotional_label"] = cand.emotional_label
        if cand.intensity is not None:
            doc["intensity"] = cand.intensity
        if cand.pattern:
            doc["pattern"] = cand.pattern
        if cand.occurs_at is not None:
            doc["occurs_at"] = cand.occurs_at
        if cand.horizon is not None:
            doc["horizon"] = cand.horizon
        if cand.outcome_known is not None:
            doc["outcome_known"] = cand.outcome_known
        return doc
