"""Activity parameter table for Sarah's life simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from persona_runtime.persona.constants import CURRENT_PROJECTS, EMPLOYMENT_PROFILE

if TYPE_CHECKING:
    from random import Random


@dataclass(frozen=True)
class ActivityParams:
    key: str
    location: str
    availability: float
    attention: float
    interruption_tolerance: float
    # delay ranges in minutes (before LIFE_TIME_SCALE)
    delay_min_minutes: float
    delay_max_minutes: float
    typical_duration_minutes: float
    response_probability: float
    may_mention: bool
    sleeping: bool = False
    busy: bool = False


ACTIVITIES: dict[str, ActivityParams] = {
    "sleeping": ActivityParams(
        key="sleeping",
        location="home",
        availability=0.0,
        attention=1.0,
        interruption_tolerance=0.0,
        delay_min_minutes=0,
        delay_max_minutes=0,
        typical_duration_minutes=420,
        response_probability=0.0,
        may_mention=False,
        sleeping=True,
        busy=True,
    ),
    "waking_up": ActivityParams(
        key="waking_up",
        location="home",
        availability=0.35,
        attention=0.40,
        interruption_tolerance=0.40,
        delay_min_minutes=5,
        delay_max_minutes=25,
        typical_duration_minutes=30,
        response_probability=0.55,
        may_mention=True,
    ),
    "breakfast": ActivityParams(
        key="breakfast",
        location="home",
        availability=0.70,
        attention=0.35,
        interruption_tolerance=0.70,
        delay_min_minutes=2,
        delay_max_minutes=20,
        typical_duration_minutes=30,
        response_probability=0.80,
        may_mention=True,
    ),
    "commuting": ActivityParams(
        key="commuting",
        location="commute",
        availability=0.45,
        attention=0.50,
        interruption_tolerance=0.55,
        delay_min_minutes=5,
        delay_max_minutes=30,
        typical_duration_minutes=45,
        response_probability=0.65,
        may_mention=True,
    ),
    "working": ActivityParams(
        key="working",
        location="office",
        availability=0.60,
        attention=0.75,
        interruption_tolerance=0.45,
        delay_min_minutes=3,
        delay_max_minutes=30,
        typical_duration_minutes=120,
        response_probability=0.70,
        may_mention=True,
        busy=False,
    ),
    "deep_work": ActivityParams(
        key="deep_work",
        location="office",
        availability=0.20,
        attention=0.95,
        interruption_tolerance=0.15,
        delay_min_minutes=15,
        delay_max_minutes=60,
        typical_duration_minutes=90,
        response_probability=0.40,
        may_mention=False,
        busy=True,
    ),
    "meeting": ActivityParams(
        key="meeting",
        location="office",
        availability=0.05,
        attention=0.95,
        interruption_tolerance=0.05,
        delay_min_minutes=20,
        delay_max_minutes=120,
        typical_duration_minutes=45,
        response_probability=0.10,
        may_mention=True,
        busy=True,
    ),
    "lunch": ActivityParams(
        key="lunch",
        location="office",
        availability=0.65,
        attention=0.40,
        interruption_tolerance=0.70,
        delay_min_minutes=5,
        delay_max_minutes=25,
        typical_duration_minutes=45,
        response_probability=0.75,
        may_mention=True,
    ),
    "coffee_break": ActivityParams(
        key="coffee_break",
        location="office",
        availability=0.80,
        attention=0.35,
        interruption_tolerance=0.85,
        delay_min_minutes=1,
        delay_max_minutes=15,
        typical_duration_minutes=15,
        response_probability=0.90,
        may_mention=True,
    ),
    "gym": ActivityParams(
        key="gym",
        location="gym",
        availability=0.30,
        attention=0.70,
        interruption_tolerance=0.25,
        delay_min_minutes=5,
        delay_max_minutes=40,
        typical_duration_minutes=60,
        response_probability=0.45,
        may_mention=True,
        busy=True,
    ),
    "shopping": ActivityParams(
        key="shopping",
        location="city",
        availability=0.40,
        attention=0.55,
        interruption_tolerance=0.45,
        delay_min_minutes=10,
        delay_max_minutes=60,
        typical_duration_minutes=60,
        response_probability=0.55,
        may_mention=True,
    ),
    "cooking": ActivityParams(
        key="cooking",
        location="home",
        availability=0.45,
        attention=0.60,
        interruption_tolerance=0.40,
        delay_min_minutes=10,
        delay_max_minutes=35,
        typical_duration_minutes=45,
        response_probability=0.60,
        may_mention=True,
    ),
    "eating": ActivityParams(
        key="eating",
        location="home",
        availability=0.55,
        attention=0.35,
        interruption_tolerance=0.60,
        delay_min_minutes=5,
        delay_max_minutes=25,
        typical_duration_minutes=30,
        response_probability=0.70,
        may_mention=True,
    ),
    "reading": ActivityParams(
        key="reading",
        location="home",
        availability=0.70,
        attention=0.55,
        interruption_tolerance=0.65,
        delay_min_minutes=10,
        delay_max_minutes=45,
        typical_duration_minutes=60,
        response_probability=0.75,
        may_mention=True,
    ),
    "watching_tv": ActivityParams(
        key="watching_tv",
        location="home",
        availability=0.80,
        attention=0.30,
        interruption_tolerance=0.85,
        delay_min_minutes=1,
        delay_max_minutes=20,
        typical_duration_minutes=90,
        response_probability=0.90,
        may_mention=True,
    ),
    "walking": ActivityParams(
        key="walking",
        location="outdoors",
        availability=0.55,
        attention=0.45,
        interruption_tolerance=0.60,
        delay_min_minutes=5,
        delay_max_minutes=30,
        typical_duration_minutes=30,
        response_probability=0.70,
        may_mention=True,
    ),
    "with_friends": ActivityParams(
        key="with_friends",
        location="city",
        availability=0.25,
        attention=0.70,
        interruption_tolerance=0.20,
        delay_min_minutes=15,
        delay_max_minutes=90,
        typical_duration_minutes=120,
        response_probability=0.35,
        may_mention=True,
        busy=True,
    ),
    "family_call": ActivityParams(
        key="family_call",
        location="home",
        availability=0.15,
        attention=0.85,
        interruption_tolerance=0.15,
        delay_min_minutes=15,
        delay_max_minutes=60,
        typical_duration_minutes=30,
        response_probability=0.30,
        may_mention=True,
        busy=True,
    ),
    "relaxing": ActivityParams(
        key="relaxing",
        location="home",
        availability=0.85,
        attention=0.40,
        interruption_tolerance=0.85,
        delay_min_minutes=1,
        delay_max_minutes=20,
        typical_duration_minutes=90,
        response_probability=0.95,
        may_mention=False,
    ),
    "personal_time": ActivityParams(
        key="personal_time",
        location="home",
        availability=0.85,
        attention=0.40,
        interruption_tolerance=0.85,
        delay_min_minutes=1,
        delay_max_minutes=20,
        typical_duration_minutes=120,
        response_probability=0.90,
        may_mention=False,
    ),
    "running_errands": ActivityParams(
        key="running_errands",
        location="city",
        availability=0.40,
        attention=0.55,
        interruption_tolerance=0.40,
        delay_min_minutes=10,
        delay_max_minutes=45,
        typical_duration_minutes=45,
        response_probability=0.55,
        may_mention=True,
    ),
    "travelling": ActivityParams(
        key="travelling",
        location="transit",
        availability=0.35,
        attention=0.50,
        interruption_tolerance=0.45,
        delay_min_minutes=5,
        delay_max_minutes=40,
        typical_duration_minutes=60,
        response_probability=0.50,
        may_mention=True,
    ),
}


# Optional experience slots materialised for an open activity window
EXPERIENCE_SLOTS_BY_ACTIVITY: dict[str, tuple[str, ...]] = {
    "breakfast": ("meal",),
    "lunch": ("meal",),
    "eating": ("meal",),
}

# Catalogs for simulated experience values (deterministic pick per window)
EXPERIENCE_SLOT_CATALOGS: dict[str, list[str]] = {
    "meal": [
        "a chicken sandwich",
        "leftover pasta",
        "a tuna wrap",
        "soup and a roll",
        "a cheese toastie",
        "a salad bowl",
        "rice and veg",
        "a jacket potato",
    ],
}


def experience_slots_for(activity_key: str) -> tuple[str, ...]:
    return EXPERIENCE_SLOTS_BY_ACTIVITY.get(activity_key or "", ())


# Workday activities that keep today's project/task (cleared once she leaves work)
WORKDAY_TASK_KEEP_ACTIVITIES = frozenset(
    {"working", "deep_work", "meeting", "lunch", "coffee_break"}
)
WORKDAY_LOCATION_TYPES = frozenset({"office"})

# Accountant tasks tied to the project catalog (stable for a work block / day)
WORK_TASKS: list[dict[str, str]] = [
    {
        "current_task": p["current_task"],
        "task_detail": p["task_detail"],
        "current_project": p["name"],
    }
    for p in CURRENT_PROJECTS
    if p.get("status") == "active"
] or [
    {
        "current_task": "monthly financial reporting",
        "task_detail": (
            "checking the revenue figures and making sure everything "
            "reconciles before the report goes out"
        ),
        "current_project": "Monthly Financial Reporting",
    },
]

OFFICE_NAME = EMPLOYMENT_PROFILE["office"]["name"]
HOME_NAME = "home"

# Named place for each coarse location key
LOCATION_DISPLAY_NAMES: dict[str, str] = {
    "office": OFFICE_NAME,
    "home": HOME_NAME,
    "commute": "commute",
    "transit": "transit",
    "city": "Manchester city centre",
    "gym": "the gym",
    "near_work": OFFICE_NAME,
}

LOCATION_TYPE_BY_KEY: dict[str, str] = {
    "office": "office",
    "home": "home",
    "commute": "transit",
    "transit": "transit",
    "city": "city",
    "gym": "city",
    "near_work": "office",
}

# Natural "where I am / what this looks like" phrasing per activity
SITUATION_BY_ACTIVITY: dict[str, str] = {
    "sleeping": "in bed at home",
    "waking_up": "at home, just getting up",
    "breakfast": "at home having breakfast",
    "commuting": "on the commute",
    "working": "at the office at my desk",
    "deep_work": "at the office, heads-down at my desk",
    "meeting": "in a meeting at the office",
    "lunch": "at the office, having lunch",
    "coffee_break": "at the office on a coffee break",
    "gym": "at the gym",
    "shopping": "out shopping in the city",
    "cooking": "at home in the kitchen",
    "eating": "at home eating",
    "reading": "at home reading",
    "watching_tv": "at home watching something",
    "walking": "out for a walk",
    "with_friends": "out with friends in the city",
    "family_call": "at home on a family call",
    "relaxing": "at home relaxing",
    "personal_time": "at home in my own time",
    "running_errands": "out running errands in the city",
    "travelling": "travelling",
}

NEXT_ACTIVITY_PHRASE: dict[str, str] = {
    "working": "get back to my desk",
    "deep_work": "get back into deep work",
    "meeting": "head into a meeting",
    "lunch": "have lunch",
    "coffee_break": "grab a coffee",
    "commuting": "head home",
    "relaxing": "relax for a bit",
    "personal_time": "have a bit of personal time",
    "gym": "go to the gym",
    "cooking": "make something to eat",
    "sleeping": "get some sleep",
}

# Claim phrases that must match current_activity keys
ACTIVITY_CLAIM_PATTERNS: list[tuple[str, list[str]]] = [
    ("gym", ["gym", "at the gym", "workout", "working out"]),
    ("meeting", ["in a meeting", "in meetings", "mid-meeting", "stuck in a meeting"]),
    ("cooking", ["cooking", "making dinner", "making lunch", "in the kitchen"]),
    ("commuting", ["heading home", "on my way home", "commuting", "on the train", "on the bus"]),
    ("working", ["at work", "at the office", "at my desk", "finance office"]),
    ("sleeping", ["asleep", "sleeping", "in bed"]),
    ("with_friends", ["with friends", "out with friends", "enjoying some time in the city", "out in the city"]),
    ("shopping", ["out shopping", "in the shops"]),
    ("running_errands", ["running errands"]),
    ("lunch", ["at lunch", "having lunch", "finished lunch", "just finished lunch"]),
    ("eating", ["eating", "having dinner", "having breakfast"]),
    ("travelling", ["travelling", "traveling"]),
]


def situation_for_activity(activity_key: str) -> str:
    key = (activity_key or "").lower()
    if key in SITUATION_BY_ACTIVITY:
        return SITUATION_BY_ACTIVITY[key]
    params = get_activity(key)
    return SITUATION_BY_ACTIVITY.get(params.key, f"at {params.location}")


def availability_label(availability: float | None, *, busy: bool = False, sleeping: bool = False) -> str:
    if sleeping:
        return "unavailable"
    if busy:
        return "unavailable"
    avail = float(availability if availability is not None else 0.5)
    if avail < 0.25:
        return "unavailable"
    if avail < 0.55:
        return "limited"
    return "available_for_chat"


def pick_work_task(rng: "Random") -> dict[str, str]:
    """Pick a stable work task from the catalog using a Random-like object."""
    choice = rng.choice(WORK_TASKS)
    return {
        "current_task": choice["current_task"],
        "task_detail": choice["task_detail"],
        "current_project": choice.get("current_project") or "",
    }


def location_display_name(location_key: str | None) -> str:
    key = (location_key or "").lower()
    return LOCATION_DISPLAY_NAMES.get(key, key or "somewhere")


def location_type_for(location_key: str | None, activity_key: str | None = None) -> str:
    key = (location_key or "").lower()
    if key in LOCATION_TYPE_BY_KEY:
        return LOCATION_TYPE_BY_KEY[key]
    activity = (activity_key or "").lower()
    if activity in WORKDAY_TASK_KEEP_ACTIVITIES:
        return "office"
    if activity in {"sleeping", "waking_up", "breakfast", "cooking", "eating", "reading", "watching_tv", "relaxing", "personal_time", "family_call"}:
        return "home"
    if activity in {"commuting", "travelling"}:
        return "transit"
    return "city"


def next_activity_phrase(activity_key: str | None) -> str | None:
    key = (activity_key or "").lower()
    if not key:
        return None
    if key in NEXT_ACTIVITY_PHRASE:
        return NEXT_ACTIVITY_PHRASE[key]
    return f"move on to {key.replace('_', ' ')}"


def keeps_workday_task(activity_key: str | None) -> bool:
    return (activity_key or "").lower() in WORKDAY_TASK_KEEP_ACTIVITIES


def get_activity(key: str) -> ActivityParams:
    if key in ACTIVITIES:
        return ACTIVITIES[key]
    # soft fallback for free-text legacy values
    lower = (key or "").lower()
    for k, params in ACTIVITIES.items():
        if k in lower or lower in k:
            return params
    return ACTIVITIES["relaxing"]


def activity_to_state_fields(params: ActivityParams) -> dict[str, Any]:
    return {
        "current_activity": params.key,
        "current_location": params.location,
        "availability": params.availability,
        "focus_level": params.attention,
        "busy": params.busy or params.availability < 0.25,
        "busy_reason": params.key if (params.busy or params.availability < 0.25) else None,
        "sleeping": params.sleeping,
    }
