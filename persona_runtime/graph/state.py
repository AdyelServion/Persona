"""LangGraph typed state."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class PersonaGraphState(TypedDict, total=False):
    persona_id: str
    user_id: str
    conversation_id: str
    event_type: Literal["user_message", "conversation_start", "message_seen"]
    incoming_message: str
    pending_messages: list[dict[str, Any]]
    response_strategy: str
    response_job: dict[str, Any]
    busy_ack: bool
    recent_messages: list[dict[str, Any]]
    user_context: dict[str, Any]
    canonical_context: dict[str, Any]
    selected_context: dict[str, Any]
    conversation_context: dict[str, Any]
    understanding: dict[str, Any]
    retrieved_memories: list[dict[str, Any]]
    allowed_evidence_ids: list[str]
    relationship_state: dict[str, Any]
    persona_state: dict[str, Any]
    active_goals: list[str]
    active_fears: list[str]
    relevant_boundaries: list[dict[str, Any]]
    topic: str
    intent: str
    user_emotion: str
    needs_subcategory: bool
    subcategory_category: str | None
    subcategory_topic: str | None
    keywords: list[str]
    generated_subcategory: dict[str, Any] | None
    behaviour_plan: dict[str, Any]
    engagement_brief: dict[str, Any]
    response_plan: dict[str, Any]
    disclose_fact_ids: list[str]
    suppressed_fact_ids: list[str]
    generated_response: str
    generated_messages: list[dict[str, Any]]
    validation: dict[str, Any]
    validation_feedback: list[str]
    validation_attempts: int
    memory_candidates: list[dict[str, Any]]
    state_updates: dict[str, Any]
    relationship_updates: dict[str, float]
    errors: list[str]
    request_id: str
    skip_response: bool
    user_message_id: str | None
    assistant_message_id: str | None
    assistant_message_ids: list[str]
    stored_memories: list[dict[str, Any]]
    all_canonical_facts: list[dict[str, Any]]
    clock_snapshot: dict[str, Any]
    timeline_transitions: list[dict[str, Any]]
    state_version: int
