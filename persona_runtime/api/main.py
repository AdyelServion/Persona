"""FastAPI application for the persona runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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
            settings=settings,
            life_simulator=LifeSimulator(runtime.state_repo, tz_name=settings.timezone),
        )
    return _scheduler


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


app = FastAPI(title="Sarah Persona Runtime API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ConversationCreate(BaseModel):
    persona_id: str | None = None
    user_id: str | None = None


class MessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    user_id: str | None = None


class SeenEvent(BaseModel):
    conversation_id: str
    message_id: str | None = None
    persona_id: str | None = None
    user_id: str | None = None


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
        "timestamp": to_iso(ts) if hasattr(ts, "isoformat") else ts,
        "metadata": _public_metadata(m.get("metadata") if isinstance(m.get("metadata"), dict) else {}),
    }


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        db = get_db(settings)
        db.command("ping")
        mongo_ok = True
    except Exception as exc:  # noqa: BLE001
        mongo_ok = False
        return {"status": "degraded", "mongodb": False, "error": str(exc)}
    return {
        "status": "ok",
        "mongodb": mongo_ok,
        "db_name": settings.db_name,
        "model": settings.openai_model_name,
        "worker_enabled": settings.response_worker_enabled,
    }


@app.post("/api/conversations")
def create_conversation(body: ConversationCreate) -> dict[str, Any]:
    runtime = get_runtime()
    persona_id = body.persona_id or settings.default_persona_id
    user_id = body.user_id or settings.default_user_id
    # Ensure life state exists
    LifeSimulator(runtime.state_repo, tz_name=settings.timezone).ensure_life_state(persona_id)
    conv = runtime.conversation_repo.get_or_create(persona_id, user_id)
    return {
        "conversation_id": conv["conversation_id"],
        "persona_id": conv["persona_id"],
        "user_id": conv["user_id"],
        "status": conv.get("status"),
    }


@app.get("/api/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    after_sequence: int | None = Query(default=None),
) -> dict[str, Any]:
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = runtime.conversation_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msgs = runtime.conversation_repo.list_messages(
        conversation_id, limit=200, after_sequence=after_sequence
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "messages": [_serialize_msg(m) for m in msgs],
        "presence": snap["presence"],
        "scheduled_for": snap.get("scheduled_for"),
        "spare_time": snap.get("spare_time"),
        "activity": snap.get("activity"),
        "activity_label": snap.get("activity_label"),
        "reason": snap.get("reason"),
        "inbox": runtime.conversation_repo.inbox_projection(conversation_id),
    }


@app.post("/api/conversations/{conversation_id}/messages")
def post_message(conversation_id: str, body: MessageCreate) -> dict[str, Any]:
    """Accept a user message immediately. Does NOT wait for Sarah's reply."""
    content = body.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Empty message")
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = runtime.conversation_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_id = body.user_id or conv["user_id"]
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
        "presence": snap["presence"],
        "scheduled_for": snap.get("scheduled_for"),
        "spare_time": snap.get("spare_time"),
        "activity": snap.get("activity"),
        "activity_label": snap.get("activity_label"),
        "reason": snap.get("reason"),
    }


@app.post("/api/conversations/{conversation_id}/resume")
def resume_conversation(conversation_id: str) -> dict[str, Any]:
    """User returned to the chat — optionally schedule one proactive message.

    With PROACTIVE_OUTBOUND_ENABLED=false (default), no outbound job is created;
    engagement still applies on the next user message / explicit content path.
    """
    from persona_runtime.conversation.proactive import evaluate_proactive_policy
    from persona_runtime.db.time_utils import utcnow

    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = runtime.conversation_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    ctx = runtime.conversation_context_repo.get_or_create(
        conversation_id=conversation_id,
        persona_id=conv["persona_id"],
        user_id=conv["user_id"],
    )
    state_doc = runtime.state_repo.get_state(conv["persona_id"])
    open_job = runtime.job_repo.get_open_for_conversation(conversation_id)
    policy = evaluate_proactive_policy(
        situation="user_resumed",
        settings=settings,
        conversation_context=ctx,
        open_job=open_job,
        persona_state=state_doc,
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    if not policy.get("allow_outbound"):
        return {
            "conversation_id": conversation_id,
            "scheduled": False,
            "reason": policy.get("reason"),
            "situation": policy.get("situation"),
            "use_engagement_in_reply": policy.get("use_engagement_in_reply"),
            "presence": snap["presence"],
            "scheduled_for": snap.get("scheduled_for"),
        }

    job = scheduler.schedule_resume(
        conversation_id=conversation_id,
        persona_id=conv["persona_id"],
        user_id=conv["user_id"],
    )
    now = utcnow()
    day_key = now.date().isoformat()
    day_count = int(ctx.get("proactive_count_today") or 0)
    if (ctx.get("proactive_day_key") or "") != day_key:
        day_count = 0
    runtime.conversation_context_repo.update(
        conversation_id,
        {
            "last_proactive_at": now,
            "proactive_count_today": day_count + 1,
            "proactive_day_key": day_key,
        },
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "scheduled": bool(job),
        "job_id": (job or {}).get("job_id"),
        "reason": policy.get("reason"),
        "situation": policy.get("situation"),
        "presence": snap["presence"],
        "scheduled_for": snap.get("scheduled_for") or (
            to_iso(job["scheduled_for"]) if job and job.get("scheduled_for") else None
        ),
    }


@app.post("/api/conversations/{conversation_id}/opening")
def opening(conversation_id: str) -> dict[str, Any]:
    runtime = get_runtime()
    scheduler = get_scheduler()
    conv = runtime.conversation_repo.get(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if runtime.conversation_repo.count_messages(conversation_id) > 0:
        msgs = runtime.conversation_repo.list_messages(conversation_id, limit=200)
        snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
        return {
            "conversation_id": conversation_id,
            "skipped": True,
            "messages": [_serialize_msg(m) for m in msgs],
            "presence": snap["presence"],
            "scheduled_for": snap.get("scheduled_for"),
            "spare_time": snap.get("spare_time"),
            "activity": snap.get("activity"),
            "activity_label": snap.get("activity_label"),
            "reason": snap.get("reason"),
        }
    job = scheduler.schedule_opening(
        conversation_id=conversation_id,
        persona_id=conv["persona_id"],
        user_id=conv["user_id"],
    )
    snap = scheduler.presence_snapshot(conversation_id, conv["persona_id"])
    return {
        "conversation_id": conversation_id,
        "skipped": False,
        "status": "scheduled",
        "job_id": (job or {}).get("job_id"),
        "presence": snap["presence"],
        "scheduled_for": snap.get("scheduled_for"),
        "spare_time": snap.get("spare_time"),
        "activity": snap.get("activity"),
        "activity_label": snap.get("activity_label"),
        "reason": snap.get("reason"),
    }


@app.post("/api/events/message_seen")
def message_seen(body: SeenEvent) -> dict[str, Any]:
    """User saw Sarah's message — record only; do not run LangGraph."""
    runtime = get_runtime()
    conv = runtime.conversation_repo.get(body.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    runtime.conversation_repo.record_event(
        "message_seen",
        {
            "conversation_id": body.conversation_id,
            "persona_id": body.persona_id or conv["persona_id"],
            "user_id": body.user_id or conv["user_id"],
            "message_id": body.message_id,
            "action": "none",
            "reason": "user_seen_assistant_message",
        },
    )
    return {
        "ok": True,
        "follow_up": False,
        "action": "none",
        "event_type": "message_seen",
    }
