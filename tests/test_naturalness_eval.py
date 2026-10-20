"""Optional LLM-based naturalness evaluation. Skipped unless RUN_LLM_EVAL=1."""

from __future__ import annotations

import json
import os

import pytest

from persona_runtime.graph.grounding import build_answer_plan, retrieve_facts
from persona_runtime.graph.questions import extract_questions
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.state.repositories import PersonaStateRepository

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LLM_EVAL") != "1",
    reason="Set RUN_LLM_EVAL=1 to run live naturalness scoring",
)


# Live scoring notes (RUN_LLM_EVAL=1): also judge conversational naturalness —
# wording variety, unnecessary-question rate, topic continuity, and engagement
# that is not interview-mode. Deterministic engagement coverage lives in
# tests/test_engagement.py.
SCENARIOS = [
    {
        "id": "lunch_meal",
        "message": "What are you having for lunch?",
        "force_activity": "lunch",
        "expect_slots": ["meal_now"],
    },
    {
        "id": "occupation",
        "message": "What do you do?",
        "force_activity": None,
        "expect_slots": ["occupation"],
    },
    {
        "id": "multi",
        "message": "whats your favorite dish ?\nwhat are you doing right now ?",
        "force_activity": "lunch",
        "expect_slots": ["preference", "activity_now"],
    },
    {
        "id": "travel_engagement",
        "message": "I like travelling.",
        "force_activity": None,
        "expect_slots": [],
        "engagement_notes": "acknowledge interest; optional established preference; at most one specific follow-up",
    },
    {
        "id": "emotional_first",
        "message": "I had a terrible day.",
        "force_activity": None,
        "expect_slots": [],
        "engagement_notes": "supportive tone before any new topic",
    },
]


def test_answer_plan_ready_for_llm_eval(ingested_db):
    """Deterministic gate: plans must be ready before any live scoring."""
    repo = PersonaStateRepository(ingested_db)
    life = LifeSimulator(repo)
    for scenario in SCENARIOS:
        if not scenario.get("expect_slots"):
            # Engagement-only scenarios — no ANSWER_PLAN slots required
            continue
        if scenario["force_activity"]:
            life.force_activity("sarah_taylor_001", scenario["force_activity"], duration_minutes=40)
        pending = scenario["message"].split("\n")
        qs = extract_questions(scenario["message"], pending_messages=pending)
        assert [q.slot for q in qs] == scenario["expect_slots"]
        facts = retrieve_facts(
            qs,
            persona_id="sarah_taylor_001",
            persona_state=repo.get_state("sarah_taylor_001"),
            state_repo=repo,
        )
        plan = build_answer_plan(qs, facts)
        assert len(plan["answers"]) == len(scenario["expect_slots"])
        # Metadata for optional scorer (no conversation text dumped beyond slots)
        meta = {
            "scenario": scenario["id"],
            "slots": [a["slot"] for a in plan["answers"]],
            "statuses": [a["status"] for a in plan["answers"]],
        }
        assert json.dumps(meta)


def test_live_naturalness_scores(ingested_db, runtime):
    """Score relevance / tone / leakage with the configured OpenAI model."""
    from persona_runtime.llm.client import LLMClient

    client = LLMClient()
    repo = PersonaStateRepository(ingested_db)
    life = LifeSimulator(repo)
    life.force_activity("sarah_taylor_001", "lunch", duration_minutes=40)

    conv = runtime.conversation_repo.get_or_create("sarah_taylor_001", "eval_user")
    text = "What are you having for lunch?"
    msg = runtime.conversation_repo.add_message(
        conversation_id=conv["conversation_id"], sender="user", content=text
    )
    result = runtime.run(
        event_type="user_message",
        persona_id="sarah_taylor_001",
        user_id="eval_user",
        conversation_id=conv["conversation_id"],
        incoming_message=text,
        user_message_id=msg["message_id"],
    )
    reply = result.get("generated_response") or ""
    assert reply.strip()

    score = client.complete_json(
        system=(
            "Score the assistant dating-app reply JSON. "
            "Return {relevance:0-5, naturalness:0-5, leakage:0-5} where leakage 5 means "
            "no unrelated bio/employer/zodiac facts. No other keys."
        ),
        user=json.dumps({"user": text, "reply": reply}),
        temperature=0.0,
    )
    assert int(score.get("relevance", 0)) >= 3
    assert int(score.get("naturalness", 0)) >= 3
    assert int(score.get("leakage", 0)) >= 3
