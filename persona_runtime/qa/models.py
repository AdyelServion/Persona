"""Pydantic models for persona QA suites, steps, assertions, and results."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AssertionStatus = Literal["pass", "fail", "blocked", "not_applicable", "needs_review"]
CaseStatus = Literal["passed", "failed", "blocked", "skipped"]
RunStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
Severity = Literal["critical", "high", "medium", "low", "needs_review"]
EvaluationMethod = Literal["deterministic", "llm"]
FactSource = Literal["canonical", "clock", "world", "literal", "habit", "transport", "employment"]


class FactRef(BaseModel):
    """Reference resolved at runtime from cloned persona / clock / world state."""

    source: FactSource
    fact_id: str | None = None
    field: str | None = None
    path: str | None = None
    value: Any = None
    habit_id: str | None = None


class AssertionDef(BaseModel):
    type: str
    path: str | None = None
    expected: Any = None
    expected_ref: FactRef | None = None
    required: bool = True
    evaluation_mode: Literal["deterministic", "live"] = "deterministic"
    min_confidence: float = 0.7
    options: dict[str, Any] = Field(default_factory=dict)


class StepDef(BaseModel):
    order: int
    step_type: str = "user_message"
    user_message: str | None = None
    action: str | None = None
    expected_facts: dict[str, Any] = Field(default_factory=dict)
    forbidden_facts: dict[str, Any] = Field(default_factory=dict)
    expected_behavior: str | dict[str, Any] | None = None
    expected_state_changes: dict[str, Any] = Field(default_factory=dict)
    wait_for_event: dict[str, Any] = Field(default_factory=dict)
    assertions: list[AssertionDef] = Field(default_factory=list)
    action_params: dict[str, Any] = Field(default_factory=dict)


class TestCaseDef(BaseModel):
    test_key: str
    category: str
    title: str
    description: str = ""
    priority: int = 50
    severity: Severity = "medium"
    preconditions: dict[str, Any] = Field(default_factory=dict)
    setup_actions: list[dict[str, Any]] = Field(default_factory=list)
    assertions: list[AssertionDef] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    steps: list[StepDef] = Field(default_factory=list)
    is_active: bool = True
    evaluation_mode: Literal["deterministic", "live", "mixed"] = "deterministic"


class AssertionResult(BaseModel):
    type: str
    status: AssertionStatus
    expected: Any = None
    actual: Any = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    evaluation_method: EvaluationMethod = "deterministic"
    confidence: float | None = None
    explanation: str = ""
    path: str | None = None


class LedgerClaim(BaseModel):
    subject: str
    attribute: str
    value: Any
    source: str
    timestamp: datetime | None = None
    confidence: float = 1.0
    status: Literal[
        "canonical", "simulated", "planned", "completed", "uncertain", "stated"
    ] = "stated"
    conversation_id: str | None = None
    message_id: str | None = None
