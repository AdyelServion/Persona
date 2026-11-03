"""Post-generation checks that the reply obeys the turn's capability policy."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.capability.policy import _pick_fallback_style

_CODE_FENCE = re.compile(r"```")
_CODE_MARKERS = [
    re.compile(r"#include\s*<", re.I),
    re.compile(r"\bcout\s*<<"),
    re.compile(r"\bstd::"),
    re.compile(r"\bint\s+main\s*\("),
    re.compile(r"\bdef\s+\w+\s*\("),
    re.compile(r"\bclass\s+\w+\s*[:{]"),
    re.compile(r"\b(?:public|private|protected)\s+(?:static\s+)?void\b"),
    re.compile(r"\bfor\s*\(\s*int\b"),
    re.compile(r"using\s+namespace\s+std"),
    re.compile(r"\bfn\s+\w+\s*\("),
    re.compile(r"^\s*import\s+\w+", re.M),
    re.compile(r"\{\s*[^}]{0,80};"),
]
_NUMBERED_STEPS = re.compile(r"(?:^|\n)\s*(?:\d+[\).]|[-*])\s+\S")
_EXPERIENCE = [
    re.compile(r"\bwhen i (?:was|used to)\s+(?:cod|program|develop|engineer)", re.I),
    re.compile(r"\bi(?:'ve| have) (?:built|developed|written|shipped|coded)\s+(?:a |an |the )?(?:app|application|website|system|api|program)", re.I),
    re.compile(r"\bi (?:used to|once) (?:code|program|develop|practi[cs]e law|diagnose)", re.I),
    re.compile(r"\bin my (?:days|years) as (?:a |an )?(?:developer|programmer|engineer|lawyer|doctor)", re.I),
    re.compile(r"\bwhen i (?:built|developed|wrote) (?:a |an |the )?(?:mobile )?(?:app|application)", re.I),
]
_QUALIFICATION = re.compile(
    r"\b(?:as a |i(?:'m| am) (?:a |an )?|i work as (?:a |an )?)"
    r"(software engineer|developer|programmer|backend engineer|lawyer|solicitor|"
    r"doctor|physician|nurse|tax adviser|tax advisor|investment adviser|"
    r"investment advisor|architect)\b",
    re.I,
)
_HIGH_STAKES = [
    re.compile(r"\byou (?:should|must) (?:take|buy|sell|invest|file|sue)\b", re.I),
    re.compile(r"\btake\s+\d+\s*(?:mg|ml|tablets?)\b", re.I),
    re.compile(r"\bthis is (?:definitely )?(?:cancer|a heart attack|illegal)\b", re.I),
    re.compile(r"\binvest (?:in|everything)\b", re.I),
    re.compile(r"\bfile (?:your )?(?:taxes|tax return) (?:by|with|on)\b", re.I),
    re.compile(r"\byou have (?:stage|type)\b", re.I),
]
_JURISDICTION = [
    re.compile(r"\bhmrc\b", re.I),
    re.compile(r"\birs\b", re.I),
    re.compile(r"\bself[- ]assessment\b", re.I),
    re.compile(r"\bform 1040\b", re.I),
    re.compile(r"\bgov\.uk/tax\b", re.I),
    re.compile(r"\binternal revenue\b", re.I),
]
_ROBOTIC = [
    re.compile(r"\bas an ai(?: language model)?\b", re.I),
    re.compile(r"\bas a language model\b", re.I),
    re.compile(r"\bi (?:cannot|can't|am unable to) (?:provide|assist|help|write|generate)\b", re.I),
    re.compile(r"\boutside my expertise\b", re.I),
    re.compile(r"\bi recommend consulting a professional\b", re.I),
    re.compile(r"\bthis (?:subject|topic) is outside my\b", re.I),
]
_NATURAL_LIMIT = re.compile(
    r"\b(?:isn't really|is not really|not really my|beyond me|no idea|haven't really|havent really|"
    r"wrong person|outside my (?:world|area)|not my (?:thing|department|area))\b",
    re.I,
)
_FILING_STEPS = re.compile(
    r"\b(?:submit|file|filing|online|website|deadline|tax authority|paper (?:tax )?return)\b",
    re.I,
)
_ASKS_WHERE = re.compile(
    r"\b(?:where (?:do you|are you)|which country|depends on where|where you live)\b",
    re.I,
)
_GENERIC_FALLBACKS = [
    "thats not really something id know much about",
    "haha i honestly have no idea about that",
    "youre asking someone who spends most of her day on financial reports",
    "i've actually never looked into that",
]
_TEACHING_LEAK = re.compile(
    r"\b(?:but you could|you would typically|you can use|try using|use a loop|for loop|"
    r"print the multiples|step by step|here'?s how|something like this|pseudocode)\b",
    re.I,
)
_REFUSAL_THEN_ANSWER = re.compile(
    r"\b(?:i can'?t|cannot|wouldn'?t know how).{0,80}\bbut\b",
    re.I | re.DOTALL,
)
_SQL_SCAFFOLD = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\s+.+\bFROM\b", re.I)


def _opening(reply: str, n: int = 60) -> str:
    line = (reply or "").strip().split("\n")[0].strip()
    return re.sub(r"\s+", " ", line)[:n].lower()


def _profession_aliases(profile: dict[str, Any] | None) -> set[str]:
    profile = profile or {}
    aliases = {str(a).lower() for a in (profile.get("profession_aliases") or []) if a}
    if profile.get("profession"):
        aliases.add(str(profile["profession"]).lower())
    return aliases


def validate_blocked_reply(state: dict[str, Any], reply: str) -> list[str]:
    """Strict validation for capability-blocked turns."""
    failures = list(validate_capability(state, reply))
    lower = (reply or "").lower()
    if _TEACHING_LEAK.search(reply or ""):
        failures.append("capability_teaching_leak")
    if _REFUSAL_THEN_ANSWER.search(reply or ""):
        failures.append("capability_refusal_then_answer")
    if _SQL_SCAFFOLD.search(reply or ""):
        failures.append("capability_artifact_leak")
    if len(reply or "") > 280 and not _NATURAL_LIMIT.search(reply or ""):
        failures.append("capability_depth_exceeded")
    if "designated expertise" in lower or "outside my expertise" in lower:
        failures.append("capability_robotic_disclaimer")
    return list(dict.fromkeys(failures))


def validate_capability_messages(state: dict[str, Any], messages: list[str]) -> list[str]:
    """Validate each bubble and the joined turn."""
    failures: list[str] = []
    texts = [t for t in messages if t and str(t).strip()]
    for text in texts:
        failures.extend(validate_capability(state, text))
    if state.get("capability_decision", {}).get("capability_blocked"):
        joined = "\n".join(texts)
        failures.extend(validate_blocked_reply(state, joined))
        if len(texts) > 1:
            first, rest = texts[0], "\n".join(texts[1:])
            if _NATURAL_LIMIT.search(first) and (
                _CODE_FENCE.search(rest)
                or any(p.search(rest) for p in _CODE_MARKERS)
                or _TEACHING_LEAK.search(rest)
            ):
                failures.append("capability_bubble_leak")
    else:
        if texts:
            failures.extend(validate_capability(state, "\n".join(texts)))
    return list(dict.fromkeys(failures))


def validate_capability(state: dict[str, Any], reply: str) -> list[str]:
    """Return structured failure codes. Empty list means the reply is allowed."""
    decision = state.get("capability_decision") or {}
    if not decision.get("category"):
        return []
    reply = reply or ""
    lower = reply.lower()
    failures: list[str] = []
    category = str(decision.get("category") or "")
    profile = state.get("capability_profile") or {}
    allowed_exp = {str(x) for x in (profile.get("experience_claims_allowed") or [])}
    matched = decision.get("matched_domain")

    if not decision.get("may_produce_artifacts"):
        if _CODE_FENCE.search(reply) or any(p.search(reply) for p in _CODE_MARKERS):
            failures.append("capability_artifact_leak")

    blocked = bool(decision.get("capability_blocked")) or category in {"E", "U"}
    if category == "E" or blocked:
        steps = _NUMBERED_STEPS.findall(reply)
        long_technical = len(reply) > 120 and bool(
            re.search(
                r"\b(?:algorithm|pointer|template|metaprogram|allocator|kernel|protocol|"
                r"qubit|decoherence|compiler|dirac|hamiltonian)\b",
                lower,
            )
        )
        no_limit = not _NATURAL_LIMIT.search(reply)
        if len(steps) > 3 or long_technical or (no_limit and len(reply) > 220):
            failures.append("capability_depth_exceeded")

    if matched not in allowed_exp:
        if any(p.search(reply) for p in _EXPERIENCE):
            failures.append("capability_invented_experience")

    job = _QUALIFICATION.search(reply)
    if job:
        claimed = job.group(1).lower()
        aliases = _profession_aliases(profile)
        if claimed not in aliases and not any(claimed in a or a in claimed for a in aliases if a):
            failures.append(f"capability_false_qualification:{claimed}")

    if category == "F" and any(p.search(reply) for p in _HIGH_STAKES):
        failures.append("capability_high_stakes_advice")

    if decision.get("must_clarify") == "jurisdiction":
        if any(p.search(reply) for p in _JURISDICTION) or (
            _FILING_STEPS.search(reply) and not _ASKS_WHERE.search(reply)
        ):
            failures.append("capability_assumed_jurisdiction")
        if not _ASKS_WHERE.search(reply) or len(reply.strip()) < 50:
            failures.append("capability_missing_jurisdiction_ask")

    if decision.get("user_domain") and category in {"B", "C", "D"} and len(reply.strip()) < 40:
        failures.append("capability_thin_reply")

    if category != "F" and any(p.search(reply) for p in _ROBOTIC):
        failures.append("capability_robotic_disclaimer")

    if category in {"E", "U"} and not decision.get("capability_blocked"):
        conv = state.get("conversation_context") or {}
        recent = [str(x).lower() for x in (conv.get("recent_capability_declines") or [])]
        opening = _opening(reply)
        if opening and any(opening[:40] and opening[:40] in r for r in recent):
            failures.append("repeated_capability_decline")

    return list(dict.fromkeys(failures))


def capability_fallback_reply(state: dict[str, Any]) -> str | None:
    """Natural decline / limit line when generation or repair cannot be trusted."""
    decision = state.get("capability_decision") or {}
    category = decision.get("category")
    user_domain = decision.get("user_domain")
    if decision.get("must_clarify") == "jurisdiction":
        return (
            "It depends a bit on where you live. I'm more on the accounting side "
            "than the actual filing process. Where are you based?"
        )
    if user_domain and category in {"B", "C", "D"}:
        return (
            f"I only know the basics of that from the outside. I'm much more of a "
            f"numbers person. What kind of work do you do as {user_domain}?"
        )
    if category not in {"E", "F", "U"}:
        return None
    profile = state.get("capability_profile") or {}
    conv = state.get("conversation_context") or {}
    recent = list(conv.get("recent_capability_declines") or [])
    topic = str((decision.get("classification") or {}).get("topic") or "that")
    style = decision.get("fallback_style")
    if not style:
        from persona_runtime.capability.schemas import CapabilityProfile

        try:
            parsed = CapabilityProfile.model_validate({**profile, "persona_id": profile.get("persona_id") or "x"})
            style = _pick_fallback_style(parsed, state.get("incoming_message") or "", recent)
            if style:
                style = style.replace("{topic}", topic)
        except Exception:  # noqa: BLE001
            style = None
    if not style:
        used = {r.lower() for r in recent}
        pool = [s for s in _GENERIC_FALLBACKS if s.lower() not in used] or _GENERIC_FALLBACKS
        idx = abs(hash(state.get("incoming_message") or topic)) % len(pool)
        style = pool[idx]
    if category == "F":
        return f"{style} For something this specific you'd want someone properly qualified."
    if user_domain:
        return f"{style} What kind of work do you usually do?"
    return style


_LEGACY_JOBS = re.compile(
    r"\bi(?:'m| am| work as) (?:a |an )?(software engineer|doctor|lawyer|teacher|nurse)\b",
    re.I,
)


def occupation_claim_failure(state: dict[str, Any], reply: str) -> str | None:
    """Contradiction if the persona claims a job that is not their configured profession."""
    m = _QUALIFICATION.search(reply or "") or _LEGACY_JOBS.search(reply or "")
    if not m:
        return None
    claimed = m.group(1).lower()
    profile = state.get("capability_profile") or {}
    aliases = _profession_aliases(profile)
    title = profile.get("profession") or "Management Accountant"
    if aliases and (claimed in aliases or any(claimed in a or a in claimed for a in aliases if a)):
        return None
    if not aliases and claimed in {"software engineer", "doctor", "lawyer", "teacher", "nurse"}:
        return f"contradicts_canonical:occupation!={title} ({m.group(1)})"
    if aliases:
        return f"contradicts_canonical:occupation!={title} ({m.group(1)})"
    return None
