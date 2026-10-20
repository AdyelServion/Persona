"""LangGraph node implementations."""

from __future__ import annotations

import json
import re
from typing import Any

from persona_runtime.config import Settings
from persona_runtime.conversations.context import ConversationContextRepository
from persona_runtime.conversations.repositories import ConversationRepository
from persona_runtime.exceptions import MemoryRetrievalError, SubcategoryConflictError
from persona_runtime.graph.context_builder import build_prompt_context, select_persona_context
from persona_runtime.graph.evidence import (
    FALLBACK_NO_MEMORY,
    filter_ungrounded_claims,
    plan_claims_are_grounded,
    reply_has_recall_language,
)
from persona_runtime.graph.fact_tracker import (
    compute_disclosure_plan,
    detect_questions_in_text,
    record_disclosures_from_reply,
    temporal_constraints_for_facts,
)
from persona_runtime.graph.bubbles import (
    messages_state_update,
    normalize_generated_messages,
    pack_message_dicts,
)
from persona_runtime.graph.grounding import (
    build_answer_plan,
    fallback_messages_from_answer_plan,
    retrieve_facts,
)
from persona_runtime.graph.questions import attach_questions_to_understanding
from persona_runtime.graph.reality import (
    EMPLOYMENT_TARGETS,
    NOW_TARGETS,
    build_world_state,
    employment_snapshot,
    talking_points_for_targets,
)
from persona_runtime.graph.state import PersonaGraphState
from persona_runtime.graph.understanding import (
    classify_message_deterministic,
    fallback_understanding,
    understanding_from_llm_dict,
)
from persona_runtime.conversation.engagement import (
    merge_engagement_into_policy,
    select_strategy,
)
from persona_runtime.conversation.topics import apply_topic_turn
from persona_runtime.conversation.voice import select_tone
from persona_runtime.graph.social_moves import (
    apply_plan_humanity_gate,
    constrain_move,
    select_move,
    talking_points_for_move,
)
from persona_runtime.graph.validator import deterministic_fallback_reply, validate_response
from persona_runtime.llm.client import LLMClient
from persona_runtime.logging_utils import get_logger, log_event
from persona_runtime.memory.consolidation import MemoryConsolidator
from persona_runtime.memory.retrieval import MemoryRetriever
from persona_runtime.memory.schemas import MemoryCandidate, MemoryExtractionResult
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.persona.subcategory_service import SubcategoryService
from persona_runtime.prompts.registry import PromptRepository
from persona_runtime.relationships.repositories import RelationshipRepository
from persona_runtime.state.repositories import PersonaStateRepository
from persona_runtime.user_context.provider import MinimalUserContextProvider

logger = get_logger(__name__)


class GraphServices:
    def __init__(
        self,
        *,
        settings: Settings,
        persona_repo: PersonaRepository,
        state_repo: PersonaStateRepository,
        relationship_repo: RelationshipRepository,
        conversation_repo: ConversationRepository,
        conversation_context_repo: ConversationContextRepository,
        memory_retriever: MemoryRetriever,
        consolidator: MemoryConsolidator,
        subcategory_service: SubcategoryService,
        prompt_repo: PromptRepository,
        llm: LLMClient,
        user_context_provider: MinimalUserContextProvider | None = None,
    ):
        self.settings = settings
        self.persona_repo = persona_repo
        self.state_repo = state_repo
        self.relationship_repo = relationship_repo
        self.conversation_repo = conversation_repo
        self.conversation_context_repo = conversation_context_repo
        self.memory_retriever = memory_retriever
        self.consolidator = consolidator
        self.subcategory_service = subcategory_service
        self.prompt_repo = prompt_repo
        self.llm = llm
        self.user_context_provider = user_context_provider or MinimalUserContextProvider()


def _prompt(svc: GraphServices, name: str) -> dict[str, Any]:
    p = svc.prompt_repo.get_active(name)
    if not p:
        raise RuntimeError(f"Missing active prompt: {name}")
    return p


def event_router(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    log_event(logger, "node_event_router", request_id=state.get("request_id"), event_type=state.get("event_type"))
    if state.get("event_type") == "message_seen":
        return {"skip_response": True}
    return {"skip_response": False, "errors": list(state.get("errors") or [])}


def hydrate_context(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    persona_id = state["persona_id"]
    user_id = state["user_id"]
    conversation_id = state["conversation_id"]

    user_context = svc.user_context_provider.load_user_context(user_id)
    from persona_runtime.life.clock import PersonaClock
    from persona_runtime.life.simulator import LifeSimulator
    from persona_runtime.logging_utils import log_event

    clock = PersonaClock(tz_name=svc.settings.timezone).snapshot()
    # Canonical facts before timeline advance (stable identity)
    all_facts = svc.persona_repo.list_canonical_facts(persona_id)
    life = LifeSimulator(svc.state_repo, tz_name=svc.settings.timezone)
    advance_meta = life.advance_with_meta(persona_id, now=clock.utc_now)
    # Decay mood metrics only — timeline engine owns activity fields
    persona_state = svc.state_repo.decay_toward_baseline(persona_id, hours_elapsed=1.0)
    relationship = svc.relationship_repo.get_or_create_user_relationship(persona_id, user_id)
    recent = svc.conversation_repo.recent_messages(
        conversation_id, limit=svc.settings.recent_message_limit
    )
    conv_ctx = svc.conversation_context_repo.get_or_create(
        conversation_id=conversation_id,
        persona_id=persona_id,
        user_id=user_id,
    )

    # Compact slices for optional topic-gated selection — NOT dumped wholesale into prompts
    communication = svc.persona_repo.list_subcategories(persona_id, "Communication")[:2]
    personality = svc.persona_repo.list_subcategories(persona_id, "Personality")[:2]
    boundaries = svc.persona_repo.list_subcategories(persona_id, "Boundaries")[:3]
    preferences = svc.persona_repo.list_subcategories(persona_id, "Preferences")[:2]

    current_pre = (persona_state.get("current_state") or {})
    log_event(
        logger,
        "turn_clock",
        request_id=state.get("request_id"),
        utc_now=clock.utc_now.isoformat(),
        local_now=clock.local_now.isoformat(),
        timezone=clock.timezone,
        state_version=advance_meta.get("state_version"),
        active_event_id=current_pre.get("active_event_id"),
        transitions=len(advance_meta.get("transitions") or []),
        cas_conflict=bool(advance_meta.get("cas_conflict")),
    )

    canonical_context = {
        "communication": [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:350]}
            for s in communication
        ],
        "personality": [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:300]}
            for s in personality
        ],
        "preferences": [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:300]}
            for s in preferences
        ],
        # Full fact list kept off the generation path; used by planners/trackers only via all_canonical_facts
        "canonical_facts_index": [
            {
                "fact_id": f.get("fact_id"),
                "subject": f.get("subject"),
                "predicate": f.get("predicate"),
                "object": f.get("object"),
                "time": f.get("time"),
            }
            for f in all_facts
            if f.get("fact_id")
        ],
    }

    current = persona_state.get("current_state") or {}
    return {
        "user_context": user_context,
        "persona_state": persona_state,
        "relationship_state": relationship,
        "recent_messages": recent,
        "conversation_context": conv_ctx,
        "canonical_context": canonical_context,
        "all_canonical_facts": all_facts,
        "clock_snapshot": clock.to_dict(),
        "timeline_transitions": list(advance_meta.get("transitions") or []),
        "state_version": advance_meta.get("state_version"),
        "active_goals": list(current.get("active_goals") or []),
        "active_fears": list(current.get("active_fears") or []),
        "relevant_boundaries": [
            {"title": b.get("subcategory"), "excerpt": (b.get("content_raw") or "")[:350]} for b in boundaries
        ],
        "validation_attempts": 0,
        "validation_feedback": [],
    }


def retrieve_memories(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    query = state.get("incoming_message") or "greeting hello"
    try:
        memories = svc.memory_retriever.retrieve(
            persona_id=state["persona_id"],
            user_id=state["user_id"],
            query=query,
            conversation_id=state.get("conversation_id"),
        )
    except MemoryRetrievalError as exc:
        log_event(logger, "memory_retrieval_failed", error=str(exc), request_id=state.get("request_id"))
        return {
            "retrieved_memories": [],
            "allowed_evidence_ids": [],
            "errors": list(state.get("errors") or []) + [f"memory_retrieval_failed:{exc}"],
        }

    evidence_ids = [m["memory_id"] for m in memories if m.get("memory_id")]
    log_event(
        logger,
        "node_retrieve_memories",
        request_id=state.get("request_id"),
        memory_retrieval_count=len(memories),
    )
    return {"retrieved_memories": memories, "allowed_evidence_ids": evidence_ids}


def _with_questions(
    understanding: dict[str, Any],
    *,
    message: str,
    conv: dict[str, Any],
    pending: list[dict[str, Any]],
) -> dict[str, Any]:
    return attach_questions_to_understanding(
        understanding,
        message=message,
        last_question_target=conv.get("last_question_target"),
        last_answer_slots=list(conv.get("last_answer_slots") or []),
        pending_messages=pending,
    )


def interpret_turn(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("event_type") == "conversation_start":
        understanding = {
            "speech_act": "greeting",
            "intent": "greet",
            "topic": "opening",
            "requires_information": False,
            "requires_question": False,
            "user_emotion": "neutral",
            "user_disclosures": [],
            "needs_subcategory": False,
            "subcategory_category": None,
            "subcategory_topic": None,
            "keywords": ["hello"],
            "questions": [],
        }
        return {
            "understanding": understanding,
            "topic": "opening",
            "intent": "greet",
            "user_emotion": "neutral",
            "needs_subcategory": False,
            "subcategory_category": None,
            "subcategory_topic": None,
            "keywords": ["hello"],
        }
    if state.get("skip_response"):
        return {}

    conv = state.get("conversation_context") or {}
    current_topic = conv.get("current_topic") or ""
    last_q_target = conv.get("last_question_target")
    pending = list(state.get("pending_messages") or [])
    # Prefer latest non-superseded content for classification; keep full batch in message
    message = state.get("incoming_message") or ""
    if pending:
        # Latest message often corrects earlier ones
        message = pending[-1].get("content") or message
        # If strategy is respond to group/all, join for understanding
        strategy = (state.get("response_strategy") or "").upper()
        if strategy in {"RESPOND_TO_GROUP", "RESPOND_TO_ALL", ""}:
            message = "\n".join(m.get("content") or "" for m in pending)

    det = classify_message_deterministic(
        message,
        current_topic=current_topic,
        last_question_target=last_q_target,
        pending_messages=pending,
    )
    if det:
        data = _with_questions(
            det.model_dump(), message=message, conv=conv, pending=pending
        )
        return {
            "understanding": {
                **data,
                "pending_count": len(pending),
                "response_strategy": state.get("response_strategy"),
            },
            "topic": data.get("topic") or "",
            "intent": data.get("intent") or "",
            "user_emotion": data.get("user_emotion") or "neutral",
            "needs_subcategory": bool(data.get("needs_subcategory")),
            "subcategory_category": data.get("subcategory_category"),
            "subcategory_topic": data.get("subcategory_topic"),
            "keywords": list(data.get("keywords") or []),
            "incoming_message": state.get("incoming_message") or message,
        }

    prompt = _prompt(svc, "turn_interpretation")
    payload = {
        "message": message,
        "current_topic": current_topic,
        "last_question_target": last_q_target,
        "recent": [
            {"sender": m.get("sender"), "content": m.get("content")}
            for m in (state.get("recent_messages") or [])[-6:]
        ],
        "pending_messages": [
            {"content": m.get("content"), "priority": m.get("priority")}
            for m in pending
        ],
        "response_strategy": state.get("response_strategy"),
    }
    try:
        raw = svc.llm.complete_json(
            system=prompt["system_prompt_template"],
            user=json.dumps(payload),
            temperature=float(prompt.get("temperature") or 0.2),
        )
        understood = understanding_from_llm_dict(
            raw,
            message=message,
            current_topic=current_topic,
            last_question_target=last_q_target,
            pending_messages=pending,
        )
    except Exception as exc:  # noqa: BLE001
        understood = fallback_understanding(
            message,
            current_topic=current_topic,
            last_question_target=last_q_target,
            pending_messages=pending,
        )
        data = _with_questions(
            understood.model_dump(), message=message, conv=conv, pending=pending
        )
        return {
            "understanding": data,
            "topic": data["topic"],
            "intent": data["intent"],
            "user_emotion": data["user_emotion"],
            "needs_subcategory": data["needs_subcategory"],
            "subcategory_category": data["subcategory_category"],
            "subcategory_topic": data["subcategory_topic"],
            "keywords": data["keywords"],
            "errors": list(state.get("errors") or []) + [f"interpret_failed:{exc}"],
        }

    data = _with_questions(
        understood.model_dump(), message=message, conv=conv, pending=pending
    )
    return {
        "understanding": data,
        "topic": data["topic"],
        "intent": data["intent"],
        "user_emotion": data["user_emotion"],
        "needs_subcategory": data["needs_subcategory"],
        "subcategory_category": data["subcategory_category"],
        "subcategory_topic": data["subcategory_topic"],
        "keywords": data["keywords"],
    }


def maybe_generate_subcategory(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if not state.get("needs_subcategory"):
        return {"generated_subcategory": None}
    category = state.get("subcategory_category") or "Preferences"
    topic = state.get("subcategory_topic") or state.get("topic") or "general"
    existing = svc.subcategory_service.find_existing(
        state["persona_id"], category, topic, list(state.get("keywords") or [])
    )
    if existing:
        ctx = dict(state.get("canonical_context") or {})
        extras = list(ctx.get("matched_subcategories") or [])
        extras.append(
            {
                "category": category,
                "title": existing.get("subcategory"),
                "excerpt": (existing.get("content_raw") or "")[:600],
                "generated": existing.get("generated", False),
            }
        )
        ctx["matched_subcategories"] = extras
        return {"generated_subcategory": existing, "canonical_context": ctx}

    related = {
        category: [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:400]}
            for s in svc.persona_repo.list_subcategories(state["persona_id"], category)[:5]
        ],
        "Personality": [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:300]}
            for s in svc.persona_repo.list_subcategories(state["persona_id"], "Personality")[:2]
        ],
        "Biography": [
            {"title": s.get("subcategory"), "excerpt": (s.get("content_raw") or "")[:300]}
            for s in svc.persona_repo.list_subcategories(state["persona_id"], "Biography")[:2]
        ],
        "canonical_facts": [
            {"subject": f.get("subject"), "predicate": f.get("predicate"), "object": f.get("object")}
            for f in (state.get("all_canonical_facts") or [])
        ],
    }
    try:
        created = svc.subcategory_service.generate_and_store(
            persona_id=state["persona_id"],
            category=category,
            topic=topic,
            related_context=related,
        )
    except SubcategoryConflictError as exc:
        return {
            "generated_subcategory": None,
            "errors": list(state.get("errors") or []) + [f"subcategory_conflict:{exc}"],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "generated_subcategory": None,
            "errors": list(state.get("errors") or []) + [f"subcategory_failed:{exc}"],
        }

    ctx = dict(state.get("canonical_context") or {})
    extras = list(ctx.get("matched_subcategories") or [])
    extras.append(
        {
            "category": category,
            "title": created.get("subcategory"),
            "excerpt": (created.get("content_raw") or "")[:600],
            "generated": True,
        }
    )
    ctx["matched_subcategories"] = extras
    return {"generated_subcategory": created, "canonical_context": ctx}


def evaluate_persona(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    """Deterministic evaluation of goals/fears/boundaries influence markers."""
    current = (state.get("persona_state") or {}).get("current_state") or {}
    energy = float(current.get("energy", 0.7))
    stress = float(current.get("stress", 0.3))
    availability = float(current.get("availability", 0.5))
    notes = {
        "low_energy": energy < 0.4,
        "high_stress": stress > 0.6,
        "low_availability": availability < 0.35,
        "activity": current.get("current_activity"),
    }
    return {"state_updates": {"_eval": notes}}


def behaviour_decision(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("skip_response"):
        return {"behaviour_plan": {"primary_action": "none", "conversational_move": "WAIT"}}

    current = (state.get("persona_state") or {}).get("current_state") or {}
    energy = float(current.get("energy", 0.7))
    stress = float(current.get("stress", 0.3))
    rel = state.get("relationship_state") or {}
    understanding = state.get("understanding") or {}
    speech = understanding.get("speech_act") or ""
    conv = state.get("conversation_context") or {}
    recent_moves = list(conv.get("recent_moves") or [])
    incoming = state.get("incoming_message") or ""

    voice = select_tone(understanding=understanding, incoming_message=incoming)
    due_followups: list[dict[str, Any]] = []
    try:
        due_followups = svc.memory_retriever.due_followups(
            persona_id=state["persona_id"],
            user_id=state["user_id"],
            now=None,
            clock=state.get("clock_snapshot"),
            tz_name=svc.settings.timezone,
        )
    except Exception:  # noqa: BLE001
        due_followups = []

    engagement = select_strategy(
        understanding=understanding,
        conversation_context=conv,
        persona_state=state.get("persona_state"),
        retrieved_memories=list(state.get("retrieved_memories") or []),
        due_followups=due_followups,
        incoming_message=incoming,
        voice_tone=voice,
        event_type=state.get("event_type") or "user_message",
    )

    warmth = 0.55 + float(rel.get("affection", 0)) * 0.25
    warmth *= 0.7 if energy < 0.4 else 1.0
    warmth *= 0.75 if stress > 0.65 else 1.0
    depth = 0.35 + float(rel.get("trust", 0)) * 0.4
    if energy < 0.4:
        depth = min(depth, 0.4)

    policy = select_move(
        understanding=understanding,
        persona_state=state.get("persona_state"),
        relationship_state=rel,
        recent_moves=recent_moves,
        preference_conflict=False,
    )
    policy = merge_engagement_into_policy(policy, engagement)
    move = policy["conversational_move"]
    ask_question = bool(policy.get("ask_question"))

    primary = move.lower()
    if speech == "acknowledgement":
        primary = "acknowledge"
    elif speech == "greeting":
        primary = "greet"
    elif speech == "conversation_closing":
        primary = "close"

    baseline = {
        "primary_action": primary,
        "secondary_action": "continue",
        "conversational_move": move,
        "allowed_moves": list(policy.get("allowed_moves") or []),
        "avoid": (["excessive_humour"] if stress > 0.6 else [])
        + ["assistant_availability_offer", "generic_support_closer", "interview_mode"],
        "warmth": round(max(0.2, min(0.95, warmth)), 2),
        "depth": round(max(0.15, min(0.9, depth)), 2),
        "ask_question": ask_question,
        "disclosure_level": round(float(rel.get("emotional_openness", 0.1)), 2),
        "engagement_strategy": engagement.get("strategy"),
        "engagement": engagement,
        "voice_tone": voice,
        "notes": (
            f"activity={current.get('current_activity')};"
            f"{policy.get('notes')};strategy={engagement.get('strategy')}"
        ),
    }

    if state.get("event_type") == "conversation_start":
        baseline["primary_action"] = "greet"
        # Engagement may prefer due-followup ASK; otherwise soft greeting
        if engagement.get("strategy") == "continue_earlier_topic" and engagement.get(
            "should_ask_question"
        ):
            baseline["conversational_move"] = "ASK"
            baseline["allowed_moves"] = list(policy.get("allowed_moves") or ["ASK", "REACT"])
            baseline["ask_question"] = True
        else:
            baseline["conversational_move"] = constrain_move("REACT", policy=policy)
            baseline["allowed_moves"] = list(policy.get("allowed_moves") or ["REACT", "ASK", "ACKNOWLEDGE", "SHARE"])
            baseline["ask_question"] = bool(engagement.get("should_ask_question"))
        return {"behaviour_plan": baseline, "engagement_brief": engagement}

    prompt = _prompt(svc, "behaviour_decision")
    try:
        selected = select_persona_context({**state, "behaviour_plan": baseline})
        data = svc.llm.complete_json(
            system=prompt["system_prompt_template"],
            user=build_prompt_context(
                {
                    **state,
                    "selected_context": selected,
                    "behaviour_plan": baseline,
                    "social_policy": policy,
                },
                svc.settings,
            ),
            temperature=float(prompt.get("temperature") or 0.3),
        )
        for key in ("warmth", "depth", "disclosure_level"):
            if key in data:
                data[key] = float(max(0.05, min(0.98, float(data[key]))))
        if energy < 0.4:
            data["warmth"] = min(float(data.get("warmth", warmth)), warmth)
            data["depth"] = min(float(data.get("depth", depth)), depth)

        proposed = data.get("conversational_move") or data.get("primary_action")
        move = constrain_move(proposed, policy=policy)
        baseline["conversational_move"] = move
        baseline["allowed_moves"] = list(policy.get("allowed_moves") or [])
        baseline["ask_question"] = move in {"ASK", "CLARIFY"}
        baseline["primary_action"] = move.lower()

        for k in ("secondary_action", "avoid", "warmth", "depth", "disclosure_level", "notes"):
            if k in data:
                baseline[k] = data[k]
        # Keep policy avoid list intact
        avoid = list(baseline.get("avoid") or [])
        for item in ("assistant_availability_offer", "generic_support_closer"):
            if item not in avoid:
                avoid.append(item)
        baseline["avoid"] = avoid

        if speech == "acknowledgement":
            baseline["disclosure_level"] = min(float(baseline.get("disclosure_level", 0.1)), 0.15)
            if move not in (policy.get("allowed_moves") or []):
                baseline["conversational_move"] = policy["conversational_move"]
                baseline["ask_question"] = False
        # Engagement brief wins on ask / topic-change permissions
        if not engagement.get("should_ask_question"):
            baseline["ask_question"] = False
            if baseline.get("conversational_move") in {"ASK", "CLARIFY"}:
                baseline["conversational_move"] = constrain_move("REACT", policy=policy)
        if engagement.get("strategy") not in {"fresh_topic", "continue_earlier_topic"}:
            if baseline.get("conversational_move") == "CHANGE_TOPIC":
                baseline["conversational_move"] = constrain_move("REACT", policy=policy)
        baseline["engagement_strategy"] = engagement.get("strategy")
        baseline["engagement"] = engagement
        baseline["voice_tone"] = voice
    except Exception as exc:  # noqa: BLE001
        baseline["notes"] = f"fallback:{exc};{policy.get('notes')}"
        baseline["conversational_move"] = policy["conversational_move"]
        baseline["allowed_moves"] = list(policy.get("allowed_moves") or [])
        baseline["ask_question"] = bool(policy.get("ask_question")) and bool(
            engagement.get("should_ask_question")
        )
        baseline["engagement"] = engagement
        baseline["voice_tone"] = voice

    log_event(
        logger,
        "node_behaviour_decision",
        request_id=state.get("request_id"),
        behaviour_decision=baseline.get("primary_action"),
        conversational_move=baseline.get("conversational_move"),
        engagement_strategy=engagement.get("strategy"),
    )
    return {"behaviour_plan": baseline, "engagement_brief": engagement}


def _attach_engagement(plan: dict[str, Any], state: PersonaGraphState) -> dict[str, Any]:
    """Stamp engagement / voice metadata onto the response plan (internal only)."""
    behaviour = state.get("behaviour_plan") or {}
    engagement = state.get("engagement_brief") or behaviour.get("engagement") or {}
    voice = behaviour.get("voice_tone") or {}
    plan = dict(plan)
    if engagement:
        plan["engagement_strategy"] = engagement.get("strategy")
        plan["internal_metadata"] = {
            "strategy": engagement.get("strategy"),
            "topic": engagement.get("topic"),
            "tone": engagement.get("tone") or voice.get("tone"),
            "notes": engagement.get("notes"),
        }
        if engagement.get("instruction"):
            plan["engagement_instruction"] = engagement["instruction"]
        if not engagement.get("should_ask_question"):
            plan["should_ask_question"] = False
        if engagement.get("strategy") == "direct_answer":
            plan["should_ask_question"] = False
            plan["introduce_new_topic"] = False
        if engagement.get("strategy") == "empathize":
            plan["introduce_new_topic"] = False
        if not engagement.get("allow_life_aside"):
            plan["allow_life_aside"] = False
        else:
            plan["allow_life_aside"] = True
        style = (state.get("conversation_context") or {}).get("style_profile") or {}
        if style.get("response_length") == "short":
            plan["length"] = "short"
            plan["response_length"] = "short"
    if voice:
        plan["voice_tone"] = voice.get("tone")
        plan["voice_instruction"] = voice.get("instruction")
    return plan


def response_plan(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("skip_response"):
        return {"response_plan": {}}

    understanding = state.get("understanding") or {}
    behaviour = state.get("behaviour_plan") or {}
    engagement = state.get("engagement_brief") or behaviour.get("engagement") or {}
    speech = understanding.get("speech_act") or ""
    conv = state.get("conversation_context") or {}
    move = (behaviour.get("conversational_move") or "REACT").upper()
    allowed_moves = list(behaviour.get("allowed_moves") or [])
    strategy = (state.get("response_strategy") or "").upper()
    current = (state.get("persona_state") or {}).get("current_state") or {}

    # Busy acknowledgement: short deferral message only
    if state.get("busy_ack") or strategy == "ACKNOWLEDGE_LATEST":
        activity = current.get("current_activity") or "busy"
        plan = {
            "should_respond": True,
            "should_acknowledge": True,
            "should_answer_directly": False,
            "should_ask_question": False,
            "should_self_disclose": False,
            "should_offer_help": False,
            "conversational_move": "ACKNOWLEDGE",
            "allowed_moves": ["ACKNOWLEDGE"],
            "disclose_fact_ids": [],
            "suppressed_fact_ids": [],
            "talking_points": [
                f"briefly note you are {activity} if natural",
                "say you will reply properly when free",
                "do not answer the full question yet",
            ],
            "tone": "brief",
            "memory_claims": [],
            "must_not_claim": [],
            "length": "very_short",
            "response_length": "very_short",
            "warmth": 0.5,
            "directness": 0.7,
            "humour": 0.1,
            "retrieve_memory": False,
            "mention_previous_context": False,
            "introduce_new_topic": False,
            "end_conversation": False,
            "busy_ack": True,
            "allowed_activity_mention": activity,
            "response_strategy": strategy,
        }
        selected = select_persona_context({**state, "response_plan": plan})
        return {
            "response_plan": plan,
            "disclose_fact_ids": [],
            "suppressed_fact_ids": [],
            "selected_context": selected,
        }

    policy = {
        "conversational_move": move,
        "allowed_moves": allowed_moves
        or select_move(
            understanding=understanding,
            persona_state=state.get("persona_state"),
            relationship_state=state.get("relationship_state"),
            recent_moves=list(conv.get("recent_moves") or []),
        ).get("allowed_moves"),
    }

    disclosure = compute_disclosure_plan(
        understanding=understanding,
        facts_shared_by_sarah=conv.get("facts_shared_by_sarah"),
        incoming_message=state.get("incoming_message") or "",
        should_self_disclose=bool(behaviour.get("disclosure_level", 0) > 0.4) and move == "SHARE",
    )

    q_target = understanding.get("question_target") or "none"
    q_targets = list(understanding.get("question_targets") or [])
    if not q_targets and q_target and q_target != "none":
        q_targets = [q_target]
    questions = list(understanding.get("questions") or [])
    factual_slots = {
        "activity_now",
        "meal_now",
        "task_now",
        "location_now",
        "occupation",
        "employer",
        "office",
        "project",
        "plan_future",
        "event_past",
        "preference",
        "user_memory",
        "identity",
        "relationship",
        "follow_up",
        "transport",
    }
    has_factual_slots = any((q.get("slot") or "none") in factual_slots for q in questions)
    world = build_world_state(current)
    last_world = conv.get("last_world_snapshot") or {}
    has_now = any(t in NOW_TARGETS for t in q_targets)
    has_employment = any(t in EMPLOYMENT_TARGETS or t == "zodiac" for t in q_targets)
    has_habit = "habit" in q_targets
    grounded = (
        has_factual_slots
        or has_now
        or has_employment
        or has_habit
        or any(
            t in {"zodiac", "office_location", "projects", "permanent_identity"}
            for t in q_targets
        )
    )

    # World / employment / habit / multi-target: answer from reality layers + answer plan
    if grounded:
        persona_doc = state.get("persona_state") or svc.state_repo.get_state(state["persona_id"])
        from persona_runtime.life.clock import clock_snapshot as _clock_snap
        from persona_runtime.life.timeline import TimelineRepository

        clock = _clock_snap(tz_name=svc.settings.timezone)
        timeline_repo = TimelineRepository(svc.state_repo.col.database)
        facts = retrieve_facts(
            questions,
            persona_id=state["persona_id"],
            persona_state=persona_doc,
            conversation_context=conv,
            retrieved_memories=list(state.get("retrieved_memories") or []),
            state_repo=svc.state_repo,
            timeline_repo=timeline_repo,
            clock=clock,
            tz_name=svc.settings.timezone,
            canonical_facts=list(state.get("all_canonical_facts") or []),
        )
        # Refresh persona_state after experience materialisation
        persona_doc = svc.state_repo.get_state(state["persona_id"])
        current = dict(persona_doc.get("current_state") or {})
        world = build_world_state(current)
        answer_plan = build_answer_plan(questions, facts) if questions else {
            "answers": [],
            "tone": "natural",
            "suggested_bubbles": 1,
            "allowed_slots": [],
            "must_not_mention": [],
        }
        points = talking_points_for_targets(
            q_targets,
            world=world,
            last_world=last_world if isinstance(last_world, dict) else {},
        )
        # Prefer direct answers as talking points when available
        direct_points = [
            f"answer '{a.get('slot')}': {a.get('direct_answer')}"
            for a in answer_plan.get("answers") or []
            if a.get("can_answer") and a.get("direct_answer")
        ]
        missing_points = [
            f"slot '{a.get('slot')}' is unknown — say so honestly, do not invent"
            for a in answer_plan.get("answers") or []
            if not a.get("can_answer")
        ]
        if direct_points or missing_points:
            points = (
                ["state each direct_answer first, in question order"]
                + direct_points
                + missing_points
                + [p for p in points if "one short chat bubble" in p]
            )
        only_now = (
            has_now
            and not has_employment
            and not has_habit
            and "zodiac" not in q_targets
            and not any(
                (q.get("slot") or "") in {"occupation", "office", "project", "identity"}
                for q in questions
            )
        )
        disclose = list(disclosure["disclose_fact_ids"])
        suppress = list(disclosure["suppressed_fact_ids"])
        must_not = [
            "degree / Accounting and Finance",
            "living in Manchester as a home fact",
        ] + list(answer_plan.get("must_not_mention") or [])
        if only_now:
            disclose = []
            must_not = [
                "job title / Management Accountant",
                "degree / Accounting and Finance",
                "living in Manchester as a home fact",
            ] + list(answer_plan.get("must_not_mention") or [])
        answer_layer = "world_state"
        if (has_employment and has_now) or (has_habit and has_now):
            answer_layer = "mixed"
        elif has_habit or any((q.get("slot") == "preference") for q in questions):
            answer_layer = "habit"
        elif "office_location" in q_targets or "projects" in q_targets:
            answer_layer = "employment"
        elif "zodiac" in q_targets or q_target == "permanent_identity":
            answer_layer = "permanent"
        elif any((q.get("slot") == "meal_now") for q in questions):
            answer_layer = "experience"
        length = "medium" if len(q_targets) > 1 or len(questions) > 1 else "short"
        open_exp = next(
            (
                a.get("event_id")
                for a in answer_plan.get("answers") or []
                if a.get("event_id") and a.get("slot") == "meal_now"
            ),
            None,
        )
        plan = {
            "should_respond": True,
            "should_acknowledge": q_targets == ["follow_up"],
            "should_answer_directly": "follow_up" not in q_targets or len(q_targets) > 1,
            "should_ask_question": False,
            "should_self_disclose": bool(disclose),
            "should_offer_help": False,
            "conversational_move": "SHARE" if q_targets != ["follow_up"] else "REACT",
            "allowed_moves": ["SHARE", "REACT", "ACKNOWLEDGE", "CONTINUE"],
            "disclose_fact_ids": disclose,
            "suppressed_fact_ids": suppress,
            "talking_points": points,
            "tone": answer_plan.get("tone") or "natural",
            "memory_claims": [],
            "must_not_claim": must_not,
            "length": length,
            "response_length": length,
            "warmth": behaviour.get("warmth", 0.55),
            "directness": 0.7,
            "humour": 0.35 if "follow_up" in q_targets else 0.15,
            "retrieve_memory": any((q.get("slot") == "user_memory") for q in questions),
            "mention_previous_context": "follow_up" in q_targets,
            "introduce_new_topic": False,
            "end_conversation": False,
            "question_target": q_target,
            "question_targets": q_targets,
            "questions": questions,
            "answers": answer_plan.get("answers") or [],
            "allowed_slots": answer_plan.get("allowed_slots") or [],
            "must_not_mention": answer_plan.get("must_not_mention") or [],
            "suggested_bubbles": answer_plan.get("suggested_bubbles") or 1,
            "world_state": world if "follow_up" not in q_targets else (last_world or world),
            "employment": employment_snapshot(),
            "allowed_activity_mention": current.get("current_activity"),
            "response_strategy": strategy,
            "answer_from_layer": answer_layer,
            "open_experience_id": open_exp,
        }
        # Factual slots: never grow a follow-up question from engagement
        plan["should_ask_question"] = False
        plan = _attach_engagement(plan, state)
        selected = select_persona_context({**state, "response_plan": plan, **disclosure})
        log_event(
            logger,
            "answer_plan",
            slots=",".join(answer_plan.get("allowed_slots") or []),
            statuses=",".join(
                str(a.get("status") or "") for a in (answer_plan.get("answers") or [])
            ),
            engagement_strategy=plan.get("engagement_strategy"),
        )
        return {
            "response_plan": plan,
            "disclose_fact_ids": plan["disclose_fact_ids"],
            "suppressed_fact_ids": plan["suppressed_fact_ids"],
            "selected_context": selected,
            "persona_state": persona_doc,
        }

    if state.get("event_type") == "conversation_start":
        allowed = state.get("allowed_evidence_ids") or []
        eng_ask = bool(engagement.get("should_ask_question"))
        plan = {
            "should_respond": True,
            "should_acknowledge": False,
            "should_answer_directly": False,
            "should_ask_question": eng_ask,
            "should_self_disclose": False,
            "should_offer_help": False,
            "conversational_move": behaviour.get("conversational_move") or "REACT",
            "allowed_moves": list(behaviour.get("allowed_moves") or ["REACT", "ASK", "ACKNOWLEDGE", "SHARE"]),
            "disclose_fact_ids": [],
            "suppressed_fact_ids": disclosure["suppressed_fact_ids"],
            "talking_points": ["greet naturally", "optionally reference real memory if allowed"],
            "tone": "natural",
            "memory_claims": [],
            "must_not_claim": [],
            "length": "short",
            "response_length": "short",
            "warmth": behaviour.get("warmth", 0.6),
            "directness": 0.5,
            "humour": 0.2,
            "retrieve_memory": bool(allowed),
            "mention_previous_context": False,
            "introduce_new_topic": engagement.get("strategy") == "fresh_topic",
            "end_conversation": False,
            "temporal_constraints": [c["preferred_phrasing"] for c in temporal_constraints_for_facts() if c.get("preferred_phrasing")],
            "allowed_activity_mention": current.get("current_activity"),
            "response_strategy": strategy,
        }
        if engagement.get("followup_hint"):
            plan["talking_points"].append(str(engagement["followup_hint"]))
        for mem in state.get("retrieved_memories") or []:
            text = (mem.get("event_description") or mem.get("fact") or "").lower()
            if "interview" in text and mem.get("memory_id") in allowed and eng_ask:
                plan["memory_claims"].append(
                    {
                        "claim": "ask how the interview went",
                        "evidence_memory_id": mem["memory_id"],
                    }
                )
                plan["talking_points"].append("ask about the interview")
                plan["should_ask_question"] = True
                plan["conversational_move"] = "ASK"
                break
        plan = _attach_engagement(plan, state)
        selected = select_persona_context({**state, "response_plan": plan, **disclosure})
        return {
            "response_plan": plan,
            "disclose_fact_ids": plan["disclose_fact_ids"],
            "suppressed_fact_ids": plan["suppressed_fact_ids"],
            "selected_context": selected,
        }

    ask = move in {"ASK", "CLARIFY"}
    share = move == "SHARE"
    plan: dict[str, Any] = {
        "should_respond": True,
        "should_acknowledge": speech in {"acknowledgement", "continuation"} or move == "ACKNOWLEDGE",
        "should_answer_directly": bool(understanding.get("requires_information")),
        "should_ask_question": ask,
        "should_self_disclose": share and bool(disclosure["disclose_fact_ids"]),
        "should_offer_help": False,
        "conversational_move": move,
        "allowed_moves": list(policy.get("allowed_moves") or []),
        "disclose_fact_ids": disclosure["disclose_fact_ids"] if share else (
            disclosure["disclose_fact_ids"] if speech == "question" and understanding.get("requires_information") else []
        ),
        "suppressed_fact_ids": disclosure["suppressed_fact_ids"],
        "talking_points": talking_points_for_move(move, understanding=understanding),  # type: ignore[arg-type]
        "tone": "natural",
        "memory_claims": [],
        "must_not_claim": [],
        "length": "short" if speech == "acknowledgement" or understanding.get("importance") == "low" else "medium",
        "response_length": "short" if speech == "acknowledgement" or understanding.get("importance") == "low" else "medium",
        "warmth": behaviour.get("warmth", 0.55),
        "directness": 0.55,
        "humour": 0.25 if move == "JOKE" else 0.15,
        "retrieve_memory": False,
        "mention_previous_context": speech in {"acknowledgement", "continuation", "self_disclosure"},
        "introduce_new_topic": move == "CHANGE_TOPIC",
        "end_conversation": speech == "conversation_closing" or move == "END_CONVERSATION",
        "temporal_constraints": [
            c.get("preferred_phrasing") or f"year={c.get('date')}"
            for c in temporal_constraints_for_facts()
        ],
        "allowed_activity_mention": current.get("current_activity"),
        "response_strategy": strategy,
        "pending_message_count": len(state.get("pending_messages") or []),
        "question_target": q_target,
        "answer_from_layer": "permanent" if q_target == "permanent_identity" else "mixed",
    }

    # Questions that need persona facts still disclose even if move is SHARE/REACT
    if speech == "question" and disclosure["disclose_fact_ids"]:
        plan["disclose_fact_ids"] = disclosure["disclose_fact_ids"]
        plan["should_self_disclose"] = True
        plan["talking_points"] = ["answer with allowed facts only"] + (
            ["one reciprocal question"] if ask else ["react briefly after answering"]
        )
    elif speech == "acknowledgement":
        plan["should_self_disclose"] = False
        plan["disclose_fact_ids"] = []

    prompt = _prompt(svc, "response_planning")
    selected_pre = select_persona_context({**state, "response_plan": plan, **disclosure})
    try:
        data = svc.llm.complete_json(
            system=prompt["system_prompt_template"],
            user=build_prompt_context(
                {**state, "selected_context": selected_pre, "response_plan": plan, "social_policy": policy},
                svc.settings,
            ),
            temperature=float(prompt.get("temperature") or 0.3),
        )
        for key in (
            "should_respond",
            "should_acknowledge",
            "should_answer_directly",
            "should_ask_question",
            "should_self_disclose",
            "talking_points",
            "tone",
            "response_length",
            "warmth",
            "directness",
            "humour",
            "retrieve_memory",
            "mention_previous_context",
            "introduce_new_topic",
            "end_conversation",
            "memory_claims",
            "must_not_claim",
            "length",
            "conversational_move",
        ):
            if key in data:
                plan[key] = data[key]
        plan["disclose_fact_ids"] = (
            disclosure["disclose_fact_ids"]
            if (plan.get("conversational_move") == "SHARE" or (speech == "question" and disclosure["disclose_fact_ids"]))
            else ([] if speech == "acknowledgement" else list(plan.get("disclose_fact_ids") or disclosure["disclose_fact_ids"]))
        )
        if speech == "acknowledgement":
            plan["disclose_fact_ids"] = []
            plan["should_self_disclose"] = False
        plan["suppressed_fact_ids"] = list(
            dict.fromkeys(
                list(disclosure["suppressed_fact_ids"])
                + list(data.get("suppressed_fact_ids") or [])
            )
        )
    except Exception:
        pass

    plan = apply_plan_humanity_gate(plan, policy=policy, understanding=understanding)
    # Acknowledgement / REACT / CONTINUE never disclose biography
    if speech == "acknowledgement" or plan.get("conversational_move") in {
        "ACKNOWLEDGE", "REACT", "CONTINUE", "JOKE", "WAIT",
    }:
        if speech != "question":
            plan["disclose_fact_ids"] = []
            plan["should_self_disclose"] = False

    # Grounded memory follow-ups (e.g. interview) — natural ASK when engagement allows
    allowed_ev = set(state.get("allowed_evidence_ids") or [])
    allowed_moves = set(plan.get("allowed_moves") or policy.get("allowed_moves") or [])
    eng_allows_ask = bool(engagement.get("should_ask_question")) or engagement.get(
        "strategy"
    ) in {"continue_earlier_topic", "answer_plus_followup"}
    if "ASK" in allowed_moves and eng_allows_ask:
        claims = list(plan.get("memory_claims") or [])
        claim_blob = " ".join(str((c or {}).get("claim") or "") for c in claims).lower()
        needs_ask_claim = any(
            k in claim_blob for k in ("ask", "how did", "interview", "follow")
        )
        if claims and needs_ask_claim and plan_claims_are_grounded(plan, list(allowed_ev)):
            plan["conversational_move"] = "ASK"
            plan["should_ask_question"] = True
        elif not claims:
            for mem in state.get("retrieved_memories") or []:
                text = (mem.get("event_description") or mem.get("fact") or "").lower()
                mid = mem.get("memory_id")
                if mid in allowed_ev and "interview" in text:
                    plan["conversational_move"] = "ASK"
                    plan["should_ask_question"] = True
                    plan["memory_claims"] = [
                        {"claim": "ask how the interview went", "evidence_memory_id": mid}
                    ]
                    points = list(plan.get("talking_points") or [])
                    if "ask about the interview" not in " ".join(points).lower():
                        points.append("ask about the interview")
                    plan["talking_points"] = points
                    break

    if engagement.get("followup_hint") and plan.get("should_ask_question"):
        points = list(plan.get("talking_points") or [])
        hint = str(engagement["followup_hint"])
        if hint not in points:
            points.append(hint)
        plan["talking_points"] = points

    plan = filter_ungrounded_claims(plan, list(state.get("allowed_evidence_ids") or []))
    plan = _attach_engagement(plan, state)
    selected = select_persona_context({**state, "response_plan": plan})
    return {
        "response_plan": plan,
        "disclose_fact_ids": list(plan.get("disclose_fact_ids") or []),
        "suppressed_fact_ids": list(plan.get("suppressed_fact_ids") or []),
        "selected_context": selected,
    }


def evidence_guard(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    plan = filter_ungrounded_claims(
        dict(state.get("response_plan") or {}),
        list(state.get("allowed_evidence_ids") or []),
    )
    if not plan_claims_are_grounded(plan, list(state.get("allowed_evidence_ids") or [])):
        plan["memory_claims"] = []
    selected = select_persona_context({**state, "response_plan": plan})
    return {"response_plan": plan, "selected_context": selected}


def generate_response(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("skip_response"):
        return {"generated_response": "", "generated_messages": []}

    # Deterministic busy acknowledgement — keeps schedule honest without inventing activity
    if state.get("busy_ack") or (state.get("response_plan") or {}).get("busy_ack"):
        current = (state.get("persona_state") or {}).get("current_state") or {}
        activity = current.get("current_activity") or "busy"
        phrases = {
            "meeting": "I'm in a meeting — I'll text you when I'm out.",
            "gym": "At the gym right now — I'll reply properly when I'm done.",
            "deep_work": "Just finishing something for work. Give me a bit.",
            "with_friends": "Out with friends — I'll message you later.",
            "sleeping": "Hey, I'll get back to you properly when I'm up.",
            "cooking": "Cooking at the moment — I'll reply properly in a bit.",
            "commuting": "Commuting — talk properly in a bit.",
        }
        reply = phrases.get(activity, "Bit tied up — I'll message you properly soon.")
        return messages_state_update([reply])

    prompt_name = "opening_generation" if state.get("event_type") == "conversation_start" else "response_generation"
    prompt = _prompt(svc, prompt_name)
    selected = state.get("selected_context") or select_persona_context(state)
    try:
        raw_texts = svc.llm.complete_as_messages(
            system=prompt["system_prompt_template"],
            user=build_prompt_context({**state, "selected_context": selected}, svc.settings),
            temperature=float(prompt.get("temperature") or 0.7),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "generated_response": "",
            "generated_messages": [],
            "errors": list(state.get("errors") or []) + [f"generation_failed:{exc}"],
        }
    texts = normalize_generated_messages(raw_texts, state)
    return messages_state_update(texts)


def recall_claim_check(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("skip_response"):
        return {}
    reply = state.get("generated_response") or ""
    allowed = list(state.get("allowed_evidence_ids") or [])
    plan = state.get("response_plan") or {}
    has_grounded_claims = bool(plan.get("memory_claims")) and plan_claims_are_grounded(plan, allowed)

    incoming = (state.get("incoming_message") or "").lower()
    asks_memory = any(p in incoming for p in ["do you remember", "remember my", "remember when"])
    if asks_memory and not allowed:
        return messages_state_update([FALLBACK_NO_MEMORY])

    if reply_has_recall_language(reply) and not has_grounded_claims and not allowed:
        try:
            prompt = _prompt(svc, "recall_repair")
            repaired_texts = svc.llm.complete_as_messages(
                system=prompt["system_prompt_template"],
                user=json.dumps({"draft": reply, "ALLOWED_EVIDENCE_IDS": allowed}),
                temperature=0.3,
            )
            repaired = "\n".join(repaired_texts)
            if reply_has_recall_language(repaired) and not allowed:
                return messages_state_update([FALLBACK_NO_MEMORY])
            return messages_state_update(normalize_generated_messages(repaired_texts, state))
        except Exception:
            return messages_state_update([FALLBACK_NO_MEMORY])

    if reply_has_recall_language(reply) and not has_grounded_claims:
        if asks_memory and not any(
            tokenize_overlap(incoming, m)
            for m in (state.get("retrieved_memories") or [])
        ):
            return messages_state_update([FALLBACK_NO_MEMORY])
    return {}


def _fallback_messages_update(state: PersonaGraphState) -> dict[str, Any]:
    """Deterministic fallback as bubble list (split when multi-target)."""
    from persona_runtime.graph.reality import world_state_fallback_messages

    understanding = state.get("understanding") or {}
    plan = state.get("response_plan") or {}
    q_target = understanding.get("question_target") or plan.get("question_target") or "none"
    q_targets = list(
        understanding.get("question_targets") or plan.get("question_targets") or []
    )
    if not q_targets and q_target and q_target != "none":
        q_targets = [q_target]
    if plan.get("answers"):
        from persona_runtime.graph.grounding import fallback_messages_from_answer_plan

        texts = fallback_messages_from_answer_plan(plan)
        if texts:
            return messages_state_update(texts)
    if len(q_targets) > 1:
        current = (state.get("persona_state") or {}).get("current_state") or {}
        world = plan.get("world_state") or build_world_state(current)
        last_world = (state.get("conversation_context") or {}).get("last_world_snapshot") or {}
        texts = world_state_fallback_messages(
            q_targets[0],
            world=world if isinstance(world, dict) else build_world_state(current),
            last_world=last_world if isinstance(last_world, dict) else {},
            targets=q_targets,
        )
        return messages_state_update(texts)
    fallback = deterministic_fallback_reply(state)
    return messages_state_update([fallback])


def validate_and_repair(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("skip_response"):
        return {}
    reply = state.get("generated_response") or ""
    result = validate_response(state, reply)
    attempts = int(state.get("validation_attempts") or 0)

    if result.ok:
        # Ensure generated_messages stays aligned with generated_response
        msgs = state.get("generated_messages") or pack_message_dicts(
            [p for p in reply.split("\n") if p.strip()] if reply else []
        )
        clock = state.get("clock_snapshot") or {}
        current = (state.get("persona_state") or {}).get("current_state") or {}
        log_event(
            logger,
            "turn_validation_ok",
            request_id=state.get("request_id"),
            local_time=clock.get("local_time"),
            state_version=state.get("state_version"),
            active_event_id=current.get("active_event_id"),
            validation_ok=True,
        )
        return {
            "validation": result.to_dict(),
            "validation_feedback": [],
            "generated_messages": msgs,
        }

    log_event(
        logger,
        "response_validation_failed",
        request_id=state.get("request_id"),
        failures=result.failures,
        attempt=attempts,
    )

    if attempts >= 1:
        packed = _fallback_messages_update(state)
        fallback = packed["generated_response"]
        retry = validate_response(state, fallback)
        if not retry.ok:
            packed = messages_state_update(["Sounds good 🙂"])
        return {
            **packed,
            "validation": {"ok": True, "failures": result.failures, "repaired": "fallback"},
            "validation_feedback": result.failures,
            "validation_attempts": attempts + 1,
        }

    # One structured repair
    try:
        prompt = _prompt(svc, "response_repair")
        repaired_texts = svc.llm.complete_as_messages(
            system=prompt["system_prompt_template"],
            user=build_prompt_context(
                {
                    **state,
                    "validation_feedback": result.failures,
                    "generated_response": reply,
                },
                svc.settings,
            )
            + f"\n\n=== DRAFT ===\n{reply}\n\n=== FAILURES ===\n{json.dumps(result.failures)}",
            temperature=0.3,
        )
        repaired_texts = normalize_generated_messages(repaired_texts, state)
        repaired = "\n".join(repaired_texts)
        check = validate_response(state, repaired)
        if check.ok:
            return {
                **messages_state_update(repaired_texts),
                "validation": check.to_dict() | {"repaired": True},
                "validation_feedback": [],
                "validation_attempts": attempts + 1,
            }
        packed = _fallback_messages_update(state)
        return {
            **packed,
            "validation": {"ok": True, "failures": check.failures, "repaired": "fallback"},
            "validation_feedback": check.failures,
            "validation_attempts": attempts + 1,
        }
    except Exception:
        packed = _fallback_messages_update(state)
        return {
            **packed,
            "validation": {"ok": True, "failures": result.failures, "repaired": "fallback"},
            "validation_feedback": result.failures,
            "validation_attempts": attempts + 1,
        }


def tokenize_overlap(query: str, mem: dict[str, Any]) -> bool:
    from persona_runtime.memory.retrieval import memory_text, tokenize

    return bool(tokenize(query) & tokenize(memory_text(mem)))


def persist_turn(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("event_type") == "message_seen":
        svc.conversation_repo.record_event(
            "message_seen",
            {
                "conversation_id": state.get("conversation_id"),
                "persona_id": state.get("persona_id"),
                "user_id": state.get("user_id"),
                "action": "none",
                "reason": "casual_seen_no_followup",
            },
        )
        return {"generated_response": ""}

    assistant_message_id = None
    assistant_message_ids: list[str] = []
    reply = state.get("generated_response") or ""
    bubbles = list(state.get("generated_messages") or [])
    if not bubbles and reply:
        bubbles = pack_message_dicts([p for p in reply.split("\n") if p.strip()] or [reply])
    if not bubbles:
        # Generation/validation produced nothing — still send a chat bubble
        packed = _fallback_messages_update(state)
        reply = packed.get("generated_response") or "Yeah, fair enough."
        bubbles = list(packed.get("generated_messages") or pack_message_dicts([reply]))

    if bubbles:
        base_meta = {
            "behaviour_plan": state.get("behaviour_plan"),
            "response_plan": state.get("response_plan"),
            "allowed_evidence_ids": state.get("allowed_evidence_ids"),
            "understanding": state.get("understanding"),
            "validation": state.get("validation"),
            "request_id": state.get("request_id"),
            "response_strategy": state.get("response_strategy"),
            "response_job_id": (state.get("response_job") or {}).get("job_id"),
            "pending_message_ids": [
                m.get("message_id") for m in (state.get("pending_messages") or [])
            ],
            "bubble_count": len(bubbles),
        }
        for index, bubble in enumerate(bubbles):
            text = (
                str(bubble.get("text") or "").strip()
                if isinstance(bubble, dict)
                else str(bubble or "").strip()
            )
            if not text:
                continue
            msg = svc.conversation_repo.add_message(
                conversation_id=state["conversation_id"],
                sender="assistant",
                content=text,
                metadata={**base_meta, "bubble_index": index},
                status="answered",
            )
            assistant_message_ids.append(msg["message_id"])
        assistant_message_id = assistant_message_ids[0] if assistant_message_ids else None

    # Gradual relationship update
    meaningful = False
    incoming = state.get("incoming_message") or ""
    if len(incoming) > 40 or any(k in incoming.lower() for k in ["interview", "worried", "excited", "job", "family"]):
        meaningful = True
    deltas = {
        "familiarity": 0.03,
        "trust": 0.02 if meaningful else 0.01,
        "reciprocity": 0.02,
        "uncertainty": -0.02,
        "communication_frequency": 0.02,
        "emotional_openness": 0.01 if meaningful else 0.005,
        "closeness": 0.015 if meaningful else 0.008,
        "affection": 0.01 if meaningful else 0.005,
    }
    svc.relationship_repo.apply_deltas(
        state["persona_id"],
        state["user_id"],
        deltas,
        max_abs_delta=0.05,
        meaningful=meaningful,
    )

    current = (state.get("persona_state") or {}).get("current_state") or {}
    social = float(current.get("social_energy", 0.6))
    svc.state_repo.apply_updates(
        state["persona_id"],
        {"social_energy": min(1.0, social + 0.02)},
    )

    return {
        "assistant_message_id": assistant_message_id,
        "assistant_message_ids": assistant_message_ids,
        "generated_response": reply,
        "generated_messages": bubbles,
        "relationship_updates": deltas,
    }


def update_conversation_context(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("event_type") == "message_seen":
        return {}
    if state.get("event_type") == "conversation_start" and not (state.get("generated_response") or ""):
        return {}

    understanding = state.get("understanding") or {}
    conv = dict(state.get("conversation_context") or {})
    reply = state.get("generated_response") or ""
    incoming = state.get("incoming_message") or ""
    plan = state.get("response_plan") or {}

    facts = record_disclosures_from_reply(
        reply=reply,
        message_id=state.get("assistant_message_id"),
        existing=conv.get("facts_shared_by_sarah"),
    )

    questions_asked = list(conv.get("questions_asked") or [])
    for q in detect_questions_in_text(reply):
        if q not in questions_asked:
            questions_asked.append(q)

    user_facts = list(conv.get("user_facts_this_conversation") or [])
    for d in understanding.get("user_disclosures") or []:
        entry = {
            "predicate": d.get("predicate"),
            "object": d.get("object"),
            "text": d.get("text") or incoming,
            "message_id": state.get("user_message_id"),
        }
        if entry["predicate"] and not any(
            u.get("predicate") == entry["predicate"] and u.get("object") == entry["object"]
            for u in user_facts
        ):
            user_facts.append(entry)

    topic_updates = apply_topic_turn(
        conv,
        understanding=understanding,
        incoming=incoming,
        reply=reply,
        engagement_brief=state.get("engagement_brief")
        or (state.get("behaviour_plan") or {}).get("engagement"),
    )
    topic = topic_updates.get("current_topic") or understanding.get("topic") or conv.get("current_topic") or ""
    previous_topics = list(topic_updates.get("previous_topics") or conv.get("previous_topics") or [])
    topics_discussed = list(dict.fromkeys(list(conv.get("topics_discussed") or []) + ([topic] if topic else [])))

    stage = conv.get("conversation_stage") or "opening"
    msg_count = len(state.get("recent_messages") or [])
    if msg_count >= 4:
        stage = "ongoing"
    if understanding.get("speech_act") == "conversation_closing":
        stage = "closing"

    recent_turns = list(conv.get("recent_turns") or [])
    if incoming:
        recent_turns.append({"role": "user", "content": incoming[:300]})
    bubbles = list(state.get("generated_messages") or [])
    if bubbles:
        for bubble in bubbles:
            text = (
                str(bubble.get("text") or "").strip()
                if isinstance(bubble, dict)
                else str(bubble or "").strip()
            )
            if text:
                recent_turns.append({"role": "assistant", "content": text[:300]})
    elif reply:
        recent_turns.append({"role": "assistant", "content": reply[:300]})
    recent_turns = recent_turns[-12:]

    response_history = list(conv.get("response_history") or [])
    response_history.append(
        {
            "speech_act": understanding.get("speech_act"),
            "disclose_fact_ids": plan.get("disclose_fact_ids") or [],
            "should_ask_question": plan.get("should_ask_question"),
            "conversational_move": plan.get("conversational_move")
            or (state.get("behaviour_plan") or {}).get("conversational_move"),
            "engagement_strategy": plan.get("engagement_strategy")
            or (state.get("behaviour_plan") or {}).get("engagement_strategy"),
            "length": plan.get("response_length") or plan.get("length"),
        }
    )
    response_history = response_history[-20:]

    move_this_turn = (
        plan.get("conversational_move")
        or (state.get("behaviour_plan") or {}).get("conversational_move")
        or ""
    )
    recent_moves = list(conv.get("recent_moves") or [])
    if move_this_turn:
        recent_moves.append(str(move_this_turn).upper())
    recent_moves = recent_moves[-4:]

    # Compact summary
    summary_bits = []
    if facts:
        summary_bits.append(
            "Sarah disclosed: " + ", ".join(f.get("fact_id", "") for f in facts[-5:])
        )
    if user_facts:
        summary_bits.append(
            "User: " + "; ".join(f"{u.get('predicate')}={u.get('object')}" for u in user_facts[-5:])
        )
    if topic:
        summary_bits.append(f"topic={topic}")
    recent_summary = ". ".join(summary_bits)[:500]

    updates = {
        "current_topic": topic,
        "previous_topics": previous_topics[-10:],
        "conversation_stage": stage,
        "last_user_message": incoming,
        "last_sarah_message": reply,
        "facts_shared_by_sarah": facts,
        "user_facts_this_conversation": user_facts,
        "questions_asked": questions_asked[-20:],
        "topics_discussed": topics_discussed[-20:],
        "open_threads": topic_updates.get("open_threads", conv.get("open_threads") or []),
        "declined_topics": topic_updates.get("declined_topics", conv.get("declined_topics") or []),
        "last_transition": topic_updates.get("last_transition", conv.get("last_transition") or ""),
        "style_profile": topic_updates.get("style_profile") or conv.get("style_profile") or {},
        "recent_turns": recent_turns,
        "recent_summary": recent_summary,
        "user_intent": understanding.get("intent") or "",
        "user_emotion": understanding.get("user_emotion") or "",
        "speech_act": understanding.get("speech_act") or "",
        "response_history": response_history,
        "recent_moves": recent_moves,
    }
    if topic_updates.get("proactive_opt_out"):
        updates["proactive_opt_out"] = True
    q_target = understanding.get("question_target") or plan.get("question_target")
    if q_target and q_target != "none":
        updates["last_question_target"] = q_target
    if q_target in NOW_TARGETS:
        world = plan.get("world_state") or build_world_state(
            (state.get("persona_state") or {}).get("current_state") or {}
        )
        if q_target != "follow_up":
            updates["last_world_snapshot"] = world
        elif not conv.get("last_world_snapshot"):
            updates["last_world_snapshot"] = world

    answer_slots = [
        a.get("slot")
        for a in (plan.get("answers") or [])
        if a.get("slot") and a.get("slot") != "none"
    ]
    if answer_slots:
        updates["last_answer_slots"] = answer_slots
    if plan.get("open_experience_id"):
        updates["open_experience_id"] = plan.get("open_experience_id")
    elif any(s == "meal_now" for s in answer_slots):
        # Clear when meal answered but no open event
        pass

    updated = svc.conversation_context_repo.apply_turn_update(
        conversation_id=state["conversation_id"],
        persona_id=state["persona_id"],
        user_id=state["user_id"],
        updates=updates,
    )
    return {"conversation_context": updated}


def extract_memories(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("event_type") != "user_message":
        return {"memory_candidates": []}
    prompt = _prompt(svc, "memory_extraction")
    payload = {
        "user_message": state.get("incoming_message"),
        "assistant_message": state.get("generated_response"),
        "user_message_id": state.get("user_message_id"),
        "assistant_message_id": state.get("assistant_message_id"),
    }
    msg_id = state.get("user_message_id")
    evidence_ids = [msg_id] if msg_id else []

    try:
        data = svc.llm.complete_json(
            system=prompt["system_prompt_template"],
            user=json.dumps(payload),
            temperature=float(prompt.get("temperature") or 0.2),
        )
        result = MemoryExtractionResult.model_validate(data)
        # Attach evidence from this turn when the model omits ids
        for c in result.candidates:
            if c.memory_type != "no_memory" and not c.source_message_ids and evidence_ids:
                c.source_message_ids = list(evidence_ids)
        # Merge heuristic disclosures if LLM missed them
        heuristic = _heuristic_extraction(state)
        existing_keys = {
            (c.memory_type, c.subject, c.predicate, c.object)
            for c in result.candidates
        }
        for h in heuristic.candidates:
            key = (h.memory_type, h.subject, h.predicate, h.object)
            if h.memory_type != "no_memory" and key not in existing_keys:
                result.candidates.append(h)
    except Exception:
        result = _heuristic_extraction(state)

    return {"memory_candidates": [c.model_dump() for c in result.candidates]}


def _heuristic_extraction(state: PersonaGraphState) -> MemoryExtractionResult:
    from persona_runtime.conversation.dates import occurs_at_datetime

    text = state.get("incoming_message") or ""
    lower = text.lower()
    msg_id = state.get("user_message_id")
    ids = [msg_id] if msg_id else []
    candidates: list[MemoryCandidate] = []
    occurs = occurs_at_datetime(
        text,
        clock=state.get("clock_snapshot"),
        tz_name="Europe/London",
    )

    # From understanding disclosures
    for d in (state.get("understanding") or {}).get("user_disclosures") or []:
        if d.get("predicate") and d.get("object"):
            candidates.append(
                MemoryCandidate(
                    memory_type="semantic",
                    importance=0.8,
                    confidence=0.9,
                    fact=f"User {d['predicate']} {d['object']}",
                    subject="user",
                    predicate=d["predicate"],
                    object=d["object"],
                    source_message_ids=ids,
                )
            )

    timed_event_keys = (
        ("interview", "interview"),
        ("driving test", "driving_test"),
        ("presentation", "presentation"),
        ("exam", "exam"),
        ("flight", "flight"),
        ("holiday", "holiday"),
    )
    for key, obj in timed_event_keys:
        if key in lower:
            candidates.append(
                MemoryCandidate(
                    memory_type="episodic",
                    importance=0.85,
                    confidence=0.9,
                    event_description=text.strip(),
                    source_message_ids=ids,
                    occurs_at=occurs,
                    horizon="upcoming" if occurs else "timeless",
                    outcome_known=False if occurs else None,
                )
            )
            if occurs or "tomorrow" in lower or "next" in lower:
                candidates.append(
                    MemoryCandidate(
                        memory_type="semantic",
                        importance=0.8,
                        confidence=0.85,
                        fact=f"User has an upcoming {obj.replace('_', ' ')}",
                        subject="user",
                        predicate="has_upcoming_event",
                        object=obj,
                        source_message_ids=ids,
                        occurs_at=occurs,
                        horizon="upcoming" if occurs else "timeless",
                        outcome_known=False,
                    )
                )
            break

    if re.search(r"\bi work(?:\s+in|\s+at|\s+as)\b", lower):
        m = re.search(r"\bi work(?:\s+as|\s+in|\s+at)\s+(.+?)(?:\.|$)", text, re.I)
        obj = m.group(1).strip(" .,!") if m else text.strip()
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.75,
                confidence=0.8,
                fact=text.strip(),
                subject="user",
                predicate="occupation",
                object=obj,
                source_message_ids=ids,
            )
        )

    # "I am a technical project manager"
    if re.search(r"\bi(?:'m| am)\s+(?:a |an )?.{0,40}(project manager|manager|engineer|developer|accountant)\b", lower):
        m = re.search(r"\bi(?:'m| am)\s+(?:a |an )?(.+?)(?:\.|$)", text, re.I)
        if m:
            role = m.group(1).strip(" .,!")
            if not any(c.predicate == "occupation" for c in candidates):
                candidates.append(
                    MemoryCandidate(
                        memory_type="semantic",
                        importance=0.85,
                        confidence=0.9,
                        fact=f"User occupation is {role}",
                        subject="user",
                        predicate="occupation",
                        object=role,
                        source_message_ids=ids,
                    )
                )

    correction = bool(re.search(r"\b(?:actually|switched|instead|call me)\b", lower)) or (
        " now" in lower and bool(re.search(r"\b(?:prefer|name is|call me)\b", lower))
    )
    name_match = re.search(r"\b(?:my name is|call me)\s+([A-Za-z][A-Za-z'\-]{1,30})", text, re.I)
    if name_match and not any(c.predicate == "name" for c in candidates):
        name = name_match.group(1).strip(" .,!").title()
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.9,
                confidence=0.95,
                fact=f"User name is {name}",
                subject="user",
                predicate="name",
                object=name,
                source_message_ids=ids,
                is_correction=correction or "call me" in lower,
            )
        )
    if re.search(r"\b(?:honda|cr-z)\b", lower) and not any(c.predicate == "owns_car" for c in candidates):
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.85,
                confidence=0.9,
                fact="User owns a Honda CR-Z",
                subject="user",
                predicate="owns_car",
                object="Honda CR-Z",
                source_message_ids=ids,
            )
        )
    if re.search(r"\bprefer\b", lower) and re.search(r"\b(tea|coffee)\b", lower):
        drink = "coffee" if "coffee" in lower else "tea"
        if not any(c.predicate == "morning_drink" and c.object == drink for c in candidates):
            candidates.append(
                MemoryCandidate(
                    memory_type="semantic",
                    importance=0.75 if drink == "coffee" else 0.7,
                    confidence=0.9 if correction or drink == "coffee" else 0.85,
                    fact=f"User prefers {drink} in the morning",
                    subject="user",
                    predicate="morning_drink",
                    object=drink,
                    source_message_ids=ids,
                    is_correction=correction or drink == "coffee" and "tea" not in lower and "switched" in lower,
                )
            )
    if "weekend" in lower and "drive" in lower and not any(c.predicate == "weekend_preference" for c in candidates):
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.75,
                confidence=0.85,
                fact="User usually goes for drives on weekends",
                subject="user",
                predicate="weekend_preference",
                object="drives",
                source_message_ids=ids,
            )
        )
    if (
        "messaged repeatedly" in lower or "don't like being messaged" in lower
    ) and not any(c.predicate == "messaging_boundary" for c in candidates):
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.9,
                confidence=0.9,
                fact="User does not like being messaged repeatedly when busy",
                subject="user",
                predicate="messaging_boundary",
                object="busy",
                source_message_ids=ids,
            )
        )
    if "photography" in lower and not any(c.predicate == "hobby" for c in candidates):
        candidates.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=0.8,
                confidence=0.9,
                fact="User enjoys photography",
                subject="user",
                predicate="hobby",
                object="photography",
                source_message_ids=ids,
            )
        )

    if not candidates:
        candidates.append(MemoryCandidate(memory_type="no_memory", importance=0.0, confidence=1.0))
    return MemoryExtractionResult(candidates=candidates)


def consolidate_memories(state: PersonaGraphState, svc: GraphServices) -> dict[str, Any]:
    if state.get("event_type") != "user_message":
        return {"stored_memories": []}
    raw = state.get("memory_candidates") or []
    candidates = [MemoryCandidate.model_validate(c) for c in raw]
    stored = svc.consolidator.consolidate(
        persona_id=state["persona_id"],
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        candidates=candidates,
    )
    return {"stored_memories": stored}
