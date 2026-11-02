"""AppUsers persistence. user_id is always generated server-side."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow

MAX_DISPLAY_NAME = 40
MAX_INTERESTS = 8


def clean_display_name(raw: str | None) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    name = re.sub(r"[<>\"'`]", "", name)
    return name[:MAX_DISPLAY_NAME] or "Guest"


def clean_timezone(raw: str | None, default: str = "Europe/London") -> str:
    tz = (raw or "").strip()
    if not tz:
        return default
    try:
        ZoneInfo(tz)
    except Exception:  # noqa: BLE001
        return default
    return tz


def clean_interests(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        val = re.sub(r"\s+", " ", str(item or "").strip().lower())[:40]
        if val and val not in out:
            out.append(val)
    return out[:MAX_INTERESTS]


class AppUserRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["app_users"]]

    def create(
        self,
        *,
        display_name: str | None,
        timezone: str | None = None,
        interests: list[str] | None = None,
        source: str = "web_lightweight",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = utcnow()
        doc = {
            "user_id": user_id or str(uuid4()),
            "display_name": clean_display_name(display_name),
            "timezone": clean_timezone(timezone),
            "interests": clean_interests(interests),
            "source": source,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self.col.insert_one(doc)
        return doc

    def get(self, user_id: str) -> dict[str, Any] | None:
        return self.col.find_one({"user_id": user_id, "status": {"$ne": "deleted"}})

    def get_many(self, user_ids: list[str]) -> list[dict[str, Any]]:
        if not user_ids:
            return []
        return list(self.col.find({"user_id": {"$in": list(user_ids)}, "status": {"$ne": "deleted"}}))

    def update(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        clean: dict[str, Any] = {}
        if "display_name" in updates:
            clean["display_name"] = clean_display_name(updates["display_name"])
        if "timezone" in updates:
            clean["timezone"] = clean_timezone(updates["timezone"])
        if "interests" in updates:
            clean["interests"] = clean_interests(updates["interests"])
        if not clean:
            return self.get(user_id)
        clean["updated_at"] = utcnow()
        self.col.update_one({"user_id": user_id}, {"$set": clean})
        return self.get(user_id)

    def ensure(self, user_id: str, *, display_name: str = "Guest", source: str = "legacy") -> dict[str, Any]:
        existing = self.col.find_one({"user_id": user_id})
        if existing:
            return existing
        return self.create(display_name=display_name, source=source, user_id=user_id)
