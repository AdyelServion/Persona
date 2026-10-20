"""Persona ingestion and subcategory tests."""

from __future__ import annotations

import pytest

from persona_runtime.exceptions import SubcategoryConflictError
from persona_runtime.persona.canonical import conflicts_with_canonical
from persona_runtime.persona.constants import TOP_LEVEL_CATEGORIES
from persona_runtime.persona.loader import PersonaIngestionService
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.persona.subcategory_service import SubcategoryService
from persona_runtime.prompts.registry import PromptRepository


def test_ingestion_maps_categories(ingested_db):
    repo = PersonaRepository(ingested_db)
    cats = repo.categories_present("sarah_taylor_001")
    for required in TOP_LEVEL_CATEGORIES:
        assert required in cats, f"missing category {required}"
    root = repo.get_root("sarah_taylor_001")
    assert root["display_name"] == "Sarah Taylor"
    assert root["source_files"]
    subs = repo.list_subcategories("sarah_taylor_001")
    assert len(subs) > 20
    # Provenance preserved
    assert all(s.get("content_raw") for s in subs[:5])
    assert all(s.get("source_filename") for s in subs[:5])


def test_canonical_facts_seeded(ingested_db):
    repo = PersonaRepository(ingested_db)
    facts = repo.list_canonical_facts("sarah_taylor_001")
    objects = {(f["predicate"], f["object"]) for f in facts}
    assert ("lives_in", "Manchester") in objects
    assert ("hometown", "Sheffield") in objects


def test_conflict_detection_manchester_london(ingested_db):
    repo = PersonaRepository(ingested_db)
    facts = repo.list_canonical_facts("sarah_taylor_001")
    reasons = conflicts_with_canonical({"city": "London", "summary": "Sarah lives in London"}, facts)
    assert reasons


def test_generated_subcategory_persist_and_reuse(ingested_db, fake_llm):
    repo = PersonaRepository(ingested_db)
    prompts = PromptRepository(ingested_db)
    svc = SubcategoryService(repo, prompts, fake_llm)
    topic = "Favourite Ceramic Mug Ritual"
    created = svc.generate_and_store(
        persona_id="sarah_taylor_001",
        category="Preferences",
        topic=topic,
        related_context={"Preferences": [], "canonical_facts": repo.list_canonical_facts("sarah_taylor_001")},
    )
    assert created.get("generated") is True
    assert created.get("generation_prompt_text")
    assert created.get("generation_model")
    again = svc.generate_and_store(
        persona_id="sarah_taylor_001",
        category="Preferences",
        topic=topic,
        related_context={"Preferences": []},
    )
    assert again["subcategory_key"] == created["subcategory_key"]
    matches = [
        s
        for s in repo.list_subcategories("sarah_taylor_001", "Preferences")
        if s.get("subcategory_key") == created["subcategory_key"]
    ]
    assert len(matches) == 1


def test_generated_subcategory_conflict_rejected(ingested_db, fake_llm):
    fake_llm._scripted.mode = "conflict_london"
    repo = PersonaRepository(ingested_db)
    prompts = PromptRepository(ingested_db)
    svc = SubcategoryService(repo, prompts, fake_llm)
    with pytest.raises(SubcategoryConflictError):
        svc.generate_and_store(
            persona_id="sarah_taylor_001",
            category="Preferences",
            topic="Hypothetical Alternate Capital City Residence XYZ",
            related_context={"Preferences": []},
        )
    found = repo.get_subcategory(
        "sarah_taylor_001", "Preferences", "home_city_preference"
    )
    assert found is None
