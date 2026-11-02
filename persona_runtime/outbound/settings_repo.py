"""Per user+persona proactive messaging settings (opt-in, quiet hours, caps, backoff)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.config import Settings, get_settings
from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.users.repositories import clean_timezone

PROACTIVE_TYPES = (
    "interest_followup",
    "event_followup",
    "hobby_followup",
    "weekend_followup",
    "conversation_resumption",
    "new_topic",
    "returning_user_greeting",
)

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
HISTORY_LIMIT = 30


def _validate_hhmm(value: str) -> str:
    v = (value or "").strip()
    if not _HHMM.match(v):
        raise ValueError(f"Invalid time {value!r}; expected HH:MM")
    return v


class ProactiveSettingsRepository:
    def __init__(self, db: Database, settings: Settings | None = None):
        self.col = db[COLLECTION_NAMES["proactive_settings"]]
        self.settings = settings or get_settings()

    def _defaults(self, user_id: str, persona_id: str, timezone: str | None) -> dict[str, Any]:
        now = utcnow()
        s = self.settings
        return {
            "settings_id": str(uuid4()),
            "user_id": user_id,
            "persona_id": persona_id,
            "enabled": False,
            "opted_in_at": None,
            "timezone": clean_timezone(timezone, s.timezone),
            "quiet_start": s.proactive_quiet_start,
            "quiet_end": s.proactive_quiet_end,
            "daily_limit": int(s.proactive_max_per_day),
            "weekly_limit": int(s.proactive_max_per_week),
            "min_gap_hours": float(s.proactive_min_gap_hours),
            "paused_until": None,
            "muted_types": [],
            "unanswered_outbound_id": None,
            "unanswered_since": None,
            "consecutive_unanswered": 0,
            "backoff_level": 0,
            "last_outbound_at": None,
            "outbound_history": [],
            "topic_history": [],
            "created_at": now,
            "updated_at": now,
        }

    def get(self, user_id: str, persona_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"user_id": user_id, "persona_id": persona_id})

    def get_or_create(
        self,
        user_id: str,
        persona_id: str,
        *,
        timezone: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        existing = self.get(user_id, persona_id)
        if existing:
            if enabled is not None and bool(existing.get("enabled")) != enabled:
                return self.update_public(user_id, persona_id, {"enabled": enabled})
            return existing
        doc = self._defaults(user_id, persona_id, timezone)
        if enabled:
            doc["enabled"] = True
            doc["opted_in_at"] = utcnow()
        try:
            self.col.insert_one(doc)
        except Exception:  # noqa: BLE001 — concurrent create; read the winner
            found = self.get(user_id, persona_id)
            if found:
                return found
            raise
        return doc

    def _set(self, user_id: str, persona_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        updates = {**updates, "updated_at": utcnow()}
        self.col.update_one({"user_id": user_id, "persona_id": persona_id}, {"$set": updates})
        doc = self.get(user_id, persona_id)
        if not doc:
            raise KeyError(f"ProactiveSettings missing for {user_id}")
        return doc

    def update_public(self, user_id: str, persona_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Apply user-controllable fields only."""
        current = self.get_or_create(user_id, persona_id)
        updates: dict[str, Any] = {}
        if "enabled" in data:
            enabled = bool(data["enabled"])
            updates["enabled"] = enabled
            if enabled and not current.get("enabled"):
                updates["opted_in_at"] = utcnow()
                updates["backoff_level"] = 0
                updates["consecutive_unanswered"] = 0
        if data.get("quiet_start") is not None:
            updates["quiet_start"] = _validate_hhmm(data["quiet_start"])
        if data.get("quiet_end") is not None:
            updates["quiet_end"] = _validate_hhmm(data["quiet_end"])
        if data.get("timezone"):
            updates["timezone"] = clean_timezone(data["timezone"], current.get("timezone") or self.settings.timezone)
        if "pause_hours" in data and data["pause_hours"] is not None:
            hours = float(data["pause_hours"])
            updates["paused_until"] = utcnow() + timedelta(hours=hours) if hours > 0 else None
        if data.get("muted_types") is not None:
            updates["muted_types"] = [t for t in data["muted_types"] if t in PROACTIVE_TYPES]
        if not updates:
            return current
        return self._set(user_id, persona_id, updates)

    def opt_out(self, user_id: str, persona_id: str, *, reason: str = "user_request") -> dict[str, Any]:
        self.get_or_create(user_id, persona_id)
        return self._set(user_id, persona_id, {"enabled": False, "opt_out_reason": reason})

    def mute_type(self, user_id: str, persona_id: str, proactive_type: str) -> dict[str, Any]:
        doc = self.get_or_create(user_id, persona_id)
        muted = list(doc.get("muted_types") or [])
        if proactive_type in PROACTIVE_TYPES and proactive_type not in muted:
            muted.append(proactive_type)
        return self._set(user_id, persona_id, {"muted_types": muted})

    def record_outbound(
        self,
        user_id: str,
        persona_id: str,
        *,
        outbound_id: str,
        proactive_type: str,
        topic: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = ensure_utc(now or utcnow())
        doc = self.get_or_create(user_id, persona_id)
        history = [h for h in (doc.get("outbound_history") or []) if isinstance(h, dict)]
        history.append({"at": now, "outbound_id": outbound_id, "type": proactive_type, "topic": topic})
        topics = list(doc.get("topic_history") or [])
        if topic:
            topics.append({"topic": topic, "at": now})
        return self._set(
            user_id,
            persona_id,
            {
                "last_outbound_at": now,
                "unanswered_outbound_id": outbound_id,
                "unanswered_since": now,
                "outbound_history": history[-HISTORY_LIMIT:],
                "topic_history": topics[-HISTORY_LIMIT:],
            },
        )

    def record_user_reply(self, user_id: str, persona_id: str) -> dict[str, Any] | None:
        """Clear the unanswered marker; returns the outbound id that was answered (if any)."""
        doc = self.get(user_id, persona_id)
        if not doc:
            return None
        answered = doc.get("unanswered_outbound_id")
        updates: dict[str, Any] = {"consecutive_unanswered": 0, "backoff_level": 0}
        if answered:
            updates.update({"unanswered_outbound_id": None, "unanswered_since": None})
        self._set(user_id, persona_id, updates)
        return {"answered_outbound_id": answered} if answered else None

    def record_ignored(self, user_id: str, persona_id: str) -> dict[str, Any]:
        """An outbound expired unanswered — increase backoff, auto-pause after repeated silence."""
        doc = self.get_or_create(user_id, persona_id)
        count = int(doc.get("consecutive_unanswered") or 0) + 1
        updates: dict[str, Any] = {
            "consecutive_unanswered": count,
            "backoff_level": min(count, 4),
            "unanswered_outbound_id": None,
            "unanswered_since": None,
        }
        if count >= 4:
            updates["enabled"] = False
            updates["opt_out_reason"] = "auto_paused_no_engagement"
        return self._set(user_id, persona_id, updates)

    def list_enabled(self, persona_id: str, limit: int = 500) -> list[dict[str, Any]]:
        return list(self.col.find({"persona_id": persona_id, "enabled": True}).limit(limit))
