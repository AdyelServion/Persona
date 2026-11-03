"""Load / seed the per-persona capability profile (Identity doc_type ``capability_profile``)."""

from __future__ import annotations

from typing import Any

from persona_runtime.capability.schemas import CapabilityProfile
from persona_runtime.capability.seed import _DEFAULT_RESTRICTED

DOC_TYPE = "capability_profile"


def minimal_capability_profile(persona_id: str) -> dict[str, Any]:
    """Fallback when no Identity capability_profile exists — not an unrestricted assistant."""
    return CapabilityProfile.model_validate(
        {
            "persona_id": persona_id,
            "general_assistant_mode": False,
            "unsupported_request_behavior": "natural_persona_limitation",
            "uncertain_domain_behavior": "deny_substantive_answer",
            "restricted_domains": list(_DEFAULT_RESTRICTED),
            "domains": [],
            "fallback_styles": [
                "thats not really something id know much about",
                "youve lost me there tbh",
            ],
            "limitation_templates": {
                "generic": [
                    "i've actually never looked into that",
                    "thats not really something id know much about",
                ],
            },
        }
    ).model_dump()


def load_capability_profile(persona_repo: Any, persona_id: str) -> dict[str, Any] | None:
    """Return the validated profile as a dict.

    When the persona has no stored profile, returns a minimal restrictive default
    so capability enforcement still applies.
    """
    doc: dict[str, Any] | None = None
    try:
        doc = persona_repo.get_capability_profile(persona_id)
    except Exception:  # noqa: BLE001
        doc = None
    if not doc or not isinstance(doc.get("profile"), dict):
        return minimal_capability_profile(persona_id)
    try:
        return CapabilityProfile.model_validate({**doc["profile"], "persona_id": persona_id}).model_dump()
    except Exception:  # noqa: BLE001
        return minimal_capability_profile(persona_id)


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
    restricted = [r.get("domain_id") for r in (profile.get("restricted_domains") or []) if r.get("domain_id")]
    return {
        "profession": profile.get("profession"),
        "education": profile.get("education"),
        "industry": profile.get("industry"),
        "core_expertise": labels("core", 7),
        "related_knowledge": labels("related", 5),
        "personal_interests": labels("interest", 6),
        "low_knowledge_areas": weak,
        "restricted_domains": restricted[:8],
        "never_claim": list(profile.get("never_claim") or [])[:4],
        "general_assistant_mode": profile.get("general_assistant_mode", False),
    }
