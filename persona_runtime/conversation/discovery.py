"""Progressive discovery: what Sarah would naturally want to learn next about this user.

Discovery never runs as a questionnaire — at most one target per reply, only on turns where
a question is already allowed, and never twice within `discovery_min_turn_gap` turns.
"""

from __future__ import annotations

from typing import Any

# (area, memory keys that cover it, natural hint, minimum stage)
DISCOVERY_AREAS: list[tuple[str, tuple[str, ...], str, str]] = [
    ("everyday", ("occupation",), "what their day-to-day looks like (work or study), only if it fits", "getting_to_know"),
    ("hobbies", ("hobby",), "what they enjoy doing in their free time", "getting_to_know"),
    ("weekends", ("weekend_preference",), "what a usual weekend looks like for them", "getting_to_know"),
    ("music", ("music_preference",), "what they've been listening to lately", "building"),
    ("food", ("favourite_food",), "a food they could eat every week", "building"),
    ("sports", ("supports_team",), "whether they follow any sport", "building"),
    ("travel", ("travel_preference",), "a place they'd love to visit", "building"),
    ("lifestyle", ("morning_drink", "lifestyle"), "whether they're a morning person or a night owl", "familiar"),
]

_STAGE_RANK = {"getting_to_know": 0, "building": 1, "familiar": 2}


def discovery_stage(coverage: dict[str, int] | None) -> str:
    total = sum(int(v or 0) for v in (coverage or {}).values())
    if total < 3:
        return "getting_to_know"
    if total < 9:
        return "building"
    return "familiar"


def next_discovery_target(
    *,
    coverage: dict[str, int] | None,
    known_keys: set[str] | None,
    declined_topics: list[str] | None = None,
    recent_topics: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return the first uncovered area appropriate for the current stage, or None."""
    stage = discovery_stage(coverage)
    known = {k for k in (known_keys or set()) if k}
    declined = {d.lower() for d in (declined_topics or [])}
    recent = {r.lower() for r in (recent_topics or []) if r}
    for area, keys, hint, min_stage in DISCOVERY_AREAS:
        if _STAGE_RANK[min_stage] > _STAGE_RANK[stage]:
            continue
        if area in declined or area in recent:
            continue
        if any(k in known for k in keys):
            continue
        return {"area": area, "hint": hint, "stage": stage}
    return None
