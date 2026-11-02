"""Per-persona typing register. Spelling variation is instructed, never injected."""

from __future__ import annotations

import re
from typing import Any

# Missing keys on a stored document. A persona with no document is not given this layer.
FIELD_DEFAULTS: dict[str, Any] = {
    "style": "neutral",
    "emoji_enabled": True,
    "lowercase_preference": "standard",
    "casual_contractions_enabled": True,
    "informal_abbreviations_enabled": False,
    "slang_intensity": "none",
    "punctuation_style": "standard",
    "intentional_typo_rate": 0.0,
    "max_intentional_typos_per_message": 0,
    "allow_sentence_fragments": False,
    "allow_short_messages": True,
    "allow_multiple_bubbles": True,
    "protect_factual_accuracy": True,
}

SARAH_TYPING_STYLE: dict[str, Any] = {
    "style": "casual_gen_z",
    "emoji_enabled": False,
    "lowercase_preference": "frequent_but_variable",
    "casual_contractions_enabled": True,
    "informal_abbreviations_enabled": True,
    "slang_intensity": "moderate",
    "punctuation_style": "relaxed",
    "intentional_typo_rate": 0.12,
    "max_intentional_typos_per_message": 1,
    "allow_sentence_fragments": True,
    "allow_short_messages": True,
    "allow_multiple_bubbles": True,
    "protect_factual_accuracy": True,
}

_STYLES = {"neutral", "casual_gen_z", "unspecified"}
_LOWERCASE = {"standard", "frequent_but_variable", "rare"}
_SLANG = {"none", "light", "moderate", "heavy"}
_PUNCTUATION = {"standard", "relaxed"}

_PROTECTED_SLOTS = frozenset(
    {
        "office_location",
        "permanent_identity",
        "zodiac",
        "projects",
        "location_now",
        "transport",
    }
)
_ACCURACY_DOMAINS = frozenset(
    {
        "programming",
        "taxation",
        "management_accounting",
        "budgeting",
        "financial_reporting",
        "reconciliation",
        "variance_analysis",
        "financial_analysis",
        "investing",
    }
)
_CALC = re.compile(
    r"\b(?:calculate|calculation|percent|percentage|how much is|variance|reconcil)\b|[£$]\s*\d|\d+(?:\.\d+)?\s*%",
    re.I,
)
_CLOCK = re.compile(
    r"\b(?:today'?s date|what(?:'s| is) (?:the )?(?:date|time|day)|what day is it|what time is it)\b",
    re.I,
)
_TECH = re.compile(
    r"\b(?:code|script|function|algorithm|c\+\+|python|javascript|spreadsheet formula)\b",
    re.I,
)
_ACCOUNTING_EXPLAIN = re.compile(
    r"\b(?:budget|variance|reconcil|tax return|financial report|management account)\b",
    re.I,
)


def merge_typing_style(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a stored document. Unknown keys are dropped."""
    out = dict(FIELD_DEFAULTS)
    data = raw or {}
    style = str(data.get("style") or out["style"])
    out["style"] = style if style in _STYLES else out["style"]
    if "emoji_enabled" in data:
        out["emoji_enabled"] = bool(data.get("emoji_enabled"))
    lower = str(data.get("lowercase_preference") or out["lowercase_preference"])
    out["lowercase_preference"] = lower if lower in _LOWERCASE else out["lowercase_preference"]
    for flag in (
        "casual_contractions_enabled",
        "informal_abbreviations_enabled",
        "allow_sentence_fragments",
        "allow_short_messages",
        "allow_multiple_bubbles",
        "protect_factual_accuracy",
    ):
        if flag in data:
            out[flag] = bool(data.get(flag))
    slang = str(data.get("slang_intensity") or out["slang_intensity"])
    out["slang_intensity"] = slang if slang in _SLANG else out["slang_intensity"]
    punct = str(data.get("punctuation_style") or out["punctuation_style"])
    out["punctuation_style"] = punct if punct in _PUNCTUATION else out["punctuation_style"]
    try:
        rate = float(data.get("intentional_typo_rate", out["intentional_typo_rate"]))
    except (TypeError, ValueError):
        rate = float(out["intentional_typo_rate"])
    out["intentional_typo_rate"] = max(0.0, min(1.0, rate))
    try:
        cap = int(data.get("max_intentional_typos_per_message", out["max_intentional_typos_per_message"]))
    except (TypeError, ValueError):
        cap = int(out["max_intentional_typos_per_message"])
    out["max_intentional_typos_per_message"] = max(0, min(2, cap))
    return out


def load_typing_style(persona_repo: Any, persona_id: str) -> dict[str, Any] | None:
    """Return the merged style, or None when this persona has no document."""
    try:
        doc = persona_repo.get_typing_style(persona_id)
    except Exception:  # noqa: BLE001
        return None
    if not doc or not isinstance(doc.get("params"), dict):
        return None
    return merge_typing_style(doc["params"])


def typos_allowed_for_turn(style: dict[str, Any] | None, state: dict[str, Any]) -> bool:
    """False on turns where a slip could change a fact, figure, name, or date."""
    if not style:
        return False
    if float(style.get("intentional_typo_rate") or 0) <= 0:
        return False
    if int(style.get("max_intentional_typos_per_message") or 0) <= 0:
        return False
    if not style.get("protect_factual_accuracy", True):
        return True

    decision = state.get("capability_decision") or {}
    classification = decision.get("classification") or {}
    if decision.get("high_stakes") or classification.get("high_stakes"):
        return False
    request = classification.get("request_type") or decision.get("request_type")
    if request == "produce_artifact":
        return False
    domain = str(classification.get("domain") or decision.get("domain") or "").lower()
    matched = str(classification.get("matched_domain") or "").lower()
    if domain in _ACCURACY_DOMAINS or matched in _ACCURACY_DOMAINS:
        return False

    incoming = state.get("incoming_message") or ""
    if _CALC.search(incoming) or _CLOCK.search(incoming) or _TECH.search(incoming):
        return False
    if _ACCOUNTING_EXPLAIN.search(incoming):
        return False

    understanding = state.get("understanding") or {}
    targets = {t for t in (understanding.get("question_targets") or []) if t and t != "none"}
    primary = understanding.get("question_target")
    if primary and primary != "none":
        targets.add(primary)
    if targets & _PROTECTED_SLOTS:
        return False

    for answer in (state.get("response_plan") or {}).get("answers") or []:
        slot = str(answer.get("slot") or "")
        if slot in _PROTECTED_SLOTS:
            return False
        direct = str(answer.get("direct_answer") or "")
        if re.search(r"\d", direct) or "£" in direct or "$" in direct:
            return False
    return True


def typing_style_brief(style: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Compact prompt view. typos_allowed is decided for this turn only."""
    allowed = typos_allowed_for_turn(style, state)
    return {
        "style": style.get("style"),
        "emoji_enabled": bool(style.get("emoji_enabled")),
        "lowercase_preference": style.get("lowercase_preference"),
        "casual_contractions_enabled": bool(style.get("casual_contractions_enabled")),
        "informal_abbreviations_enabled": bool(style.get("informal_abbreviations_enabled")),
        "slang_intensity": style.get("slang_intensity"),
        "punctuation_style": style.get("punctuation_style"),
        "intentional_typo_rate": style.get("intentional_typo_rate"),
        "max_intentional_typos_per_message": style.get("max_intentional_typos_per_message"),
        "typos_allowed": allowed,
        "allow_sentence_fragments": bool(style.get("allow_sentence_fragments")),
        "allow_short_messages": bool(style.get("allow_short_messages")),
        "allow_multiple_bubbles": bool(style.get("allow_multiple_bubbles")),
        "note": (
            "Casual wording still applies. Spell every fact, number, name, date, and "
            "technical term correctly."
            if not allowed
            else (
                "At most one minor informal spelling in this message, and only if it "
                "fits. Do not add one just to meet the rate."
            )
        ),
    }
