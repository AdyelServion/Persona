"""Django views: render chat UI and proxy to FastAPI (secrets stay server-side)."""

from __future__ import annotations

import json

import httpx
from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST


def _api() -> str:
    return settings.FASTAPI_BASE_URL.rstrip("/")


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
def index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "chat/index.html",
        {
            "persona_name": "Sarah Taylor",
            "persona_id": settings.DEFAULT_PERSONA_ID,
        },
    )


@require_GET
def bootstrap(request: HttpRequest) -> JsonResponse:
    try:
        with httpx.Client(timeout=30.0) as client:
            conv = client.post(
                f"{_api()}/api/conversations",
                json={
                    "persona_id": settings.DEFAULT_PERSONA_ID,
                    "user_id": settings.DEFAULT_USER_ID,
                },
            )
            conv.raise_for_status()
            data = conv.json()
            conversation_id = data["conversation_id"]
            opening = client.post(f"{_api()}/api/conversations/{conversation_id}/opening")
            opening.raise_for_status()
            messages = client.get(f"{_api()}/api/conversations/{conversation_id}/messages")
            messages.raise_for_status()
        return JsonResponse(
            {
                "conversation_id": conversation_id,
                "opening": opening.json(),
                "messages": messages.json().get("messages", []),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)


@require_GET
def proxy_messages(request: HttpRequest) -> JsonResponse:
    conversation_id = request.GET.get("conversation_id")
    if not conversation_id:
        return JsonResponse({"error": "conversation_id required"}, status=400)
    after_sequence = request.GET.get("after_sequence")
    qs = ""
    if after_sequence is not None and after_sequence != "":
        qs = f"?after_sequence={after_sequence}"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{_api()}/api/conversations/{conversation_id}/messages{qs}"
            )
            resp.raise_for_status()
        return JsonResponse(resp.json())
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)


@csrf_exempt
@require_POST
def proxy_send(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    conversation_id = body.get("conversation_id")
    content = (body.get("content") or "").strip()
    if not conversation_id or not content:
        return JsonResponse({"error": "conversation_id and content required"}, status=400)
    try:
        # Short timeout — API no longer waits for Sarah
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{_api()}/api/conversations/{conversation_id}/messages",
                json={"content": content, "user_id": settings.DEFAULT_USER_ID},
            )
            if resp.status_code >= 400:
                return JsonResponse({"error": resp.text}, status=resp.status_code)
            return JsonResponse(resp.json())
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)


@csrf_exempt
@require_POST
def proxy_seen(request: HttpRequest) -> JsonResponse:
    try:
        body = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(f"{_api()}/api/events/message_seen", json=body)
            resp.raise_for_status()
            return JsonResponse(resp.json())
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"error": str(exc)}, status=502)
