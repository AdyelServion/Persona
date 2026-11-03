"""Detection helpers for 'are you AI?' / 'who created you?' style probes."""

from __future__ import annotations

import re

# General-knowledge asks — not Sarah's nature-of-being
_META_IDENTITY_EXCLUDE = re.compile(
    r"\bwhat\s+is\s+(?:an?\s+)?(?:artificial\s+intelligence|ai)\b|"
    r"\bexplain\s+(?:ai|artificial\s+intelligence)\b|"
    r"\bhow\s+does\s+(?:ai|artificial\s+intelligence)\b|"
    r"\bdefine\s+(?:ai|artificial\s+intelligence)\b",
    re.I,
)

_META_IDENTITY = re.compile(
    r"\bwho\s+(?:created|made|built)\s+you\b|"
    r"\b(?:created|made|built)\s+you\b|"
    r"\bare\s+you\s+(?:an?\s+)?(?:ai|artificial\s+intelligence|bot|robot|chatbot|language\s+model|gpt|computer\s+program)\b|"
    r"\bare\s+you\s+(?:even\s+)?(?:real|human|a\s+person|a\s+real\s+person)\b|"
    r"\b(?:you(?:'re|\s+are)\s+(?:an?\s+)?(?:ai|bot|robot|chatbot|not\s+real|fake))\b|"
    r"\byou\s+a\s+bot\b|"
    r"\bhuman\s+or\s+ai\b|"
    r"\bai\s+or\s+human\b|"
    r"\bnot\s+a\s+real\s+person\b|"
    r"\bare\s+you\s+just\s+(?:a\s+)?(?:bot|program|ai)\b",
    re.I,
)


def is_meta_identity_question(text: str) -> bool:
    norm = " ".join((text or "").lower().split())
    if not norm:
        return False
    if _META_IDENTITY_EXCLUDE.search(norm):
        return False
    return bool(_META_IDENTITY.search(norm))


def meta_identity_probe(text: str) -> str:
    """creation | ai_accusation | human_check"""
    norm = " ".join((text or "").lower().split())
    if re.search(r"\bwho\s+(?:created|made|built)\s+you\b", norm) or re.search(
        r"\b(?:created|made|built)\s+you\b", norm
    ):
        return "creation"
    if re.search(r"\bhuman\s+or\s+ai\b|\bai\s+or\s+human\b|\bare\s+you\s+human\b", norm):
        return "human_check"
    return "ai_accusation"
