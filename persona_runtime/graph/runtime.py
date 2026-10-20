"""Reusable LangGraph persona runtime."""

from __future__ import annotations

from typing import Any, Callable, Literal
from uuid import uuid4

from langgraph.graph import END, StateGraph

from persona_runtime.config import Settings, get_settings
from persona_runtime.conversations.context import ConversationContextRepository
from persona_runtime.conversations.repositories import ConversationRepository
from persona_runtime.db import ensure_indexes, get_db
from persona_runtime.graph import nodes as N
from persona_runtime.graph.state import PersonaGraphState
from persona_runtime.llm.client import LLMClient
from persona_runtime.logging_utils import get_logger, log_event, setup_logging
from persona_runtime.memory.consolidation import MemoryConsolidator
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.memory.retrieval import MemoryRetriever
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.persona.subcategory_service import SubcategoryService
from persona_runtime.prompts.registry import PromptRepository
from persona_runtime.relationships.repositories import RelationshipRepository
from persona_runtime.state.repositories import PersonaStateRepository
from persona_runtime.scheduling.jobs import ResponseJobRepository
from persona_runtime.user_context.provider import MinimalUserContextProvider

logger = get_logger(__name__)


def _bind(fn: Callable, svc: N.GraphServices):
    def _node(state: PersonaGraphState) -> dict[str, Any]:
        return fn(state, svc)

    return _node


def _route_after_interpret(state: PersonaGraphState) -> Literal["generate_subcategory", "evaluate"]:
    if state.get("needs_subcategory"):
        return "generate_subcategory"
    return "evaluate"


def _route_after_event(state: PersonaGraphState) -> Literal["hydrate", "seen_end"]:
    if state.get("event_type") == "message_seen":
        return "seen_end"
    return "hydrate"


def build_graph(svc: N.GraphServices):
    graph = StateGraph(PersonaGraphState)
    graph.add_node("event_router", _bind(N.event_router, svc))
    graph.add_node("hydrate_context", _bind(N.hydrate_context, svc))
    graph.add_node("retrieve_memories", _bind(N.retrieve_memories, svc))
    graph.add_node("interpret_turn", _bind(N.interpret_turn, svc))
    graph.add_node("generate_subcategory", _bind(N.maybe_generate_subcategory, svc))
    graph.add_node("evaluate_persona", _bind(N.evaluate_persona, svc))
    graph.add_node("behaviour_decision", _bind(N.behaviour_decision, svc))
    graph.add_node("response_plan", _bind(N.response_plan, svc))
    graph.add_node("evidence_guard", _bind(N.evidence_guard, svc))
    graph.add_node("generate_response", _bind(N.generate_response, svc))
    graph.add_node("recall_claim_check", _bind(N.recall_claim_check, svc))
    graph.add_node("validate_and_repair", _bind(N.validate_and_repair, svc))
    graph.add_node("persist_turn", _bind(N.persist_turn, svc))
    graph.add_node("update_conversation_context", _bind(N.update_conversation_context, svc))
    graph.add_node("extract_memories", _bind(N.extract_memories, svc))
    graph.add_node("consolidate", _bind(N.consolidate_memories, svc))
    graph.add_node("seen_persist", _bind(N.persist_turn, svc))

    graph.set_entry_point("event_router")
    graph.add_conditional_edges(
        "event_router",
        _route_after_event,
        {"hydrate": "hydrate_context", "seen_end": "seen_persist"},
    )
    graph.add_edge("seen_persist", END)
    graph.add_edge("hydrate_context", "retrieve_memories")
    graph.add_edge("retrieve_memories", "interpret_turn")
    graph.add_conditional_edges(
        "interpret_turn",
        _route_after_interpret,
        {"generate_subcategory": "generate_subcategory", "evaluate": "evaluate_persona"},
    )
    graph.add_edge("generate_subcategory", "evaluate_persona")
    graph.add_edge("evaluate_persona", "behaviour_decision")
    graph.add_edge("behaviour_decision", "response_plan")
    graph.add_edge("response_plan", "evidence_guard")
    graph.add_edge("evidence_guard", "generate_response")
    graph.add_edge("generate_response", "recall_claim_check")
    graph.add_edge("recall_claim_check", "validate_and_repair")
    graph.add_edge("validate_and_repair", "persist_turn")
    graph.add_edge("persist_turn", "update_conversation_context")
    graph.add_edge("update_conversation_context", "extract_memories")
    graph.add_edge("extract_memories", "consolidate")
    graph.add_edge("consolidate", END)
    return graph.compile()


class PersonaRuntime:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None, db=None):
        setup_logging()
        self.settings = settings or get_settings()
        self.db = db if db is not None else get_db(self.settings)
        if db is None:
            ensure_indexes(self.db)

        self.persona_repo = PersonaRepository(self.db)
        self.state_repo = PersonaStateRepository(self.db)
        self.relationship_repo = RelationshipRepository(self.db)
        self.conversation_repo = ConversationRepository(self.db)
        self.conversation_context_repo = ConversationContextRepository(self.db)
        self.job_repo = ResponseJobRepository(self.db)
        self.memory_repo = MemoryRepository(self.db)
        self.prompt_repo = PromptRepository(self.db)
        self.prompt_repo.seed()
        self.llm = llm or LLMClient(self.settings)
        self.subcategory_service = SubcategoryService(
            self.persona_repo, self.prompt_repo, self.llm, self.settings
        )
        self.services = N.GraphServices(
            settings=self.settings,
            persona_repo=self.persona_repo,
            state_repo=self.state_repo,
            relationship_repo=self.relationship_repo,
            conversation_repo=self.conversation_repo,
            conversation_context_repo=self.conversation_context_repo,
            memory_retriever=MemoryRetriever(self.memory_repo, self.settings),
            consolidator=MemoryConsolidator(self.memory_repo, self.settings),
            subcategory_service=self.subcategory_service,
            prompt_repo=self.prompt_repo,
            llm=self.llm,
            user_context_provider=MinimalUserContextProvider(),
        )
        self.graph = build_graph(self.services)

    def run(
        self,
        *,
        event_type: str,
        persona_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        incoming_message: str = "",
        user_message_id: str | None = None,
        request_id: str | None = None,
        pending_messages: list[dict[str, Any]] | None = None,
        response_strategy: str | None = None,
        response_job: dict[str, Any] | None = None,
        busy_ack: bool = False,
    ) -> dict[str, Any]:
        persona_id = persona_id or self.settings.default_persona_id
        user_id = user_id or self.settings.default_user_id
        if not conversation_id:
            conv = self.conversation_repo.get_or_create(persona_id, user_id)
            conversation_id = conv["conversation_id"]

        request_id = request_id or str(uuid4())
        pending = list(pending_messages or [])
        if not incoming_message and pending:
            incoming_message = "\n".join(m.get("content") or "" for m in pending)

        initial: PersonaGraphState = {
            "persona_id": persona_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "event_type": event_type,  # type: ignore[typeddict-item]
            "incoming_message": incoming_message,
            "pending_messages": pending,
            "response_strategy": response_strategy or "",
            "response_job": response_job or {},
            "busy_ack": busy_ack,
            "recent_messages": [],
            "user_context": {},
            "canonical_context": {},
            "selected_context": {},
            "conversation_context": {},
            "understanding": {},
            "retrieved_memories": [],
            "allowed_evidence_ids": [],
            "relationship_state": {},
            "persona_state": {},
            "active_goals": [],
            "active_fears": [],
            "relevant_boundaries": [],
            "topic": "",
            "intent": "",
            "user_emotion": "",
            "needs_subcategory": False,
            "subcategory_category": None,
            "subcategory_topic": None,
            "keywords": [],
            "generated_subcategory": None,
            "behaviour_plan": {},
            "response_plan": {},
            "disclose_fact_ids": [],
            "suppressed_fact_ids": [],
            "generated_response": "",
            "generated_messages": [],
            "validation": {},
            "validation_feedback": [],
            "validation_attempts": 0,
            "memory_candidates": [],
            "state_updates": {},
            "relationship_updates": {},
            "errors": [],
            "request_id": request_id,
            "skip_response": False,
            "user_message_id": user_message_id,
            "assistant_message_id": None,
            "assistant_message_ids": [],
            "stored_memories": [],
            "all_canonical_facts": [],
        }
        log_event(
            logger,
            "runtime_invoke",
            request_id=request_id,
            persona_id=persona_id,
            user_id=user_id,
            conversation_id=conversation_id,
            event_type=event_type,
            response_strategy=response_strategy,
            pending_count=len(pending),
        )
        result = self.graph.invoke(initial)
        return result
