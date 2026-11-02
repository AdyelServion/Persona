"""Proactive outbound engine: permission gates, triggers, bursts, idempotency, isolation.

Uses TestDelivery only — no real notifications are ever sent from tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from persona_runtime.config import get_settings
from persona_runtime.db import MEMORY_COLLECTIONS
from persona_runtime.db.time_utils import utcnow
from persona_runtime.outbound.delivery import TestDelivery
from persona_runtime.outbound.planner import ProactivePlanner, cancel_pending_proactive
from persona_runtime.outbound.policy import evaluate_outbound, in_quiet_hours
from persona_runtime.outbound.triggers import select_trigger
from persona_runtime.scheduling.scheduler import ResponseScheduler
from persona_runtime.scheduling.worker import ResponseWorker


@pytest.fixture()
def app_settings():
    return get_settings().model_copy(update={"proactive_outbound_enabled": True, "proactive_delivery": "test"})


@pytest.fixture()
def planner(runtime, app_settings):
    delivery = TestDelivery(runtime.conversation_repo)
    return ProactivePlanner(runtime=runtime, settings=app_settings, delivery=delivery)


def _user(runtime, name: str, *, opt_in: bool = True, chatted: bool = True, hours_ago: float = 30):
    persona_id = runtime.settings.default_persona_id
    uid = runtime.user_repo.create(display_name=name)["user_id"]
    conv = runtime.conversation_repo.get_or_create(persona_id, uid)
    runtime.proactive_settings_repo.get_or_create(uid, persona_id, enabled=opt_in)
    # No quiet hours unless a test sets them
    runtime.proactive_settings_repo.update_public(uid, persona_id, {"quiet_start": "00:00", "quiet_end": "00:00"})
    if chatted:
        runtime.conversation_repo.add_message(conversation_id=conv["conversation_id"], sender="user", content="hey")
        runtime.conversation_repo.add_message(conversation_id=conv["conversation_id"], sender="assistant", content="hey!")
        runtime.db["Conversations"].update_one(
            {"conversation_id": conv["conversation_id"]},
            {"$set": {"last_message_at": utcnow() - timedelta(hours=hours_ago)}},
        )
        runtime.db["ConversationMessages"].update_many(
            {"conversation_id": conv["conversation_id"]}, {"$set": {"status": "answered"}}
        )
    return uid, runtime.conversation_repo.get(conv["conversation_id"])


def _fact(runtime, uid: str, key: str, obj: str, category: str = "hobby", **extra) -> str:
    mid = f"m-{uid[:6]}-{key}-{obj}".replace(" ", "_")
    runtime.db[MEMORY_COLLECTIONS["semantic"]].insert_one(
        {
            "memory_id": mid,
            "persona_id": runtime.settings.default_persona_id,
            "user_id": uid,
            "scope": "user",
            "status": "active",
            "subject": "user",
            "predicate": key,
            "memory_key": key,
            "category": category,
            "object": obj,
            "fact": f"User {key} {obj}",
            "importance": 0.8,
            "confidence": 0.9,
            "temporal": "stable",
            **extra,
        }
    )
    return mid


def _prefs(runtime, uid):
    return runtime.proactive_settings_repo.get(uid, runtime.settings.default_persona_id)


# ---------------------------------------------------------------- policy gates


def _doc(**over):
    now = utcnow()
    base = {
        "user_id": "u",
        "enabled": True,
        "opted_in_at": now - timedelta(days=3),
        "timezone": "Europe/London",
        "quiet_start": "00:00",
        "quiet_end": "00:00",
        "daily_limit": 1,
        "weekly_limit": 3,
        "min_gap_hours": 20,
        "backoff_level": 0,
        "outbound_history": [],
        "muted_types": [],
    }
    return {**base, **over}


def test_gates_block_in_order(app_settings):
    now = utcnow()
    disabled = get_settings().model_copy(update={"proactive_outbound_enabled": False})
    assert evaluate_outbound(settings_doc=_doc(), app_settings=disabled, now=now).reason == "globally_disabled"
    assert evaluate_outbound(settings_doc=_doc(enabled=False), app_settings=app_settings, now=now).reason == "not_opted_in"
    assert evaluate_outbound(settings_doc=None, app_settings=app_settings, now=now).reason == "not_opted_in"
    paused = _doc(paused_until=now + timedelta(hours=2))
    assert evaluate_outbound(settings_doc=paused, app_settings=app_settings, now=now).reason == "paused"
    muted = _doc(muted_types=["new_topic"])
    assert evaluate_outbound(settings_doc=muted, app_settings=app_settings, now=now, proactive_type="new_topic").reason == "type_muted"
    waiting = _doc(unanswered_outbound_id="ob-1")
    assert evaluate_outbound(settings_doc=waiting, app_settings=app_settings, now=now).reason == "awaiting_reply"
    assert evaluate_outbound(settings_doc=_doc(), app_settings=app_settings, now=now, open_proactive_jobs=1).reason == "already_scheduled"
    assert evaluate_outbound(settings_doc=_doc(), app_settings=app_settings, now=now).allow


def test_caps_gap_and_backoff(app_settings):
    now = utcnow()
    recent = _doc(last_outbound_at=now - timedelta(hours=5), outbound_history=[{"at": now - timedelta(hours=5)}])
    assert evaluate_outbound(settings_doc=recent, app_settings=app_settings, now=now).reason == "min_gap"
    backoff = _doc(last_outbound_at=now - timedelta(hours=30), backoff_level=1)
    assert evaluate_outbound(settings_doc=backoff, app_settings=app_settings, now=now).reason == "backoff"
    daily = _doc(min_gap_hours=1, outbound_history=[{"at": now - timedelta(hours=3)}])
    assert evaluate_outbound(settings_doc=daily, app_settings=app_settings, now=now).reason == "daily_cap"
    weekly = _doc(outbound_history=[{"at": now - timedelta(days=d)} for d in (2, 3, 4)])
    assert evaluate_outbound(settings_doc=weekly, app_settings=app_settings, now=now).reason == "weekly_cap"
    old = _doc(outbound_history=[{"at": now - timedelta(days=d)} for d in (8, 9, 10)])
    assert evaluate_outbound(settings_doc=old, app_settings=app_settings, now=now).allow


def test_quiet_hours_use_the_users_timezone(app_settings):
    assert in_quiet_hours(datetime(2026, 1, 1, 23, 0), "22:00", "08:00")
    assert in_quiet_hours(datetime(2026, 1, 1, 7, 59), "22:00", "08:00")
    assert not in_quiet_hours(datetime(2026, 1, 1, 12, 0), "22:00", "08:00")
    assert in_quiet_hours(datetime(2026, 1, 1, 14, 0), "13:00", "15:00")
    # 12:00 UTC is 17:00 in Karachi and 04:00 in Los Angeles
    noon_utc = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    quiet = {"quiet_start": "22:00", "quiet_end": "08:00"}
    karachi = _doc(timezone="Asia/Karachi", **quiet)
    la = _doc(timezone="America/Los_Angeles", **quiet)
    assert evaluate_outbound(settings_doc=karachi, app_settings=app_settings, now=noon_utc).allow
    assert evaluate_outbound(settings_doc=la, app_settings=app_settings, now=noon_utc).reason == "quiet_hours"


# ---------------------------------------------------------------- triggers


def _trigger(**kw):
    now = utcnow()
    base = dict(
        user_id="u1",
        persona_id="p",
        now=now,
        local_now=now,
        settings_doc={"muted_types": [], "topic_history": []},
        profile_card=[],
        due_followups=[],
        conversation_context={},
        user_topics=[],
        last_message_at=now - timedelta(hours=1),
    )
    base.update(kw)
    return select_trigger(**base)


def test_trigger_priority_and_grounding():
    due = [{"memory_id": "e1", "user_id": "u1", "event_description": "I have my driving test on Friday"}]
    card = [{"memory_id": "h1", "user_id": "u1", "memory_key": "hobby", "object": "photography", "fact": "User enjoys photography"}]
    t = _trigger(due_followups=due, profile_card=card)
    assert t["proactive_type"] == "event_followup" and t["subject"] == "your driving test"
    assert "do not assume" in t["hint"] and t["evidence_memory_ids"] == ["e1"]
    t = _trigger(profile_card=card)
    assert t["proactive_type"] == "hobby_followup" and t["evidence_memory_ids"] == ["h1"]
    t = _trigger()
    assert t["proactive_type"] == "new_topic"


def test_trigger_ignores_foreign_former_and_muted():
    foreign = [{"memory_id": "x", "user_id": "someone-else", "event_description": "my interview"}]
    assert _trigger(due_followups=foreign)["proactive_type"] == "new_topic"
    former = [{"memory_id": "f", "user_id": "u1", "memory_key": "hobby", "object": "guitar", "interest_status": "former"}]
    assert _trigger(profile_card=former)["proactive_type"] == "new_topic"
    all_muted = {"muted_types": ["new_topic", "hobby_followup", "interest_followup"], "topic_history": []}
    card = [{"memory_id": "h1", "user_id": "u1", "memory_key": "hobby", "object": "photography"}]
    assert _trigger(settings_doc=all_muted, profile_card=card) is None


def test_sports_followup_never_claims_a_result():
    card = [{"memory_id": "t1", "user_id": "u1", "memory_key": "supports_team", "object": "Arsenal"}]
    t = _trigger(profile_card=card)
    assert t["proactive_type"] == "interest_followup"
    assert "do NOT claim" in t["hint"]


def test_weekend_followup_only_when_weekend_habit_is_known():
    saturday = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
    card = [{"memory_id": "w1", "user_id": "u1", "memory_key": "weekend_preference", "object": "drives"}]
    t = _trigger(profile_card=card, now=saturday, local_now=saturday)
    assert t["proactive_type"] == "weekend_followup"
    assert _trigger(now=saturday, local_now=saturday)["proactive_type"] == "new_topic"


# ---------------------------------------------------------------- planner end to end


def test_scan_schedules_one_job_and_execute_sends_a_grounded_burst(runtime, planner):
    uid, conv = _user(runtime, "John")
    _fact(runtime, uid, "hobby", "photography")
    outcomes = planner.scan()
    mine = [o for o in outcomes if o["user_id"] == uid]
    assert mine and mine[0]["scheduled"], mine
    job = mine[0]["job"]
    assert job["user_id"] == uid and job["event_type"] == "proactive"
    assert job["proactive_type"] == "hobby_followup"

    # A second scan never stacks another job
    again = [o for o in planner.scan() if o["user_id"] == uid]
    assert not again[0]["scheduled"] and again[0]["reason"] == "already_scheduled"

    runtime.db["ResponseJobs"].update_one({"job_id": job["job_id"]}, {"$set": {"status": "running"}})
    out = planner.execute(runtime.job_repo.get(job["job_id"]))
    assert out["sent"], out
    msgs = [runtime.conversation_repo.get_message(m) for m in out["message_ids"]]
    assert 1 <= len(msgs) <= 3
    assert {m["message_type"] for m in msgs} == {"proactive"}
    assert len({m["outbound_id"] for m in msgs}) == 1
    assert sum((m["content"] or "").count("?") for m in msgs) <= 1
    assert planner.delivery.sent and planner.delivery.sent[0]["user_id"] == uid

    prefs = _prefs(runtime, uid)
    assert prefs["unanswered_outbound_id"] == msgs[0]["outbound_id"]
    blocked = [o for o in planner.scan() if o["user_id"] == uid][0]
    assert blocked["reason"] == "awaiting_reply"


def test_not_opted_in_users_are_never_contacted(runtime, planner):
    uid, _ = _user(runtime, "Quiet", opt_in=False)
    _fact(runtime, uid, "hobby", "chess")
    assert all(o["user_id"] != uid for o in planner.scan())
    assert planner.evaluate_user(uid)["reason"] == "not_opted_in"


def test_brand_new_user_without_history_is_not_messaged(runtime, planner):
    uid, _ = _user(runtime, "Fresh", chatted=False)
    assert planner.evaluate_user(uid)["reason"] == "no_conversation_yet"


def test_outbound_is_isolated_per_user(runtime, planner):
    alex, _ = _user(runtime, "Alex")
    john, _ = _user(runtime, "John")
    _fact(runtime, alex, "owns_car", "Honda CR-Z", category="lifestyle")
    _fact(runtime, alex, "hobby", "cars")
    _fact(runtime, john, "hobby", "photography")
    out = planner.evaluate_user(john)
    brief = out["job"]["proactive_brief"]
    assert brief["subject"] == "photography"
    assert "cr-z" not in str(brief).lower() and "cars" not in str(brief.get("subject")).lower()
    owned_ids = {m["memory_id"] for m in runtime.user_memory.list_for_user(runtime.settings.default_persona_id, john)}
    assert set(brief["evidence_memory_ids"]) <= owned_ids


def test_execute_rechecks_gates_ownership_and_expiry(runtime, planner):
    uid, conv = _user(runtime, "Ria")
    job = planner.evaluate_user(uid)["job"]
    persona_id = runtime.settings.default_persona_id
    runtime.proactive_settings_repo.update_public(uid, persona_id, {"enabled": False})
    assert planner.execute(job)["reason"] == "not_opted_in"
    runtime.proactive_settings_repo.update_public(uid, persona_id, {"enabled": True})

    forged = {**job, "user_id": "someone-else"}
    assert planner.execute(forged)["reason"] == "ownership_mismatch"
    expired = {**job, "expires_at": utcnow() - timedelta(minutes=1)}
    assert planner.execute(expired)["reason"] == "expired"
    assert runtime.conversation_repo.count_messages(conv["conversation_id"]) == 2


def test_idempotency_key_prevents_duplicates(runtime, planner):
    uid, conv = _user(runtime, "Ida")
    first = planner.evaluate_user(uid)["job"]
    dup = runtime.job_repo.create_idempotent({**first, "job_id": None, "_id": None, "idempotency_key": first["idempotency_key"]})
    assert dup is None


def test_user_reply_clears_suppression_and_user_spoke_first_cancels(runtime, planner, app_settings):
    uid, conv = _user(runtime, "Max")
    persona_id = runtime.settings.default_persona_id
    sched = ResponseScheduler(
        conversation_repo=runtime.conversation_repo,
        job_repo=runtime.job_repo,
        state_repo=runtime.state_repo,
        relationship_repo=runtime.relationship_repo,
        settings=runtime.settings,
        proactive_settings_repo=runtime.proactive_settings_repo,
        conversation_context_repo=runtime.conversation_context_repo,
    )
    job = planner.evaluate_user(uid)["job"]
    sched.accept_user_message(conversation_id=conv["conversation_id"], persona_id=persona_id, user_id=uid, content="hey there")
    assert runtime.job_repo.get(job["job_id"])["status"] == "cancelled"

    runtime.proactive_settings_repo.record_outbound(uid, persona_id, outbound_id="ob-9", proactive_type="new_topic")
    assert _prefs(runtime, uid)["unanswered_outbound_id"] == "ob-9"
    sched.accept_user_message(conversation_id=conv["conversation_id"], persona_id=persona_id, user_id=uid, content="haha yes")
    assert _prefs(runtime, uid)["unanswered_outbound_id"] is None


def test_opt_out_in_conversation_disables_and_cancels(runtime, planner):
    uid, conv = _user(runtime, "Opal")
    persona_id = runtime.settings.default_persona_id
    job = planner.evaluate_user(uid)["job"]
    sched = ResponseScheduler(
        conversation_repo=runtime.conversation_repo,
        job_repo=runtime.job_repo,
        state_repo=runtime.state_repo,
        relationship_repo=runtime.relationship_repo,
        settings=runtime.settings,
        proactive_settings_repo=runtime.proactive_settings_repo,
        conversation_context_repo=runtime.conversation_context_repo,
    )
    sched.accept_user_message(
        conversation_id=conv["conversation_id"], persona_id=persona_id, user_id=uid, content="please stop messaging me first"
    )
    assert _prefs(runtime, uid)["enabled"] is False
    assert runtime.job_repo.get(job["job_id"])["status"] == "cancelled"


def test_unanswered_expiry_backs_off_then_auto_pauses(runtime, planner):
    uid, _ = _user(runtime, "Gus")
    persona_id = runtime.settings.default_persona_id
    repo = runtime.proactive_settings_repo
    now = utcnow()
    for i in range(4):
        repo.record_outbound(uid, persona_id, outbound_id=f"ob-{i}", proactive_type="new_topic", now=now)
        planner.expire_unanswered(now + timedelta(hours=73))
        prefs = _prefs(runtime, uid)
        assert prefs["unanswered_outbound_id"] is None
        assert prefs["consecutive_unanswered"] == i + 1
    assert _prefs(runtime, uid)["enabled"] is False


def test_cancel_pending_on_settings_change(runtime, planner):
    uid, _ = _user(runtime, "Cy")
    job = planner.evaluate_user(uid)["job"]
    assert cancel_pending_proactive(runtime, uid, reason="settings_changed") == 1
    assert runtime.job_repo.get(job["job_id"])["status"] == "cancelled"


def test_resume_greeting_respects_opt_in_and_idle_gap(runtime, planner):
    quiet_uid, quiet_conv = _user(runtime, "NoOpt", opt_in=False, hours_ago=6)
    assert planner.on_user_resumed(quiet_conv)["reason"] == "not_opted_in"
    recent_uid, recent_conv = _user(runtime, "Recent", hours_ago=1)
    assert planner.on_user_resumed(recent_conv)["reason"] == "recent_activity"
    uid, conv = _user(runtime, "Back", hours_ago=6)
    out = planner.on_user_resumed(conv)
    assert out["job"] and out["job"]["proactive_type"] == "returning_user_greeting"
    assert planner.on_user_resumed(runtime.conversation_repo.get(conv["conversation_id"]))["reason"] in {
        "already_scheduled",
        "recent_activity",
    }


def test_event_followup_never_assumes_outcome(runtime, planner):
    uid, conv = _user(runtime, "Eve")
    runtime.db[MEMORY_COLLECTIONS["episodic"]].insert_one(
        {
            "memory_id": "ev-1",
            "persona_id": runtime.settings.default_persona_id,
            "user_id": uid,
            "scope": "user",
            "status": "active",
            "event_description": "I have a presentation tomorrow",
            "occurs_at": utcnow() - timedelta(hours=20),
            "horizon": "upcoming",
            "outcome_known": False,
            "importance": 0.9,
            "confidence": 0.9,
        }
    )
    job = planner.evaluate_user(uid)["job"]
    assert job["proactive_type"] == "event_followup"
    runtime.db["ResponseJobs"].update_one({"job_id": job["job_id"]}, {"$set": {"status": "running"}})
    out = planner.execute(runtime.job_repo.get(job["job_id"]))
    text = " ".join(runtime.conversation_repo.get_message(m)["content"] for m in out["message_ids"]).lower()
    for claim in ("went well", "congrat", "nailed it", "smashed it"):
        assert claim not in text


def test_worker_tick_scans_and_delivers_without_stacking(runtime, app_settings):
    uid, conv = _user(runtime, "Wes")
    _fact(runtime, uid, "hobby", "hiking")
    worker = ResponseWorker(runtime=runtime, settings=app_settings)
    worker._planner = ProactivePlanner(runtime=runtime, settings=app_settings, delivery=TestDelivery(runtime.conversation_repo))
    for _ in range(3):
        worker.process_due()
    proactive = [
        m for m in runtime.conversation_repo.list_messages(conv["conversation_id"], limit=50)
        if m.get("message_type") == "proactive"
    ]
    assert 1 <= len(proactive) <= 3
    assert len({m["outbound_id"] for m in proactive}) == 1
    assert "hiking" in " ".join(m["content"] for m in proactive).lower()
    worker._last_proactive_scan = None
    worker.process_due()
    again = [
        m for m in runtime.conversation_repo.list_messages(conv["conversation_id"], limit=50)
        if m.get("message_type") == "proactive"
    ]
    assert len(again) == len(proactive)


def test_engagement_report_counts_outbound_events(runtime, planner):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "engagement_report", Path(__file__).resolve().parent.parent / "scripts" / "engagement_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    uid, _ = _user(runtime, "Rae")
    _fact(runtime, uid, "hobby", "climbing")
    job = [o for o in planner.scan() if o["user_id"] == uid][0]["job"]
    assert planner.execute(runtime.job_repo.get(job["job_id"]))["sent"]

    report = module.build_report(runtime.db, days=1)
    assert report["counts"]["proactive_scheduled"] >= 1
    assert report["counts"]["proactive_sent"] >= 1
    assert report["by_proactive_type"]["hobby_followup"]["sent"] >= 1
    assert report["users"]["awaiting_reply"] >= 1
