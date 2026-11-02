"""Browser session of chats this browser has opened.

The signed cookie remembers those user ids so the sidebar can switch without retyping.
Opening a chat on another browser requires the user id, which Django checks against
AppUsers before adding it here. The active id is forwarded to FastAPI by the proxy.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest

OWNED_KEY = "owned_user_ids"
ACTIVE_KEY = "active_user_id"


def owned_user_ids(request: HttpRequest) -> list[str]:
    raw = request.session.get(OWNED_KEY) or []
    return [str(u) for u in raw if isinstance(u, str)]


def active_user_id(request: HttpRequest) -> str | None:
    active = request.session.get(ACTIVE_KEY)
    if active and active in owned_user_ids(request):
        return active
    return None


def add_owned_user(request: HttpRequest, user_id: str) -> None:
    owned = [u for u in owned_user_ids(request) if u != user_id]
    owned.insert(0, user_id)
    request.session[OWNED_KEY] = owned[: settings.MAX_USERS_PER_BROWSER]
    request.session[ACTIVE_KEY] = user_id


def forget_user(request: HttpRequest, user_id: str) -> None:
    """Drop an id this browser remembered when that user no longer exists."""
    owned = [u for u in owned_user_ids(request) if u != user_id]
    request.session[OWNED_KEY] = owned
    if request.session.get(ACTIVE_KEY) == user_id:
        request.session[ACTIVE_KEY] = owned[0] if owned else None


def switch_active(request: HttpRequest, user_id: str) -> bool:
    if user_id not in owned_user_ids(request):
        return False
    request.session[ACTIVE_KEY] = user_id
    return True


def can_create_more(request: HttpRequest) -> bool:
    return len(owned_user_ids(request)) < settings.MAX_USERS_PER_BROWSER
