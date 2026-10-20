"""Resolve fact references from cloned persona, clock, and world state."""

from __future__ import annotations

from typing import Any

from persona_runtime.graph.reality import SEMI_PERSISTENT_HABITS
from persona_runtime.persona.constants import EMPLOYMENT_PROFILE, TRANSPORT_PROFILE
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.qa.models import FactRef


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def resolve_fact_ref(
    ref: FactRef | dict[str, Any],
    *,
    persona_repo: PersonaRepository | None = None,
    persona_id: str | None = None,
    clock_snapshot: dict[str, Any] | None = None,
    persona_state: dict[str, Any] | None = None,
) -> Any:
    data = FactRef.model_validate(ref) if isinstance(ref, dict) else ref
    if data.source == "literal":
        return data.value
    if data.source == "canonical":
        if not persona_repo or not persona_id or not data.fact_id:
            return None
        for fact in persona_repo.list_canonical_facts(persona_id):
            if fact.get("fact_id") == data.fact_id:
                return fact.get("object")
        return None
    if data.source == "clock":
        snap = clock_snapshot or {}
        field = data.field or "local_time"
        val = snap.get(field)
        if hasattr(val, "isoformat"):
            return val.isoformat()
        return val
    if data.source == "world":
        state = persona_state or {}
        path = data.path or "current_state.location"
        if path.startswith("current_state."):
            current = state.get("current_state") or state
            return _dig(current, path[len("current_state.") :])
        return _dig(state, path)
    if data.source == "habit":
        for habit in SEMI_PERSISTENT_HABITS:
            if habit.get("habit_id") == data.habit_id:
                return habit.get("phrasing") or habit.get("text")
        return None
    if data.source == "transport":
        path = data.path or "commute_mode"
        return _dig(TRANSPORT_PROFILE, path)
    if data.source == "employment":
        path = data.path or "job.title"
        return _dig(EMPLOYMENT_PROFILE, path)
    return data.value


def resolve_expected_map(
    expected: dict[str, Any],
    *,
    persona_repo: PersonaRepository | None = None,
    persona_id: str | None = None,
    clock_snapshot: dict[str, Any] | None = None,
    persona_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in (expected or {}).items():
        if isinstance(val, dict) and "source" in val:
            out[key] = resolve_fact_ref(
                val,
                persona_repo=persona_repo,
                persona_id=persona_id,
                clock_snapshot=clock_snapshot,
                persona_state=persona_state,
            )
        else:
            out[key] = val
    return out
