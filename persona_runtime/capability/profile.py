"""Load / seed the per-persona capability profile (Identity doc_type ``capability_profile``)."""

from __future__ import annotations

from typing import Any

from persona_runtime.capability.schemas import CapabilityProfile

DOC_TYPE = "capability_profile"


def load_capability_profile(persona_repo: Any, persona_id: str) -> dict[str, Any] | None:
    """Return the validated profile as a dict, or None when the persona has none.

    No profile means the capability engine is a no-op for that persona.
    """
    try:
        doc = persona_repo.get_capability_profile(persona_id)
    except Exception:  # noqa: BLE001
        return None
    if not doc or not isinstance(doc.get("profile"), dict):
        return None
    try:
        return CapabilityProfile.model_validate({**doc["profile"], "persona_id": persona_id}).model_dump()
    except Exception:  # noqa: BLE001
        return None


def knowledge_profile_brief(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact prompt view: identity, top core/related domains, interests, low-knowledge areas."""
    if not profile:
        return None
    domains = list(profile.get("domains") or [])

    def labels(tier: str, limit: int) -> list[str]:
        picked = sorted((d for d in domains if d.get("tier") == tier), key=lambda d: -float(d.get("level") or 0))
        return [d.get("label") for d in picked[:limit]]

    weak = [
        d.get("label")
        for d in sorted(domains, key=lambda d: float(d.get("level") or 0))
        if float(d.get("level") or 0) < 0.45
    ][:4]
    return {
        "profession": profile.get("profession"),
        "education": profile.get("education"),
        "industry": profile.get("industry"),
        "core_expertise": labels("core", 7),
        "related_knowledge": labels("related", 5),
        "personal_interests": labels("interest", 6),
        "low_knowledge_areas": weak,
        "never_claim": list(profile.get("never_claim") or [])[:4],
    }
