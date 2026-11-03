"""Persona knowledge / capability profile and per-turn capability decision models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["core", "related", "general", "interest"]
Depth = Literal["awareness", "basic", "working", "expert"]
Category = Literal["A", "B", "C", "D", "E", "F", "U"]
Strategy = Literal[
    "answer_confident",
    "answer_basic_with_limits",
    "answer_general",
    "answer_from_persona",
    "decline_naturally",
    "safe_general_info",
]

CATEGORY_LABELS: dict[str, str] = {
    "A": "core_professional_expertise",
    "B": "related_professional_knowledge",
    "C": "general_everyday_knowledge",
    "D": "casual_conversation_personal_interests",
    "E": "outside_expertise",
    "F": "high_stakes_professional",
    "U": "uncertain_domain",
}

CATEGORY_NAMES: dict[str, str] = {
    "A": "CORE_DOMAIN",
    "B": "RELATED_DOMAIN",
    "C": "EVERYDAY_SOCIAL",
    "D": "PERSONAL_CONTEXT",
    "E": "OUTSIDE_DOMAIN",
    "F": "HIGH_STAKES",
    "U": "UNCERTAIN",
}

NAME_TO_CATEGORY: dict[str, str] = {v: k for k, v in CATEGORY_NAMES.items()}

DEPTH_ORDER: list[str] = ["awareness", "basic", "working", "expert"]


class RestrictedDomain(BaseModel):
    domain_id: str
    keywords: list[str] = Field(default_factory=list)


class KnowledgeDomain(BaseModel):
    domain_id: str
    label: str
    tier: Tier
    level: float = Field(ge=0.0, le=1.0)
    source: str = "general_exposure"
    keywords: list[str] = Field(default_factory=list)
    max_depth: Depth = "basic"


class CapabilityProfile(BaseModel):
    persona_id: str
    education: str = ""
    profession: str = ""
    industry: str = ""
    profession_aliases: list[str] = Field(default_factory=list)
    domains: list[KnowledgeDomain] = Field(default_factory=list)
    restricted_domains: list[RestrictedDomain] = Field(default_factory=list)
    high_stakes_domains: list[str] = Field(default_factory=list)
    experience_claims_allowed: list[str] = Field(default_factory=list)
    never_claim: list[str] = Field(default_factory=list)
    fallback_styles: list[str] = Field(default_factory=list)
    limitation_templates: dict[str, list[str]] = Field(default_factory=dict)
    general_assistant_mode: bool = False
    unsupported_request_behavior: str = "natural_persona_limitation"
    uncertain_domain_behavior: str = "deny_substantive_answer"

    def domain(self, domain_id: str) -> KnowledgeDomain | None:
        for d in self.domains:
            if d.domain_id == domain_id:
                return d
        return None

    def by_tier(self, tier: str) -> list[KnowledgeDomain]:
        return [d for d in self.domains if d.tier == tier]

    def restricted_domain_ids(self) -> set[str]:
        return {r.domain_id for r in self.restricted_domains}


class CapabilityDecision(BaseModel):
    category: Category = "C"
    category_label: str = CATEGORY_LABELS["C"]
    category_name: str = CATEGORY_NAMES["C"]
    domain: str = "general"
    matched_domain: str | None = None
    level: float | None = None
    request_type: str = "explain"
    request_depth: str = "basic"
    allowed_depth: Depth = "basic"
    strategy: Strategy = "answer_general"
    may_produce_artifacts: bool = False
    must_clarify: str | None = None
    high_stakes: str | None = None
    forbidden_claims: list[str] = Field(default_factory=list)
    curiosity_hint: str | None = None
    user_domain: str | None = None
    fallback_style: str | None = None
    reasons: list[str] = Field(default_factory=list)
    classification: dict[str, Any] = Field(default_factory=dict)
    capability_blocked: bool = False
    limitation_topic: str | None = None
    limitation_path: str | None = None
