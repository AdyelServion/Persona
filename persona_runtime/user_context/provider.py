"""User context abstraction for future external user DB."""

from __future__ import annotations

from typing import Any, Protocol


class UserContextProvider(Protocol):
    def load_user_context(self, user_id: str) -> dict[str, Any]:
        ...


class MinimalUserContextProvider:
    def load_user_context(self, user_id: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "display_name": None,
            "profile": {},
        }
