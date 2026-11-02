"""User / social context providers.

Only explicitly authorized sources are read. Today the single source is the AppUsers
profile (display name, timezone, interests the user typed at sign-up). Posts, bios or
shared content can be added later as further ContextSource implementations. Likes,
follows and views are never treated as preferences.
"""

from __future__ import annotations

from typing import Any, Protocol

from pymongo.database import Database


class UserContextProvider(Protocol):
    def load_user_context(self, user_id: str) -> dict[str, Any]:
        ...


class MinimalUserContextProvider:
    def load_user_context(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "display_name": None,
            "profile": {},
            "authorized_context": [],
        }


class ContextSource(Protocol):
    name: str

    def load(self, user_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return (profile fields, authorized context items) for this user only."""
        ...


class AppUserProfileSource:
    name = "app_user_profile"

    def __init__(self, db: Database):
        from persona_runtime.users.repositories import AppUserRepository

        self.repo = AppUserRepository(db)

    def load(self, user_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        user = self.repo.get(user_id)
        if not user:
            return {}, []
        profile = {
            "display_name": user.get("display_name"),
            "timezone": user.get("timezone"),
            "interests": list(user.get("interests") or []),
        }
        items = [
            {
                "source": self.name,
                "kind": "self_declared_interest",
                "text": f"Listed '{interest}' as an interest when joining",
                "value": interest,
            }
            for interest in profile["interests"]
        ]
        return profile, items


class SocialContextProvider:
    """Aggregates authorized context sources for one user."""

    def __init__(self, sources: list[ContextSource]):
        self.sources = list(sources)

    @classmethod
    def default(cls, db: Database) -> "SocialContextProvider":
        return cls([AppUserProfileSource(db)])

    def load_authorized_context(self, user_id: str) -> list[dict[str, Any]]:
        return self.load_user_context(user_id)["authorized_context"]

    def load_user_context(self, user_id: str) -> dict[str, Any]:
        profile: dict[str, Any] = {}
        items: list[dict[str, Any]] = []
        for source in self.sources:
            try:
                fields, found = source.load(user_id)
            except Exception:  # noqa: BLE001 — a broken source must not break the turn
                continue
            profile.update({k: v for k, v in fields.items() if v not in (None, "", [])})
            items.extend(found)
        return {
            "user_id": user_id,
            "display_name": profile.get("display_name"),
            "profile": profile,
            "authorized_context": items[:10],
        }
