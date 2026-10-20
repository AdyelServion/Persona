"""Current reality layers: permanent / semi-persistent / world / conversation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from persona_runtime.db.time_utils import utcnow
from persona_runtime.life.activities import (
    availability_label,
    location_display_name,
    location_type_for,
    next_activity_phrase,
    situation_for_activity,
)
from persona_runtime.persona.constants import (
    CURRENT_PROJECTS,
    EMPLOYMENT_PROFILE,
    SEED_CANONICAL_FACTS,
)

QuestionTarget = Literal[
    "location_now",
    "activity_now",
    "current_task",
    "at_home",
    "office_location",
    "projects",
    "zodiac",
    "permanent_identity",
    "habit",
    "follow_up",
    "none",
]

NOW_TARGETS = frozenset(
    {"location_now", "activity_now", "current_task", "at_home", "follow_up"}
)
EMPLOYMENT_TARGETS = frozenset({"office_location", "projects", "permanent_identity"})
PROFILE_TARGETS = frozenset({"zodiac", "permanent_identity", "office_location", "projects"})

BIOGRAPHY_FACT_IDS = (
    "PERSONA_FACT_OCCUPATION",
    "PERSONA_FACT_DEGREE",
    "PERSONA_FACT_LIVES_IN",
    "PERSONA_FACT_MOVED_MANCHESTER",
    "PERSONA_FACT_UNIVERSITY",
)

EMPLOYMENT_FACT_IDS = (
    "PERSONA_FACT_OCCUPATION",
    "PERSONA_FACT_EMPLOYER",
    "PERSONA_FACT_OFFICE",
)

SEMI_PERSISTENT_HABITS: list[dict[str, str]] = [
    {
        "habit_id": "usually_office",
        "text": "Sarah usually works from an office.",
        "phrasing": "usually works from an office",
    },
    {
        "habit_id": "enjoys_coffee",
        "text": "Sarah enjoys coffee.",
        "phrasing": "enjoys coffee",
    },
    {
        "habit_id": "likes_friends",
        "text": "Sarah likes going out with friends.",
        "phrasing": "likes going out with friends",
    },
    {
        "habit_id": "favourite_food",
        "text": (
            "Sarah's favourite foods include Italian pasta and risotto, "
            "Japanese sushi, Thai pad thai, and a British Sunday roast."
        ),
        "phrasing": "love Italian food — especially a good pasta or risotto",
    },
    {
        "habit_id": "favourite_hobbies",
        "text": (
            "Sarah's hobbies include cooking new recipes, walking around Manchester, "
            "reading, photography, trying new cafes, personal budgeting, and weekend city breaks."
        ),
        "phrasing": (
            "love cooking new recipes and walking around Manchester — "
            "reading and photography when I get the time"
        ),
    },
]

_LOCATION_NOW = re.compile(
    r"\bwhere\s+are\s+you\b|"
    r"\bwhere\s+are\s+you\s+at\b|"
    r"\bwhere\s*(?:r|re)\s+you\b|"
    r"\bwhereabouts\s+are\s+you\b|"
    r"\bwhere\s+are\s+you\s+(?:right\s+)?now\b|"
    r"\bwhere\s+you\s+at\b",
    re.I,
)
_LOCATION_LIVE = re.compile(
    r"\bwhere\s+do\s+you\s+live\b|"
    r"\bwhere\s+are\s+you\s+from\b|"
    r"\byour\s+city\b|"
    r"\bwhich\s+city\b",
    re.I,
)
_WORKING_ON = re.compile(
    r"\bwhat\s+are\s+you\s+(?:currently\s+)?working\s+on\b|"
    r"\bwhat(?:'s|\s+is)\s+you(?:r)?\s+working\s+on\b|"
    r"\bwhat\s+you\s+working\s+on\b|"
    r"\bwhat\s+are\s+you\s+currently\s+working\s+on\b",
    re.I,
)
_PROJECTS_ASK = re.compile(
    r"\bwhat\s+projects?\s+(?:are\s+you|you)\s+working\s+on\b|"
    r"\bwhat\s+(?:kind\s+of\s+)?projects?\b|"
    r"\byour\s+projects?\b|"
    r"\bwhich\s+projects?\b",
    re.I,
)
_DOING_NOW = re.compile(
    r"\bwhat\s+are\s+you\s+doing\b|"
    r"\bwhat(?:'s|\s+is)\s+up\s+(?:with\s+you\s+)?(?:right\s+)?now\b|"
    r"\bwhat(?:'s|\s+is)\s+going\s+on\s+(?:with\s+you\s+)?(?:right\s+)?now\b",
    re.I,
)
_AT_HOME = re.compile(
    r"\bare\s+you\s+at\s+home\b|"
    r"\byou\s+at\s+home\b|"
    r"\bat\s+home\s*\??\s*$|"
    r"\bare\s+you\s+home\b",
    re.I,
)
_OFFICE_ASK = re.compile(
    r"\bwhere\s+is\s+your\s+office\b|"
    r"\bwhere(?:'s|\s+is)\s+the\s+office\b|"
    r"\byour\s+office\s+located\b|"
    r"\boffice\s+located\b|"
    r"\bwhere(?:'s|\s+is)\s+your\s+office\b|"
    r"\boffice\s+location\b|"
    r"\bwhere\s+is\s+your\s+office\s+located\b",
    re.I,
)
_JOB_ASK = re.compile(
    r"\bwhat\s+do\s+you\s+do\b|"
    r"\bwhat\s+do\s+you\s+actually\s+do\b|"
    r"\bwhat\s+do\s+you\s+do\s+there\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+job\b|"
    r"\bwhat\s+is\s+your\s+job\b|"
    r"\byour\s+occupation\b|"
    r"\bwhat\s+do\s+you\s+work\s+as\b|"
    r"\bwhere\s+do\s+you\s+work\b",
    re.I,
)
_ZODIAC_ASK = re.compile(
    r"\bzodi[ac]+\s+sign\b|"
    r"\bstar\s+sign\b|"
    r"\byour\s+sign\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+sign\b",
    re.I,
)
_DOB_ASK = re.compile(
    r"\bdate\s+of\s+birth\b|"
    r"\bbirthday\b|"
    r"\bwhen\s+(?:were|was)\s+you\s+born\b|"
    r"\bborn\s+on\b",
    re.I,
)
_HABIT_ASK = re.compile(
    r"\busually\b|"
    r"\bdo\s+you\s+(?:like|enjoy|tend|prefer)\b|"
    r"\bwhat\s+do\s+you\s+(?:like|enjoy)\b",
    re.I,
)
_FAVORITE_ASK = re.compile(
    r"\b(?:what(?:'s|\s+is)|whats)\s+your\s+(?:favou?rite|favorite)\b|"
    r"\byour\s+(?:favou?rite|favorite)\s+(?:dish|food|meal|cuisine|thing)\b|"
    r"\b(?:favou?rite|favorite)\s+(?:dish|food|meal)\b",
    re.I,
)
# Breaks / meetings: "what are you doing?" = the activity, not the day's desk task
_ACTIVITY_ONLY = frozenset({"lunch", "coffee_break", "meeting"})
_FOLLOW_UP_REACTION = re.compile(
    r"^(?:sounds?\s+(?:boring|dull|tedious|fun|nice|good)|"
    r"haha|lol|lmao|😂|😅|"
    r"boring|tedious|"
    r"(?:that(?:'s| is)\s+)?(?:rough|tough|fair|true)|"
    r"nice|cool|fair\s+enough|"
    r"yeah|yep|true)[\s!.😂😅]*$",
    re.I,
)
_RIGHT_NOW = re.compile(r"\bright\s+now\b|\bat\s+this\s+time\b|\bat\s+the\s+moment\b", re.I)

def _classify_single(norm: str, raw: str, *, last_question_target: str | None) -> QuestionTarget:
    """Classify one short question / clause."""
    if not norm:
        return "none"

    if last_question_target in NOW_TARGETS and _FOLLOW_UP_REACTION.match(norm):
        return "follow_up"
    if last_question_target in NOW_TARGETS and len(norm.split()) <= 6 and "?" not in raw:
        if any(k in norm for k in ("boring", "haha", "lol", "sounds", "😂")):
            return "follow_up"

    if _ZODIAC_ASK.search(norm):
        return "zodiac"
    if _DOB_ASK.search(norm):
        return "permanent_identity"

    if _OFFICE_ASK.search(norm):
        return "office_location"
    if _AT_HOME.search(norm):
        return "at_home"

    if _LOCATION_NOW.search(norm) and not _LOCATION_LIVE.search(norm):
        return "location_now"
    if _LOCATION_LIVE.search(norm):
        return "permanent_identity"
    if _LOCATION_NOW.search(norm):
        return "location_now"

    if _PROJECTS_ASK.search(norm):
        return "projects"
    if _WORKING_ON.search(norm):
        return "current_task"
    if _DOING_NOW.search(norm) or (_RIGHT_NOW.search(norm) and "where" not in norm.split()[:3]):
        if any(k in norm for k in ("work", "working", "task", "report")):
            return "current_task"
        return "activity_now"

    if _JOB_ASK.search(norm):
        return "permanent_identity"

    if _FAVORITE_ASK.search(norm):
        return "habit"
    if _HABIT_ASK.search(norm) and "?" in raw:
        return "habit"

    return "none"


def classify_question_target(
    message: str,
    *,
    last_question_target: str | None = None,
) -> QuestionTarget:
    """Route a user message to permanent / habit / world / follow-up layers.

    For multi-question bursts, returns the primary (first meaningful) target;
    use ``classify_question_targets`` for the full list.
    """
    targets = classify_question_targets(
        message, last_question_target=last_question_target
    )
    return targets[0] if targets else "none"


def _split_question_chunks(message: str) -> list[str]:
    """Split a batched / multi-line message into classifiable chunks."""
    raw = (message or "").strip()
    if not raw:
        return []
    # Prefer newline-separated pending messages
    parts = re.split(r"[\n]+", raw)
    chunks: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Also split on ? when several questions are in one line
        if part.count("?") >= 2:
            pieces = re.split(r"(?<=[?])\s+", part)
            chunks.extend(p.strip() for p in pieces if p.strip())
        else:
            chunks.append(part)
    return chunks or [raw]


def classify_question_targets(
    message: str,
    *,
    last_question_target: str | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> list[QuestionTarget]:
    """Classify every question in a burst; preserve answer order."""
    texts: list[str] = []
    if pending_messages:
        for m in pending_messages:
            if isinstance(m, dict):
                content = (m.get("content") or "").strip()
            else:
                content = str(m or "").strip()
            if content:
                texts.append(content)
    if not texts:
        texts = _split_question_chunks(message)

    found: list[QuestionTarget] = []
    seen: set[str] = set()
    for text in texts:
        for chunk in _split_question_chunks(text):
            norm = " ".join(chunk.lower().split())
            target = _classify_single(
                norm, chunk, last_question_target=last_question_target
            )
            if target == "none" or target in seen:
                continue
            seen.add(target)
            found.append(target)

    if not found:
        norm = " ".join((message or "").lower().split())
        single = _classify_single(
            norm, message or "", last_question_target=last_question_target
        )
        if single != "none":
            return [single]
        return []

    # Preserve user-message discovery order (one bubble per question as asked)
    return found


def build_world_state(
    current: dict[str, Any] | None,
    *,
    tz_name: str = "Europe/London",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = current or {}
    activity = current.get("current_activity")
    location_key = current.get("current_location")
    situation = current.get("situation") or situation_for_activity(activity or "")
    avail = current.get("availability")
    loc_type = current.get("location_type") or location_type_for(location_key, activity)
    display_loc = location_display_name(location_key)
    # Prefer named office when at work
    if loc_type == "office":
        display_loc = EMPLOYMENT_PROFILE["office"]["name"]
    elif loc_type == "home":
        display_loc = "home"

    moment = now or utcnow()
    try:
        local = moment.astimezone(ZoneInfo(tz_name))
    except Exception:  # noqa: BLE001
        local = moment

    next_act = current.get("next_planned_activity") or next_activity_phrase(
        current.get("next_activity")
    )
    last_loc = current.get("last_location")
    if last_loc:
        last_loc_display = (
            EMPLOYMENT_PROFILE["office"]["name"]
            if (last_loc or "").lower() in {"office", "near_work"}
            else location_display_name(last_loc)
        )
    else:
        last_loc_display = display_loc

    return {
        "date": local.date().isoformat(),
        "time": local.strftime("%H:%M"),
        "location": display_loc,
        "location_key": location_key,
        "location_type": loc_type,
        "activity": activity,
        "current_task": current.get("current_task"),
        "task_detail": current.get("task_detail"),
        "current_project": current.get("current_project"),
        "situation": situation,
        "availability": availability_label(
            float(avail) if avail is not None else None,
            busy=bool(current.get("busy")),
            sleeping=bool(current.get("sleeping")),
        ),
        "busy": bool(current.get("busy")),
        "sleeping": bool(current.get("sleeping")),
        "last_location": last_loc_display,
        "next_planned_activity": next_act,
        "next_activity": current.get("next_activity"),
    }


def employment_snapshot() -> dict[str, Any]:
    return {
        "employer": dict(EMPLOYMENT_PROFILE["employer"]),
        "job": dict(EMPLOYMENT_PROFILE["job"]),
        "office": dict(EMPLOYMENT_PROFILE["office"]),
    }


def projects_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "name": p["name"],
            "status": p["status"],
            "description": p["description"],
        }
        for p in CURRENT_PROJECTS
    ]


def permanent_facts_snapshot() -> list[dict[str, Any]]:
    wanted = {
        "PERSONA_FACT_OCCUPATION",
        "PERSONA_FACT_DEGREE",
        "PERSONA_FACT_LIVES_IN",
        "PERSONA_FACT_DOB",
        "PERSONA_FACT_ZODIAC",
        "PERSONA_FACT_EMPLOYER",
        "PERSONA_FACT_OFFICE",
    }
    out = []
    for f in SEED_CANONICAL_FACTS:
        if f.get("fact_id") in wanted:
            out.append(
                {
                    "fact_id": f["fact_id"],
                    "predicate": f.get("predicate"),
                    "object": f.get("object"),
                }
            )
    return out


def build_reality_layers(
    *,
    current: dict[str, Any] | None,
    understanding: dict[str, Any] | None,
    conversation_context: dict[str, Any] | None,
    tz_name: str = "Europe/London",
) -> dict[str, Any]:
    understanding = understanding or {}
    conv = conversation_context or {}
    world = build_world_state(current, tz_name=tz_name)
    target = understanding.get("question_target") or conv.get("last_question_target") or "none"
    targets = list(understanding.get("question_targets") or [])
    if not targets and target and target != "none":
        targets = [target]
    return {
        "permanent": permanent_facts_snapshot(),
        "employment": employment_snapshot(),
        "projects": projects_snapshot(),
        "semi_persistent": [
            {"habit_id": h["habit_id"], "text": h["text"]} for h in SEMI_PERSISTENT_HABITS
        ],
        "world_state": world,
        "conversation_state": {
            "question_target": target,
            "question_targets": targets,
            "current_topic": conv.get("current_topic") or understanding.get("topic"),
            "last_question_target": conv.get("last_question_target"),
            "last_world_snapshot": conv.get("last_world_snapshot") or {},
        },
        "rule": (
            "Answer now-questions (location_now, activity_now, current_task, at_home, follow_up) "
            "only from world_state / last_world_snapshot. "
            "Answer office_location from employment.office (address + city + employer). "
            "Answer projects from projects + world_state.current_project. "
            "Answer zodiac / DOB / job-title questions from permanent / employment when allowed. "
            "Answer habit / favourite questions from the matching semi_persistent habit only "
            "(food → Italian pasta/risotto etc.; hobby → cooking, walking, reading, photography; "
            "coffee → enjoys coffee; friends → going out) — never substitute a different favourite "
            "than what was asked. Phrase as usually / generally — never as this moment. "
            "When question_targets has several entries: one short chat bubble per target, in order — "
            "never mash unrelated answers into one paragraph. Answer only what was asked. "
            "Do not invent a different location or activity than world_state."
        ),
    }


def talking_points_for_target(
    target: str,
    *,
    world: dict[str, Any],
    last_world: dict[str, Any] | None = None,
    employment: dict[str, Any] | None = None,
    projects: list[dict[str, Any]] | None = None,
) -> list[str]:
    snap = world if target != "follow_up" else (last_world or world)
    situation = snap.get("situation") or ""
    task = snap.get("current_task") or ""
    detail = snap.get("task_detail") or ""
    activity = snap.get("activity") or ""
    location = snap.get("location") or ""
    loc_type = snap.get("location_type") or ""
    project = snap.get("current_project") or ""
    next_plan = snap.get("next_planned_activity") or ""
    emp = employment or employment_snapshot()
    office = emp.get("office") or {}
    job = emp.get("job") or {}
    employer = emp.get("employer") or {}
    proj_list = projects if projects is not None else projects_snapshot()

    if target == "location_now":
        points = [f"say you are {situation}" if situation else f"say you are at {location}"]
        if activity == "lunch" and next_plan:
            points.append(f"mention you are heading back soon: {next_plan}")
        elif activity in {"working", "deep_work"} and task:
            points.append(f"optionally mention you are working on {task}")
        return points
    if target == "at_home":
        if loc_type == "home":
            return ["say yes, you are at home", f"situation: {situation}"]
        return [
            "say no, you are not at home",
            f"say you are at {location} / {situation}",
            "keep it light and natural",
        ]
    if target == "current_task":
        if task:
            return [
                f"answer with current task/project: {project or task}",
                f"detail: {detail}" if detail else "keep it concrete and short",
                "do not recite degree or living-in-Manchester",
            ]
        return [
            f"describe what you are doing now: {activity or situation}",
            "do not recite degree or living-in-Manchester",
        ]
    if target == "activity_now":
        if activity in _ACTIVITY_ONLY:
            return [
                f"say you are {situation or activity}",
                "do not mention current_task or task_detail — you are on a break/meeting",
                "do not recite degree or living-in-Manchester",
            ]
        return [
            f"say you are {situation or activity}",
            f"task: {task}" if task and activity in {"working", "deep_work"} else "stay with the current activity",
            "do not recite degree or living-in-Manchester",
        ]
    if target == "office_location":
        return [
            f"office is in {office.get('city', 'Manchester')} city centre",
            f"employer: {employer.get('name')}",
            f"address: {office.get('address')}",
            "do not answer with only 'I usually work from an office'",
        ]
    if target == "projects":
        names = [p["name"] for p in proj_list]
        lead = project or (names[0] if names else task)
        return [
            f"lead with current project: {lead}",
            f"also mention: {', '.join(names)}" if names else "mention active projects",
            "keep it conversational",
        ]
    if target == "zodiac":
        return ["say you are an Aries", "optionally tie to birthday April 17 if natural"]
    if target == "permanent_identity":
        return [
            f"job title: {job.get('title')}",
            f"summary: {job.get('summary')}",
            "answer only what was asked",
        ]
    if target == "follow_up":
        bits = ["react naturally to what you just said"]
        if task:
            bits.append(f"stay on {task} — do not change topic to biography")
        elif situation:
            bits.append(f"stay on being {situation}")
        return bits
    if target == "habit":
        return [
            "answer the preference topic that was asked from the matching semi_persistent habit",
            "food/dish → Italian pasta or risotto (also Japanese, Thai, British favourites)",
            "hobby/hobbies → cooking, walking around Manchester, reading, photography, cafes",
            "coffee/drink → enjoys coffee; friends/going out → likes going out with friends",
            "never answer a hobby question with food, or a food question with hobbies",
            "phrase as usually / generally — do not claim it is happening right now",
        ]
    return []


def talking_points_for_targets(
    targets: list[str],
    *,
    world: dict[str, Any],
    last_world: dict[str, Any] | None = None,
) -> list[str]:
    if not targets:
        return []
    emp = employment_snapshot()
    projects = projects_snapshot()
    points: list[str] = []
    if len(targets) > 1:
        points.append(
            f"one short chat bubble per target, in order (separate messages): {', '.join(targets)}"
        )
    for t in targets:
        points.extend(
            talking_points_for_target(
                t, world=world, last_world=last_world, employment=emp, projects=projects
            )
        )
    return points


def _fallback_fragment(target: str, snap: dict[str, Any]) -> str:
    situation = (snap.get("situation") or "").strip()
    task = (snap.get("current_task") or "").strip()
    detail = (snap.get("task_detail") or "").strip()
    activity = (snap.get("activity") or "").strip()
    location = (snap.get("location") or "").strip()
    loc_type = (snap.get("location_type") or "").strip()
    project = (snap.get("current_project") or "").strip()
    next_plan = (snap.get("next_planned_activity") or "").strip()
    emp = employment_snapshot()
    office = emp["office"]
    job = emp["job"]
    employer = emp["employer"]

    if target == "location_now":
        if activity == "lunch":
            bit = f"I'm at the office at the moment — just finished lunch"
            if next_plan:
                bit += f" and I'm heading back to my desk"
            return bit + "."
        if situation and task and activity in {"working", "deep_work"}:
            return f"I'm {situation} at the moment, working through some {task}."
        if situation:
            return f"I'm {situation} at the moment."
        if location:
            return f"I'm at the {location} at the moment."
        return "I'm just getting on with my day at the moment."

    if target == "at_home":
        if loc_type == "home":
            return "Yeah, I'm at home today."
        place = location or "work"
        return f"Nope 😂 I'm at work today. I'm in the finance office in Manchester." if "office" in (
            location or ""
        ).lower() or loc_type == "office" else f"Nope — I'm at {place} right now."

    if target == "current_task":
        label = project or task
        if label and detail:
            return f"I'm working on the {label} at the moment. I'm {detail}."
        if label:
            return f"I'm working on the {label} at the moment."
        if task:
            return f"Mostly the {task}."
        if situation:
            return f"Just {situation} right now."
        return "Just the usual bits and pieces for today."

    if target == "activity_now":
        if activity in _ACTIVITY_ONLY:
            if situation:
                return f"I'm {situation}."
            return f"I'm {activity}."
        if situation and task and activity in {"working", "deep_work"}:
            return f"I'm {situation}, working through {task}."
        if situation:
            return f"I'm {situation}."
        return f"I'm {activity or 'just getting on with things'}."

    if target == "office_location":
        return (
            f"It's in {office['city']} city centre. I work for {employer['name']}, "
            f"and our finance office is at {office['address']}."
        )

    if target == "projects":
        names = [p["name"] for p in projects_snapshot()]
        lead = project or (names[0] if names else "monthly financial reporting")
        others = [n for n in names if n.lower() != lead.lower()]
        reply = f"At the moment I'm mainly working on the {lead}."
        if others:
            reply += f" I'm also helping with {others[0].lower()}"
            if len(others) > 1:
                reply += f", and we've started preparing for the {others[1].lower()}"
            reply += "."
        return reply

    if target == "zodiac":
        return "I'm an Aries."

    if target == "permanent_identity":
        return (
            f"I'm a {job['title']}. {job['summary']}"
        )

    if target == "follow_up":
        if task:
            return (
                f"Haha, it definitely has its moments 😂 "
                f"But I actually don't mind it when the {task} finally lines up."
            )
        if situation:
            return f"Haha, yeah — {situation} isn't always thrilling, but it is what it is."
        return "Haha, yeah, it has its moments."

    if target == "habit":
        # Generic habit fallback — do not assume food; answer_plan path is kind-aware
        return "Depends what you mean — happy to say more if you narrow it down."

    return ""


def world_state_fallback_messages(
    target: str,
    *,
    world: dict[str, Any],
    last_world: dict[str, Any] | None = None,
    targets: list[str] | None = None,
) -> list[str]:
    """One short bubble per target (or a single fragment)."""
    snap = last_world if target == "follow_up" and last_world else world
    use_targets = list(targets or [])
    if not use_targets and target and target != "none":
        use_targets = [target]

    if len(use_targets) > 1:
        messages: list[str] = []
        for t in use_targets[:5]:
            frag = _fallback_fragment(t, snap if t != "follow_up" else (last_world or snap))
            if frag:
                messages.append(frag.strip())
        return messages or ["Yeah, fair enough."]

    frag = _fallback_fragment(use_targets[0] if use_targets else target, snap)
    return [frag.strip()] if frag else ["Yeah, fair enough."]


def world_state_fallback_reply(
    target: str,
    *,
    world: dict[str, Any],
    last_world: dict[str, Any] | None = None,
    targets: list[str] | None = None,
) -> str:
    messages = world_state_fallback_messages(
        target, world=world, last_world=last_world, targets=targets
    )
    return "\n".join(messages)


def reply_has_biography_dump(reply: str) -> bool:
    lower = (reply or "").lower()
    markers = (
        "management accountant",
        "accounting and finance",
        "living in manchester",
        "lived in manchester",
        "been living in manchester",
        "been in manchester for",
    )
    return any(m in lower for m in markers)


def reply_is_habit_only_office(reply: str) -> bool:
    """True when the reply only says she usually works from an office (no address)."""
    lower = (reply or "").lower()
    if "alderbrook" in lower or "northbridge" in lower:
        return False
    return bool(
        re.search(r"\busually\s+work(?:s)?\s+from\s+an?\s+office\b", lower)
    ) and "manchester" not in lower
