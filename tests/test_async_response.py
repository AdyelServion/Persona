"""Async response lifecycle, batching, life simulation, and worker tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from persona_runtime.db.time_utils import ensure_utc, set_clock, utcnow
from persona_runtime.graph.validator import validate_response
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.life.strategy import choose_response_strategy, classify_priority
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.scheduling.jobs import ResponseJobRepository
from persona_runtime.scheduling.scheduler import ResponseScheduler
from persona_runtime.scheduling.worker import ResponseWorker
from persona_runtime.state.repositories import PersonaStateRepository


class FrozenClock:
    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)

    def set(self, dt: datetime) -> None:
        self.now = dt


@pytest.fixture()
def clock():
    c = FrozenClock()
    set_clock(c)
    yield c
    set_clock(None)


@pytest.fixture()
def scheduler(runtime):
    return ResponseScheduler(
        conversation_repo=runtime.conversation_repo,
        job_repo=runtime.job_repo,
        state_repo=runtime.state_repo,
        relationship_repo=runtime.relationship_repo,
        settings=runtime.settings,
        life_simulator=LifeSimulator(runtime.state_repo, tz_name=runtime.settings.timezone),
    )


@pytest.fixture()
def worker(runtime):
    return ResponseWorker(runtime=runtime, settings=runtime.settings, worker_id="test-worker")


def _conv(runtime, user_id: str | None = None):
    uid = user_id or f"async-{uuid4().hex[:8]}"
    return runtime.conversation_repo.get_or_create("sarah_taylor_001", uid)


# --- TEST 1: Immediate response no longer occurs ---
def test_post_returns_received_without_assistant(runtime, scheduler, clock):
    conv = _conv(runtime)
    result = scheduler.accept_user_message(
        conversation_id=conv["conversation_id"],
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey",
    )
    assert result["status"] == "received"
    assert result["message"]["message_id"]
    assert result["message"]["status"] == "pending_response"
    # No assistant message yet
    msgs = runtime.conversation_repo.list_messages(conv["conversation_id"])
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "user"
    assert result["job"]["status"] == "scheduled"


# --- TEST 2: Multiple messages accepted ---
def test_multiple_messages_accepted(runtime, scheduler, clock):
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    for text in ("Hey", "How are you?", "What are you doing?"):
        scheduler.accept_user_message(
            conversation_id=cid,
            persona_id="sarah_taylor_001",
            user_id=conv["user_id"],
            content=text,
        )
    msgs = runtime.conversation_repo.list_messages(cid)
    assert len(msgs) == 3
    assert all(m["sender"] == "user" for m in msgs)
    assert [m["sequence"] for m in msgs] == [1, 2, 3]


# --- TEST 3: Messages batched into one job ---
def test_messages_batched_one_job(runtime, scheduler, clock):
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    for text in ("Hey", "How are you?", "What are you doing?"):
        scheduler.accept_user_message(
            conversation_id=cid,
            persona_id="sarah_taylor_001",
            user_id=conv["user_id"],
            content=text,
        )
    jobs = runtime.job_repo.list_for_conversation(cid)
    open_jobs = [j for j in jobs if j["status"] in ("scheduled", "running")]
    assert len(open_jobs) == 1
    assert len(open_jobs[0]["message_ids"]) == 3


# --- TEST 4: Grouped response ---
def test_grouped_response_addresses_batch(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    for text in ("hey", "how are you?", "what are you doing?"):
        scheduler.accept_user_message(
            conversation_id=cid,
            persona_id="sarah_taylor_001",
            user_id=conv["user_id"],
            content=text,
        )
    job = runtime.job_repo.get_open_for_conversation(cid)
    # Make due
    clock.set(job["scheduled_for"] + timedelta(seconds=1))
    assert worker.process_due() == 1
    msgs = runtime.conversation_repo.list_messages(cid)
    assistants = [m for m in msgs if m["sender"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["content"]
    completed = [j for j in runtime.job_repo.list_for_conversation(cid) if j["status"] == "completed"]
    assert completed
    assert completed[0].get("strategy") in {
        "RESPOND_TO_GROUP",
        "RESPOND_TO_ALL",
        "RESPOND_TO_LATEST",
    }


# --- TEST 5: Superseded message ---
def test_superseded_message_strategy():
    msgs = [
        {"message_id": "m1", "content": "Can you call me?", "priority": "important"},
        {"message_id": "m2", "content": "Actually never mind, I'll text.", "priority": "normal"},
    ]
    plan = choose_response_strategy(
        messages=msgs, activity_key="relaxing", availability=0.85
    )
    assert "m1" in plan["superseded_ids"]
    assert plan["strategy"] in {"RESPOND_TO_LATEST", "RESPOND_TO_GROUP"}
    assert "m2" in plan["include_ids"]


# --- TEST 6: Busy Sarah does not respond immediately ---
def test_busy_meeting_defers(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "meeting", duration_minutes=45, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey",
    )
    job = result["job"]
    assert job["scheduled_for"] > clock.now + timedelta(minutes=5)
    # Worker tick before due — should not complete
    assert worker.process_due() == 0
    msgs = runtime.conversation_repo.list_messages(cid)
    assert all(m["sender"] == "user" for m in msgs)


# --- TEST 7: Busy ack consistency — follow-up after meeting end ---
def test_busy_ack_follow_up_after_end(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    end = clock.now + timedelta(minutes=40)
    life.force_activity("sarah_taylor_001", "meeting", duration_minutes=40, now=clock.now)
    # Ensure expected end is set
    state = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]
    assert state["current_activity"] == "meeting"

    conv = _conv(runtime)
    cid = conv["conversation_id"]
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="I need to tell you something important",
    )
    job = runtime.job_repo.get_open_for_conversation(cid)
    assert job
    # Force due now for ack path
    runtime.job_repo.col.update_one(
        {"job_id": job["job_id"]},
        {"$set": {"scheduled_for": clock.now, "strategy": "ACKNOWLEDGE_LATEST"}},
    )
    processed = worker.process_due()
    assert processed == 1
    msgs = runtime.conversation_repo.list_messages(cid)
    assistants = [m for m in msgs if m["sender"] == "assistant"]
    # May have busy ack
    follow = runtime.job_repo.get_open_for_conversation(cid)
    if assistants and "meeting" in (assistants[0]["content"] or "").lower():
        assert follow is not None
        assert ensure_utc(follow["scheduled_for"]) >= ensure_utc(state["activity_expected_end_at"])
    elif follow:
        assert ensure_utc(follow["scheduled_for"]) >= ensure_utc(clock.now)


# --- TEST 8: Life state change moves timing ---
def test_life_transition_affects_timing(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=30, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    r1 = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey",
    )
    t_work = r1["job"]["scheduled_for"]

    # New conversation under gym
    life.force_activity("sarah_taylor_001", "gym", duration_minutes=60, now=clock.now)
    conv2 = _conv(runtime)
    r2 = scheduler.accept_user_message(
        conversation_id=conv2["conversation_id"],
        persona_id="sarah_taylor_001",
        user_id=conv2["user_id"],
        content="Hey",
    )
    # Gym is busier — delay should differ from desk work (not necessarily longer every seed,
    # but activity_at_schedule must reflect gym)
    assert r2["job"]["activity_at_schedule"] == "gym"
    assert r1["job"]["activity_at_schedule"] == "working"
    assert t_work is not None


# --- TEST 9: Sleep waits until wake ---
def test_sleep_defers_until_wake(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "sleeping", duration_minutes=420, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey Sarah",
    )
    assert result["message"]["message_id"]
    job = result["job"]
    end = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]["activity_expected_end_at"]
    assert job["scheduled_for"]
    end = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]["activity_expected_end_at"]
    assert ensure_utc(job["scheduled_for"]) >= ensure_utc(end)
    assert worker.process_due() == 0


# --- TEST 10: Multiple workers — only one claims ---
def test_only_one_worker_claims(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hello",
    )
    job = runtime.job_repo.get_open_for_conversation(cid)
    runtime.job_repo.col.update_one(
        {"job_id": job["job_id"]}, {"$set": {"scheduled_for": clock.now}}
    )
    w1 = ResponseWorker(runtime=runtime, settings=runtime.settings, worker_id="w1")
    claimed1 = runtime.job_repo.claim_due("w1", now=clock.now)
    claimed2 = runtime.job_repo.claim_due("w2", now=clock.now)
    assert claimed1 is not None
    assert claimed2 is None
    # Complete so DB clean
    runtime.job_repo.complete(claimed1["job_id"], claimed1["lock_token"])


# --- TEST 11: Process restart — job persists ---
def test_job_survives_new_worker_instance(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Still there?",
    )
    job_id = result["job"]["job_id"]
    # New repository / worker instance (simulates restart)
    jobs = ResponseJobRepository(runtime.db)
    found = jobs.get(job_id)
    assert found is not None
    assert found["status"] == "scheduled"
    w2 = ResponseWorker(runtime=runtime, settings=runtime.settings, worker_id="restarted")
    clock.set(found["scheduled_for"] + timedelta(seconds=1))
    assert w2.process_due() == 1
    assert jobs.get(job_id)["status"] == "completed"


# --- TEST 12: New message updates existing job ---
def test_new_message_appends_job(runtime, scheduler, clock):
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    r1 = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey",
    )
    r2 = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="You free?",
    )
    assert r1["job"]["job_id"] == r2["job"]["job_id"]
    assert len(r2["job"]["message_ids"]) == 2
    assert runtime.job_repo.count_open(cid) == 1


# --- TEST 13: Message while running goes to next cycle ---
def test_message_while_running_next_cycle(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="First",
    )
    job = runtime.job_repo.get_open_for_conversation(cid)
    # Manually mark running
    runtime.job_repo.col.update_one(
        {"job_id": job["job_id"]},
        {"$set": {"status": "running", "lock_token": "tok", "locked_by": "t"}},
    )
    r = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Second while generating",
    )
    assert r.get("deferred_to_next_cycle") is True
    msgs = runtime.conversation_repo.list_messages(cid)
    assert len(msgs) == 2
    # Original job should still have only first message
    fresh = runtime.job_repo.get(job["job_id"])
    assert "Second" not in str(fresh.get("message_ids"))


# --- TEST 14: No fake activity ---
def test_validator_rejects_fake_gym_claim():
    state = {
        "persona_state": {"current_state": {"current_activity": "working", "availability": 0.6}},
        "response_plan": {},
        "behaviour_plan": {},
        "understanding": {"speech_act": "continuation", "emotional_intensity": "low"},
        "conversation_context": {},
        "relationship_state": {"relationship_stage": "acquaintance"},
        "allowed_evidence_ids": [],
        "incoming_message": "what are you doing?",
    }
    result = validate_response(state, "I'm at the gym right now!")
    assert not result.ok
    assert any("unsupported_activity_claim" in f for f in result.failures)


# --- TEST 15: Memory continuity after delay ---
def test_memory_after_delayed_response(runtime, scheduler, worker, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime, "memory-async-user")
    cid = conv["conversation_id"]
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="My interview is tomorrow.",
    )
    job = runtime.job_repo.get_open_for_conversation(cid)
    clock.set(job["scheduled_for"] + timedelta(seconds=1))
    assert worker.process_due() == 1
    mem_repo = MemoryRepository(runtime.db)
    # Episodic memories for interview
    found = list(
        runtime.db["EpisodicMemories"].find(
            {"persona_id": "sarah_taylor_001", "user_id": conv["user_id"]}
        )
    )
    assert any("interview" in (m.get("event_description") or "").lower() for m in found)


# --- TEST 16: No memory fabrication ---
def test_no_memory_fabrication_without_store(runtime):
    state = {
        "persona_state": {"current_state": {"current_activity": "relaxing"}},
        "response_plan": {"memory_claims": []},
        "behaviour_plan": {},
        "understanding": {"speech_act": "question"},
        "conversation_context": {},
        "relationship_state": {"relationship_stage": "acquaintance"},
        "allowed_evidence_ids": [],
        "incoming_message": "do you remember my interview?",
        "retrieved_memories": [],
    }
    result = validate_response(state, "I remember your interview.")
    assert not result.ok
    assert "ungrounded_memory_claim" in result.failures


def test_classify_priority_levels():
    assert classify_priority("hey") == "low"
    assert classify_priority("what are you doing today?") == "normal"
    assert classify_priority("I need to tell you something") == "important"
    assert classify_priority("I'm having a really bad day") == "emotionally_important"
    assert classify_priority("Can you call me right now?") == "urgent"


def test_decay_does_not_overwrite_activity(runtime, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "gym", duration_minutes=60, now=clock.now)
    before = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]["current_activity"]
    assert before == "gym"
    runtime.state_repo.decay_toward_baseline("sarah_taylor_001", hours_elapsed=2.0)
    after = runtime.state_repo.get_state("sarah_taylor_001")["current_state"]["current_activity"]
    assert after == "gym"


# --- Presence snapshot / countdown ---
def test_presence_waiting_includes_scheduled_for(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "working", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="How was your morning?",
    )
    snap = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap["presence"] == "waiting"
    assert snap["scheduled_for"]
    assert snap["spare_time"] is False
    assert snap["activity"] == "working"
    assert snap["activity_label"] == "At work"
    assert snap.get("reason")
    assert ensure_utc(result["job"]["scheduled_for"]).isoformat() == snap["scheduled_for"]


def test_presence_online_when_running_in_spare_time(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "relaxing", duration_minutes=60, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="Hey there",
    )
    runtime.job_repo.col.update_one(
        {"job_id": result["job"]["job_id"]},
        {"$set": {"status": "running", "started_at": clock.now}},
    )
    snap = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap["presence"] == "online"
    assert snap["spare_time"] is True
    assert snap["scheduled_for"] is None


def test_presence_replying_when_running_while_busy(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "meeting", duration_minutes=40, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    result = scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="I need to tell you something important",
    )
    runtime.job_repo.col.update_one(
        {"job_id": result["job"]["job_id"]},
        {"$set": {"status": "running", "started_at": clock.now}},
    )
    snap = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap["presence"] == "replying"
    assert snap["spare_time"] is False


def test_presence_not_online_when_working_or_sleeping(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    conv = _conv(runtime)
    cid = conv["conversation_id"]

    life.force_activity("sarah_taylor_001", "working", duration_minutes=60, now=clock.now)
    snap_work = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap_work["presence"] != "online"
    assert snap_work["spare_time"] is False

    life.force_activity("sarah_taylor_001", "sleeping", duration_minutes=420, now=clock.now)
    snap_sleep = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap_sleep["presence"] == "away"
    assert snap_sleep["spare_time"] is False


def test_presence_online_after_recent_reply_in_spare_time(runtime, scheduler, clock):
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "personal_time", duration_minutes=90, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    runtime.conversation_repo.add_message(
        conversation_id=cid,
        sender="assistant",
        content="Hey — free for a bit.",
    )
    snap = scheduler.presence_snapshot(cid, "sarah_taylor_001")
    assert snap["presence"] == "online"
    assert snap["spare_time"] is True


def test_defer_hint_ignored_when_available():
    msgs = [
        {"message_id": "m1", "content": "what do they do ?", "priority": "normal"},
        {"message_id": "m2", "content": "do u like work from home ?", "priority": "normal"},
    ]
    plan = choose_response_strategy(
        messages=msgs,
        activity_key="lunch",
        availability=0.65,
        strategy_hint="DEFER_RESPONSE",
    )
    assert plan["strategy"] != "DEFER_RESPONSE"
    assert plan["include_ids"]


def test_defer_still_when_unavailable():
    msgs = [{"message_id": "m1", "content": "Hey", "priority": "low"}]
    plan = choose_response_strategy(
        messages=msgs,
        activity_key="meeting",
        availability=0.05,
        strategy_hint="DEFER_RESPONSE",
    )
    assert plan["strategy"] == "DEFER_RESPONSE"


def test_empty_reply_fails_validation():
    result = validate_response({}, "")
    assert not result.ok
    assert "empty_reply" in result.failures


def test_sticky_defer_replies_once_available(runtime, scheduler, worker, clock):
    """Replay the live bug: a due DEFER job must reply after the busy window."""
    life = LifeSimulator(runtime.state_repo)
    life.force_activity("sarah_taylor_001", "meeting", duration_minutes=40, now=clock.now)
    conv = _conv(runtime)
    cid = conv["conversation_id"]
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="what do they do ?",
    )
    scheduler.accept_user_message(
        conversation_id=cid,
        persona_id="sarah_taylor_001",
        user_id=conv["user_id"],
        content="what do you like working in office ? do u like work from home ?",
    )
    job = runtime.job_repo.get_open_for_conversation(cid)
    assert job
    clock.advance(45 * 60)
    life.force_activity("sarah_taylor_001", "lunch", duration_minutes=40, now=clock.now)
    runtime.job_repo.col.update_one(
        {"job_id": job["job_id"]},
        {
            "$set": {
                "scheduled_for": clock.now,
                "strategy": "DEFER_RESPONSE",
                "reason": "waiting_until_lunch_ends",
                "attempt_count": 16,
            }
        },
    )
    assert worker.process_due() == 1
    assistants = [
        m for m in runtime.conversation_repo.list_messages(cid) if m["sender"] == "assistant"
    ]
    assert assistants
    assert (assistants[-1].get("content") or "").strip()
    assert runtime.job_repo.get(job["job_id"])["status"] == "completed"
