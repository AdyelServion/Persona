"""Post-generation response validator with structured failure reasons."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.graph.evidence import reply_has_recall_language
from persona_runtime.graph.fact_tracker import (
    detect_facts_in_text,
    detect_questions_in_text,
    disclosed_fact_ids,
    near_duplicate_question,
    temporal_constraints_for_facts,
)
from persona_runtime.graph.grounding import (
    LEAKAGE_PHRASES_BY_SLOT,
    fallback_messages_from_answer_plan,
)
from persona_runtime.graph.reality import (
    NOW_TARGETS,
    build_world_state,
    reply_has_biography_dump,
    reply_is_habit_only_office,
    world_state_fallback_reply,
)
from persona_runtime.persona.constants import FACT_CONTRADICTIONS, SEED_CANONICAL_FACTS
from persona_runtime.life.activities import ACTIVITY_CLAIM_PATTERNS, EXPERIENCE_SLOT_CATALOGS

# Location / scene phrases that imply a place other than the office / home desk
_MISMATCH_LOCATION_PHRASES: list[tuple[str, set[str]]] = [
    ("out with friends", {"with_friends"}),
    ("with friends", {"with_friends"}),
    ("enjoying some time in the city", {"with_friends", "shopping", "running_errands"}),
    ("out in the city", {"with_friends", "shopping", "running_errands"}),
    ("at the gym", {"gym"}),
    ("in a meeting", {"meeting"}),
    ("on the train", {"commuting", "travelling"}),
    ("on the bus", {"commuting", "travelling"}),
    ("at home", {"home", "relaxing", "personal_time", "cooking", "eating", "breakfast", "sleeping", "waking_up", "reading", "watching_tv", "family_call"}),
]

ASSISTANT_VOICE = [
    re.compile(r"\bas an ai\b", re.I),
    re.compile(r"\bhow can i help\b", re.I),
    re.compile(r"\bi(?:'d| would) be happy to\b", re.I),
    re.compile(r"\bcertainly[!.,]", re.I),
    re.compile(r"\bas a language model\b", re.I),
    re.compile(r"\bhow may i assist\b", re.I),
]

# Availability / service closers — Sarah exists for the user
SERVICE_OFFER = [
    re.compile(r"\bi(?:'m| am) here to listen\b", re.I),
    re.compile(r"\bi(?:'m| am) here to help\b", re.I),
    re.compile(r"\bi(?:'m| am) here if you (?:need|want|ever)\b", re.I),
    re.compile(r"\bi(?:'m| am) always here\b", re.I),
    re.compile(r"\bi(?:'m| am) available whenever\b", re.I),
    re.compile(r"\bfeel free to share\b", re.I),
    re.compile(r"\blet me know if you need\b", re.I),
    re.compile(r"\bhappy to help\b", re.I),
    re.compile(r"\bi(?:'d| would) be happy to\b", re.I),
    re.compile(r"\banything else i can (?:help|do|assist)\b", re.I),
    re.compile(r"\bhow can i (?:support|assist|help) you\b", re.I),
    re.compile(r"\bif you(?:'d| would) like to (?:talk|share|tell me)\b", re.I),
    re.compile(r"\bif you ever want to share\b", re.I),
    re.compile(r"\bi(?:'m| am) here to (?:chat|talk|support)\b", re.I),
    re.compile(r"\bwhatever(?:'s| is) on your mind\b", re.I),
]

# Stock validation on low-intensity turns
STOCK_VALIDATION = [
    re.compile(r"\bi(?:'m| am) pleased to hear that\b", re.I),
    re.compile(r"\bi(?:'m| am) glad to hear that\b", re.I),
    re.compile(r"\bthat(?:'s| is) understandable\b", re.I),
    re.compile(r"\bi appreciate you sharing\b", re.I),
    re.compile(r"\bthank you for sharing\b", re.I),
]

CITY_CLAIMS = re.compile(
    r"\b(?:live|living|moved|based)\b[^.?]{0,40}\b(london|birmingham|leeds|sheffield|liverpool|newcastle)\b",
    re.I,
)
JOB_CLAIMS = re.compile(
    r"\bi(?:'m| am| work as) (?:a |an )?(software engineer|doctor|lawyer|teacher|nurse)\b",
    re.I,
)


class ValidationResult:
    def __init__(self, ok: bool, failures: list[str] | None = None):
        self.ok = ok
        self.failures = failures or []

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "failures": self.failures}


def validate_response(state: dict[str, Any], reply: str) -> ValidationResult:
    failures: list[str] = []
    reply = reply or ""
    lower = reply.lower()
    if not reply.strip():
        failures.append("empty_reply")
    plan = state.get("response_plan") or {}
    behaviour = state.get("behaviour_plan") or {}
    understanding = state.get("understanding") or {}
    conv = state.get("conversation_context") or {}
    move = (plan.get("conversational_move") or behaviour.get("conversational_move") or "").upper()
    allowed_facts = set(plan.get("disclose_fact_ids") or [])
    suppressed = set(plan.get("suppressed_fact_ids") or []) | disclosed_fact_ids(
        conv.get("facts_shared_by_sarah")
    )
    # Allowed this turn is not suppressed for the purpose of repetition check
    suppressed_for_check = suppressed - allowed_facts

    # 1. Canonical contradictions
    for pred, mapping in FACT_CONTRADICTIONS.items():
        for canonical_obj, bad_set in mapping.items():
            for bad in bad_set:
                if pred == "lives_in" and re.search(
                    rf"\b(?:live|living|moved|based)\b[^.?]{{0,40}}\b{re.escape(bad)}\b",
                    reply,
                    re.I,
                ):
                    planned = " ".join(
                        str(a.get("direct_answer") or "") for a in (plan.get("answers") or [])
                    ).lower()
                    if bad.lower() not in planned:
                        failures.append(f"contradicts_canonical:{pred}={canonical_obj}_not_{bad}")
                elif pred == "hometown" and re.search(
                    rf"\b(?:from|hometown)\b[^.?]{{0,30}}\b{re.escape(bad)}\b",
                    reply,
                    re.I,
                ):
                    failures.append(f"contradicts_canonical:{pred}={canonical_obj}_not_{bad}")
                elif pred == "university" and bad.lower() in lower:
                    failures.append(f"contradicts_canonical:{pred}={canonical_obj}_not_{bad}")

    job_m = JOB_CLAIMS.search(reply)
    if job_m:
        failures.append(f"contradicts_canonical:occupation!=Management Accountant ({job_m.group(1)})")

    # 2. Repeated disclosed facts
    mentioned = detect_facts_in_text(reply)
    for fid in mentioned:
        if fid in suppressed_for_check:
            failures.append(f"repeats_disclosed_fact:{fid}")

    # 3. Ungrounded memory claim
    allowed_ids = list(state.get("allowed_evidence_ids") or [])
    has_grounded = bool(plan.get("memory_claims")) and all(
        (c or {}).get("evidence_memory_id") in set(allowed_ids)
        for c in (plan.get("memory_claims") or [])
    )
    if reply_has_recall_language(reply) and not has_grounded and not allowed_ids:
        failures.append("ungrounded_memory_claim")

    # 4. Unsupported personal experience (cities/jobs outside canonical)
    city_m = CITY_CLAIMS.search(reply)
    if city_m and city_m.group(1).lower() != "manchester":
        city = city_m.group(1).lower()
        planned = " ".join(
            str(a.get("direct_answer") or "") for a in (plan.get("answers") or [])
        ).lower()
        # A grounded canonical update (for example a QA residence correction) may
        # name a city other than the seed default. An unplanned city is still rejected.
        if city not in planned:
            failures.append(f"unsupported_experience:city={city}")

    # 4b. Personal car ownership vs established transport facts
    if re.search(
        r"\b(?:my|i own a|i've got a|i have a)\s+(?:car|vehicle)\b|"
        r"\bi drive (?:my|to work)\b|"
        r"\bin my car\b",
        reply,
        re.I,
    ):
        # Allow company vehicle phrasing only when explicitly grounded
        answers = (plan.get("answers") or []) if isinstance(plan, dict) else []
        transport_ok = any(
            a.get("slot") == "transport"
            and a.get("can_answer")
            and (a.get("direct_answer") or "").lower().find("car") >= 0
            for a in answers
        )
        if not transport_ok:
            failures.append("contradicts_canonical:owns_personal_vehicle=false")

    # 4c. Clock authority — refuse invented weekdays that conflict with snapshot
    clock = state.get("clock_snapshot") or {}
    clock_weekday = (clock.get("weekday") or "").lower()
    if clock_weekday:
        for day in (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ):
            if day in lower and day != clock_weekday:
                # Only flag when she asserts today is that day
                if re.search(rf"\b(?:today(?:'s| is)?|it(?:'s| is))\s+{day}\b", lower):
                    failures.append(f"contradicts_clock:weekday={clock_weekday}_not_{day}")

    # 5. Temporal consistency
    for constraint in temporal_constraints_for_facts():
        for phrase in constraint.get("forbidden_recency_phrases") or []:
            if phrase.lower() in lower:
                failures.append(f"temporal_inconsistency:{phrase}")

    # 6. Relationship boundary / over-disclosure early stage
    stage = (state.get("relationship_state") or {}).get("relationship_stage") or "new_contact"
    disclosure = float(behaviour.get("disclosure_level") or 0.1)
    if stage in {"new_contact", "unknown", "acquaintance"} and disclosure < 0.35:
        deep_topics = ("i love you", "my trauma", "my depression", "my ex ")
        if any(t in lower for t in deep_topics):
            failures.append("boundary_violation:early_relationship_overshare")

    # 7. Ignores current topic / restates biography on acknowledgement
    speech = understanding.get("speech_act") or ""
    if speech in {"acknowledgement", "continuation"} and mentioned:
        bio = {
            "PERSONA_FACT_OCCUPATION",
            "PERSONA_FACT_DEGREE",
            "PERSONA_FACT_LIVES_IN",
            "PERSONA_FACT_MOVED_MANCHESTER",
        }
        if set(mentioned) & bio:
            failures.append("ignores_topic_restarts_biography")

    # 8. Unnecessary restatement of user message
    incoming = (state.get("incoming_message") or "").strip()
    if incoming and len(incoming) > 12:
        if incoming.lower() in lower and len(incoming) > 20:
            failures.append("restates_user_message")

    # 9. Redundant question
    asked = list(conv.get("questions_asked") or [])
    for q in detect_questions_in_text(reply):
        if near_duplicate_question(q, asked):
            failures.append(f"redundant_question:{q[:80]}")

    # 10. Assistant voice
    for pat in ASSISTANT_VOICE:
        if pat.search(reply):
            failures.append("assistant_voice")
            break

    # 11. Service / availability offer posture
    for pat in SERVICE_OFFER:
        if pat.search(reply):
            failures.append("assistant_service_offer")
            break

    # 12. Stock validation on low-intensity / non-SUPPORT turns
    intensity = (understanding.get("emotional_intensity") or "low").lower()
    importance = (understanding.get("importance") or "medium").lower()
    if move != "SUPPORT" and (intensity == "low" or importance == "low" or speech == "acknowledgement"):
        for pat in STOCK_VALIDATION:
            if pat.search(reply):
                failures.append("stock_validation")
                break

    # 13. Question when plan forbids it
    if not plan.get("should_ask_question") and "?" in reply:
        # Allow embedded rhetorical marks only if no interrogative question detected
        qs = detect_questions_in_text(reply)
        if qs or re.search(r"\?\s*$", reply.strip()):
            failures.append("unnecessary_question")

    # Legacy: ack + biography + question
    if (
        speech == "acknowledgement"
        and not understanding.get("requires_question")
        and not plan.get("should_ask_question")
        and "?" in reply
        and mentioned
    ):
        failures.append("unnecessary_question_with_biography")

    # 14. Internal simulation / persona-data terminology
    if re.search(r"\blife simulation\b|\bunavailable due to\b|\bschedule(?:r|d response)\b", reply, re.I):
        failures.append("exposes_internal_simulation")
    if re.search(
        r"\bworld state\b|"
        r"\bretrieved (?:that )?from my memory\b|"
        r"\bmy (?:system|world state|memory) says\b|"
        r"\bfrom my (?:long[- ]term )?memory\b|"
        r"\bfact[_ ]?id\b",
        reply,
        re.I,
    ):
        failures.append("exposes_internal_persona_data")

    # 15. Activity claims must match current_state
    current = (state.get("persona_state") or {}).get("current_state") or {}
    activity = (current.get("current_activity") or "").lower()
    location = (current.get("current_location") or "").lower()
    for claim_activity, phrases in ACTIVITY_CLAIM_PATTERNS:
        for phrase in phrases:
            if phrase.lower() in lower:
                # Claim is OK only if current activity matches or is a close synonym
                if claim_activity not in activity and activity not in claim_activity:
                    # special-case: working covers office desk; commuting covers heading home
                    related = {
                        "working": {
                            "deep_work",
                            "working",
                            "office",
                            "lunch",
                            "coffee_break",
                            "meeting",
                        },
                        "deep_work": {"working", "deep_work", "lunch", "coffee_break", "meeting"},
                        "lunch": {"lunch", "eating", "working", "coffee_break"},
                        "commuting": {"commuting", "travelling"},
                        "eating": {"eating", "lunch", "breakfast", "cooking"},
                        "cooking": {"cooking", "eating"},
                        "with_friends": {"with_friends"},
                        "shopping": {"shopping", "running_errands"},
                    }
                    allowed = related.get(claim_activity, {claim_activity})
                    if activity not in allowed and claim_activity not in activity:
                        failures.append(f"unsupported_activity_claim:{claim_activity}_while_{activity or 'unknown'}")
                break

    q_target = understanding.get("question_target") or plan.get("question_target") or "none"
    q_targets = list(
        understanding.get("question_targets") or plan.get("question_targets") or []
    )
    if not q_targets and q_target and q_target != "none":
        q_targets = [q_target]

    # 16. Pure now-questions must not dump permanent biography
    if q_targets and all(t in NOW_TARGETS for t in q_targets) and reply_has_biography_dump(reply):
        failures.append("biography_instead_of_now")
    elif q_target in NOW_TARGETS and not q_targets and reply_has_biography_dump(reply):
        failures.append("biography_instead_of_now")

    # 16b. Office questions must not fall through to habit-only phrasing
    if "office_location" in q_targets and reply_is_habit_only_office(reply):
        failures.append("habit_instead_of_office_location")

    # 17. Location / scene phrases must match current location/activity
    for phrase, allowed_activities in _MISMATCH_LOCATION_PHRASES:
        if phrase in lower:
            if activity and activity not in allowed_activities:
                # "at home" also ok when location is home
                if phrase == "at home" and location == "home":
                    continue
                # Negations like "Nope I'm not at home" / "not at home" are fine away from home
                if phrase == "at home" and re.search(
                    r"\b(?:not|nope|aren't|are not)\b.{0,20}\bat home\b|\bat home\b.{0,12}\b(?:today|right now)\b",
                    lower,
                ):
                    # Allow denying home when not at home
                    if location != "home" and activity not in allowed_activities:
                        continue
                failures.append(f"unsupported_location_claim:{phrase.replace(' ', '_')}_while_{activity or 'unknown'}")

    # 18. Answer-plan grounding: direct answers, unknowns, leakage
    answers = list(plan.get("answers") or [])
    allowed_slots = set(plan.get("allowed_slots") or [])
    _HOBBY_REPLY_TERMS = (
        "cooking",
        "walking",
        "reading",
        "photography",
        "cafe",
        "cafes",
        "hobby",
        "hobbies",
        "city break",
        "budgeting",
    )
    _FOOD_PREF_REPLY_TERMS = (
        "pasta",
        "risotto",
        "italian",
        "sushi",
        "pad thai",
        "roast",
    )
    if answers:
        for ans in answers:
            slot = ans.get("slot") or "none"
            if slot == "none":
                continue
            pref_kind = ans.get("preference_kind")
            if slot == "preference" and not pref_kind:
                q_text = (ans.get("text") or "").lower()
                if any(k in q_text for k in ("hobby", "hobbies", "pastime")):
                    pref_kind = "hobby"
                elif any(k in q_text for k in ("food", "dish", "meal", "cuisine")):
                    pref_kind = "food"
            if (
                slot == "preference"
                and pref_kind == "hobby"
                and any(t in lower for t in _FOOD_PREF_REPLY_TERMS)
                and not any(t in lower for t in _HOBBY_REPLY_TERMS)
            ):
                failures.append("preference_topic_mismatch:hobby")
            if ans.get("can_answer") and ans.get("direct_answer"):
                aliases = [str(a).lower() for a in (ans.get("aliases") or []) if a]
                direct = str(ans.get("direct_answer") or "").lower()
                tokens = [t for t in re.split(r"\W+", direct) if len(t) > 2]
                hit = False
                for alias in aliases + ([direct] if direct else []) + tokens[:4]:
                    if alias and alias in lower:
                        hit = True
                        break
                if not hit and slot != "follow_up":
                    failures.append(f"missing_direct_answer:{slot}")
            else:
                # Unknown: must not invent catalog meals or unrelated slots
                for meal in EXPERIENCE_SLOT_CATALOGS.get("meal") or []:
                    meal_l = meal.lower()
                    core = meal_l.replace("a ", "").replace("an ", "")
                    if core and core in lower and "not" not in lower[:40]:
                        # Allow "not sure" style; flag concrete catalog claims
                        if not re.search(
                            r"\b(?:not sure|don'?t know|no idea|haven'?t|not eating)\b",
                            lower,
                        ):
                            failures.append(f"invented_unknown:{slot}:{core[:40]}")
                            break
                # Unknown preference must not invent food favourites
                if slot == "preference" and any(t in lower for t in _FOOD_PREF_REPLY_TERMS):
                    if not re.search(
                        r"\b(?:not sure|don'?t know|no idea|nothing specific|haven'?t)\b",
                        lower,
                    ):
                        failures.append("invented_unknown:preference:food")

        # Leakage: phrases belonging to slots not in allowed_slots
        for slot_key, phrases in LEAKAGE_PHRASES_BY_SLOT.items():
            if slot_key in allowed_slots:
                continue
            # occupation allowed when office asked (employer often paired) — still block title
            for phrase in phrases:
                if phrase in lower:
                    # office slot may mention northbridge; occupation may too
                    if phrase == "northbridge" and (
                        "office" in allowed_slots
                        or "occupation" in allowed_slots
                        or "employer" in allowed_slots
                    ):
                        continue
                    failures.append(f"unrelated_context_leak:{phrase}")

        # Closed / unknown meal must not be described as current if not meal_now
        if "meal_now" not in allowed_slots:
            for meal in EXPERIENCE_SLOT_CATALOGS.get("meal") or []:
                core = meal.lower().replace("a ", "").replace("an ", "")
                if core and core in lower and activity not in {"lunch", "breakfast", "eating"}:
                    failures.append(f"stale_experience_as_now:{core[:40]}")
                    break

    return ValidationResult(ok=not failures, failures=list(dict.fromkeys(failures)))


def deterministic_fallback_reply(state: dict[str, Any]) -> str:
    """Safe continuation without persona biography or assistant posture."""
    understanding = state.get("understanding") or {}
    plan = state.get("response_plan") or {}
    behaviour = state.get("behaviour_plan") or {}
    speech = understanding.get("speech_act") or ""
    topic = (understanding.get("topic") or state.get("topic") or "").lower()
    move = (plan.get("conversational_move") or behaviour.get("conversational_move") or "").upper()
    conv = state.get("conversation_context") or {}
    user_facts = conv.get("user_facts_this_conversation") or []
    current = (state.get("persona_state") or {}).get("current_state") or {}
    world = plan.get("world_state") or build_world_state(current)
    last_world = conv.get("last_world_snapshot") or {}
    q_target = understanding.get("question_target") or plan.get("question_target") or "none"
    q_targets = list(
        understanding.get("question_targets") or plan.get("question_targets") or []
    )
    if not q_targets and q_target and q_target != "none":
        q_targets = [q_target]

    if plan.get("answers"):
        return "\n".join(fallback_messages_from_answer_plan(plan))

    grounded = q_target in NOW_TARGETS or q_target == "habit" or any(
        t
        in {
            "location_now",
            "activity_now",
            "current_task",
            "at_home",
            "follow_up",
            "office_location",
            "projects",
            "zodiac",
            "permanent_identity",
            "habit",
        }
        for t in q_targets
    )
    if grounded:
        return world_state_fallback_reply(
            q_target,
            world=world if isinstance(world, dict) else build_world_state(current),
            last_world=last_world if isinstance(last_world, dict) else {},
            targets=q_targets,
        )

    if move == "END_CONVERSATION" or speech == "conversation_closing":
        return "Take care — talk soon."
    if move == "WAIT":
        return "Mm, yeah."
    if speech == "acknowledgement" or move in {"ACKNOWLEDGE", "REACT", "CONTINUE", "JOKE"}:
        if plan.get("should_ask_question") and "career" in topic:
            return "Nice 🙂 What sort of technical projects do you usually work on?"
        if "career" in topic or "project" in topic:
            return "Nice 🙂"
        return "Ah nice."
    if speech == "self_disclosure":
        occ = next((f.get("object") for f in user_facts if f.get("predicate") == "occupation"), None)
        if not occ:
            for d in understanding.get("user_disclosures") or []:
                if d.get("predicate") == "occupation":
                    occ = d.get("object")
                    break
        if plan.get("should_ask_question"):
            if occ and "project" in (occ or "").lower():
                return "That's interesting. What kind of technical projects do you usually manage?"
            return "That's interesting — tell me more about that?"
        if occ and "project" in (occ or "").lower():
            return "That makes sense. I imagine half the job is keeping everyone aligned."
        return "That makes sense."
    if speech == "question" and plan.get("disclose_fact_ids"):
        ids = plan.get("disclose_fact_ids") or []
        bits = []
        if "PERSONA_FACT_OCCUPATION" in ids:
            bits.append("I'm a Management Accountant")
        if "PERSONA_FACT_DEGREE" in ids:
            bits.append("I studied Accounting and Finance")
        if "PERSONA_FACT_LIVES_IN" in ids or "PERSONA_FACT_MOVED_MANCHESTER" in ids:
            bits.append("I've been living in Manchester for a few years now")
        body = ". ".join(bits) + "." if bits else "Hmm, good question."
        if plan.get("should_ask_question"):
            body += " What kind of projects do you work on?"
        return body
    if speech == "greeting" or move == "REACT" and not speech:
        return "Hey — how's your day going?"
    if speech == "emotional_statement":
        if move == "SUPPORT":
            return "That sounds rough. What happened?"
        return "Ugh. What's going on?"
    return "Yeah, fair enough."
