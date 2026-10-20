"""Persisted ConversationContext — separate from persona Identity and user memories."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow


def empty_conversation_context(
    *,
    conversation_id: str,
    persona_id: str,
    user_id: str,
) -> dict[str, Any]:
    from persona_runtime.conversation.topics import default_style_profile

    now = utcnow()
    return {
        "context_id": str(uuid4()),
        "conversation_id": conversation_id,
        "persona_id": persona_id,
        "user_id": user_id,
        "current_topic": "",
        "previous_topics": [],
        "conversation_stage": "opening",
        "conversation_goal": "build_rapport",
        "last_user_message": "",
        "last_sarah_message": "",
        "facts_shared_by_sarah": [],
        "user_facts_this_conversation": [],
        "questions_asked": [],
        "questions_answered": [],
        "unresolved_questions": [],
        "topics_discussed": [],
        "unresolved_topics": [],
        "open_threads": [],
        "declined_topics": [],
        "last_transition": "",
        "style_profile": default_style_profile(),
        "proactive_opt_out": False,
        "last_proactive_at": None,
        "proactive_count_today": 0,
        "proactive_day_key": "",
        "recent_turns": [],
        "recent_summary": "",
        "user_intent": "",
        "user_emotion": "",
        "speech_act": "",
        "response_history": [],
        "recent_moves": [],
        "last_question_target": None,
        "last_world_snapshot": {},
        "last_answer_slots": [],
        "open_experience_id": None,
        "created_at": now,
        "updated_at": now,
    }


class ConversationContextRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["conversation_contexts"]]

    def get_or_create(
        self,
        *,
        conversation_id: str,
        persona_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        existing = self.col.find_one({"conversation_id": conversation_id})
        if existing:
            return existing
        doc = empty_conversation_context(
            conversation_id=conversation_id,
            persona_id=persona_id,
            user_id=user_id,
        )
        self.col.insert_one(doc)
        return doc

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"conversation_id": conversation_id})

    def update(self, conversation_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        updates = {**updates, "updated_at": utcnow()}
        self.col.update_one({"conversation_id": conversation_id}, {"$set": updates})
        doc = self.col.find_one({"conversation_id": conversation_id})
        if not doc:
            raise KeyError(f"ConversationContext missing for {conversation_id}")
        return doc

    def apply_turn_update(
        self,
        *,
        conversation_id: str,
        persona_id: str,
        user_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        self.get_or_create(
            conversation_id=conversation_id,
            persona_id=persona_id,
            user_id=user_id,
        )
        return self.update(conversation_id, updates)
