"""Django views: render chat UI and proxy to FastAPI (secrets stay server-side).

The active user comes from the signed session (chat/identity.py) and is forwarded to
FastAPI as X-User-Id with the shared X-Internal-Token. FastAPI re-checks ownership.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from chat import identity

_USER_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _api() -> str:
    return settings.FASTAPI_BASE_URL.rstrip("/")


def _headers(user_id: str | None = None) -> dict[str, str]:
    headers = {"X-Internal-Token": settings.INTERNAL_API_TOKEN}
    if user_id:
        headers["X-User-Id"] = user_id
    return headers


def _call(
    method: str,
    path: str,
    *,
    user_id: str | None = None,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method,
            f"{_api()}{path}",
            headers=_headers(user_id),
            json=json_body,
            params=params,
        )
    try:
        payload = resp.json()
    except ValueError:
        payload = {"error": resp.text}
    return resp.status_code, payload


def _relay(status: int, payload: Any) -> JsonResponse:
    if status >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return JsonResponse({"error": detail or payload}, status=status)
    return JsonResponse(payload, safe=isinstance(payload, dict))


def _json_body(request: HttpRequest) -> dict[str, Any] | None:
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _no_user() -> JsonResponse:
    return JsonResponse({"error": "No active user", "needs_user": True}, status=409)


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    """Public health check used by Render. Proxies FastAPI so both processes are live."""
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{_api()}/health")
            payload = resp.json() if "application/json" in resp.headers.get("content-type", "") else {"body": resp.text}
        if resp.status_code >= 500:
            return JsonResponse({"status": "unhealthy", "api": payload}, status=503)
        return JsonResponse({"status": "ok", "api": payload})
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"status": "starting", "error": str(exc)}, status=503)


@require_GET
@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "chat/index.html",
        {
            "persona_name": "Sarah Taylor",
            "persona_id": settings.DEFAULT_PERSONA_ID,
        },
    )


# ---------------------------------------------------------------- users


@require_GET
def users_list(request: HttpRequest) -> JsonResponse:
    owned = identity.owned_user_ids(request)
    active = identity.active_user_id(request)
    if not owned:
        return JsonResponse({"users": [], "active_user_id": None, "can_create": True})
    try:
        status, payload = _call("POST", "/api/users/summaries", json_body={"user_ids": owned})
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    if status >= 400:
        return _relay(status, payload)
    users = payload.get("users") or []
    known = {u["user_id"] for u in users}
    if active not in known:
        active = users[0]["user_id"] if users else None
        if active:
            identity.switch_active(request, active)
    return JsonResponse(
        {
            "users": users,
            "active_user_id": active,
            "can_create": identity.can_create_more(request),
        }
    )


@require_POST
def users_new(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    name = (body.get("display_name") or "").strip()
    if not name:
        return JsonResponse({"error": "display_name required"}, status=400)
    if not identity.can_create_more(request):
        return JsonResponse({"error": "User limit reached for this browser"}, status=429)
    interests = body.get("interests") or []
    if isinstance(interests, str):
        interests = [i.strip() for i in interests.split(",") if i.strip()]
    try:
        status, payload = _call(
            "POST",
            "/api/users",
            json_body={
                "display_name": name[:60],
                "timezone": (body.get("timezone") or "")[:64] or None,
                "interests": interests[:8] if isinstance(interests, list) else [],
                "proactive_opt_in": bool(body.get("proactive_opt_in")),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    if status >= 400:
        return _relay(status, payload)
    identity.add_owned_user(request, payload["user_id"])
    return JsonResponse(payload)


@require_POST
def users_resume(request: HttpRequest) -> JsonResponse:
    """Open an existing chat by user id and remember it on this browser."""
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    user_id = str(body.get("user_id") or "").strip()
    if not _USER_ID.match(user_id):
        return JsonResponse({"error": "Enter a valid user id"}, status=400)
    if user_id not in identity.owned_user_ids(request) and not identity.can_create_more(request):
        return JsonResponse({"error": "User limit reached for this browser"}, status=429)
    try:
        status, payload = _call("GET", f"/api/users/{user_id}")
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    if status == 404:
        return JsonResponse({"error": "No chat found for that user id"}, status=404)
    if status >= 400:
        return _relay(status, payload)
    identity.add_owned_user(request, str(payload.get("user_id") or user_id))
    return JsonResponse(payload)


@require_POST
def users_switch(request: HttpRequest) -> JsonResponse:
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    if not identity.switch_active(request, str(body.get("user_id") or "")):
        return JsonResponse({"error": "Forbidden"}, status=403)
    return JsonResponse({"ok": True, "active_user_id": identity.active_user_id(request)})


# ---------------------------------------------------------------- chat


@require_GET
def bootstrap(request: HttpRequest) -> JsonResponse:
    user_id = identity.active_user_id(request)
    if not user_id:
        return JsonResponse({"needs_user": True})
    try:
        status, looked_up = _call("GET", f"/api/users/{user_id}")
        if status == 404:
            identity.forget_user(request, user_id)
            if not identity.active_user_id(request):
                return JsonResponse({"needs_user": True})
            return bootstrap(request)
        if status >= 400:
            return _relay(status, looked_up)
        status, conv = _call("POST", "/api/conversations", user_id=user_id, json_body={})
        if status >= 400:
            return _relay(status, conv)
        conversation_id = conv["conversation_id"]
        _, opening = _call("POST", f"/api/conversations/{conversation_id}/opening", user_id=user_id)
        resume: dict[str, Any] = {}
        if opening.get("skipped"):
            _, resume = _call("POST", f"/api/conversations/{conversation_id}/resume", user_id=user_id)
        status, messages = _call("GET", f"/api/conversations/{conversation_id}/messages", user_id=user_id)
        if status >= 400:
            return _relay(status, messages)
        _, me = _call("GET", "/api/me", user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    presence_src = resume if resume.get("scheduled") else opening
    return JsonResponse(
        {
            "user_id": user_id,
            "me": me,
            "conversation_id": conversation_id,
            "opening": presence_src,
            "messages": messages.get("messages", []),
            "last_read_sequence": messages.get("last_read_sequence", 0),
        }
    )


@require_GET
def proxy_messages(request: HttpRequest) -> JsonResponse:
    user_id = identity.active_user_id(request)
    if not user_id:
        return _no_user()
    conversation_id = request.GET.get("conversation_id")
    if not conversation_id:
        return JsonResponse({"error": "conversation_id required"}, status=400)
    params: dict[str, Any] = {}
    after_sequence = request.GET.get("after_sequence")
    if after_sequence not in (None, ""):
        params["after_sequence"] = after_sequence
    try:
        status, payload = _call(
            "GET", f"/api/conversations/{conversation_id}/messages", user_id=user_id, params=params
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    return _relay(status, payload)


@require_POST
def proxy_send(request: HttpRequest) -> JsonResponse:
    user_id = identity.active_user_id(request)
    if not user_id:
        return _no_user()
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    conversation_id = body.get("conversation_id")
    content = (body.get("content") or "").strip()
    if not conversation_id or not content:
        return JsonResponse({"error": "conversation_id and content required"}, status=400)
    try:
        status, payload = _call(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            user_id=user_id,
            json_body={"content": content[:4000]},
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    return _relay(status, payload)


@require_POST
def proxy_seen(request: HttpRequest) -> JsonResponse:
    user_id = identity.active_user_id(request)
    if not user_id:
        return _no_user()
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    conversation_id = body.get("conversation_id")
    if not conversation_id:
        return JsonResponse({"error": "conversation_id required"}, status=400)
    try:
        status, payload = _call(
            "POST",
            "/api/events/message_seen",
            user_id=user_id,
            json_body={"conversation_id": conversation_id, "message_id": body.get("message_id")},
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    return _relay(status, payload)


@require_http_methods(["GET", "POST"])
def proactive_settings(request: HttpRequest) -> JsonResponse:
    user_id = identity.active_user_id(request)
    if not user_id:
        return _no_user()
    try:
        if request.method == "GET":
            status, payload = _call("GET", "/api/proactive-settings", user_id=user_id)
        else:
            body = _json_body(request)
            if body is None:
                return JsonResponse({"error": "Invalid JSON"}, status=400)
            allowed = {"enabled", "quiet_start", "quiet_end", "timezone", "pause_hours", "muted_types"}
            status, payload = _call(
                "PUT",
                "/api/proactive-settings",
                user_id=user_id,
                json_body={k: v for k, v in body.items() if k in allowed},
            )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
    return _relay(status, payload)
