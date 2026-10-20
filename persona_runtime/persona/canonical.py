"""Canonical fact contradiction checking."""

from __future__ import annotations

import re
from typing import Any

from persona_runtime.persona.constants import FACT_CONTRADICTIONS


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def extract_candidate_claims(content: Any) -> list[tuple[str, str, str]]:
    """Extract (subject, predicate, object) triples from generated content."""
    claims: list[tuple[str, str, str]] = []
    text = ""
    if isinstance(content, dict):
        text = " ".join(str(v) for v in content.values())
        # Structured fields
        for key, value in content.items():
            key_l = str(key).lower()
            if key_l in {"city", "lives_in", "location", "home_city"} and value:
                claims.append(("sarah", "lives_in", str(value)))
            if key_l in {"hometown", "birthplace"} and value:
                claims.append(("sarah", "hometown", str(value)))
            if key_l in {"university", "alma_mater"} and value:
                claims.append(("sarah", "university", str(value)))
            if key_l in {"occupation", "job_title", "job"} and value:
                claims.append(("sarah", "occupation", str(value)))
    else:
        text = str(content)

    text_l = text.lower()
    city_patterns = [
        (r"lives in ([a-zA-Z ]+)", "lives_in"),
        (r"based in ([a-zA-Z ]+)", "lives_in"),
        (r"from ([a-zA-Z ]+) originally", "hometown"),
        (r"born in ([a-zA-Z ]+)", "hometown"),
        (r"studied at ([a-zA-Z .]+)", "university"),
        (r"works as (?:a |an )?([a-zA-Z ]+)", "occupation"),
    ]
    for pattern, predicate in city_patterns:
        for match in re.finditer(pattern, text_l):
            obj = match.group(1).strip(" .,")
            # Keep original casing lightly
            claims.append(("sarah", predicate, obj.title() if predicate != "occupation" else obj))
    return claims


def conflicts_with_canonical(
    candidate_content: Any,
    canonical_facts: list[dict[str, Any]],
) -> list[str]:
    """Return human-readable conflict reasons, empty if consistent."""
    reasons: list[str] = []
    claims = extract_candidate_claims(candidate_content)
    fact_map: dict[tuple[str, str], set[str]] = {}
    for fact in canonical_facts:
        key = (_normalize(fact["subject"]), _normalize(fact["predicate"]))
        fact_map.setdefault(key, set()).add(str(fact["object"]))

    for subject, predicate, obj in claims:
        key = (_normalize(subject), _normalize(predicate))
        known = fact_map.get(key, set())
        if not known:
            # Check contradiction table against known canonical values for same predicate
            for (s, p), values in fact_map.items():
                if p == _normalize(predicate):
                    known = values
                    break
        if not known:
            continue

        # Direct mismatch
        if all(_normalize(k) != _normalize(obj) for k in known):
            # Use FACT_CONTRADICTIONS if listed
            for known_obj in known:
                banned = FACT_CONTRADICTIONS.get(predicate, {}).get(known_obj, set())
                banned_norm = {_normalize(b) for b in banned}
                if _normalize(obj) in banned_norm or _normalize(obj) not in {_normalize(k) for k in known}:
                    # Only flag if clearly contradictory city/place/uni style
                    if predicate in FACT_CONTRADICTIONS or predicate in {
                        "lives_in",
                        "hometown",
                        "university",
                        "occupation",
                        "date_of_birth",
                        "country",
                    }:
                        reasons.append(
                            f"Claim sarah.{predicate}={obj} conflicts with canonical {sorted(known)}"
                        )
                        break
    # Deduplicate
    return list(dict.fromkeys(reasons))
