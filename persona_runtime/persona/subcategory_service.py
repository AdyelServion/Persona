"""Dynamic subcategory generation with provenance and conflict rejection."""

from __future__ import annotations

import json
from typing import Any

from persona_runtime.config import Settings, get_settings
from persona_runtime.db.time_utils import utcnow
from persona_runtime.exceptions import SubcategoryConflictError
from persona_runtime.llm.client import LLMClient
from persona_runtime.logging_utils import get_logger
from persona_runtime.persona.canonical import conflicts_with_canonical
from persona_runtime.persona.loader.parser import slugify
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.persona.schemas import SubcategoryDocument
from persona_runtime.prompts.registry import PromptRepository

logger = get_logger(__name__)


class SubcategoryService:
    def __init__(
        self,
        persona_repo: PersonaRepository,
        prompt_repo: PromptRepository,
        llm: LLMClient,
        settings: Settings | None = None,
    ):
        self.persona_repo = persona_repo
        self.prompt_repo = prompt_repo
        self.llm = llm
        self.settings = settings or get_settings()

    def find_existing(
        self, persona_id: str, category: str, topic: str, keywords: list[str]
    ) -> dict[str, Any] | None:
        key = slugify(topic)
        direct = self.persona_repo.get_subcategory(persona_id, category, key)
        if direct:
            return direct
        # Prefer strong title overlap; avoid weak keyword collisions
        topic_tokens = {t.lower() for t in topic.split() if len(t) > 2}
        matches = self.persona_repo.find_subcategories_by_keywords(
            persona_id, category, keywords or topic.split()
        )
        for match in matches:
            title_tokens = {t.lower() for t in str(match.get("subcategory") or "").split() if len(t) > 2}
            if topic_tokens and topic_tokens.issubset(title_tokens | set(keywords or [])):
                return match
            if slugify(str(match.get("subcategory") or "")) == key:
                return match
            # Exact phrase in title
            if topic.lower() in str(match.get("subcategory") or "").lower():
                return match
        return None

    def generate_and_store(
        self,
        *,
        persona_id: str,
        category: str,
        topic: str,
        related_context: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.find_existing(persona_id, category, topic, topic.split())
        if existing:
            return existing

        prompt = self.prompt_repo.get_active("persona_subcategory_generation")
        if not prompt:
            raise RuntimeError("Missing prompt persona_subcategory_generation")

        canonical_facts = self.persona_repo.list_canonical_facts(persona_id)
        user_payload = {
            "category": category,
            "topic": topic,
            "CANONICAL_FACTS": [
                {"subject": f["subject"], "predicate": f["predicate"], "object": f["object"]}
                for f in canonical_facts
            ],
            "SOURCE_CATEGORY_DATA": related_context,
        }
        prompt_text = prompt["system_prompt_template"]
        generated = self.llm.complete_json(
            system=prompt_text,
            user=json.dumps(user_payload, default=str),
            temperature=float(prompt.get("temperature") or 0.4),
        )

        conflicts = conflicts_with_canonical(generated, canonical_facts)
        # Also check claims array
        for claim in generated.get("claims") or []:
            if isinstance(claim, dict):
                conflicts.extend(
                    conflicts_with_canonical(
                        {
                            claim.get("predicate", "lives_in"): claim.get("object"),
                            "city": claim.get("object") if claim.get("predicate") == "lives_in" else None,
                        },
                        canonical_facts,
                    )
                )
        conflicts = list(dict.fromkeys(conflicts))
        if conflicts:
            logger.warning("subcategory_rejected conflicts=%s", conflicts)
            raise SubcategoryConflictError("; ".join(conflicts))

        title = str(generated.get("title") or topic)
        key = slugify(str(generated.get("subcategory_key") or title))
        # Re-check after slug
        again = self.persona_repo.get_subcategory(persona_id, category, key)
        if again:
            return again

        details = generated.get("details") if isinstance(generated.get("details"), dict) else generated
        content_raw = str(generated.get("summary") or "") + "\n" + json.dumps(details, ensure_ascii=False)
        doc = SubcategoryDocument(
            persona_id=persona_id,
            category=category,
            subcategory=title,
            subcategory_key=key,
            content_raw=content_raw,
            content_structured=generated,
            hierarchy=[category, title],
            source_filename="llm_generated",
            source="llm_generated",
            generated=True,
            canonical=False,
            generation_model=self.settings.openai_model_name,
            generation_prompt_id=prompt.get("prompt_id"),
            generation_prompt_text=prompt_text,
            source_categories=list(related_context.keys()),
            consistency_checked=True,
            version=1,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        return self.persona_repo.upsert_subcategory(doc)
