"""Capability decision: LLM classification + persona profile + fixed rules -> response strategy.

The LLM only *describes* the question (domain, depth, request type, high-stakes flag,
confidence). The category and strategy are decided here, deterministically, from the
persona's own capability profile, so each persona follows its own boundaries.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from persona_runtime.capability.schemas import (
    CATEGORY_LABELS,
    DEPTH_ORDER,
    CapabilityDecision,
    CapabilityProfile,
)
from persona_runtime.graph.reality import EMPLOYMENT_TARGETS, NOW_TARGETS, PROFILE_TARGETS

REQUEST_TYPES = {"explain", "produce_artifact", "advice", "persona_experience", "opinion", "chit_chat"}
REQUEST_DEPTHS = ["basic", "intermediate", "advanced", "expert"]
HIGH_STAKES = {"medical", "legal", "investment", "tax"}

_CLASSIFY_SPEECH = {"question", "request", "self_disclosure", "unclear", "continuation"}
_PERSONA_TARGETS = set(NOW_TARGETS) | set(EMPLOYMENT_TARGETS) | set(PROFILE_TARGETS) | {"habit"}

_ARTIFACT_VERB = re.compile(
    r"\b(?:write|code|build|create|make|generate|draft|implement|program|debug|fix)\b", re.I
)
_CODE_TERMS = re.compile(
    r"\b(?:code|script|program|function|class|app|application|website|api|algorithm|sql|query)\b"
    r"|c\+\+|\bpython\b|\bjava(?:script)?\b|\brust\b|\bgolang\b",
    re.I,
)
_LEGAL_DOC = re.compile(r"\b(?:contract|will|lease|nda|legal letter|terms and conditions)\b", re.I)
_ADVANCED = re.compile(
    r"\b(?:advanced|in depth|in-depth|deep dive|metaprogramming|internals|architecture|"
    r"mathematically|derive|proof|optimi[sz]e|low[- ]level|template)\b",
    re.I,
)
_MEDICAL = re.compile(
    r"\b(?:diagnos\w*|symptom\w*|dosage|dose|medication|prescri\w+|chest pain|rash|tumou?r|"
    r"is it cancer|should i take)\b",
    re.I,
)
_LEGAL = re.compile(r"\b(?:sue|lawsuit|legal advice|court|solicitor|lawyer|liable|custody)\b", re.I)
_INVEST = re.compile(
    r"\b(?:should i (?:buy|sell|invest)|which (?:stock|shares|crypto)|best (?:stock|investment)|"
    r"invest in)\b",
    re.I,
)
_TAX = re.compile(r"\b(?:tax|taxes|tax return|vat|self assessment|hmrc|irs)\b", re.I)
_TAX_FILING = re.compile(r"\b(?:submit|file|filing|pay|claim|return)\b", re.I)
_EXPERIENCE_Q = re.compile(
    r"\b(?:have you ever|did you ever|have you (?:built|made|developed|worked|done|written)|"
    r"do you (?:code|program))\b",
    re.I,
)
_USER_ROLE = re.compile(
    r"\bi(?:'m| am)\s+(?:actually\s+)?(?:a|an)\s+([a-z][a-z \-]{2,40}?)(?:[.,!?]|\s+and\b|\s+so\b|$)",
    re.I,
)
_CLOCK_Q = re.compile(
    r"\b(?:today'?s date|what(?:'s| is) (?:the )?(?:date|time|day)|what day is it|what time is it)\b",
    re.I,
)


def neutral_classification() -> dict[str, Any]:
    return {
        "domain": "general",
        "subdomain": None,
        "matched_domain": None,
        "request_type": "explain",
        "depth": "basic",
        "requires_specialist": False,
        "high_stakes": None,
        "needs_jurisdiction": False,
        "user_self_disclosure_domain": None,
        "model_confidence": 0.5,
    }


def should_assess(state: dict[str, Any]) -> str:
    """'skip' | 'persona' (self-questions answered by grounded layers) | 'classify'."""
    if not state.get("capability_profile"):
        return "skip"
    if state.get("event_type") != "user_message" or state.get("busy_ack") or state.get("skip_response"):
        return "skip"
    understanding = state.get("understanding") or {}
    speech = understanding.get("speech_act") or ""
    if speech not in _CLASSIFY_SPEECH:
        return "skip"
    targets = set(understanding.get("question_targets") or [])
    if understanding.get("question_target") and understanding.get("question_target") != "none":
        targets.add(understanding["question_target"])
    message = state.get("incoming_message") or ""
    if _CLOCK_Q.search(message):
        return "skip"
    if targets and targets <= _PERSONA_TARGETS and not _EXPERIENCE_Q.search(message):
        return "persona"
    return "classify"


def classification_payload(state: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    recent = [
        {"sender": m.get("sender"), "content": (m.get("content") or "")[:200]}
        for m in (state.get("recent_messages") or [])[-4:]
    ]
    user_occupation = next(
        (
            c.get("object")
            for c in (state.get("user_profile_card") or [])
            if (c.get("memory_key") or c.get("predicate")) == "occupation"
        ),
        None,
    )
    return {
        "message": state.get("incoming_message") or "",
        "recent": recent,
        "domain_catalogue": [
            {"domain_id": d.get("domain_id"), "label": d.get("label")}
            for d in (profile.get("domains") or [])
        ],
        "known_user_occupation": user_occupation,
    }


def heuristic_classification(message: str) -> dict[str, Any]:
    """Conservative keyword signals merged with the LLM view (never relied on alone)."""
    text = message or ""
    out = neutral_classification()
    out["model_confidence"] = None
    if _ARTIFACT_VERB.search(text) and (_CODE_TERMS.search(text) or _LEGAL_DOC.search(text)):
        out["request_type"] = "produce_artifact"
        out["requires_specialist"] = True
    if _ADVANCED.search(text):
        out["depth"] = "advanced"
    if _EXPERIENCE_Q.search(text):
        out["request_type"] = "persona_experience"
    if _MEDICAL.search(text):
        out["high_stakes"] = "medical"
    elif _LEGAL.search(text) or (_LEGAL_DOC.search(text) and out["request_type"] == "produce_artifact"):
        out["high_stakes"] = "legal"
    elif _INVEST.search(text):
        out["high_stakes"] = "investment"
    elif _TAX.search(text) and _TAX_FILING.search(text):
        out["high_stakes"] = "tax"
        out["needs_jurisdiction"] = True
    role = _USER_ROLE.search(text)
    if role:
        out["user_self_disclosure_domain"] = role.group(1).strip()
    return out


def _deeper(a: str, b: str) -> str:
    ia = REQUEST_DEPTHS.index(a) if a in REQUEST_DEPTHS else 0
    ib = REQUEST_DEPTHS.index(b) if b in REQUEST_DEPTHS else 0
    return REQUEST_DEPTHS[max(ia, ib)]


def merge_classification(llm: dict[str, Any] | None, heuristic: dict[str, Any]) -> dict[str, Any]:
    """Combine conservatively: either source can raise risk, neither can lower it."""
    llm = dict(llm or {})
    merged = neutral_classification()
    merged.update({k: v for k, v in llm.items() if v is not None})
    rt = str(merged.get("request_type") or "explain").lower()
    merged["request_type"] = rt if rt in REQUEST_TYPES else "explain"
    if heuristic.get("request_type") in {"produce_artifact", "persona_experience"} and merged["request_type"] in {
        "explain",
        "chit_chat",
        "opinion",
        "advice",
    }:
        merged["request_type"] = heuristic["request_type"]
    depth = str(merged.get("depth") or "basic").lower()
    merged["depth"] = _deeper(depth if depth in REQUEST_DEPTHS else "basic", heuristic.get("depth") or "basic")
    merged["requires_specialist"] = bool(merged.get("requires_specialist")) or bool(
        heuristic.get("requires_specialist")
    )
    hs = merged.get("high_stakes")
    hs = str(hs).lower() if hs else None
    merged["high_stakes"] = hs if hs in HIGH_STAKES else heuristic.get("high_stakes")
    merged["needs_jurisdiction"] = bool(merged.get("needs_jurisdiction")) or bool(
        heuristic.get("needs_jurisdiction")
    )
    if not merged.get("user_self_disclosure_domain"):
        merged["user_self_disclosure_domain"] = heuristic.get("user_self_disclosure_domain")
    try:
        conf = float(llm.get("model_confidence")) if llm.get("model_confidence") is not None else 0.5
    except (TypeError, ValueError):
        conf = 0.5
    merged["model_confidence"] = max(0.0, min(1.0, conf))
    merged["llm_available"] = bool(llm)
    return merged


def _match_domain(classification: dict[str, Any], profile: CapabilityProfile, message: str) -> Any:
    wanted = classification.get("matched_domain")
    if wanted and wanted != "none":
        found = profile.domain(str(wanted))
        if found:
            return found
    hay = f" {(message or '').lower()} {str(classification.get('domain') or '').lower()} {str(classification.get('subdomain') or '').lower()} "
    best = None
    best_len = 0
    for d in profile.domains:
        for kw in d.keywords:
            k = kw.lower()
            if k.strip() and k in hay and len(k) > best_len:
                best, best_len = d, len(k)
    return best


def _cap_depth(max_depth: str, cap: str) -> str:
    return DEPTH_ORDER[min(DEPTH_ORDER.index(max_depth), DEPTH_ORDER.index(cap))]


def _user_location_known(profile_card: list[dict[str, Any]]) -> bool:
    keys = {"lives_in", "location", "city", "country", "home_city"}
    return any((c.get("memory_key") or c.get("predicate")) in keys for c in profile_card or [])


def _pick_fallback_style(profile: CapabilityProfile, message: str, recent: list[str]) -> str | None:
    styles = list(profile.fallback_styles)
    if not styles:
        return None
    used = {r.lower() for r in recent}
    fresh = [s for s in styles if s.split("{")[0].strip().lower() not in used and s.lower() not in used]
    pool = fresh or styles
    idx = int(hashlib.sha1((message or "").encode()).hexdigest(), 16) % len(pool)
    return pool[idx]


def persona_decision(profile_dict: dict[str, Any]) -> dict[str, Any]:
    """Self-questions (activity, office, habits) are answered from grounded persona layers."""
    return CapabilityDecision(
        category="D",
        category_label=CATEGORY_LABELS["D"],
        domain="persona_self",
        strategy="answer_from_persona",
        allowed_depth="working",
        reasons=["grounded_persona_question"],
    ).model_dump()


def decide(
    classification: dict[str, Any] | None,
    profile_dict: dict[str, Any],
    *,
    message: str,
    conversation_context: dict[str, Any] | None = None,
    profile_card: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = CapabilityProfile.model_validate(profile_dict)
    conv = conversation_context or {}
    cls = merge_classification(classification, heuristic_classification(message))
    reasons: list[str] = []
    rt = cls["request_type"]
    depth = cls["depth"]
    advanced = depth in {"advanced", "expert"}
    domain = _match_domain(cls, profile, message)
    level = float(domain.level) if domain else None
    tier = domain.tier if domain else None
    label = domain.label if domain else str(cls.get("domain") or "that")
    topic = str(cls.get("subdomain") or cls.get("domain") or (domain.label if domain else "that")).strip() or "that"

    category = "C"
    strategy = "answer_general"
    allowed_depth = "basic"
    may_artifacts = False
    must_clarify = None
    forbidden: list[str] = []

    hs = cls.get("high_stakes")
    hs_key = "tax_compliance" if hs == "tax" else hs
    hs_active = bool(hs) and (hs_key in profile.high_stakes_domains or hs in profile.high_stakes_domains)
    hs_serious = rt in {"advice", "produce_artifact"} or advanced or bool(cls.get("requires_specialist"))

    if hs_active and hs == "tax" and domain is not None and tier in {"core", "related"} and not advanced:
        # Tax basics sit next to accounting: answer the general idea, never assume a jurisdiction.
        category, strategy = "B", "answer_basic_with_limits"
        allowed_depth = _cap_depth(domain.max_depth, "basic")
        if cls.get("needs_jurisdiction") and not _user_location_known(profile_card or []):
            must_clarify = "jurisdiction"
        reasons.append("tax_related_to_profession")
    elif hs_active and hs_serious:
        category, strategy = "F", "safe_general_info"
        allowed_depth = "basic"
        forbidden.append(f"specialist {hs} advice or professional qualification in {hs}")
        if hs == "tax" and cls.get("needs_jurisdiction") and not _user_location_known(profile_card or []):
            must_clarify = "jurisdiction"
        reasons.append(f"high_stakes:{hs}")
    elif rt == "persona_experience" and not (
        domain is not None and domain.domain_id in profile.experience_claims_allowed and tier == "core"
    ):
        category, strategy = "D", "answer_from_persona"
        allowed_depth = "basic"
        specialist = bool(cls.get("requires_specialist")) or bool(_CODE_TERMS.search(message or ""))
        if (domain is not None and domain.domain_id not in profile.experience_claims_allowed) or (
            domain is None and specialist
        ):
            forbidden.append(f"personal or professional experience with {topic}")
            reasons.append("experience_not_in_profile")
        else:
            reasons.append("experience_allowed")
    elif rt == "produce_artifact" and not (domain and tier == "core" and (level or 0) >= 0.75):
        if cls.get("requires_specialist") or domain is None or (level or 0) < 0.6:
            category, strategy = "E", "decline_naturally"
            allowed_depth = "awareness"
            reasons.append("artifact_outside_core")
        else:
            category, strategy = "B", "answer_basic_with_limits"
            allowed_depth = _cap_depth(domain.max_depth, "basic")
            reasons.append("artifact_in_related_domain")
    elif domain is None:
        if advanced or cls.get("requires_specialist"):
            category, strategy = "E", "decline_naturally"
            allowed_depth = "awareness"
            reasons.append("unmatched_specialist")
        else:
            category, strategy = "C", "answer_general"
            allowed_depth = "basic"
            reasons.append("unmatched_general")
    elif tier == "core" and level >= 0.75:
        category, strategy = "A", "answer_confident"
        allowed_depth = domain.max_depth
        may_artifacts = True
        reasons.append("core_domain")
    elif tier == "interest":
        category, strategy = "D", "answer_from_persona"
        allowed_depth = domain.max_depth
        reasons.append("personal_interest")
    elif tier == "general":
        specialist_advanced = advanced or (
            bool(cls.get("requires_specialist")) and rt not in {"explain", "chit_chat", "opinion"}
        )
        if specialist_advanced and level < 0.6:
            category, strategy = "E", "decline_naturally"
            allowed_depth = _cap_depth(domain.max_depth, "basic")
            reasons.append("advanced_low_knowledge")
        else:
            category, strategy = "C", "answer_general"
            allowed_depth = DEPTH_ORDER[max(DEPTH_ORDER.index(domain.max_depth), DEPTH_ORDER.index("basic"))]
            allowed_depth = _cap_depth(allowed_depth, "working")
            reasons.append("general_knowledge")
    else:
        # related tier, or a core domain below the expertise threshold
        category, strategy = "B", "answer_basic_with_limits"
        allowed_depth = _cap_depth(domain.max_depth, "basic" if advanced else "working")
        reasons.append("related_domain")

    # Low model confidence may only lower confidence, never raise it.
    if cls.get("llm_available") and cls["model_confidence"] < 0.45:
        if category == "A":
            category, strategy = "B", "answer_basic_with_limits"
            may_artifacts = False
            reasons.append("low_confidence_downgrade")

    if category in {"B", "C", "D", "E", "F"} and domain is not None and domain.domain_id not in profile.experience_claims_allowed:
        forbidden.append(f"professional qualifications or practical experience in {domain.label}")
    if category in {"E", "F"}:
        forbidden.extend(profile.never_claim)

    user_domain = cls.get("user_self_disclosure_domain")
    curiosity = None
    if user_domain:
        aliases = {a.lower() for a in profile.profession_aliases} | {profile.profession.lower()}
        if not any(a and a in str(user_domain).lower() for a in aliases):
            curiosity = (
                f"The user works as {user_domain}: be genuinely curious about their work; "
                "discuss it at a general level without adopting it as your own expertise."
            )
            forbidden.append(f"professional expertise in {user_domain}")
    elif category == "E":
        curiosity = "Optionally ask what they are working on or why it interests them."

    recent_declines = list(conv.get("recent_capability_declines") or [])
    style = _pick_fallback_style(profile, message, recent_declines) if category == "E" else None

    return CapabilityDecision(
        category=category,  # type: ignore[arg-type]
        category_label=CATEGORY_LABELS[category],
        domain=str(cls.get("domain") or (domain.domain_id if domain else "general")),
        matched_domain=domain.domain_id if domain else None,
        level=level,
        request_type=rt,
        request_depth=depth,
        allowed_depth=allowed_depth,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        may_produce_artifacts=may_artifacts,
        must_clarify=must_clarify,
        high_stakes=hs if hs_active else None,
        forbidden_claims=list(dict.fromkeys(forbidden)),
        curiosity_hint=curiosity,
        user_domain=user_domain,
        fallback_style=(style.replace("{topic}", topic) if style else None),
        reasons=reasons,
        classification={k: v for k, v in cls.items() if k != "llm_available"} | {"topic": topic, "label": label},
    ).model_dump()


_STRATEGY_POINTS: dict[str, list[str]] = {
    "answer_confident": [
        "answer confidently and practically, the way someone who does this at work would",
        "a short concrete example from day-to-day work is welcome",
    ],
    "answer_basic_with_limits": [
        "share the basics you are reasonably sure about, in plain words",
        "say casually where the specifics go beyond what you know; do not claim specialist expertise",
    ],
    "answer_general": [
        "explain simply in a sentence or two, like an educated friend, not a textbook",
    ],
    "answer_from_persona": [
        "answer from your own configured interests, preferences and background only",
        "do not invent experiences that are not part of your background",
    ],
    "decline_naturally": [
        "casually admit this is not really your area (light humour is fine, vary the wording)",
        "do NOT produce code, step-by-step solutions or expert technical detail",
        "you may say what the thing is in one plain line if you know that much",
    ],
    "safe_general_info": [
        "offer only basic general information, nothing specific to their situation",
        "make it clear naturally that this really needs someone qualified for their case",
        "no diagnoses, legal instructions, specific investment picks or tax-compliance steps",
    ],
}


def apply_capability_to_plan(
    plan: dict[str, Any], decision: dict[str, Any] | None, engagement: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not decision or not decision.get("category"):
        return plan
    plan = dict(plan)
    engagement = engagement or {}
    strategy = decision.get("strategy") or "answer_general"
    points = [p for p in list(plan.get("talking_points") or []) if p != "answer directly"]
    points = list(_STRATEGY_POINTS.get(strategy, [])) + points
    for claim in decision.get("forbidden_claims") or []:
        points.append(f"never claim {claim}")
    if decision.get("must_clarify") == "jurisdiction":
        points.insert(
            0,
            "one line: tax filing depends on the country and you know the accounting side better than the submission process",
        )
        points.insert(0, "ask where they are based (which country) before any filing steps; do not assume a country")
        plan["should_ask_question"] = True
        plan["conversational_move"] = "CLARIFY"
        allowed = list(plan.get("allowed_moves") or [])
        if "CLARIFY" not in allowed:
            plan["allowed_moves"] = allowed + ["CLARIFY"]
    elif decision.get("curiosity_hint"):
        points.append(decision["curiosity_hint"])
        if decision.get("user_domain"):
            points.append(
                "acknowledge their job in a human way and give a one-line general answer; "
                "stay curious without adopting their field"
            )
    if decision.get("category") == "E":
        plan["length"] = "short"
        plan["response_length"] = "short"
        plan["should_answer_directly"] = False
        if decision.get("fallback_style"):
            points.append(f"tone example only (do not copy): {decision['fallback_style']}")
    if decision.get("category") in {"A", "B", "C", "F"}:
        plan["should_answer_directly"] = True
    plan["talking_points"] = points[:14]
    plan["must_not_claim"] = list(
        dict.fromkeys(list(plan.get("must_not_claim") or []) + list(decision.get("forbidden_claims") or []))
    )
    plan["capability"] = {
        "category": decision.get("category"),
        "strategy": strategy,
        "allowed_depth": decision.get("allowed_depth"),
        "may_produce_artifacts": decision.get("may_produce_artifacts"),
    }
    return plan


def policy_brief(decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not decision or not decision.get("category"):
        return None
    rules = {
        "A": "Core expertise: answer confidently and naturally.",
        "B": "Related knowledge: basics only; be honest about limits; no specialist claims.",
        "C": "General knowledge: answer simply and naturally; do not pretend to know nothing.",
        "D": "Personal: use only your configured interests/background; never invent experiences.",
        "E": "Outside expertise: admit it casually and vary the wording; never produce the expert answer (code, solutions, detailed technical content) even if you could.",
        "F": "High-stakes: basic general info only; naturally say their situation needs a qualified professional; no specific advice.",
    }
    return {
        "category": decision.get("category"),
        "category_label": decision.get("category_label"),
        "topic": (decision.get("classification") or {}).get("topic"),
        "strategy": decision.get("strategy"),
        "allowed_depth": decision.get("allowed_depth"),
        "may_produce_artifacts": decision.get("may_produce_artifacts"),
        "must_clarify": decision.get("must_clarify"),
        "forbidden_claims": decision.get("forbidden_claims") or [],
        "curiosity_hint": decision.get("curiosity_hint"),
        "rule": rules.get(str(decision.get("category")), ""),
        "never": [
            "robotic disclaimers such as 'as an AI' or 'outside my expertise'",
            "repeating the same decline wording used earlier in this chat",
        ],
    }
