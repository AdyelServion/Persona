"""Life-sim reply timing: glance vs defer, sleep/meeting deferral."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from persona_runtime.life.timing import activity_label, compute_response_schedule


NOW = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


def _find_seed(*, activity: str, want_engaged: bool, priority: str = "normal") -> str:
    end = NOW + timedelta(minutes=60)
    for i in range(400):
        seed = f"probe-{activity}-{want_engaged}-{i}"
        sched = compute_response_schedule(
            activity_key=activity,
            availability=0.6 if activity == "working" else 0.05,
            priority=priority,
            now=NOW,
            activity_expected_end_at=end,
            batch_window_seconds=15.0,
            time_scale=1.0,
            seed=seed,
        )
        if bool(sched.get("engaged")) == want_engaged:
            return seed
    raise AssertionError(f"no seed for engaged={want_engaged} activity={activity}")


def test_working_glance_can_be_under_few_minutes():
    seed = _find_seed(activity="working", want_engaged=True)
    sched = compute_response_schedule(
        activity_key="working",
        availability=0.6,
        priority="normal",
        now=NOW,
        activity_expected_end_at=NOW + timedelta(minutes=90),
        batch_window_seconds=15.0,
        time_scale=1.0,
        seed=seed,
    )
    assert sched["engaged"] is True
    assert sched["reason"].startswith("glance_while_")
    assert sched["delay_seconds"] < 3 * 60
    assert sched["delay_seconds"] >= 15.0


def test_working_skip_is_later_in_band():
    seed = _find_seed(activity="working", want_engaged=False)
    sched = compute_response_schedule(
        activity_key="working",
        availability=0.6,
        priority="normal",
        now=NOW,
        activity_expected_end_at=NOW + timedelta(minutes=90),
        batch_window_seconds=15.0,
        time_scale=1.0,
        seed=seed,
    )
    assert sched["engaged"] is False
    assert sched["reason"].startswith("later_while_")
    assert sched["delay_seconds"] >= 3 * 60


def test_meeting_defers_past_end():
    end = NOW + timedelta(minutes=45)
    # Prefer skip path; meeting response_probability is 0.10
    seed = _find_seed(activity="meeting", want_engaged=False)
    sched = compute_response_schedule(
        activity_key="meeting",
        availability=0.05,
        priority="normal",
        now=NOW,
        activity_expected_end_at=end,
        batch_window_seconds=15.0,
        time_scale=1.0,
        seed=seed,
    )
    assert sched["scheduled_for"] >= end
    assert "waiting_until_meeting_ends" in sched["reason"] or sched["reason"].startswith(
        "deferred_"
    )
    assert sched["delay_seconds"] > 5 * 60


def test_sleeping_defers_until_wake():
    wake = NOW + timedelta(hours=7)
    sched = compute_response_schedule(
        activity_key="sleeping",
        availability=0.0,
        priority="normal",
        now=NOW,
        activity_expected_end_at=wake,
        batch_window_seconds=15.0,
        time_scale=1.0,
        seed="sleep-seed",
    )
    assert sched["reason"] == "currently_sleeping"
    assert sched["scheduled_for"] >= wake
    assert sched["engaged"] is False


def test_same_seed_is_stable():
    kwargs = dict(
        activity_key="working",
        availability=0.6,
        priority="normal",
        now=NOW,
        activity_expected_end_at=NOW + timedelta(minutes=60),
        batch_window_seconds=15.0,
        time_scale=1.0,
        seed="stable-seed-abc",
    )
    a = compute_response_schedule(**kwargs)
    b = compute_response_schedule(**kwargs)
    assert a["scheduled_for"] == b["scheduled_for"]
    assert a["reason"] == b["reason"]
    assert a["engaged"] == b["engaged"]


def test_activity_label_human():
    assert activity_label("working") == "At work"
    assert activity_label("meeting") == "In a meeting"
    assert activity_label("sleeping") == "Asleep"
