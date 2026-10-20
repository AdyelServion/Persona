"""Memory persistence, retrieval, and no-fabrication tests."""

from __future__ import annotations

from persona_runtime.graph.evidence import FALLBACK_NO_MEMORY
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.memory.retrieval import MemoryRetriever


def test_interview_memory_persists_and_retrieves(runtime):
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", "local-user")
    cid = conv["conversation_id"]

    user_msg = runtime.conversation_repo.add_message(
        conversation_id=cid, sender="user", content="My interview is tomorrow."
    )
    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id="local-user",
        conversation_id=cid,
        incoming_message="My interview is tomorrow.",
        user_message_id=user_msg["message_id"],
    )
    assert result.get("generated_response")
    stored = result.get("stored_memories") or []
    assert any(m.get("type") == "episodic" or m.get("event_description") for m in stored)

    # New runtime instance simulating next day / new process
    from persona_runtime.config import get_settings
    from persona_runtime.graph.runtime import PersonaRuntime

    runtime2 = PersonaRuntime(settings=get_settings(), llm=runtime.llm, db=runtime.db)
    retriever = MemoryRetriever(runtime2.memory_repo)
    found = retriever.retrieve(
        persona_id="sarah_taylor_001",
        user_id="local-user",
        query="Hey Sarah.",
    )
    assert any("interview" in (m.get("event_description") or m.get("fact") or "").lower() for m in found)

    result2 = runtime2.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id="local-user",
        conversation_id=cid,
        incoming_message="Hey Sarah.",
        user_message_id=runtime.conversation_repo.add_message(
            conversation_id=cid, sender="user", content="Hey Sarah."
        )["message_id"],
    )
    reply = (result2.get("generated_response") or "").lower()
    assert "interview" in reply


def test_no_memory_fabrication(runtime):
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", "user-no-mem")
    cid = conv["conversation_id"]
    user_msg = runtime.conversation_repo.add_message(
        conversation_id=cid, sender="user", content="Do you remember my trip?"
    )
    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id="user-no-mem",
        conversation_id=cid,
        incoming_message="Do you remember my trip?",
        user_message_id=user_msg["message_id"],
    )
    reply = result.get("generated_response") or ""
    assert "spain" not in reply.lower()
    assert (
        "don't think I have that detail" in reply.lower()
        or reply == FALLBACK_NO_MEMORY
        or "tell me again" in reply.lower()
    )


def test_memory_retrieval_failure_does_not_fabricate(runtime, monkeypatch):
    from persona_runtime.exceptions import MemoryRetrievalError

    def boom(*args, **kwargs):
        raise MemoryRetrievalError("forced failure")

    monkeypatch.setattr(runtime.services.memory_retriever, "retrieve", boom)
    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", "user-fail")
    cid = conv["conversation_id"]
    user_msg = runtime.conversation_repo.add_message(
        conversation_id=cid, sender="user", content="Do you remember my trip to Spain?"
    )
    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id="user-fail",
        conversation_id=cid,
        incoming_message="Do you remember my trip to Spain?",
        user_message_id=user_msg["message_id"],
    )
    reply = (result.get("generated_response") or "").lower()
    assert "spain" not in reply or "don't think" in reply
    assert result.get("allowed_evidence_ids") == []


def test_semantic_correction(runtime):
    repo = MemoryRepository(runtime.db)
    from persona_runtime.memory.consolidation import MemoryConsolidator
    from persona_runtime.memory.schemas import MemoryCandidate

    consolidator = MemoryConsolidator(repo)
    consolidator.consolidate(
        persona_id="sarah_taylor_001",
        user_id="local-user",
        conversation_id="c1",
        candidates=[
            MemoryCandidate(
                memory_type="semantic",
                importance=0.8,
                confidence=0.8,
                subject="user",
                predicate="works_at",
                object="Company A",
                fact="User works at Company A",
                source_message_ids=["m1"],
            )
        ],
    )
    consolidator.consolidate(
        persona_id="sarah_taylor_001",
        user_id="local-user",
        conversation_id="c1",
        candidates=[
            MemoryCandidate(
                memory_type="semantic",
                importance=0.85,
                confidence=0.9,
                subject="user",
                predicate="works_at",
                object="Company B",
                fact="User moved to Company B",
                is_correction=True,
                source_message_ids=["m2"],
            )
        ],
    )
    active = repo.find_semantic_fact(
        "sarah_taylor_001", "user", "user", "works_at", user_id="local-user"
    )
    assert active is not None
    assert active["object"] == "Company B"
    superseded = list(
        repo.collection_for("semantic").find(
            {"persona_id": "sarah_taylor_001", "status": "superseded"}
        )
    )
    assert superseded
