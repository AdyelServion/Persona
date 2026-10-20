"""Per-scenario consistency ledger for contradiction detection."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from persona_runtime.db.time_utils import utcnow
from persona_runtime.qa.models import LedgerClaim


class ConsistencyLedger:
    def __init__(self) -> None:
        self.claims: list[LedgerClaim] = []
        self.contradictions: list[dict[str, Any]] = []

    def record(
        self,
        subject: str,
        attribute: str,
        value: Any,
        *,
        source: str,
        status: str = "stated",
        confidence: float = 1.0,
        conversation_id: str | None = None,
        message_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        claim = LedgerClaim(
            subject=subject,
            attribute=attribute,
            value=value,
            source=source,
            status=status,  # type: ignore[arg-type]
            confidence=confidence,
            conversation_id=conversation_id,
            message_id=message_id,
            timestamp=timestamp or utcnow(),
        )
        prior = self.latest(subject, attribute)
        if prior is not None and self._conflicts(prior.value, value):
            # Legitimate transition if statuses allow (planned -> completed, etc.)
            if not self._valid_transition(prior, claim):
                self.contradictions.append(
                    {
                        "subject": subject,
                        "attribute": attribute,
                        "earlier": prior.model_dump(mode="json"),
                        "later": claim.model_dump(mode="json"),
                        "confirmed": True,
                    }
                )
        self.claims.append(claim)

    def latest(self, subject: str, attribute: str) -> LedgerClaim | None:
        for claim in reversed(self.claims):
            if claim.subject == subject and claim.attribute == attribute:
                return claim
        return None

    def seed_canonical(self, facts: list[dict[str, Any]]) -> None:
        for fact in facts:
            self.record(
                "persona",
                str(fact.get("predicate") or fact.get("fact_id")),
                fact.get("object"),
                source="canonical",
                status="canonical",
                confidence=float(fact.get("confidence") or 1.0),
            )

    def _conflicts(self, a: Any, b: Any) -> bool:
        if a is None or b is None:
            return False
        sa = str(a).strip().lower()
        sb = str(b).strip().lower()
        if sa == sb:
            return False
        # bool-ish
        truthy = {"true", "yes", "1"}
        falsy = {"false", "no", "0"}
        if sa in truthy and sb in falsy:
            return True
        if sa in falsy and sb in truthy:
            return True
        # Containment soft match (Manchester vs Manchester, UK)
        if sa in sb or sb in sa:
            return False
        return True

    def _valid_transition(self, prior: LedgerClaim, later: LedgerClaim) -> bool:
        if prior.status == "planned" and later.status in {"completed", "simulated", "stated"}:
            return True
        if prior.status == "simulated" and later.status in {"completed", "stated"}:
            return True
        if prior.source == "canonical" and later.source == "canonical":
            # Canonical overwrite only via explicit fixture correction
            return str(prior.value).lower() == str(later.value).lower()
        if prior.attribute in {"location", "activity", "current_meal"} and later.source in {
            "world",
            "timeline",
            "stated",
        }:
            return True
        return False

    def has_contradiction(self, attribute: str | None = None) -> bool:
        if attribute is None:
            return bool(self.contradictions)
        return any(c.get("attribute") == attribute for c in self.contradictions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": [c.model_dump(mode="json") for c in self.claims],
            "contradictions": self.contradictions,
        }
