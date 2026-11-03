"""FastAPI application for the persona runtime.

Every user-facing route resolves the caller from server-side headers set by the Django
proxy (see persona_runtime/api/auth.py) and verifies conversation ownership.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from persona_runtime.api.auth import owned_conversation_or_404, require_internal, require_user
from persona_runtime.config import get_settings
from persona_runtime.db import ensure_indexes, get_db
from persona_runtime.db.time_utils import to_iso
from persona_runtime.exceptions import DatabaseError, PersonaRuntimeError
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.logging_utils import setup_logging
from persona_runtime.scheduling.scheduler import ResponseScheduler
from persona_runtime.scheduling.worker import ResponseWorker

setup_logging()
settings = get_settings()

_runtime: PersonaRuntime | None = None
_worker: ResponseWorker | None = None
_scheduler: ResponseScheduler | None = None


def get_runtime() -> PersonaRuntime:
    global _runtime
    if _runtime is None:
        ensure_indexes(get_db(settings))
        _runtime = PersonaRuntime(settings)
    return _runtime


def get_scheduler() -> ResponseScheduler:
    global _scheduler
    if _scheduler is None:
        runtime = get_runtime()
        _scheduler = ResponseScheduler(
            conversation_repo=runtime.conversation_repo,
            job_repo=runtime.job_repo,
            state_repo=runtime.state_repo,
            relationship_repo=runtime.relationship_repo,
            settings=runtime.settings,
            life_simulator=LifeSimulator(runtime.state_repo, tz_name=runtime.settings.timezone),
            proactive_settings_repo=runtime.proactive_settings_repo,
            conversation_context_repo=runtime.conversation_context_repo,
        )
    return _scheduler


def set_runtime_for_tests(runtime: PersonaRuntime | None) -> None:
    """Inject a mongomock-backed runtime (tests only)."""
    global _runtime, _scheduler
    _runtime = runtime
    _scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker
    runtime = get_runtime()
    get_scheduler()
    if settings.response_worker_enabled:
        _worker = ResponseWorker(runtime=runtime, settings=settings)
        _worker.start()
    yield
    if _worker is not None:
        _worker.stop()
        _worker = None


# No CORS middleware: FastAPI binds to 127.0.0.1 and is only called by the Django proxy.
app = FastAPI(title="Sarah Persona Runtime API", version="0.3.0", lifespan=lifespan)


class UserCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=60)
    timezone: str | None = None
    interests: list[str] = Field(default_factory=list)
    proactive_opt_in: bool = False


class UserSummaries(BaseModel):
    user_ids: list[str] = Field(default_factory=list, max_length=50)


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    new_thread: bool = False


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)


class ReadEvent(BaseModel):
    sequence: int | None = None


class SeenEvent(BaseModel):
    conversation_id: str
    message_id: str | None = None


class ProactiveSettingsUpdate(BaseModel):
    enabled: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    timezone: str | None = None
    pause_hours: float | None = Field(default=None, ge=0, le=24 * 90)
    muted_types: list[str] | None = None


_ORCHESTRATION_META_KEYS = frozenset(
    {
        "behaviour_plan",
        "response_plan",
        "understanding",
        "validation",
        "allowed_evidence_ids",
        "engagement",
        "engagement_brief",
        "voice_tone",
        "internal_metadata",
        "memory_candidates",
        "topic_updates",
        "proactive_brief",
    }
)


def _public_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Strip orchestration internals from client-facing message metadata."""
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if key in _ORCHESTRATION_META_KEYS:
            continue
        out[key] = value
    return out


def _serialize_msg(m: dict[str, Any]) -> dict[str, Any]:
    ts = m.get("timestamp") or m.get("created_at")
    return {
        "message_id": m.get("message_id"),
        "conversation_id": m.get("conversation_id"),
        "sender": m.get("sender"),
        "content": m.get("content"),
        "sequence": m.get("sequence"),
        "status": m.get("status"),
        "priority": m.get("priority"),
        "message_type": m.get("message_type"),
        "proactive_type": m.get("proactive_type"),
        "outbound_id": m.get("outbound_id"),
        "timestamp": to_iso(ts) if hasattr(ts, "isoformat") else ts,
        "read_at": to_iso(m["read_at"]) if hasattr(m.get("read_at"), "isoformat") else None,
        "metadata": _public_metadata(m.get("metadata") if isinstance(m.get("metadata"), dict) else {}),
    }


def _iso(value: Any) -> Any:
    return to_iso(value) if hasattr(value, "isoformat") else value


def _conversation_summary(runtime: PersonaRuntime, conv: dict[str, Any]) -> dict[str, Any]:
    last = runtime.conversation_repo.last_message(conv["conversation_id"])
    return {
        "conversation_id": conv["conversation_id"],
        "persona_id": conv.get("persona_id"),
        "title": conv.get("title") or "Chat with Sarah",
        "conversation_type": conv.get("conversation_type") or "primary",
        "status": conv.get("status"),
        "created_at": _iso(conv.get("created_at")),
        "last_message_at": _iso(conv.get("last_message_at")),
        "unread_count": runtime.conversation_repo.unread_count(conv),
        "last_message": (
            {
                "sender": last.get("sender"),
                "content": (last.get("content") or "")[:120],
                "message_type": last.get("message_type"),
                "timestamp": _iso(last.get("timestamp")),
            }
            if last
            else None
        ),
    }


def _presence_payload(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "presence": snap["presence"],
        "scheduled_for": snap.get("scheduled_for"),
        "spare_time": snap.get("spare_time"),
        "activity": snap.get("activity"),
        "activity_label": snap.get("activity_label"),
        "reason": snap.get("reason"),
    }


def _public_settings(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(doc.get("enabled")),
        "opted_in_at": _iso(doc.get("opted_in_at")),
        "timezone": doc.get("timezone"),
        "quiet_start": doc.get("quiet_start"),
        "quiet_end": doc.get("quiet_end"),
        "quiet_hours_enabled": bool(doc.get("quiet_hours_enabled", True)),
        "daily_limit": doc.get("daily_limit"),
        "weekly_limit": doc.get("weekly_limit"),
        "hourly_limit": doc.get("hourly_limit"),
        "interval_options_minutes": list(doc.get("interval_options_minutes") or []),
        "allow_contextual_followups": bool(doc.get("allow_contextual_followups", True)),
        "allow_new_topic_introduction": bool(doc.get("allow_new_topic_introduction", True)),
        "paused_until": _iso(doc.get("paused_until")),
        "muted_types": list(doc.get("muted_types") or []),
        "last_outbound_at": _iso(doc.get("last_outbound_at")),
        "next_evaluation_at": _iso(doc.get("next_evaluation_at")),
        "awaiting_reply": bool(doc.get("unanswered_outbound_id")),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        db = get_db(settings)
        db.command("ping")
    except Exception as exc:  # noqa: BLE001
        return {"status": "degraded", "mongodb": False, "error": str(exc)}
    return {
        "status": "ok",
        "mongodb": True,
        "db_name": settings.db_name,
        "model": settings.openai_model_name,
        "worker_enabled": settings.response_worker_enabled,
    }


# ---------------------------------------------------------------- users (proxy-only)


@app.post("/api/users", dependencies=[Depends(require_internal)])
def create_user(body: UserCreate) -> dict[str, Any]:
    runtime = get_runtime()
    persona_id = runtime.settings.default_persona_id
    user = runtime.user_repo.create(
        display_name=body.display_name,
        timezone=body.timezone,
        interests=body.interests,
    )
    runtime.relationship_repo.get_or_create_user_relationship(persona_id, user["user_id"])
    runtime.relationship_repo.upsert_relationship(
        persona_id, user["user_id"], {"display_name": user["display_name"]}
    )
    runtime.proactive_settings_repo.get_or_create(
        user["user_id"],
        persona_id,
        timezone=user["timezone"],
        enabled=body.proactive_opt_in,
    )
    LifeSimulator(runtime.state_repo, tz_name=runtime.settings.timezone).ensure_life_state(persona_id)
    conv = runtime.conversation_repo.get_or_create(persona_id, user["user_id"])
    runtime.conversation_repo.record_event(
        "user_created",
        {"user_id": user["user_id"], "persona_id": persona_id, "proactive_opt_in": body.proactive_opt_in},
    )
    return {
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "timezone": user["timezone"],
        "conversation_id": conv["conversation_id"],
    }


@app.get("/api/users/{user_id}", dependencies=[Depends(require_internal)])
def lookup_user(user_id: str) -> dict[str, Any]:
    """Return an existing user so another browser can reopen their chat. Never creates one."""
    runtime = get_runtime()
    user = runtime.user_repo.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    persona_id = runtime.settings.default_persona_id
    convs = runtime.conversation_repo.list_for_user(user_id, persona_id)
    conv = convs[0] if convs else runtime.conversation_repo.get_or_create(persona_id, user_id)
    return {
        "user_id": user["user_id"],
        "display_name": user.get("display_name"),
        "timezone": user.get("timezone"),
        "conversation_id": conv["conversation_id"],
    }


@app.post("/api/users/summaries", dependencies=[Depends(require_internal)])
def user_summaries(body: UserSummaries) -> dict[str, Any]:
    """Sidebar data for the users a browser session owns (Django passes only owned ids)."""
    runtime = get_runtime()
    persona_id = runtime.settings.default_persona_id
    users = {u["user_id"]: u for u in runtime.user_repo.get_many(body.user_ids)}
    out: list[dict[str, Any]] = []
    for uid in body.user_ids:
        user = users.get(uid)
        if not user:
            continue
        convs = runtime.conversation_repo.list_for_user(uid, persona_id)
        summaries = [_conversation_summary(runtime, c) for c in convs]
        out.append(
            {
                "user_id": uid,
                "display_name": user.get("display_name"),
                "unread_count": sum(s["unread_count"] for s in summaries),
                "conversations": summaries,
                "last_message_at": summaries[0]["last_message_at"] if summaries else None,
            }
        )
    return {"users": out}


@app.get("/api/me")
def me(user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    user = runtime.user_repo.get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    persona_id = runtime.settings.default_persona_id
    prefs = runtime.proactive_settings_repo.get_or_create(user_id, persona_id, timezone=user.get("timezone"))
    return {
        "user_id": user_id,
        "display_name": user.get("display_name"),
        "timezone": user.get("timezone"),
        "proactive": _public_settings(prefs),
    }


# ---------------------------------------------------------------- conversations


@app.get("/api/conversations")
def list_conversations(user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    convs = runtime.conversation_repo.list_for_user(user_id, runtime.settings.default_persona_id)
    return {"conversations": [_conversation_summary(runtime, c) for c in convs]}


@app.post("/api/conversations")
def create_conversation(
    body: ConversationCreate | None = None, user_id: str = Depends(require_user)
) -> dict[str, Any]:
    runtime = get_runtime()
    body = body or ConversationCreate()
    persona_id = runtime.settings.default_persona_id
    if not runtime.user_repo.get(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    LifeSimulator(runtime.state_repo, tz_name=runtime.settings.timezone).ensure_life_state(persona_id)
    if body.new_thread:
        conv = runtime.conversation_repo.create(
            persona_id, user_id, title=body.title, conversation_type="thread"
        )
    else:
        conv = runtime.conversation_repo.get_or_create(persona_id, user_id)
    return {
        "conversation_id": conv["conversation_id"],
        "persona_id": conv["persona_id"],
        "status": conv.get("status"),
        "title": conv.get("title"),
    }


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    after_sequence: int | None = Query(default=None),
    user_id: str = Depends(require_user),
) -> dict[str, Any]:
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = owned_conversation_or_404(runtime.conversation_repo, conversation_id, user_id)
    msgs = runtime.conversation_repo.list_messages(
        conversation_id, limit=200, after_sequence=after_sequence
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "messages": [_serialize_msg(m) for m in msgs if m.get("user_id") in {None, user_id}],
        **_presence_payload(snap),
        "last_read_sequence": int(conv.get("last_read_sequence") or 0),
        "inbox": runtime.conversation_repo.inbox_projection(conversation_id),
    }


@app.post("/api/conversations/{conversation_id}/messages")
def post_message(
    conversation_id: str, body: MessageCreate, user_id: str = Depends(require_user)
) -> dict[str, Any]:
    """Accept a user message immediately. Does NOT wait for Sarah's reply."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = owned_conversation_or_404(runtime.conversation_repo, conversation_id, user_id)

    request_id = str(uuid4())
    try:
        result = scheduler.accept_user_message(
            conversation_id=conversation_id,
            persona_id=conv["persona_id"],
            user_id=user_id,
            content=content,
            metadata={"request_id": request_id},
        )
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    except PersonaRuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    msg = result["message"]
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "request_id": request_id,
        "message_id": msg["message_id"],
        "status": "received",
        "sequence": msg.get("sequence"),
        "user_message": _serialize_msg(msg),
        **_presence_payload(snap),
    }


@app.post("/api/conversations/{conversation_id}/resume")
def resume_conversation(conversation_id: str, user_id: str = Depends(require_user)) -> dict[str, Any]:
    """User returned to the chat — may schedule one returning-user greeting.

    All gates (opt-in, quiet hours, caps, unanswered outbound) live in the outbound policy.
    """
    from persona_runtime.outbound.planner import ProactivePlanner

    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = owned_conversation_or_404(runtime.conversation_repo, conversation_id, user_id)
    planner = ProactivePlanner(runtime=runtime, settings=runtime.settings)
    outcome = planner.on_user_resumed(conv)
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    job = outcome.get("job") or {}
    return {
        "conversation_id": conversation_id,
        "scheduled": bool(job),
        "job_id": job.get("job_id"),
        "reason": outcome.get("reason"),
        "situation": outcome.get("situation"),
        "use_engagement_in_reply": outcome.get("use_engagement_in_reply", False),
        **_presence_payload(snap),
    }


@app.post("/api/conversations/{conversation_id}/opening")
def opening(conversation_id: str, user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = owned_conversation_or_404(runtime.conversation_repo, conversation_id, user_id)
    if runtime.conversation_repo.count_messages(conversation_id) > 0:
        msgs = runtime.conversation_repo.list_messages(conversation_id, limit=200)
        snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
        return {
            "conversation_id": conversation_id,
            "skipped": True,
            "messages": [_serialize_msg(m) for m in msgs],
            **_presence_payload(snap),
        }
    job = scheduler.schedule_opening(
        conversation_id=conversation_id,
        persona_id=conv["persona_id"],
        user_id=user_id,
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "skipped": False,
        "status": "scheduled",
        "job_id": (job or {}).get("job_id"),
        **_presence_payload(snap),
    }


@app.post("/api/conversations/{conversation_id}/read")
def mark_read(
    conversation_id: str, body: ReadEvent | None = None, user_id: str = Depends(require_user)
) -> dict[str, Any]:
    runtime = get_runtime()
    owned_conversation_or_404(runtime.conversation_repo, conversation_id, user_id)
    seq = runtime.conversation_repo.mark_read(conversation_id, user_id, (body or ReadEvent()).sequence)
    return {"ok": True, "conversation_id": conversation_id, "last_read_sequence": seq}


@app.post("/api/events/message_seen")
def message_seen(body: SeenEvent, user_id: str = Depends(require_user)) -> dict[str, Any]:
    """User saw Sarah's message — record + mark read; never runs LangGraph."""
    runtime = get_runtime()
    conv = owned_conversation_or_404(runtime.conversation_repo, body.conversation_id, user_id)
    seq = None
    if body.message_id:
        msg = runtime.conversation_repo.get_message(body.message_id)
        if not msg or msg.get("conversation_id") != body.conversation_id:
            raise HTTPException(status_code=404, detail="Message not found")
        seq = msg.get("sequence")
    runtime.conversation_repo.mark_read(body.conversation_id, user_id, seq)
    runtime.conversation_repo.record_event(
        "message_seen",
        {
            "conversation_id": body.conversation_id,
            "persona_id": conv["persona_id"],
            "user_id": user_id,
            "message_id": body.message_id,
            "action": "none",
            "reason": "user_seen_assistant_message",
        },
    )
    return {"ok": True, "follow_up": False, "action": "none", "event_type": "message_seen"}


# ---------------------------------------------------------------- proactive settings


@app.get("/api/proactive-settings")
def get_proactive_settings(user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    user = runtime.user_repo.get(user_id) or {}
    doc = runtime.proactive_settings_repo.get_or_create(
        user_id, runtime.settings.default_persona_id, timezone=user.get("timezone")
    )
    return _public_settings(doc)


@app.put("/api/proactive-settings")
def update_proactive_settings(
    body: ProactiveSettingsUpdate, user_id: str = Depends(require_user)
) -> dict[str, Any]:
    from persona_runtime.outbound.planner import cancel_pending_proactive

    runtime = get_runtime()
    persona_id = runtime.settings.default_persona_id
    if not runtime.user_repo.get(user_id):
        raise HTTPException(status_code=404, detail="User not found")
    try:
        doc = runtime.proactive_settings_repo.update_public(
            user_id, persona_id, body.model_dump(exclude_none=True)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.timezone:
        runtime.user_repo.update(user_id, {"timezone": body.timezone})
    if not doc.get("enabled") or doc.get("paused_until") or body.muted_types is not None:
        cancel_pending_proactive(runtime, user_id, reason="settings_changed")
    runtime.conversation_repo.record_event(
        "proactive_settings_changed",
        {"user_id": user_id, "persona_id": persona_id, "enabled": bool(doc.get("enabled"))},
    )
    return _public_settings(doc)


# ---------------------------------------------------------------- memories (own only)


@app.get("/api/memories")
def list_memories(user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    items = runtime.user_memory.list_for_user(runtime.settings.default_persona_id, user_id)
    return {"memories": items}


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str, user_id: str = Depends(require_user)) -> dict[str, Any]:
    runtime = get_runtime()
    ok = runtime.user_memory.delete(runtime.settings.default_persona_id, user_id, memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    runtime.conversation_repo.record_event("memory_deleted", {"user_id": user_id, "memory_id": memory_id})
    return {"ok": True, "memory_id": memory_id}
