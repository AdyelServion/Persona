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

_MODEL_PROBE = re.compile(
    r"\b(?:what|which)\s+(?:llm|model|gpt|ai\s+model|language\s+model)\b|"
    r"\b(?:llm|model|gpt)\s+(?:is\s+)?(?:integrated|built|powering|running)\b|"
    r"\b(?:integrated|powered|built)\s+(?:into|in)\s+you\b|"
    r"\bwhat\s+(?:powers|runs)\s+you\b|"
    r"\bwhich\s+model\s+are\s+you\b|"
    r"\bare\s+you\s+(?:chatgpt|grok|claude|gemini|copilot|gpt[-\s]?\d)\b|"
    r"\bwhat\s+(?:ai|model)\s+(?:are\s+you|is\s+this|do\s+you\s+use)\b",
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
    r"\bare\s+you\s+just\s+(?:a\s+)?(?:bot|program|ai)\b|"
    + _MODEL_PROBE.pattern,
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
    """creation | human_check | model_probe | ai_accusation"""
    norm = " ".join((text or "").lower().split())
    if re.search(r"\bwho\s+(?:created|made|built)\s+you\b", norm) or re.search(
        r"\b(?:created|made|built)\s+you\b", norm
    ):
        return "creation"
    if re.search(r"\bhuman\s+or\s+ai\b|\bai\s+or\s+human\b|\bare\s+you\s+human\b", norm):
        return "human_check"
    if _MODEL_PROBE.search(norm):
        return "model_probe"
    return "ai_accusation"
