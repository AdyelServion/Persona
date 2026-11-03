"""LLM structured decision for proactive engagement (scheduler runs separately)."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator

from persona_runtime.outbound.quality import validate_decision_grounding, validate_outbound_draft
from persona_runtime.outbound.schedule import interval_options_from_doc

logger = logging.getLogger(__name__)

STRATEGIES = (
    "CONTINUE_TOPIC",
    "FOLLOW_UP_MEMORY",
    "EXPLORE_INTEREST",
    "ASK_CASUAL_QUESTION",
    "INTRODUCE_NEW_TOPIC",
    "NO_MESSAGE",
)


class EngagementDecisionModel(BaseModel):
    should_send: bool = False
    strategy: str = "NO_MESSAGE"
    topic: str | None = None
    reason: str = ""
    context_reference: str | None = None
    message_intent: str | None = None
    suggested_message: str | None = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    next_evaluation_minutes: int | None = None
    proactive_type: str | None = None
    subject: str | None = None
    evidence_memory_ids: list[str] = Field(default_factory=list)

    @field_validator("strategy")
    @classmethod
    def _strategy(cls, v: str) -> str:
        u = (v or "NO_MESSAGE").upper().replace(" ", "_")
        return u if u in STRATEGIES else "NO_MESSAGE"


def _clamp_hint_minutes(doc: dict[str, Any], app_settings: Any, hint: int | None) -> int | None:
    if hint is None:
        return None
    opts = interval_options_from_doc(doc, app_settings)
    if hint in opts:
        return hint
    return min(opts, key=lambda x: abs(x - hint))


def _strategy_to_type(strategy: str, candidate: dict[str, Any] | None) -> str:
    if candidate and candidate.get("proactive_type"):
        return str(candidate["proactive_type"])
    mapping = {
        "FOLLOW_UP_MEMORY": "hobby_followup",
        "EXPLORE_INTEREST": "interest_followup",
        "CONTINUE_TOPIC": "conversation_resumption",
        "INTRODUCE_NEW_TOPIC": "new_topic",
        "ASK_CASUAL_QUESTION": "new_topic",
    }
    return mapping.get(strategy, "new_topic")


def _pick_candidate(decision: EngagementDecisionModel, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    topic = (decision.topic or "").lower()
    subject = (decision.subject or "").lower()
    for c in candidates:
        if topic and str(c.get("topic") or "").lower() == topic:
            return c
        if subject and str(c.get("subject") or "").lower() == subject:
            return c
    if decision.strategy == "INTRODUCE_NEW_TOPIC":
        for c in candidates:
            if c.get("proactive_type") == "new_topic":
                return c
    return candidates[0]


def decision_from_rules(
    *,
    analysis: Any,
    settings_doc: dict[str, Any],
    trigger: dict[str, Any] | None,
    asked_questions: list[str],
) -> EngagementDecisionModel:
    if analysis.open_sarah_question and not analysis.last_user_text:
        return EngagementDecisionModel(
            should_send=False,
            strategy="NO_MESSAGE",
            reason="Sarah already asked something; waiting for a reply",
            next_evaluation_minutes=30,
        )
    if not trigger:
        return EngagementDecisionModel(
            should_send=False,
            strategy="NO_MESSAGE",
            reason="No grounded trigger candidate",
            next_evaluation_minutes=25,
        )
    if not settings_doc.get("allow_contextual_followups", True) and trigger.get("proactive_type") != "new_topic":
        return EngagementDecisionModel(should_send=False, strategy="NO_MESSAGE", reason="contextual_followups_disabled")
    if not settings_doc.get("allow_new_topic_introduction", True) and trigger.get("proactive_type") == "new_topic":
        return EngagementDecisionModel(should_send=False, strategy="NO_MESSAGE", reason="new_topics_disabled")

    strategy = "FOLLOW_UP_MEMORY"
    ptype = trigger.get("proactive_type") or ""
    if ptype == "event_followup":
        strategy = "FOLLOW_UP_MEMORY"
    elif ptype in {"hobby_followup", "interest_followup"}:
        strategy = "EXPLORE_INTEREST"
    elif ptype == "conversation_resumption":
        strategy = "CONTINUE_TOPIC"
    elif ptype == "new_topic":
        strategy = "INTRODUCE_NEW_TOPIC" if not analysis.mentioned_hobbies else "ASK_CASUAL_QUESTION"

    draft = trigger.get("hint") or ""
    if trigger.get("subject"):
        draft = f"ask casually about {trigger['subject']}"

    return EngagementDecisionModel(
        should_send=True,
        strategy=strategy,
        topic=trigger.get("topic"),
        subject=trigger.get("subject"),
        reason=f"Rule-based: {ptype}",
        context_reference=trigger.get("idempotency_subject"),
        message_intent=draft,
        suggested_message=None,
        confidence=0.85,
        next_evaluation_minutes=30,
        proactive_type=ptype,
        evidence_memory_ids=list(trigger.get("evidence_memory_ids") or []),
    )


def decide_proactive_engagement(
    *,
    llm: Any | None,
    prompt_repo: Any,
    analysis: Any,
    settings_doc: dict[str, Any],
    app_settings: Any,
    trigger_candidates: list[dict[str, Any]],
    asked_questions: list[str],
    last_outbound_text: str | None = None,
) -> EngagementDecisionModel:
    primary_trigger = trigger_candidates[0] if trigger_candidates else None
    rule = decision_from_rules(
        analysis=analysis,
        settings_doc=settings_doc,
        trigger=primary_trigger,
        asked_questions=asked_questions,
    )
    if not rule.should_send or llm is None or prompt_repo is None:
        return rule

    prompt = prompt_repo.get_active("proactive_engagement_decision")
    if not prompt:
        return rule

    import json

    payload = {
        "analysis": {
            "summary": analysis.summary,
            "last_user_text": analysis.last_user_text,
            "open_sarah_question": analysis.open_sarah_question,
            "mentioned_hobbies": analysis.mentioned_hobbies,
            "mentioned_plans": analysis.mentioned_plans,
            "topic_completed": analysis.topic_completed,
            "repeat_topic_risk": analysis.repeat_topic_risk,
        },
        "candidates": [
            {
                "proactive_type": c.get("proactive_type"),
                "topic": c.get("topic"),
                "subject": c.get("subject"),
                "hint": c.get("hint"),
            }
            for c in trigger_candidates[:8]
        ],
        "settings": {
            "allow_contextual_followups": settings_doc.get("allow_contextual_followups", True),
            "allow_new_topic_introduction": settings_doc.get("allow_new_topic_introduction", True),
        },
        "priority_rules": [
            "If Sarah's last question is unanswered, prefer NO_MESSAGE",
            "Prefer follow-ups grounded in recent user messages or candidates",
            "Do not invent hobbies, events, or outcomes",
            "No emojis; casual texting voice",
        ],
    }
    try:
        raw = llm.complete_json(
            system=prompt.get("system_prompt_template") or "",
            user=json.dumps(payload, ensure_ascii=False),
            temperature=float(prompt.get("temperature") or 0.4),
        )
        if not isinstance(raw, dict) or "should_send" not in raw:
            return rule
        model = EngagementDecisionModel.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("proactive_decision_llm_failed: %s", exc)
        return rule

    ok, reason = validate_decision_grounding(
        model.model_dump(),
        trigger_candidates=trigger_candidates,
        analysis_summary=analysis.summary,
    )
    if not ok:
        logger.warning("proactive_decision_ungrounded: %s", reason)
        return rule

    if model.should_send and model.suggested_message:
        ok_msg, msg_reason = validate_outbound_draft(
            model.suggested_message,
            asked_questions=asked_questions,
            last_outbound_text=last_outbound_text,
        )
        if not ok_msg:
            return EngagementDecisionModel(
                should_send=False,
                strategy="NO_MESSAGE",
                reason=f"draft_invalid:{msg_reason}",
                next_evaluation_minutes=model.next_evaluation_minutes,
            )

    model.next_evaluation_minutes = _clamp_hint_minutes(settings_doc, app_settings, model.next_evaluation_minutes)
    if model.should_send:
        cand = _pick_candidate(model, trigger_candidates)
        if cand:
            model.proactive_type = _strategy_to_type(model.strategy, cand)
            model.topic = model.topic or cand.get("topic")
            model.subject = model.subject or cand.get("subject")
            if not model.evidence_memory_ids:
                model.evidence_memory_ids = list(cand.get("evidence_memory_ids") or [])
    return model


def build_brief_from_decision(
    decision: EngagementDecisionModel,
    trigger_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not decision.should_send or decision.strategy == "NO_MESSAGE":
        return None
    cand = _pick_candidate(decision, trigger_candidates)
    if not cand:
        return None
    brief = dict(cand)
    if decision.message_intent:
        brief["hint"] = decision.message_intent
    if decision.suggested_message:
        brief["suggested_opener"] = decision.suggested_message.strip()
    brief["engagement_strategy"] = decision.strategy
    brief["decision_reason"] = decision.reason
    return brief
