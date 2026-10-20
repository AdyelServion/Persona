"""Deterministic persona fact disclosure tracking by stable fact_id."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.persona.constants import SEED_CANONICAL_FACTS

# Predicate aliases that map spoken language onto fact ids
FACT_ALIAS_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "PERSONA_FACT_OCCUPATION": [
        re.compile(r"\bmanagement accountant\b", re.I),
        re.compile(r"\bwork(?:ing)? as (?:a |an )?management accountant\b", re.I),
        re.compile(r"\bi(?:'m| am) (?:a |an )?management accountant\b", re.I),
    ],
    "PERSONA_FACT_DEGREE": [
        re.compile(r"\bbsc accounting and finance\b", re.I),
        re.compile(r"\baccounting and finance\b", re.I),
        re.compile(r"\bgraduated with (?:a )?bsc\b", re.I),
        re.compile(r"\bstudied accounting\b", re.I),
    ],
    "PERSONA_FACT_LIVES_IN": [
        re.compile(r"\bliv(?:e|ing) in manchester\b", re.I),
        re.compile(r"\bbeen in manchester\b", re.I),
        re.compile(r"\bin manchester (?:for|now|these)\b", re.I),
    ],
    "PERSONA_FACT_MOVED_MANCHESTER": [
        re.compile(r"\bmoved (?:to|from .+ to) manchester\b", re.I),
        re.compile(r"\brecently moved to manchester\b", re.I),
        re.compile(r"\brelocated to manchester\b", re.I),
    ],
    "PERSONA_FACT_UNIVERSITY": [
        re.compile(r"\buniversity of leeds\b", re.I),
    ],
    "PERSONA_FACT_HOMETOWN": [
        re.compile(r"\bfrom sheffield\b", re.I),
        re.compile(r"\bhometown (?:is |of )?sheffield\b", re.I),
    ],
    "PERSONA_FACT_ZODIAC": [
        re.compile(r"\bi(?:'m| am) an? aries\b", re.I),
        re.compile(r"\ban? aries\b", re.I),
    ],
    "PERSONA_FACT_EMPLOYER": [
        re.compile(r"\bnorthbridge financial group\b", re.I),
        re.compile(r"\bnorthbridge\b", re.I),
    ],
    "PERSONA_FACT_OFFICE": [
        re.compile(r"\b18 alderbrook square\b", re.I),
        re.compile(r"\balderbrook square\b", re.I),
        re.compile(r"\bmanchester finance office\b", re.I),
    ],
    "PERSONA_FACT_DOB": [
        re.compile(r"\bapril\s+17,?\s*1998\b", re.I),
        re.compile(r"\b17(?:th)?\s+(?:of\s+)?april\s+1998\b", re.I),
        re.compile(r"\b1998-04-17\b", re.I),
    ],
}

QUESTION_PATTERNS = re.compile(
    r"[^.!?]*\?",
    re.S,
)


def fact_catalog() -> dict[str, dict[str, Any]]:
    return {
        f["fact_id"]: f
        for f in SEED_CANONICAL_FACTS
        if f.get("fact_id")
    }


def disclosed_fact_ids(facts_shared: list[dict[str, Any]] | None) -> set[str]:
    return {
        str(item.get("fact_id"))
        for item in (facts_shared or [])
        if item.get("fact_id")
    }


def detect_facts_in_text(text: str) -> list[str]:
    """Return fact_ids whose aliases appear in text (semantic-ish via patterns)."""
    found: list[str] = []
    for fact_id, patterns in FACT_ALIAS_PATTERNS.items():
        if any(p.search(text or "") for p in patterns):
            found.append(fact_id)
    # Living in Manchester often implies the move fact was referenced vaguely
    if "PERSONA_FACT_MOVED_MANCHESTER" in found and "PERSONA_FACT_LIVES_IN" not in found:
        if re.search(r"\bmanchester\b", text or "", re.I):
            found.append("PERSONA_FACT_LIVES_IN")
    return list(dict.fromkeys(found))


def detect_questions_in_text(text: str) -> list[str]:
    qs = []
    for m in QUESTION_PATTERNS.finditer(text or ""):
        q = " ".join(m.group(0).split()).strip()
        if q:
            qs.append(q[:240])
    return qs


def user_asks_about_fact(message: str, fact_id: str) -> bool:
    from persona_runtime.graph.reality import classify_question_target, classify_question_targets

    msg = (message or "").lower()
    targets = classify_question_targets(message)
    target = targets[0] if targets else classify_question_target(message)
    residence_ask = bool(
        re.search(
            r"\bwhere do you live\b|\bwhere are you based\b|\bwhich city\b|"
            r"\bcity do you live\b|\byou live in\b|\byour city\b|\bmoved\b",
            msg,
        )
    )
    hometown_ask = bool(
        re.search(
            r"\bgrew up\b|\bhometown\b|\bwhere (?:are|were) you from\b|"
            r"\bwhere did you grow up\b",
            msg,
        )
    )

    # Pure now-questions are never permanent-fact questions.
    # Residence and hometown phrasing can look like "where are you" and still be identity.
    now_only = {"location_now", "activity_now", "current_task", "at_home", "follow_up"}
    if targets and all(t in now_only for t in targets) and not residence_ask and not hometown_ask:
        return False
    if (
        target in now_only
        and not residence_ask
        and not hometown_ask
        and not any(
            t in {"permanent_identity", "office_location", "projects", "zodiac"} for t in targets
        )
    ):
        return False

    if fact_id == "PERSONA_FACT_OCCUPATION":
        if "permanent_identity" in targets or target == "permanent_identity":
            return bool(
                re.search(
                    r"\bwhat do you do\b|\byour job\b|\bwhat(?:'s| is) your job\b|"
                    r"\byour occupation\b|\bwhat do you work as\b|\bwhere do you work\b",
                    msg,
                )
            )
        # Word-boundary: "you work" must not match inside "working"
        return bool(
            re.search(
                r"\bwhat do you do\b|\byour job\b|\bwhat(?:'s| is) your job\b|"
                r"\byour occupation\b|\byour work\b|\byou work\b(?!\s*ing)",
                msg,
            )
        )
    if fact_id in {"PERSONA_FACT_EMPLOYER", "PERSONA_FACT_OFFICE"}:
        return "office_location" in targets or bool(
            re.search(r"\bwhere\s+is\s+your\s+office\b|\boffice\s+located\b", msg)
        )
    if fact_id == "PERSONA_FACT_ZODIAC":
        return "zodiac" in targets or bool(re.search(r"\bzodi|\bstar\s+sign\b|\byour\s+sign\b", msg))
    if fact_id == "PERSONA_FACT_DOB":
        return bool(re.search(r"\bdate\s+of\s+birth\b|\bbirthday\b|\bborn\b", msg))
    if fact_id in {"PERSONA_FACT_DEGREE", "PERSONA_FACT_UNIVERSITY"}:
        return any(
            p in msg
            for p in ("study", "studied", "degree", "university", "graduate", "education")
        )
    if fact_id == "PERSONA_FACT_HOMETOWN":
        return hometown_ask
    if fact_id in {"PERSONA_FACT_LIVES_IN", "PERSONA_FACT_MOVED_MANCHESTER"}:
        # Home/city questions only — not "where are you right now?"
        if residence_ask and ("you" in msg or "your" in msg):
            return True
        if "location_now" in targets or target == "location_now":
            return False
        return False
    return False


def compute_disclosure_plan(
    *,
    understanding: dict[str, Any],
    facts_shared_by_sarah: list[dict[str, Any]] | None,
    incoming_message: str,
    should_self_disclose: bool = False,
) -> dict[str, list[str]]:
    """Decide which fact_ids may be disclosed this turn and which must be suppressed."""
    from persona_runtime.graph.reality import BIOGRAPHY_FACT_IDS, NOW_TARGETS

    already = disclosed_fact_ids(facts_shared_by_sarah)
    speech = understanding.get("speech_act") or ""
    intent = understanding.get("intent") or ""
    requires_info = bool(understanding.get("requires_information"))
    target = understanding.get("question_target") or "none"
    targets = list(understanding.get("question_targets") or [])
    if not targets and target and target != "none":
        targets = [target]

    allow: list[str] = []

    # Pure now / follow-up turns: never disclose biography
    if targets and all(t in NOW_TARGETS for t in targets):
        suppress = list(dict.fromkeys(list(already) + list(BIOGRAPHY_FACT_IDS)))
        return {"disclose_fact_ids": [], "suppressed_fact_ids": suppress}

    if "zodiac" in targets:
        allow.append("PERSONA_FACT_ZODIAC")
        if user_asks_about_fact(incoming_message, "PERSONA_FACT_DOB"):
            allow.append("PERSONA_FACT_DOB")
    if user_asks_about_fact(incoming_message, "PERSONA_FACT_LIVES_IN"):
        allow.append("PERSONA_FACT_LIVES_IN")
    if user_asks_about_fact(incoming_message, "PERSONA_FACT_HOMETOWN"):
        allow.append("PERSONA_FACT_HOMETOWN")
    if "office_location" in targets:
        allow.extend(["PERSONA_FACT_EMPLOYER", "PERSONA_FACT_OFFICE"])
    if "projects" in targets:
        # Projects come from REALITY.projects — occupation optional
        pass

    # First-time answer to "what do you do?"
    career_ask = user_asks_about_fact(incoming_message, "PERSONA_FACT_OCCUPATION") or (
        speech == "question"
        and understanding.get("topic") in {"sarah_career", "career"}
        and ("permanent_identity" in targets or target in {"permanent_identity", "none"})
    )
    if career_ask or (
        requires_info
        and "permanent_identity" in targets
        and "what do you do" in (incoming_message or "").lower()
    ):
        for fid in (
            "PERSONA_FACT_OCCUPATION",
            "PERSONA_FACT_EMPLOYER",
        ):
            if fid not in already:
                allow.append(fid)

    if should_self_disclose and speech in {"self_disclosure", "question"} and not already:
        for fid in ("PERSONA_FACT_OCCUPATION",):
            if fid not in already:
                allow.append(fid)

    # Never re-allow already disclosed unless user explicitly asks again
    filtered_allow: list[str] = []
    for fid in allow:
        if fid in already and not user_asks_about_fact(incoming_message, fid):
            continue
        filtered_allow.append(fid)

    # Suppress everything already disclosed that is not allowed this turn
    suppress = sorted(already - set(filtered_allow))
    # Also suppress biography facts on acknowledgement / continuation
    if speech in {"acknowledgement", "continuation", "greeting"} or intent == "conversation_continuation":
        for fid in BIOGRAPHY_FACT_IDS:
            if fid not in filtered_allow and fid not in suppress:
                suppress.append(fid)
    # On mixed bursts with now-questions, still suppress degree / lives-in unless asked
    if any(t in NOW_TARGETS for t in targets):
        for fid in ("PERSONA_FACT_DEGREE", "PERSONA_FACT_LIVES_IN", "PERSONA_FACT_MOVED_MANCHESTER", "PERSONA_FACT_UNIVERSITY"):
            if fid not in filtered_allow and fid not in suppress:
                suppress.append(fid)

    return {
        "disclose_fact_ids": list(dict.fromkeys(filtered_allow)),
        "suppressed_fact_ids": list(dict.fromkeys(suppress)),
    }


def record_disclosures_from_reply(
    *,
    reply: str,
    message_id: str | None,
    existing: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    existing = list(existing or [])
    have = disclosed_fact_ids(existing)
    catalog = fact_catalog()
    for fact_id in detect_facts_in_text(reply):
        if fact_id in have:
            continue
        meta = catalog.get(fact_id) or {}
        existing.append(
            {
                "fact_id": fact_id,
                "text": f"{meta.get('subject')} {meta.get('predicate')} {meta.get('object')}",
                "message_id": message_id,
            }
        )
        have.add(fact_id)
    return existing


def temporal_constraints_for_facts(facts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Build temporal constraint blocks for dated facts."""
    source = facts if facts is not None else SEED_CANONICAL_FACTS
    out: list[dict[str, Any]] = []
    for f in source:
        time = f.get("time")
        if not time:
            continue
        year = time.get("year")
        phrases = list(f.get("forbidden_recency_phrases") or [])
        out.append(
            {
                "fact_id": f.get("fact_id"),
                "fact": f"{f.get('subject')} {f.get('predicate')} {f.get('object')}",
                "date": str(year) if year is not None else time.get("date"),
                "current": bool(time.get("current", True)),
                "forbidden_recency_phrases": phrases,
                "preferred_phrasing": (
                    f"I've been in {f.get('object')} for a few years now."
                    if f.get("predicate") in {"lives_in", "moved_to"} and year and int(year) <= 2022
                    else None
                ),
            }
        )
    return out


def near_duplicate_question(candidate: str, asked: list[str] | None) -> bool:
    if not candidate or not asked:
        return False
    cand_tokens = set(re.findall(r"[a-z0-9]+", candidate.lower()))
    if len(cand_tokens) < 3:
        return False
    for prev in asked:
        prev_tokens = set(re.findall(r"[a-z0-9]+", prev.lower()))
        if not prev_tokens:
            continue
        overlap = len(cand_tokens & prev_tokens) / max(1, len(cand_tokens | prev_tokens))
        if overlap >= 0.65:
            return True
    return False
