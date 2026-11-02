"""One-off, idempotent migration from the single-user MVP to multi-user data.

Dry-run by default. Never deletes anything:
- memories about a user stored with scope "persona" (or no scope) are re-scoped to "user";
- every user id seen in Conversations gets an AppUsers profile and disabled ProactiveSettings;
- messages without an owner inherit their conversation's user_id.
"""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from persona_runtime.config import get_settings
from persona_runtime.db import COLLECTION_NAMES, MEMORY_COLLECTIONS
from persona_runtime.db.time_utils import utcnow


def migrate(db: Database, *, apply: bool = False) -> dict[str, Any]:
    settings = get_settings()
    report: dict[str, Any] = {"applied": apply, "memories_rescoped": 0, "app_users_created": 0,
                              "proactive_settings_created": 0, "messages_owned": 0, "users": []}

    for col_name in MEMORY_COLLECTIONS.values():
        col = db[col_name]
        q = {"user_id": {"$nin": [None, ""]}, "scope": {"$in": ["persona", None]}, "subject": {"$ne": "sarah"}}
        count = col.count_documents(q)
        report["memories_rescoped"] += count
        if apply and count:
            col.update_many(q, {"$set": {"scope": "user", "updated_at": utcnow(), "migrated": "multiuser_v1"}})

    convs = db[COLLECTION_NAMES["conversations"]]
    users_col = db[COLLECTION_NAMES["app_users"]]
    prefs_col = db[COLLECTION_NAMES["proactive_settings"]]
    user_ids = sorted({u for u in convs.distinct("user_id") if u})
    report["users"] = user_ids
    for uid in user_ids:
        if not users_col.find_one({"user_id": uid}):
            report["app_users_created"] += 1
            if apply:
                from persona_runtime.users.repositories import AppUserRepository

                AppUserRepository(db).create(
                    display_name="You" if uid == settings.default_user_id else "Legacy user",
                    timezone=settings.timezone,
                    source="migration",
                    user_id=uid,
                )
        if not prefs_col.find_one({"user_id": uid, "persona_id": settings.default_persona_id}):
            report["proactive_settings_created"] += 1
            if apply:
                from persona_runtime.outbound.settings_repo import ProactiveSettingsRepository

                ProactiveSettingsRepository(db, settings).get_or_create(uid, settings.default_persona_id)

    msgs = db[COLLECTION_NAMES["messages"]]
    for conv in convs.find({}, {"conversation_id": 1, "user_id": 1}):
        if not conv.get("user_id"):
            continue
        q = {"conversation_id": conv["conversation_id"], "user_id": {"$in": [None, ""]}}
        n = msgs.count_documents(q)
        report["messages_owned"] += n
        if apply and n:
            msgs.update_many(q, {"$set": {"user_id": conv["user_id"]}})
    return report
