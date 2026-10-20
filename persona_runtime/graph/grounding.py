"""Universal fact retrieval with status and provenance for answer planning."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.graph.questions import QuestionRecord, preference_kind_from_text
from persona_runtime.graph.reality import (
    SEMI_PERSISTENT_HABITS,
    build_world_state,
    employment_snapshot,
    projects_snapshot,
)

_FOOD_PREFERENCE_LEAK = [
    "pasta",
    "risotto",
    "italian food",
    "sushi",
    "pad thai",
    "sunday roast",
]
from persona_runtime.life.clock import ClockSnapshot, clock_snapshot
from persona_runtime.life.experiences import (
    find_past_events,
    resolve_experience_for_slot,
)
from persona_runtime.persona.constants import (
    EMPLOYMENT_PROFILE,
    NAMED_RELATIONSHIPS,
    SEED_CANONICAL_FACTS,
    TRANSPORT_PROFILE,
)

FactStatus = Literal["established", "simulated", "inferred", "unknown", "outdated"]


class GroundedFact(BaseModel):
    slot: str
    status: FactStatus = "unknown"
    value: Any = None
    as_of: datetime | None = None
    valid_until: datetime | None = None
    source: str = ""
    kind: str = "established_fact"
    aliases: list[str] = Field(default_factory=list)
    event_id: str | None = None
    missing: str | None = None
    question_id: str | None = None


def _canonical_by_id(
    fact_id: str,
    canonical_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Current persona facts win over the seed catalog."""
    for f in canonical_facts or []:
        if f.get("fact_id") == fact_id and f.get("object") not in (None, ""):
            return f
    for f in SEED_CANONICAL_FACTS:
        if f.get("fact_id") == fact_id:
            return f
    return None


def memory_facets(text: str) -> list[str]:
    """Which user-memory attributes a question is asking for, in ask order."""
    norm = (text or "").lower()
    rules = (
        ("name", r"\bname\b"),
        ("owns_car", r"\b(?:car|honda)\b|\bdrive\b"),
        ("morning_drink", r"\b(?:drink|tea|coffee|morning)\b"),
        ("weekend_preference", r"\bweekends?\b"),
        ("hobby", r"\b(?:hobby|photography)\b"),
        ("upcoming", r"\bcoming\s+up\b|\bpresentation\b|\bbig\s+day\b|\bnext\s+week\b"),
        ("messaging_boundary", r"\bmessag|\bbusy\b|\bboundary\b"),
    )
    found: list[str] = []
    for facet, pattern in rules:
        if re.search(pattern, norm) and facet not in found:
            found.append(facet)
    return found


def _memory_blob(mem: dict[str, Any]) -> str:
    return " ".join(
        str(mem.get(key) or "")
        for key in ("fact", "event_description", "object", "predicate", "subject", "pattern")
    ).lower()


def _memory_matches_facet(mem: dict[str, Any], facet: str) -> bool:
    pred = str(mem.get("predicate") or "")
    blob = _memory_blob(mem)
    predicates = {
        "name": {"name"},
        "owns_car": {"owns_car"},
        "morning_drink": {"morning_drink"},
        "weekend_preference": {"weekend_preference"},
        "hobby": {"hobby"},
        "upcoming": {"has_upcoming_event"},
        "messaging_boundary": {"messaging_boundary"},
    }
    needles = {
        "name": ("name",),
        "owns_car": ("honda", "cr-z", "car"),
        "morning_drink": ("tea", "coffee", "drink"),
        "weekend_preference": ("weekend", "drives"),
        "hobby": ("photography", "hobby"),
        "upcoming": ("presentation", "coming up"),
        "messaging_boundary": ("messag", "busy", "boundary"),
    }
    if pred in predicates.get(facet, set()):
        return True
    return any(needle in blob for needle in needles.get(facet, ()))


def select_user_memories(
    question: str,
    memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Active user memories that answer this question. Latest facet match wins."""
    active = [m for m in memories if (m.get("status") or "active") == "active"]
    user_scoped = [
        m
        for m in active
        if (m.get("scope") or "user") == "user"
        or (m.get("user_id") and (m.get("scope") or "") != "persona")
    ]
    if not user_scoped:
        return []
    facets = memory_facets(question)
    if not facets:
        return [user_scoped[0]]
    picked: list[dict[str, Any]] = []
    for facet in facets:
        matches = [m for m in user_scoped if _memory_matches_facet(m, facet)]
        if not matches:
            continue
        matches.sort(
            key=lambda m: (
                float(m.get("confidence") or 0),
                str(m.get("updated_at") or m.get("created_at") or ""),
            ),
            reverse=True,
        )
        picked.append(matches[0])
    return picked


def _memory_phrase(mem: dict[str, Any]) -> str:
    raw = str(mem.get("fact") or mem.get("event_description") or mem.get("object") or "").strip()
    if raw.lower().startswith("user "):
        raw = raw[5:]
    return raw


def _aliases_for_value(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    aliases = [text, text.lower()]
    # Drop leading articles for matching
    for prefix in ("a ", "an ", "the "):
        if text.lower().startswith(prefix):
            aliases.append(text[len(prefix) :])
            aliases.append(text[len(prefix) :].lower())
    return list(dict.fromkeys(a for a in aliases if a))


def _unknown(slot: str, *, question_id: str | None, missing: str, kind: str = "experience") -> GroundedFact:
    return GroundedFact(
        slot=slot,
        status="unknown",
        value=None,
        source="",
        kind=kind,
        missing=missing,
        question_id=question_id,
    )


def retrieve_fact_for_question(
    question: QuestionRecord | dict[str, Any],
    *,
    persona_id: str,
    persona_state: dict[str, Any] | None,
    conversation_context: dict[str, Any] | None = None,
    retrieved_memories: list[dict[str, Any]] | None = None,
    state_repo: Any | None = None,
    timeline_repo: Any | None = None,
    clock: ClockSnapshot | None = None,
    tz_name: str = "Europe/London",
    canonical_facts: list[dict[str, Any]] | None = None,
) -> GroundedFact:
    if isinstance(question, dict):
        q = QuestionRecord.model_validate(question)
    else:
        q = question

    state_doc = persona_state or {}
    current = dict(state_doc.get("current_state") or {})
    world = build_world_state(current, tz_name=tz_name)
    snap = clock or clock_snapshot(tz_name=tz_name)
    now = snap.utc_now
    conv = conversation_context or {}

    slot = q.slot
    qid = q.question_id

    if slot == "none":
        return _unknown("none", question_id=qid, missing="no_slot", kind=q.kind)

    if slot == "time_now":
        return GroundedFact(
            slot=slot,
            status="established",
            value={
                "local_time": snap.local_time,
                "local_date": snap.local_date.isoformat(),
                "weekday": snap.weekday,
                "timezone": snap.timezone,
            },
            as_of=now,
            source="clock:authoritative",
            kind="established_fact",
            aliases=[snap.local_time, snap.weekday, snap.local_date.isoformat()],
            question_id=qid,
        )

    if slot == "still_at_office":
        loc_type = (world.get("location_type") or current.get("location_type") or "").lower()
        activity = (world.get("activity") or current.get("current_activity") or "").lower()
        at_office = loc_type == "office" or activity in {
            "working",
            "deep_work",
            "meeting",
            "lunch",
            "coffee_break",
        }
        return GroundedFact(
            slot=slot,
            status="established",
            value={
                "at_office": at_office,
                "location": world.get("location") or current.get("current_location"),
                "location_type": loc_type,
                "activity": activity,
                "situation": world.get("situation") or current.get("situation"),
            },
            as_of=now,
            source="world_state:location",
            kind="experience",
            aliases=_aliases_for_value(world.get("situation")),
            event_id=current.get("active_event_id"),
            question_id=qid,
        )

    if slot == "leave_work":
        leave_ev = None
        if timeline_repo is not None:
            leave_ev = timeline_repo.find_next_planned(
                persona_id, after=now, activity="commuting"
            )
            # Prefer the commute that follows office work (evening)
            if leave_ev is None:
                candidates = timeline_repo.list_planned_and_active(persona_id)
                for e in candidates:
                    if e.get("activity") == "commuting" and ensure_utc(
                        e["scheduled_start"]
                    ) >= now:
                        leave_ev = e
                        break
        if leave_ev is None:
            # Fall back to next_activity if it is commuting
            if (current.get("next_activity") or "") == "commuting":
                return GroundedFact(
                    slot=slot,
                    status="simulated",
                    value={
                        "activity": "commuting",
                        "at": current.get("next_activity_at"),
                        "uncertain": True,
                        "phrase": "I'll probably leave around then",
                    },
                    as_of=now,
                    source="life_plan:next_commute",
                    kind="experience",
                    question_id=qid,
                )
            return _unknown(slot, question_id=qid, missing="leave_plan_unknown", kind="experience")
        local_leave = ensure_utc(leave_ev["scheduled_start"]).astimezone(
            __import__("zoneinfo").ZoneInfo(snap.timezone)
        )
        return GroundedFact(
            slot=slot,
            status="simulated",
            value={
                "activity": "commuting",
                "at": leave_ev.get("scheduled_start"),
                "local_time": local_leave.strftime("%H:%M"),
                "uncertain": True,
                "phrase": f"I'm aiming to leave around {local_leave.strftime('%H:%M')}",
                "source_kind": leave_ev.get("source") or "routine_template",
            },
            as_of=now,
            source="timeline:leave_work",
            kind="experience",
            aliases=[local_leave.strftime("%H:%M")],
            event_id=leave_ev.get("event_id"),
            question_id=qid,
        )

    if slot == "arrive_home":
        commute = None
        if timeline_repo is not None:
            commute = timeline_repo.find_arrive_home_estimate(persona_id, now)
        if commute is None:
            return _unknown(slot, question_id=qid, missing="arrive_home_unknown", kind="experience")
        end = ensure_utc(commute["scheduled_end"])
        local_end = end.astimezone(__import__("zoneinfo").ZoneInfo(snap.timezone))
        duration_min = int(
            (ensure_utc(commute["scheduled_end"]) - ensure_utc(commute["scheduled_start"])).total_seconds()
            / 60
        )
        return GroundedFact(
            slot=slot,
            status="simulated",
            value={
                "arrive_at": commute.get("scheduled_end"),
                "local_time": local_end.strftime("%H:%M"),
                "commute_minutes": duration_min,
                "uncertain": True,
                "phrase": (
                    f"If I leave on time I should be home around "
                    f"{local_end.strftime('%H:%M')}, give or take"
                ),
            },
            as_of=now,
            source="timeline:arrive_home",
            kind="experience",
            aliases=[local_end.strftime("%H:%M")],
            event_id=commute.get("event_id"),
            question_id=qid,
        )

    if slot == "transport":
        owns_fact = _canonical_by_id("PERSONA_FACT_OWNS_PERSONAL_VEHICLE", canonical_facts)
        if owns_fact is not None:
            owns = str(owns_fact.get("object")).strip().lower() not in {"false", "0", "no", ""}
        else:
            owns = bool(TRANSPORT_PROFILE.get("owns_personal_vehicle", False))
        mode_fact = _canonical_by_id("PERSONA_FACT_COMMUTE_MODE", canonical_facts)
        mode = (mode_fact or {}).get("object") or TRANSPORT_PROFILE.get("commute_mode") or "public_transport"
        company = TRANSPORT_PROFILE.get("company_vehicle_access")
        return GroundedFact(
            slot=slot,
            status="established",
            value={
                "owns_personal_vehicle": owns,
                "commute_mode": mode,
                "company_vehicle_access": company,
                "phrase": (
                    "I don't have my own car — I usually get in on public transport"
                    if not owns
                    else "I drive"
                ),
            },
            source="canonical:transport",
            kind="established_fact",
            aliases=["public transport", "bus", "tram", "train"] if not owns else ["car"],
            question_id=qid,
        )

    if slot == "follow_up":
        last_slots = list(conv.get("last_answer_slots") or [])
        last_world = conv.get("last_world_snapshot") or world
        situation = (last_world or {}).get("situation") or world.get("situation")
        task = (last_world or {}).get("current_task") or world.get("current_task")
        project = (last_world or {}).get("current_project") or world.get("current_project")
        value = {
            "last_slots": last_slots,
            "situation": situation,
            "activity": (last_world or {}).get("activity") or world.get("activity"),
            "current_task": task,
            "current_project": project,
            "open_experience_id": conv.get("open_experience_id"),
        }
        return GroundedFact(
            slot=slot,
            status="established",
            value=value,
            as_of=now,
            source="conversation:last_answer",
            kind="experience",
            aliases=(
                _aliases_for_value(situation)
                + _aliases_for_value(task)
                + _aliases_for_value(project)
            ),
            question_id=qid,
        )

    if slot == "location_now":
        # Prefer life-block-derived world state over a stale current_location field
        location = world.get("location") or current.get("current_location")
        loc_type = world.get("location_type")
        situation = world.get("situation")
        stale = False
        raw_loc = (current.get("current_location") or "").lower()
        block_loc = (world.get("location_key") or "").lower()
        if raw_loc and block_loc and raw_loc != block_loc:
            # world already reflects block via build_world_state when consistent;
            # if caller injected mismatched fields, mark outdated companion
            stale = True
        value = {
            "location": location,
            "location_type": loc_type,
            "situation": situation,
            "at_home": loc_type == "home",
        }
        return GroundedFact(
            slot=slot,
            status="outdated" if stale and not location else "established",
            value=value,
            as_of=current.get("activity_started_at") or now,
            valid_until=current.get("activity_expected_end_at"),
            source="world_state:location",
            kind="experience",
            aliases=_aliases_for_value(location) + _aliases_for_value(situation),
            question_id=qid,
            missing=None if location else "location_unknown",
        )

    if slot == "activity_now":
        activity = world.get("activity") or current.get("current_activity")
        situation = world.get("situation")
        if not activity:
            return _unknown(slot, question_id=qid, missing="activity_unknown")
        return GroundedFact(
            slot=slot,
            status="established",
            value={"activity": activity, "situation": situation},
            as_of=current.get("activity_started_at") or now,
            valid_until=current.get("activity_expected_end_at"),
            source="world_state:activity",
            kind="experience",
            aliases=_aliases_for_value(activity) + _aliases_for_value(situation),
            question_id=qid,
        )

    if slot == "task_now":
        task = world.get("current_task") or current.get("current_task")
        detail = world.get("task_detail") or current.get("task_detail")
        project = world.get("current_project") or current.get("current_project")
        activity = world.get("activity") or ""
        # During lunch/coffee/meeting, desk task is not the answer for activity,
        # but task_now still may return it if explicitly asked.
        if not task and not project:
            return GroundedFact(
                slot=slot,
                status="unknown",
                value={"activity": activity},
                source="world_state:task",
                kind="established_fact",
                missing="task_unknown",
                question_id=qid,
                aliases=_aliases_for_value(activity),
            )
        value = {"task": task, "detail": detail, "project": project}
        return GroundedFact(
            slot=slot,
            status="established",
            value=value,
            as_of=now,
            source="world_state:task",
            kind="established_fact",
            aliases=_aliases_for_value(project) + _aliases_for_value(task),
            question_id=qid,
        )

    if slot == "meal_now":
        activity = (world.get("activity") or current.get("current_activity") or "").lower()
        if activity not in {"lunch", "breakfast", "eating"}:
            return _unknown(
                slot,
                question_id=qid,
                missing="not_in_meal_window",
                kind="experience",
            )
        event = resolve_experience_for_slot(
            persona_id=persona_id,
            state_doc=state_doc,
            slot="meal",
            state_repo=state_repo,
        )
        if not event or event.get("ended_at"):
            return _unknown(slot, question_id=qid, missing="meal_unknown", kind="experience")
        return GroundedFact(
            slot=slot,
            status="simulated",
            value=event.get("value"),
            as_of=event.get("started_at") or now,
            valid_until=event.get("expected_end_at") or current.get("activity_expected_end_at"),
            source="experience_log:meal",
            kind="experience",
            aliases=_aliases_for_value(event.get("value")),
            event_id=event.get("event_id"),
            question_id=qid,
        )

    if slot == "occupation":
        fact = _canonical_by_id("PERSONA_FACT_OCCUPATION", canonical_facts)
        job = EMPLOYMENT_PROFILE.get("job") or {}
        title = (fact or {}).get("object") or job.get("title")
        return GroundedFact(
            slot=slot,
            status="established",
            value={"title": title, "summary": job.get("summary"), "employer": EMPLOYMENT_PROFILE["employer"]["name"]},
            source="canonical:PERSONA_FACT_OCCUPATION",
            kind="established_fact",
            aliases=_aliases_for_value(title),
            question_id=qid,
        )

    if slot == "employer":
        fact = _canonical_by_id("PERSONA_FACT_EMPLOYER", canonical_facts)
        name = (fact or {}).get("object") or (EMPLOYMENT_PROFILE.get("employer") or {}).get("name")
        return GroundedFact(
            slot=slot,
            status="established" if name else "unknown",
            value={"employer": name} if name else None,
            source="canonical:PERSONA_FACT_EMPLOYER",
            kind="established_fact",
            aliases=_aliases_for_value(name),
            question_id=qid,
            missing=None if name else "employer_unknown",
        )

    if slot == "office":
        emp = employment_snapshot()
        office = emp.get("office") or {}
        employer = emp.get("employer") or {}
        canon = _canonical_by_id("PERSONA_FACT_OFFICE", canonical_facts)
        canon_text = str((canon or {}).get("object") or "").strip()
        name = office.get("name") or ""
        address = office.get("address") or ""
        composed = ", ".join(part for part in (name, address) if part)
        display = canon_text or composed
        value = {
            "name": name,
            "address": address,
            "city": office.get("city"),
            "employer": employer.get("name"),
            "display": display,
        }
        return GroundedFact(
            slot=slot,
            status="established" if display else "unknown",
            value=value,
            source="canonical:PERSONA_FACT_OFFICE" if canon_text else "employment:office",
            kind="established_fact",
            aliases=_aliases_for_value(display)
            + _aliases_for_value(name)
            + _aliases_for_value(address)
            + _aliases_for_value(employer.get("name"))
            + _aliases_for_value(office.get("city")),
            question_id=qid,
            missing=None if display else "office_unknown",
        )

    if slot == "project":
        project = world.get("current_project") or current.get("current_project")
        names = [p["name"] for p in projects_snapshot()]
        value = {"current_project": project, "projects": names}
        return GroundedFact(
            slot=slot,
            status="established" if (project or names) else "unknown",
            value=value,
            source="projects:current",
            kind="established_fact",
            aliases=_aliases_for_value(project) + [n for n in names],
            question_id=qid,
            missing=None if (project or names) else "project_unknown",
        )

    if slot == "preference":
        pref_kind = q.preference_kind or preference_kind_from_text(q.text or "")
        habit_id_by_kind = {
            "food": "favourite_food",
            "hobby": "favourite_hobbies",
            "drink": "enjoys_coffee",
            "social": "likes_friends",
        }
        aliases_by_kind: dict[str, list[str]] = {
            "food": ["pasta", "risotto", "italian", "sushi", "pad thai", "roast"],
            "hobby": [
                "cooking",
                "walking",
                "reading",
                "photography",
                "cafes",
                "cafe",
                "manchester",
                "city breaks",
                "budgeting",
            ],
            "drink": ["coffee"],
            "social": ["friends", "going out"],
        }
        if pref_kind == "unknown" or pref_kind not in habit_id_by_kind:
            return _unknown(
                slot,
                question_id=qid,
                missing="preference_unknown",
                kind="preference",
            )
        habit_id = habit_id_by_kind[pref_kind]
        habit = next((h for h in SEMI_PERSISTENT_HABITS if h["habit_id"] == habit_id), None)
        if not habit:
            return _unknown(
                slot,
                question_id=qid,
                missing="preference_unknown",
                kind="preference",
            )
        value = {
            "habit_id": habit.get("habit_id") or habit_id,
            "text": habit.get("text"),
            "phrasing": habit.get("phrasing"),
            "preference_kind": pref_kind,
        }
        return GroundedFact(
            slot=slot,
            status="established",
            value=value,
            source=f"habits:{habit_id}",
            kind="preference",
            aliases=list(aliases_by_kind.get(pref_kind) or []),
            question_id=qid,
        )

    if slot == "identity":
        # Zodiac vs lives-in vs DOB from question text
        text = (q.text or "").lower()
        if "sign" in text or "zodi" in text:
            fact = _canonical_by_id("PERSONA_FACT_ZODIAC", canonical_facts)
            value = (fact or {}).get("object") or "Aries"
            return GroundedFact(
                slot=slot,
                status="established",
                value={"zodiac": value},
                source="canonical:PERSONA_FACT_ZODIAC",
                kind="established_fact",
                aliases=_aliases_for_value(value),
                question_id=qid,
            )
        if "born" in text or "birthday" in text or "birth" in text:
            fact = _canonical_by_id("PERSONA_FACT_DOB", canonical_facts)
            value = (fact or {}).get("object")
            return GroundedFact(
                slot=slot,
                status="established",
                value={"dob": value},
                source="canonical:PERSONA_FACT_DOB",
                kind="established_fact",
                aliases=_aliases_for_value(value),
                question_id=qid,
            )
        if any(k in text for k in ("grew up", "grow up", "hometown", "where are you from", "where were you from")):
            fact = _canonical_by_id("PERSONA_FACT_HOMETOWN", canonical_facts)
            value = (fact or {}).get("object")
            return GroundedFact(
                slot=slot,
                status="established" if value else "unknown",
                value={"hometown": value} if value else None,
                source="canonical:PERSONA_FACT_HOMETOWN",
                kind="established_fact",
                aliases=_aliases_for_value(value),
                question_id=qid,
                missing=None if value else "hometown_unknown",
            )
        fact = _canonical_by_id("PERSONA_FACT_LIVES_IN", canonical_facts)
        value = (fact or {}).get("object")
        return GroundedFact(
            slot=slot,
            status="established" if value else "unknown",
            value={"lives_in": value} if value else None,
            source="canonical:PERSONA_FACT_LIVES_IN",
            kind="established_fact",
            aliases=_aliases_for_value(value),
            question_id=qid,
            missing=None if value else "lives_in_unknown",
        )

    if slot == "relationship":
        text = (q.text or "").lower()
        matches = []
        for rel in NAMED_RELATIONSHIPS:
            name = (rel.get("display_name") or rel.get("name") or "").lower()
            role = (rel.get("relationship_type") or rel.get("role") or "").lower()
            first = name.split()[0] if name else ""
            if name and (name in text or (first and first in text)):
                matches.append(rel)
            elif role and role in text:
                matches.append(rel)
            elif role == "mother" and any(k in text for k in ("mum", "mom")):
                matches.append(rel)
            elif role == "father" and "dad" in text:
                matches.append(rel)
        if not matches and ("family" in text or "parents" in text):
            matches = [
                r
                for r in NAMED_RELATIONSHIPS
                if (r.get("relationship_type") or "").lower()
                in {"mother", "father", "sister", "brother", "parent"}
            ]
        if not matches:
            return _unknown(slot, question_id=qid, missing="relationship_unknown", kind="established_fact")
        return GroundedFact(
            slot=slot,
            status="established",
            value={"people": matches},
            source="relationships:named",
            kind="established_fact",
            aliases=[
                str(m.get("display_name") or m.get("name"))
                for m in matches
                if m.get("display_name") or m.get("name")
            ],
            question_id=qid,
        )

    if slot == "plan_future":
        next_act = world.get("next_planned_activity") or current.get("next_planned_activity")
        next_key = current.get("next_activity")
        if not next_act and not next_key:
            return _unknown(slot, question_id=qid, missing="plan_unknown", kind="experience")
        # Routine template futures are simulated with uncertainty — not guaranteed
        return GroundedFact(
            slot=slot,
            status="simulated",
            value={
                "next_activity": next_key,
                "phrase": next_act,
                "at": current.get("next_activity_at"),
                "detail_status": "unknown",
                "uncertain": True,
                "event_id": current.get("next_planned_event_id"),
            },
            as_of=now,
            source="life_plan:next",
            kind="experience",
            aliases=_aliases_for_value(next_act) + _aliases_for_value(next_key),
            event_id=current.get("next_planned_event_id"),
            question_id=qid,
        )

    if slot == "event_past":
        # Prefer completed TimelineEvents for previous local calendar day
        yesterday = (snap.local_date - timedelta(days=1)).isoformat()
        if timeline_repo is not None:
            completed = timeline_repo.list_completed_for_date(persona_id, yesterday)
            if completed:
                # Summarise yesterday's activities
                activities = [e.get("activity") for e in completed if e.get("activity")]
                latest = completed[-1]
                return GroundedFact(
                    slot=slot,
                    status="simulated",
                    value={
                        "local_date": yesterday,
                        "activities": activities,
                        "activity": latest.get("activity"),
                        "value": latest.get("activity"),
                        "started_at": latest.get("actual_start") or latest.get("scheduled_start"),
                        "ended_at": latest.get("actual_end"),
                    },
                    as_of=latest.get("actual_start"),
                    source="timeline:yesterday",
                    kind="experience",
                    aliases=_aliases_for_value(latest.get("activity")),
                    event_id=latest.get("event_id"),
                    question_id=qid,
                )
        events = list(state_doc.get("experience_events") or [])
        after = now - timedelta(hours=36)
        past = find_past_events(events, after=after, before=now)
        closed = [e for e in past if e.get("ended_at")]
        use = closed or past
        if not use:
            return _unknown(slot, question_id=qid, missing="no_past_events", kind="experience")
        latest = use[-1]
        return GroundedFact(
            slot=slot,
            status=latest.get("status") or "simulated",
            value={
                "slot": latest.get("slot"),
                "value": latest.get("value"),
                "activity": latest.get("activity"),
                "started_at": latest.get("started_at"),
                "ended_at": latest.get("ended_at"),
            },
            as_of=latest.get("started_at"),
            valid_until=latest.get("ended_at"),
            source="experience_log:past",
            kind="experience",
            aliases=_aliases_for_value(latest.get("value")),
            event_id=latest.get("event_id"),
            question_id=qid,
        )

    if slot == "user_memory":
        mems = list(retrieved_memories or [])
        active = [m for m in mems if (m.get("status") or "active") == "active"]
        # Only user-scoped memories answer "do you remember what I told you"
        user_scoped = [
            m
            for m in active
            if (m.get("scope") or "user") == "user"
            or (m.get("user_id") and (m.get("scope") or "") != "persona")
        ]
        outdated = [
            m
            for m in mems
            if (m.get("status") or "") == "superseded"
            and (m.get("scope") or "user") == "user"
        ]
        if not user_scoped:
            if outdated:
                return GroundedFact(
                    slot=slot,
                    status="outdated",
                    value=None,
                    source="memory:superseded",
                    kind="established_fact",
                    missing="memory_outdated",
                    question_id=qid,
                )
            return _unknown(slot, question_id=qid, missing="memory_unknown", kind="established_fact")
        picked = select_user_memories(q.text or "", user_scoped)
        if memory_facets(q.text or "") and not picked:
            return _unknown(slot, question_id=qid, missing="memory_unknown", kind="established_fact")
        if not picked:
            picked = [user_scoped[0]]
        phrases = [p for p in (_memory_phrase(m) for m in picked) if p]
        text = ". ".join(phrases)
        top = picked[0]
        aliases: list[str] = []
        for mem in picked:
            aliases.extend(_aliases_for_value(_memory_phrase(mem)))
            aliases.extend(_aliases_for_value(mem.get("object")))
            aliases.extend(_aliases_for_value(mem.get("fact")))
        return GroundedFact(
            slot=slot,
            status="established",
            value={
                "memory_id": top.get("memory_id"),
                "memory_ids": [m.get("memory_id") for m in picked if m.get("memory_id")],
                "text": text,
                "subject": top.get("subject"),
                "predicate": top.get("predicate"),
                "object": top.get("object"),
            },
            source=f"memory:{top.get('memory_id')}",
            kind="established_fact",
            aliases=list(dict.fromkeys(a for a in aliases if a)),
            question_id=qid,
        )

    if slot == "hypothetical":
        return GroundedFact(
            slot=slot,
            status="inferred",
            value=None,
            source="none",
            kind="hypothetical",
            missing="hypothetical_no_fact",
            question_id=qid,
        )

    return _unknown(slot, question_id=qid, missing="unsupported_slot", kind=q.kind)


def retrieve_facts(
    questions: list[QuestionRecord] | list[dict[str, Any]],
    *,
    persona_id: str,
    persona_state: dict[str, Any] | None,
    conversation_context: dict[str, Any] | None = None,
    retrieved_memories: list[dict[str, Any]] | None = None,
    state_repo: Any | None = None,
    timeline_repo: Any | None = None,
    clock: ClockSnapshot | None = None,
    tz_name: str = "Europe/London",
    canonical_facts: list[dict[str, Any]] | None = None,
) -> list[GroundedFact]:
    return [
        retrieve_fact_for_question(
            q,
            persona_id=persona_id,
            persona_state=persona_state,
            conversation_context=conversation_context,
            retrieved_memories=retrieved_memories,
            state_repo=state_repo,
            timeline_repo=timeline_repo,
            clock=clock,
            tz_name=tz_name,
            canonical_facts=canonical_facts,
        )
        for q in questions
    ]


def build_answer_plan(
    questions: list[QuestionRecord] | list[dict[str, Any]],
    facts: list[GroundedFact],
) -> dict[str, Any]:
    """Per-question answer plan with direct answers and leakage guards."""
    answers: list[dict[str, Any]] = []
    allowed_slots: list[str] = []
    must_not: list[str] = []

    leakage_pool = [
        "Northbridge Financial Group",
        "Alderbrook",
        "Management Accountant",
        "Aries",
        "Diane",
        "Mark",
        "Emily",
        "Monthly Financial Reporting",
        "Finance Dashboard",
        "Annual Budget",
    ]

    for q, fact in zip(questions, facts, strict=False):
        if isinstance(q, dict):
            slot = q.get("slot") or "none"
            qid = q.get("question_id")
            text = q.get("text") or ""
            pref_kind = q.get("preference_kind")
        else:
            slot = q.slot
            qid = q.question_id
            text = q.text
            pref_kind = q.preference_kind

        can_answer = fact.status in {"established", "simulated"} and fact.value is not None
        if fact.status == "outdated":
            can_answer = False
        if fact.status == "inferred":
            can_answer = False

        if slot == "preference":
            pref_kind = pref_kind or preference_kind_from_text(text)
            if isinstance(fact.value, dict) and fact.value.get("preference_kind"):
                pref_kind = fact.value.get("preference_kind")

        direct = _direct_answer_text(slot, fact)
        answers.append(
            {
                "question_id": qid,
                "slot": slot,
                "text": text,
                "can_answer": can_answer,
                "direct_answer": direct if can_answer else None,
                "status": fact.status,
                "source": fact.source,
                "missing": fact.missing,
                "aliases": list(fact.aliases or []),
                "event_id": fact.event_id,
                "kind": fact.kind,
                "preference_kind": pref_kind if slot == "preference" else None,
            }
        )
        if slot and slot != "none":
            allowed_slots.append(slot)
        # Non-food preference questions must not fall through to pasta/italian food
        if slot == "preference" and pref_kind and pref_kind != "food":
            for phrase in _FOOD_PREFERENCE_LEAK:
                if phrase not in must_not:
                    must_not.append(phrase)
        # Follow-ups may continue the prior thread
        if slot == "follow_up":
            for prev in (fact.value or {}).get("last_slots") or []:
                if prev and prev not in allowed_slots:
                    allowed_slots.append(prev)
            if (fact.value or {}).get("current_task") or (fact.value or {}).get("current_project"):
                if "task_now" not in allowed_slots:
                    allowed_slots.append("task_now")
                if "project" not in allowed_slots:
                    allowed_slots.append("project")

    # Abstract leakage labels for the prompt (concrete phrases stay in the validator)
    abstract_must_not = []
    slot_set = set(allowed_slots)
    if "occupation" not in slot_set and "office" not in slot_set and "employer" not in slot_set:
        abstract_must_not.append("employer_or_job_title")
    if "office" not in slot_set:
        abstract_must_not.append("office_address")
    if "identity" not in slot_set:
        abstract_must_not.append("zodiac_or_dob")
    if "relationship" not in slot_set:
        abstract_must_not.append("family_names")
    if "project" not in slot_set and "task_now" not in slot_set:
        abstract_must_not.append("project_names")
    must_not = list(dict.fromkeys(must_not + abstract_must_not))

    suggested = max(1, len([a for a in answers if a.get("slot") != "none"]))
    # Extra bubble only when a natural second sentence helps (meal detail + light aside)
    if any(a.get("slot") == "meal_now" and a.get("can_answer") for a in answers):
        suggested = max(suggested, len(answers))

    return {
        "answers": answers,
        "tone": "natural",
        "suggested_bubbles": suggested,
        "allowed_slots": allowed_slots,
        "must_not_mention": must_not,
    }


def _direct_answer_text(slot: str, fact: GroundedFact) -> str | None:
    if fact.value is None:
        return None
    v = fact.value
    if slot == "meal_now":
        return str(v)
    if slot == "activity_now" and isinstance(v, dict):
        return str(v.get("situation") or v.get("activity") or "")
    if slot == "location_now" and isinstance(v, dict):
        if v.get("situation"):
            return str(v["situation"])
        return str(v.get("location") or "")
    if slot == "task_now" and isinstance(v, dict):
        return str(v.get("project") or v.get("task") or "")
    if slot == "occupation" and isinstance(v, dict):
        return str(v.get("title") or "")
    if slot == "employer" and isinstance(v, dict):
        return str(v.get("employer") or "")
    if slot == "office" and isinstance(v, dict):
        return str(v.get("display") or v.get("address") or v.get("name") or "")
    if slot == "project" and isinstance(v, dict):
        return str(v.get("current_project") or (v.get("projects") or [""])[0])
    if slot == "preference" and isinstance(v, dict):
        return str(v.get("phrasing") or v.get("text") or "")
    if slot == "identity" and isinstance(v, dict):
        if v.get("zodiac"):
            return str(v["zodiac"])
        if v.get("hometown"):
            return f"I grew up in {v['hometown']}"
        if v.get("lives_in"):
            return f"I live in {v['lives_in']}"
        if v.get("dob"):
            return str(v["dob"])
        return ""
    if slot == "plan_future" and isinstance(v, dict):
        return str(v.get("phrase") or v.get("next_activity") or "")
    if slot == "event_past" and isinstance(v, dict):
        acts = v.get("activities")
        if acts:
            return ", ".join(str(a).replace("_", " ") for a in acts[:5])
        return str(v.get("value") or v.get("activity") or "")
    if slot == "user_memory" and isinstance(v, dict):
        return str(v.get("text") or v.get("object") or "")
    if slot == "relationship" and isinstance(v, dict):
        people = v.get("people") or []
        names = [
            p.get("display_name") or p.get("name")
            for p in people
            if isinstance(p, dict) and (p.get("display_name") or p.get("name"))
        ]
        return ", ".join(str(n) for n in names)
    if slot == "follow_up" and isinstance(v, dict):
        return str(v.get("current_task") or v.get("situation") or "")
    if slot == "time_now" and isinstance(v, dict):
        return f"{v.get('weekday')} {v.get('local_time')}"
    if slot == "still_at_office" and isinstance(v, dict):
        if v.get("at_office"):
            return str(v.get("situation") or "still at the office")
        return str(v.get("situation") or "not at the office right now")
    if slot == "leave_work" and isinstance(v, dict):
        return str(v.get("phrase") or v.get("local_time") or "")
    if slot == "arrive_home" and isinstance(v, dict):
        return str(v.get("phrase") or v.get("local_time") or "")
    if slot == "transport" and isinstance(v, dict):
        return str(v.get("phrase") or v.get("commute_mode") or "")
    return str(v)


def fallback_messages_from_answer_plan(plan: dict[str, Any]) -> list[str]:
    """Deterministic bubbles from the answer plan (one per question)."""
    messages: list[str] = []
    for ans in plan.get("answers") or []:
        slot = ans.get("slot") or "none"
        if slot == "none":
            continue
        if ans.get("can_answer") and ans.get("direct_answer"):
            messages.append(_naturalize(slot, ans["direct_answer"], ans))
        else:
            messages.append(_unknown_reply(slot, ans.get("missing")))
    return messages[:5] or ["Not sure off the top of my head, honestly."]


def _naturalize(slot: str, direct: str, ans: dict[str, Any]) -> str:
    direct = (direct or "").strip()
    if slot == "meal_now":
        return f"{direct.capitalize() if direct[:1].islower() else direct} today, actually 😂"
    if slot == "activity_now":
        return f"I'm {direct}." if direct and not direct.lower().startswith("i'm") else (direct or "Just getting on with things.")
    if slot == "location_now":
        return f"I'm {direct}." if direct and not direct.lower().startswith(("i'm", "i am")) else (direct or "Just out and about.")
    if slot == "task_now":
        return f"Working on the {direct} at the moment." if direct else "Just the usual work bits."
    if slot == "occupation":
        return f"I'm a {direct}." if direct else "I work in finance."
    if slot == "employer":
        return f"I work at {direct}." if direct else "I'd rather not say who I work for."
    if slot == "office":
        return f"Our office is at {direct}." if direct else "It's in Manchester city centre."
    if slot == "project":
        return f"Mainly the {direct} right now." if direct else "A few finance projects on the go."
    if slot == "preference":
        return f"Honestly I {direct}." if direct else "Hmm, nothing specific jumps out."
    if slot == "identity":
        if direct and "aries" in direct.lower() and "live" not in direct.lower() and "grew" not in direct.lower():
            return f"I'm an {direct}."
        return direct or "Yeah."
    if slot == "plan_future":
        return f"Probably going to {direct}." if direct else "Nothing fancy planned yet."
    if slot == "event_past":
        return f"Yesterday was mostly {direct}." if direct else "Can't remember the details, honestly."
    if slot == "user_memory":
        return f"Yeah — {direct}." if direct else "I don't think I have that detail."
    if slot == "time_now":
        return f"It's {direct}." if direct else "Not sure offhand."
    if slot == "still_at_office":
        return direct if direct else "Yeah, still at the office."
    if slot == "leave_work":
        return direct if direct else "I'll probably leave around the usual time."
    if slot == "arrive_home":
        return direct if direct else "Should be home a bit after I leave, give or take."
    if slot == "transport":
        return direct if direct else "I usually get in on public transport."
    if slot == "follow_up":
        if direct:
            return (
                f"Haha, it definitely has its moments 😂 "
                f"But I actually don't mind it when the {direct} finally lines up."
            )
        return "Haha, yeah — it has its moments 😂"
    return direct or "Yeah."


def _unknown_reply(slot: str, missing: str | None) -> str:
    if slot == "meal_now":
        return "Not sure what I'll have yet, honestly."
    if slot == "event_past":
        return "I don't think I have that detail — yesterday's a bit of a blur."
    if slot == "user_memory":
        return "I don't think I have that detail, sorry."
    if slot == "plan_future":
        return "Nothing set in stone yet."
    if slot == "leave_work":
        return "Not sure exactly when I'll finish yet."
    if slot == "arrive_home":
        return "Hard to say — depends when I leave."
    if slot == "preference" or missing == "preference_unknown":
        return "Hmm, nothing specific jumps out — not sure I have a favourite for that."
    if missing == "not_in_meal_window":
        return "I'm not eating right now."
    return "Not sure off the top of my head, honestly."


# Leakage phrases used by validator
LEAKAGE_PHRASES_BY_SLOT: dict[str, list[str]] = {
    "office": ["northbridge", "alderbrook"],
    "occupation": ["management accountant", "northbridge"],
    "identity": ["aries"],
    "relationship": ["diane", "mark", "emily", "maya", "sophie"],
    "project": ["monthly financial reporting", "finance dashboard", "annual budget"],
}
