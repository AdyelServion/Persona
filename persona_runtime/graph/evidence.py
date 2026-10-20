"""Recall claim verification helpers."""

from __future__ import annotations

import re
from typing import Any

RECALL_PATTERNS = [
    re.compile(r"\bi remember (?:when |you |that )", re.I),
    re.compile(r"\byou told me\b", re.I),
    re.compile(r"\byou mentioned\b", re.I),
    re.compile(r"\blast time you\b", re.I),
    re.compile(r"\byour (?:interview|trip|holiday|vacation|job)\b", re.I),
    re.compile(r"\bhow did (?:the|your) interview\b", re.I),
]

FALLBACK_NO_MEMORY = (
    "I don't think I have that detail from our previous conversations."
)


def reply_has_recall_language(text: str) -> bool:
    return any(p.search(text or "") for p in RECALL_PATTERNS)


def plan_claims_are_grounded(response_plan: dict[str, Any], allowed_ids: list[str]) -> bool:
    allowed = set(allowed_ids or [])
    for claim in response_plan.get("memory_claims") or []:
        eid = (claim or {}).get("evidence_memory_id")
        if not eid or eid not in allowed:
            return False
    return True


def filter_ungrounded_claims(response_plan: dict[str, Any], allowed_ids: list[str]) -> dict[str, Any]:
    allowed = set(allowed_ids or [])
    plan = dict(response_plan or {})
    grounded = []
    for claim in plan.get("memory_claims") or []:
        eid = (claim or {}).get("evidence_memory_id")
        if eid and eid in allowed:
            grounded.append(claim)
    plan["memory_claims"] = grounded
    return plan
