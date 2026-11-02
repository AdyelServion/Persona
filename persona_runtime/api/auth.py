"""Server-side identity for FastAPI.

The browser never talks to FastAPI directly. The Django proxy resolves the user from its
signed session and forwards it as X-User-Id together with the shared X-Internal-Token.
A body-supplied user_id is never accepted as proof of ownership.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Header, HTTPException

from persona_runtime.config import get_settings


def require_internal(x_internal_token: str | None = Header(default=None)) -> None:
    expected = get_settings().effective_internal_token
    if not x_internal_token or not hmac.compare_digest(x_internal_token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def require_user(
    x_internal_token: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> str:
    require_internal(x_internal_token)
    user_id = (x_user_id or "").strip()
    if not user_id or len(user_id) > 64:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


def owned_conversation_or_404(conversation_repo: Any, conversation_id: str, user_id: str) -> dict[str, Any]:
    """404 (not 403) so conversation ids cannot be probed."""
    conv = conversation_repo.get_owned(conversation_id, user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv
