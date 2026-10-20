#!/usr/bin/env python
"""Smoke: memory persist + retrieve on live Mongo using fake LLM (no OpenAI spend)."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from persona_runtime.config import get_settings
from persona_runtime.db import ensure_indexes, get_db, reset_client
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.llm.client import LLMClient
from persona_runtime.memory.retrieval import MemoryRetriever


def fake_handler(*, system: str, user: str):
    sys_l = system.lower()
    user_l = user.lower()
    if "memory candidates" in sys_l or "extract memory" in sys_l:
        return {
            "candidates": [
                {
                    "memory_type": "episodic",
                    "importance": 0.9,
                    "confidence": 0.9,
                    "event_description": "User said their interview is tomorrow",
                    "source_message_ids": [],
                    "is_correction": False,
                }
            ]
        }
    if "behaviour decision" in sys_l:
        return {
            "primary_action": "engage",
            "secondary_action": "listen",
            "avoid": [],
            "warmth": 0.6,
            "depth": 0.5,
            "ask_question": True,
            "disclosure_level": 0.2,
            "notes": "smoke",
        }
    if "plan sarah" in sys_l or "memory_claims" in sys_l:
        return {
            "talking_points": ["respond"],
            "tone": "warm",
            "memory_claims": [],
            "must_not_claim": [],
            "length": "short",
        }
    if "analyze a user message" in sys_l:
        return {
            "topic": "chat",
            "intent": "chat",
            "user_emotion": "neutral",
            "needs_subcategory": False,
            "subcategory_category": None,
            "subcategory_topic": None,
            "keywords": ["hey"],
        }
    if "remember my trip" in user_l:
        return {"reply": "Yes, I remember you went to Spain."}
    if "interview is tomorrow" in user_l.split("=== user_message")[-1]:
        return {"reply": "Good luck with the interview."}
    if "hey" in user_l.split("=== user_message")[-1] and "interview" in user_l:
        return {"reply": "Hey — how did the interview go?"}
    if "invent memories" in sys_l or "rewrite" in sys_l:
        return {"reply": "I don't think I have that detail from our previous conversations. Tell me again?"}
    return {"reply": "Hey."}


def main() -> int:
    reset_client()
    settings = get_settings()
    db = get_db(settings)
    ensure_indexes(db)
    llm = LLMClient(settings)
    llm.set_fake_handler(fake_handler)
    user_id = f"smoke-{uuid4().hex[:8]}"
    runtime = PersonaRuntime(settings=settings, llm=llm, db=db)
    conv = runtime.conversation_repo.get_or_create(settings.default_persona_id, user_id)
    cid = conv["conversation_id"]

    msg = runtime.conversation_repo.add_message(
        conversation_id=cid, sender="user", content="My interview is tomorrow."
    )
    r1 = runtime.run(
        event_type="user_message",
        persona_id=settings.default_persona_id,
        user_id=user_id,
        conversation_id=cid,
        incoming_message="My interview is tomorrow.",
        user_message_id=msg["message_id"],
    )
    assert r1.get("stored_memories"), "expected stored memories"
    print("stored_memories", len(r1["stored_memories"]))

    # New runtime instance = new process simulation
    runtime2 = PersonaRuntime(settings=settings, llm=llm, db=db)
    found = MemoryRetriever(runtime2.memory_repo).retrieve(
        persona_id=settings.default_persona_id,
        user_id=user_id,
        query="Hey Sarah.",
    )
    assert any("interview" in (m.get("event_description") or "").lower() for m in found)
    print("retrieved_interview", True)

    msg2 = runtime2.conversation_repo.add_message(
        conversation_id=cid, sender="user", content="Hey Sarah."
    )
    r2 = runtime2.run(
        event_type="user_message",
        persona_id=settings.default_persona_id,
        user_id=user_id,
        conversation_id=cid,
        incoming_message="Hey Sarah.",
        user_message_id=msg2["message_id"],
    )
    assert "interview" in (r2.get("generated_response") or "").lower()
    print("followup_reply", r2.get("generated_response"))

    # No fabrication
    user_b = f"smoke-empty-{uuid4().hex[:8]}"
    conv_b = runtime2.conversation_repo.get_or_create(settings.default_persona_id, user_b)
    msg3 = runtime2.conversation_repo.add_message(
        conversation_id=conv_b["conversation_id"],
        sender="user",
        content="Do you remember my trip?",
    )
    r3 = runtime2.run(
        event_type="user_message",
        persona_id=settings.default_persona_id,
        user_id=user_b,
        conversation_id=conv_b["conversation_id"],
        incoming_message="Do you remember my trip?",
        user_message_id=msg3["message_id"],
    )
    reply3 = (r3.get("generated_response") or "").lower()
    assert "spain" not in reply3
    assert "don't think" in reply3 or "tell me again" in reply3
    print("no_fabrication_ok", True)
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
