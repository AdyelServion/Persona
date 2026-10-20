"""Validated location transitions for the timeline engine."""

from __future__ import annotations

# Coarse location keys used by activities.location
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "home": frozenset({"home", "commute", "transit"}),
    "office": frozenset({"office", "commute", "transit", "near_work"}),
    "commute": frozenset({"commute", "transit", "office", "home", "gym", "city", "near_work"}),
    "transit": frozenset({"commute", "transit", "office", "home", "gym", "city", "near_work"}),
    "gym": frozenset({"gym", "commute", "transit", "city"}),
    "city": frozenset({"city", "commute", "transit", "gym", "home"}),
    "near_work": frozenset({"near_work", "office", "commute", "transit"}),
}


def normalize_location(location: str | None) -> str:
    key = (location or "").lower().strip()
    if key in {"transit"}:
        return "commute"
    if key in {"near_work"}:
        return "office"
    return key or "home"


def transition_allowed(from_loc: str | None, to_loc: str | None) -> bool:
    """Return True when moving from_loc → to_loc is valid (or either is empty)."""
    if not from_loc:
        return True
    src = normalize_location(from_loc)
    dst = normalize_location(to_loc)
    if src == dst:
        return True
    allowed = ALLOWED_TRANSITIONS.get(src)
    if allowed is None:
        # Unknown source: allow same-family via commute only
        return dst in {"commute", "transit"} or src == dst
    return dst in allowed or normalize_location(dst) in {
        normalize_location(a) for a in allowed
    }
