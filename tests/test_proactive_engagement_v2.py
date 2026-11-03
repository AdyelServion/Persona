"""Proactive engagement v2: scheduling, context, policy caps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from persona_runtime.config import get_settings
from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.outbound.context import analyze_recent_conversation
from persona_runtime.outbound.policy import evaluate_outbound
from persona_runtime.outbound.schedule import DEFAULT_INTERVAL_OPTIONS, pick_interval_minutes


def test_interval_picker_covers_options():
    seen = set()
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(200):
        base, _ = pick_interval_minutes(DEFAULT_INTERVAL_OPTIONS, user_id=f"user-{i}", now=now)
        seen.add(base)
    assert seen == set(DEFAULT_INTERVAL_OPTIONS)


def test_analyze_recent_photography():
    msgs = [
        {"sender": "user", "content": "I really enjoy photography"},
        {"sender": "assistant", "content": "oh nice, what do you usually like taking photos of?"},
        {"sender": "user", "content": "mostly cars and landscapes"},
    ]
    analysis = analyze_recent_conversation(msgs, limit=10)
    assert "photography" in analysis.mentioned_hobbies
    assert "cars" in analysis.last_user_text


def test_hourly_cap_v2_policy():
    app = get_settings().model_copy(update={"proactive_outbound_enabled": True})
    now = utcnow()
    doc = {
        "user_id": "u",
        "enabled": True,
        "opted_in_at": now - timedelta(days=1),
        "timezone": "Europe/London",
        "quiet_start": "00:00",
        "quiet_end": "00:00",
        "engagement_policy_version": 2,
        "hourly_limit": 2,
        "daily_limit": 8,
        "weekly_limit": 28,
        "min_gap_minutes": 5,
        "backoff_level": 0,
        "outbound_history": [{"at": now - timedelta(minutes=20)}, {"at": now - timedelta(minutes=10)}],
        "muted_types": [],
    }
    assert evaluate_outbound(settings_doc=doc, app_settings=app, now=now, check_quiet_hours=False).reason == "hourly_cap"


def test_next_evaluation_persisted_on_user_message(runtime):
    from persona_runtime.scheduling.scheduler import ResponseScheduler
    from persona_runtime.life.simulator import LifeSimulator

    persona_id = runtime.settings.default_persona_id
    uid = runtime.user_repo.create(display_name="Sched")["user_id"]
    conv = runtime.conversation_repo.get_or_create(persona_id, uid)
    runtime.proactive_settings_repo.get_or_create(uid, persona_id, enabled=True)
    runtime.proactive_settings_repo._set(uid, persona_id, {"next_evaluation_at": utcnow() - timedelta(minutes=1)})
    sched = ResponseScheduler(
        conversation_repo=runtime.conversation_repo,
        job_repo=runtime.job_repo,
        state_repo=runtime.state_repo,
        relationship_repo=runtime.relationship_repo,
        settings=runtime.settings,
        life_simulator=LifeSimulator(runtime.state_repo, tz_name=runtime.settings.timezone),
        proactive_settings_repo=runtime.proactive_settings_repo,
        conversation_context_repo=runtime.conversation_context_repo,
    )
    sched.accept_user_message(
        conversation_id=conv["conversation_id"],
        persona_id=persona_id,
        user_id=uid,
        content="hey again",
    )
    prefs = runtime.proactive_settings_repo.get(uid, persona_id)
    assert prefs.get("next_evaluation_at") is not None
    assert ensure_utc(prefs["next_evaluation_at"]) > utcnow()
