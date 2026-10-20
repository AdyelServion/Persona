"""Canonical QA test-case definitions for suite sarah_consistency v1.

Expected persona values use FactRef sources resolved at runtime from the
cloned qa persona — never hard-coded as universal truths in the runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from persona_runtime.qa.models import AssertionDef, StepDef, TestCaseDef

FIXTURES_DIR = Path(__file__).resolve().parent


def _ref(source: str, **kwargs: Any) -> dict[str, Any]:
    return {"source": source, **kwargs}


def _assert(atype: str, **kwargs: Any) -> dict[str, Any]:
    return AssertionDef(type=atype, **kwargs).model_dump()


def _step(
    order: int,
    *,
    message: str | None = None,
    action: str | None = None,
    expected_facts: dict | None = None,
    forbidden_facts: dict | None = None,
    expected_behavior: str | None = None,
    assertions: list[dict] | None = None,
    action_params: dict | None = None,
    step_type: str = "user_message",
) -> dict[str, Any]:
    return StepDef(
        order=order,
        step_type=step_type if not action else "action",
        user_message=message,
        action=action,
        expected_facts=expected_facts or {},
        forbidden_facts=forbidden_facts or {},
        expected_behavior=expected_behavior,
        assertions=[AssertionDef.model_validate(a) for a in (assertions or [])],
        action_params=action_params or {},
    ).model_dump()


def _case(
    test_key: str,
    category: str,
    title: str,
    steps: list[dict],
    *,
    description: str = "",
    severity: str = "medium",
    preconditions: dict | None = None,
    tags: list[str] | None = None,
    evaluation_mode: str = "deterministic",
    setup_actions: list[dict] | None = None,
    assertions: list[dict] | None = None,
) -> TestCaseDef:
    return TestCaseDef(
        test_key=test_key,
        category=category,
        title=title,
        description=description,
        severity=severity,  # type: ignore[arg-type]
        preconditions=preconditions
        or {"isolated_test_user": True, "fresh_persona_memory": True},
        setup_actions=setup_actions or [],
        assertions=[AssertionDef.model_validate(a) for a in (assertions or [])],
        tags=tags or [category],
        steps=[StepDef.model_validate(s) for s in steps],
        evaluation_mode=evaluation_mode,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Category A — Profile
# ---------------------------------------------------------------------------

def _profile_cases() -> list[TestCaseDef]:
    questions = [
        ("PROFILE-001", "Ask Sarah for her birthday", "When is your birthday?", "PERSONA_FACT_DOB"),
        ("PROFILE-002", "Ask for her zodiac sign", "What's your zodiac sign?", "PERSONA_FACT_ZODIAC"),
        ("PROFILE-003", "Ask where she lives", "Where do you live?", "PERSONA_FACT_LIVES_IN"),
        ("PROFILE-004", "Ask where she grew up", "Where did you grow up?", "PERSONA_FACT_HOMETOWN"),
        ("PROFILE-005", "Ask about her occupation", "What do you do for work?", "PERSONA_FACT_OCCUPATION"),
        ("PROFILE-006", "Ask about her education", "What did you study?", "PERSONA_FACT_DEGREE"),
        ("PROFILE-007", "Ask for her employer", "Who do you work for?", "PERSONA_FACT_EMPLOYER"),
        ("PROFILE-008", "Ask for her office location", "Where is your office?", "PERSONA_FACT_OFFICE"),
        (
            "PROFILE-009",
            "Ask about her interests",
            "What are your interests?",
            None,
        ),
        (
            "PROFILE-010",
            "Ask about her favorite food",
            "What's your favourite food?",
            None,
        ),
        (
            "PROFILE-011",
            "Ask about her transport arrangement",
            "How do you get to work?",
            "PERSONA_FACT_COMMUTE_MODE",
        ),
    ]
    cases: list[TestCaseDef] = []
    for key, title, msg, fact_id in questions:
        expected = {}
        asserts = [
            _assert("response_schema_valid", required=True),
            _assert("no_unsupported_claim", required=True),
        ]
        if fact_id:
            expected = {"persona.fact": _ref("canonical", fact_id=fact_id)}
            asserts.append(
                _assert(
                    "required_fact_present",
                    path="persona.fact",
                    expected_ref=_ref("canonical", fact_id=fact_id),
                    required=True,
                )
            )
            asserts.append(
                _assert(
                    "database_state_match",
                    path="canonical",
                    expected_ref=_ref("canonical", fact_id=fact_id),
                    required=True,
                )
            )
        elif key == "PROFILE-010":
            asserts.append(
                _assert(
                    "semantic_fact_match",
                    path="persona.favourite_food",
                    expected_ref=_ref("habit", habit_id="favourite_food"),
                    required=True,
                )
            )
        else:
            asserts.append(
                _assert(
                    "topic_relevance",
                    path="interests",
                    evaluation_mode="live",
                    required=False,
                )
            )
        cases.append(
            _case(
                key,
                "persona_identity",
                title,
                [_step(1, message=msg, expected_facts=expected, assertions=asserts)],
            )
        )

    cases.append(
        _case(
            "PROFILE-012",
            "persona_identity",
            "Repeat identity questions after restarting the conversation",
            [
                _step(
                    1,
                    message="Where do you live?",
                    expected_facts={"persona.lives_in": _ref("canonical", fact_id="PERSONA_FACT_LIVES_IN")},
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        )
                    ],
                ),
                _step(2, action="end_and_reopen_conversation"),
                _step(
                    3,
                    message="Where do you live again?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert("no_contradiction", path="persona.lives_in", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "PROFILE-013",
            "persona_identity",
            "Repeat identity questions in a new session",
            [
                _step(
                    1,
                    message="What do you do for work?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        )
                    ],
                ),
                _step(2, action="new_conversation_same_user"),
                _step(
                    3,
                    message="What's your job?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        )
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "PROFILE-014",
            "persona_identity",
            "Ask the same question with different wording",
            [
                _step(
                    1,
                    message="Where are you based?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        )
                    ],
                ),
                _step(
                    2,
                    message="Which city do you live in?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert("no_contradiction", path="persona.lives_in", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "PROFILE-015",
            "persona_identity",
            "Ask about an unconfigured profile field",
            [
                _step(
                    1,
                    message="What is your middle name?",
                    forbidden_facts={"persona.middle_name": "established"},
                    assertions=[
                        _assert("no_unsupported_claim", path="persona.middle_name", required=True),
                        _assert("forbidden_fact_absent", path="persona.middle_name", required=True),
                    ],
                )
            ],
            severity="medium",
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category B — Context
# ---------------------------------------------------------------------------

def _context_cases() -> list[TestCaseDef]:
    simple = [
        ("CONTEXT-001", "What's your favorite dish?", "favourite dish"),
        ("CONTEXT-002", "What are you having for lunch?", "current meal"),
        ("CONTEXT-003", "Where are you right now?", "current location"),
        ("CONTEXT-004", "What are you doing there?", "current activity"),
        ("CONTEXT-005", "Are you still at the office?", "office presence"),
        ("CONTEXT-006", "What are you working on?", "current task"),
    ]
    cases = [
        _case(
            key,
            "contextual_understanding",
            f"Direct answer: {msg}",
            [
                _step(
                    1,
                    message=msg,
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("topic_relevance", path=topic, required=True, evaluation_mode="live"),
                        _assert("no_unsupported_claim", required=True),
                    ],
                )
            ],
            evaluation_mode="mixed",
        )
        for key, msg, topic in simple
    ]
    cases.append(
        _case(
            "CONTEXT-007",
            "contextual_understanding",
            "What did I just ask you?",
            [
                _step(1, message="Where do you live?"),
                _step(
                    2,
                    message="What did I just ask you?",
                    assertions=[
                        _assert("topic_relevance", path="meta_recall", required=True, evaluation_mode="live"),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "CONTEXT-008",
            "contextual_understanding",
            "And what about tomorrow?",
            [
                _step(1, message="What are your plans for today?"),
                _step(
                    2,
                    message="And what about tomorrow?",
                    assertions=[
                        _assert("topic_relevance", path="tomorrow_plans", required=True, evaluation_mode="live"),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "CONTEXT-009",
            "contextual_understanding",
            "Why do you like it?",
            [
                _step(1, message="What's your favourite food?"),
                _step(
                    2,
                    message="Why do you like it?",
                    assertions=[
                        _assert("topic_relevance", path="food_followup", required=True, evaluation_mode="live"),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "CONTEXT-010",
            "contextual_understanding",
            "Two unrelated answerable questions in one message",
            [
                _step(
                    1,
                    message="Where do you live, and what do you do for work?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        ),
                    ],
                )
            ],
        )
    )
    cases.append(
        _case(
            "CONTEXT-011",
            "contextual_understanding",
            "Follow-up with pronoun reference",
            [
                _step(1, message="Tell me about your office."),
                _step(
                    2,
                    message="How long does it take you to get there?",
                    assertions=[
                        _assert("topic_relevance", path="commute_followup", required=True, evaluation_mode="live"),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "CONTEXT-012",
            "contextual_understanding",
            "Change topics then return",
            [
                _step(1, message="What are you working on?"),
                _step(2, message="Do you like photography?"),
                _step(
                    3,
                    message="Anyway, back to work — what were you working on?",
                    assertions=[
                        _assert("topic_relevance", path="return_topic", required=True, evaluation_mode="live"),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "CONTEXT-013",
            "contextual_understanding",
            "Ask about an unknown meal or activity",
            [
                _step(
                    1,
                    message="What exact dessert did you eat last Tuesday at 15:17?",
                    assertions=[
                        _assert("no_unsupported_claim", required=True),
                        _assert("forbidden_fact_absent", path="persona.dessert_detail", required=True),
                    ],
                )
            ],
        )
    )
    cases.append(
        _case(
            "CONTEXT-014",
            "contextual_understanding",
            "Repeat a question after intervening messages",
            [
                _step(1, message="Where do you live?"),
                _step(2, message="Nice."),
                _step(3, message="Work has been busy."),
                _step(
                    4,
                    message="Where do you live again?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert("no_contradiction", path="persona.lives_in", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "CONTEXT-015",
            "contextual_understanding",
            "Multi-part question — each part answered",
            [
                _step(
                    1,
                    message="What's your job title, who do you work for, and where is the office?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_EMPLOYER"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OFFICE"),
                            required=True,
                            options={"partial_ok": True},
                        ),
                    ],
                )
            ],
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category C — Time
# ---------------------------------------------------------------------------

def _time_cases() -> list[TestCaseDef]:
    clock_qs = [
        ("TIME-001", "Ask for the current local date", "What's today's date?", "local_date"),
        ("TIME-002", "Ask for the current weekday", "What day is it today?", "weekday"),
        ("TIME-003", "Ask for the current local time", "What time is it there?", "local_time"),
    ]
    cases = [
        _case(
            key,
            "time_timeline",
            title,
            [
                _step(
                    1,
                    action="set_clock",
                    action_params={"utc": "2026-06-10T12:00:00+00:00"},
                ),
                _step(
                    2,
                    message=msg,
                    assertions=[
                        _assert(
                            "date_time_match",
                            path=field,
                            expected_ref=_ref("clock", field=field),
                            required=True,
                        ),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
        )
        for key, title, msg, field in clock_qs
    ]
    more = [
        ("TIME-004", "Ask for the current location", "Where are you right now?"),
        ("TIME-005", "Ask what she is doing now", "What are you doing now?"),
        ("TIME-006", "Ask when she finishes work", "When do you finish work today?"),
        ("TIME-007", "Ask how long until work ends", "How long until you finish work?"),
        ("TIME-008", "Ask when she expects to arrive home", "When will you get home?"),
        ("TIME-009", "Ask whether she has left work", "Have you left work yet?"),
        ("TIME-010", "Ask whether she has reached home", "Have you got home yet?"),
        ("TIME-011", "Ask what she did yesterday", "What did you do yesterday?"),
        ("TIME-012", "Ask what she plans to do tomorrow", "What are your plans for tomorrow?"),
        ("TIME-013", "Ask about an event two hours earlier", "What were you doing two hours ago?"),
        ("TIME-014", "Ask whether a scheduled meeting has finished", "Has your meeting finished?"),
    ]
    for key, title, msg in more:
        cases.append(
            _case(
                key,
                "time_timeline",
                title,
                [
                    _step(
                        1,
                        action="set_clock",
                        action_params={"utc": "2026-06-10T13:30:00+00:00"},
                    ),
                    _step(
                        2,
                        message=msg,
                        assertions=[
                            _assert("timeline_consistency", required=True),
                            _assert("no_unsupported_claim", required=True),
                            _assert("date_time_match", path="clock_authority", required=False),
                        ],
                    ),
                ],
            )
        )
    cases.append(
        _case(
            "TIME-015",
            "time_timeline",
            "Advance the test clock across midnight",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T22:30:00+00:00"}),
                _step(2, message="What day is it?"),
                _step(3, action="advance_clock", action_params={"hours": 2}),
                _step(
                    4,
                    message="What day is it now?",
                    assertions=[
                        _assert(
                            "date_time_match",
                            path="weekday",
                            expected_ref=_ref("clock", field="weekday"),
                            required=True,
                        ),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "TIME-016",
            "time_timeline",
            "UK daylight-saving transition",
            [
                _step(
                    1,
                    action="set_clock",
                    action_params={"utc": "2026-10-25T00:30:00+00:00"},
                ),
                _step(
                    2,
                    message="What time is it locally?",
                    assertions=[
                        _assert(
                            "date_time_match",
                            path="local_time",
                            expected_ref=_ref("clock", field="local_time"),
                            required=True,
                        ),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
            tags=["time_timeline", "dst"],
        )
    )
    cases.append(
        _case(
            "TIME-017",
            "time_timeline",
            "Rebuild runtime and verify time and state",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T15:00:00+00:00"}),
                _step(2, message="What time is it?"),
                _step(3, action="rebuild_runtime"),
                _step(
                    4,
                    message="What time is it now?",
                    assertions=[
                        _assert(
                            "date_time_match",
                            path="local_time",
                            expected_ref=_ref("clock", field="local_time"),
                            required=True,
                        ),
                        _assert("database_state_match", path="persona_state", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "TIME-018",
            "time_timeline",
            "Advance beyond a scheduled event without confirming completion",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T11:00:00+00:00"}),
                _step(2, message="Do you have a meeting later?"),
                _step(3, action="advance_clock", action_params={"hours": 4}),
                _step(
                    4,
                    message="Did that meeting finish?",
                    assertions=[
                        _assert("event_status_match", required=True),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "TIME-019",
            "time_timeline",
            "Change a one-day schedule exception",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T09:00:00+00:00"}),
                _step(
                    2,
                    action="set_schedule_exception",
                    action_params={"note": "leave_early", "finish_local": "15:00"},
                ),
                _step(
                    3,
                    message="When do you finish work today?",
                    assertions=[
                        _assert("timeline_consistency", required=True),
                        _assert("event_status_match", required=False),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "TIME-020",
            "time_timeline",
            "Verify commute time calculation",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T16:45:00+00:00"}),
                _step(
                    2,
                    message="How long is your commute home?",
                    assertions=[
                        _assert("timeline_consistency", required=True),
                        _assert("no_unsupported_claim", required=True),
                    ],
                ),
            ],
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category D — State / contradictions
# ---------------------------------------------------------------------------

def _state_cases() -> list[TestCaseDef]:
    items = [
        ("STATE-001", "Ask whether Sarah owns a car", "Do you own a car?", "PERSONA_FACT_OWNS_PERSONAL_VEHICLE"),
        ("STATE-002", "Ask how she commutes", "How do you commute?", "PERSONA_FACT_COMMUTE_MODE"),
        ("STATE-003", "Ask which car she drives", "Which car do you drive?", None),
        ("STATE-004", "Ask whether the car is personally owned or company-provided", "Is that your personal car or a company car?", None),
        ("STATE-005", "Ask how long the commute takes", "How long is your commute?", None),
        ("STATE-006", "Ask whether she is at the office or at home", "Are you at the office or at home?", None),
    ]
    cases: list[TestCaseDef] = []
    for key, title, msg, fact_id in items:
        asserts = [
            _assert("no_contradiction", required=True),
            _assert("no_unsupported_claim", required=True),
        ]
        if fact_id:
            asserts.append(
                _assert(
                    "required_fact_present",
                    expected_ref=_ref("canonical", fact_id=fact_id),
                    required=True,
                    options={"normalize_bool": True},
                )
            )
        cases.append(
            _case(
                key,
                "contradiction_detection",
                title,
                [_step(1, message=msg, assertions=asserts)],
            )
        )
    cases.append(
        _case(
            "STATE-007",
            "contradiction_detection",
            "Challenge conflicting work finishing times",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T14:00:00+00:00"}),
                _step(2, message="When do you finish work?"),
                _step(
                    3,
                    message="Earlier you said something different — so when exactly do you finish?",
                    assertions=[
                        _assert("no_contradiction", path="persona.work.finish_time", required=True),
                        _assert("timeline_consistency", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "STATE-008",
            "contradiction_detection",
            "Challenge conflicting transport statements",
            [
                _step(1, message="How do you get to work?"),
                _step(
                    2,
                    message="So you drive your own car every day?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OWNS_PERSONAL_VEHICLE"),
                            required=True,
                            options={"normalize_bool": True},
                        ),
                        _assert("no_contradiction", path="persona.transport", required=True),
                    ],
                ),
            ],
        )
    )
    for key, title, msg in [
        ("STATE-009", "Verify lunch completed or planned", "Have you had lunch yet?"),
        ("STATE-010", "Verify project active or complete", "Is your current project finished?"),
        ("STATE-011", "Compare answer with authoritative persona state", "Where are you right now?"),
    ]:
        cases.append(
            _case(
                key,
                "contradiction_detection",
                title,
                [
                    _step(1, action="set_clock", action_params={"utc": "2026-06-10T13:00:00+00:00"}),
                    _step(
                        2,
                        message=msg,
                        assertions=[
                            _assert("database_state_match", path="persona_state", required=True),
                            _assert("no_contradiction", required=True),
                            _assert("event_status_match", required=False),
                        ],
                    ),
                ],
            )
        )
    cases.append(
        _case(
            "STATE-012",
            "contradiction_detection",
            "Detect contradictory claims within a single response",
            [
                _step(
                    1,
                    message="Do you own a car, and how do you commute?",
                    assertions=[_assert("no_contradiction", required=True)],
                )
            ],
        )
    )
    cases.append(
        _case(
            "STATE-013",
            "contradiction_detection",
            "Detect a response that contradicts an earlier statement",
            [
                _step(1, message="Where do you live?"),
                _step(
                    2,
                    message="Remind me — which city?",
                    assertions=[_assert("no_contradiction", path="persona.lives_in", required=True)],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "STATE-014",
            "contradiction_detection",
            "Detect a conflict caused by stale memory",
            [
                _step(1, message="My name is Alex."),
                _step(2, message="Actually my name is Jordan."),
                _step(
                    3,
                    action="end_and_reopen_conversation",
                ),
                _step(
                    4,
                    message="What's my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Jordan", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Jordan", required=True),
                    ],
                ),
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "STATE-015",
            "contradiction_detection",
            "Correct a persona fact and verify subsequent responses follow",
            [
                _step(
                    1,
                    action="correct_canonical_fact",
                    action_params={
                        "fact_id": "PERSONA_FACT_LIVES_IN",
                        "object": "Leeds",
                        "fixture_only": True,
                    },
                ),
                _step(
                    2,
                    message="Where do you live?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected=_ref("literal", value="Leeds"),
                            required=True,
                        )
                    ],
                ),
            ],
            preconditions={
                "isolated_test_user": True,
                "fresh_persona_memory": True,
                "dedicated_conflict_fixture": True,
            },
            severity="high",
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category E — Memory
# ---------------------------------------------------------------------------

MEMORY_PRELUDE = [
    "My name is Alex.",
    "I own a Honda CR-Z.",
    "I enjoy photography.",
    "I usually go for drives on weekends.",
    "I have an important presentation next Friday.",
    "I prefer tea in the morning.",
    "I don't like being messaged repeatedly when I'm busy.",
]


def _mem_cases() -> list[TestCaseDef]:
    pairs = [
        ("MEM-001", "Remember the user's name", "What's my name?", "user.name", "Alex"),
        ("MEM-002", "Remember the user's car", "What car do I drive?", "user.car", "Honda CR-Z"),
        ("MEM-003", "Remember the user's hobby", "What hobby do I enjoy?", "user.hobby", "photography"),
        ("MEM-004", "Remember the user's weekend preference", "What do I usually do on weekends?", "user.weekend", "drives"),
        ("MEM-005", "Remember an upcoming presentation", "What do I have coming up?", "user.presentation", "presentation"),
        ("MEM-006", "Remember a food or drink preference", "What do I prefer in the morning?", "user.drink", "tea"),
        ("MEM-007", "Remember the user's messaging boundary", "Do I like being messaged a lot when busy?", "user.boundary", "busy"),
    ]
    cases: list[TestCaseDef] = []
    for key, title, ask, path, expected in pairs:
        steps = [_step(i + 1, message=m) for i, m in enumerate(MEMORY_PRELUDE)]
        steps.append(
            _step(
                len(MEMORY_PRELUDE) + 1,
                message=ask,
                expected_facts={path: expected},
                assertions=[
                    _assert("memory_persisted", path=path, expected=expected, required=True),
                    _assert("memory_retrieved", path=path, expected=expected, required=True),
                    _assert("semantic_fact_match", path=path, expected=expected, required=True),
                ],
            )
        )
        cases.append(
            _case(
                key,
                "persistent_memory",
                title,
                steps,
                setup_actions=[{"action": "seed_memory_prelude"}],
                severity="high",
            )
        )

    cases.append(
        _case(
            "MEM-008",
            "persistent_memory",
            "Retrieve each memory after ending and reopening the conversation",
            [
                *[_step(i + 1, message=m) for i, m in enumerate(MEMORY_PRELUDE)],
                _step(len(MEMORY_PRELUDE) + 1, action="end_and_reopen_conversation"),
                _step(
                    len(MEMORY_PRELUDE) + 2,
                    message="Do you remember my name and my car?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("memory_retrieved", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.car", expected="Honda", required=True),
                    ],
                ),
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "MEM-009",
            "persistent_memory",
            "Retrieve each memory after restarting the backend",
            [
                *[_step(i + 1, message=m) for i, m in enumerate(MEMORY_PRELUDE[:3])],
                _step(4, action="rebuild_runtime"),
                _step(
                    5,
                    message="What's my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("memory_retrieved", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alex", required=True),
                    ],
                ),
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "MEM-010",
            "persistent_memory",
            "Retrieve a relevant memory without being explicitly reminded",
            [
                *[_step(i + 1, message=m) for i, m in enumerate(MEMORY_PRELUDE)],
                _step(
                    len(MEMORY_PRELUDE) + 1,
                    message="Any tips for my big day next week?",
                    assertions=[
                        _assert("memory_retrieved", path="user.presentation", expected="presentation", required=True),
                        _assert("semantic_fact_match", path="user.presentation", expected="presentation", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "MEM-011",
            "persistent_memory",
            "Avoid retrieving an irrelevant memory for an unrelated question",
            [
                *[_step(i + 1, message=m) for i, m in enumerate(MEMORY_PRELUDE)],
                _step(
                    len(MEMORY_PRELUDE) + 1,
                    message="What's the weather like for chatting?",
                    assertions=[
                        _assert(
                            "memory_retrieved",
                            path="user.car",
                            expected="Honda",
                            required=False,
                            options={"must_not_force": True},
                        ),
                        _assert("topic_relevance", path="smalltalk", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        )
    )
    cases.append(
        _case(
            "MEM-012",
            "persistent_memory",
            "Correct an existing memory",
            [
                _step(1, message="My name is Alex."),
                _step(2, message="Actually, call me Alexander."),
                _step(
                    3,
                    message="What's my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alexander", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alexander", required=True),
                    ],
                ),
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "MEM-013",
            "persistent_memory",
            "Resolve an outdated preference",
            [
                _step(1, message="I prefer tea in the morning."),
                _step(2, message="I've switched — I prefer coffee now."),
                _step(
                    3,
                    message="What do I drink in the morning?",
                    assertions=[
                        _assert("memory_persisted", path="user.drink", expected="coffee", required=True),
                        _assert("semantic_fact_match", path="user.drink", expected="coffee", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "MEM-014",
            "persistent_memory",
            "Avoid inventing an outcome for a past event",
            [
                _step(1, message="I have an important presentation next Friday."),
                _step(2, action="set_clock", action_params={"utc": "2026-06-20T12:00:00+00:00"}),
                _step(
                    3,
                    message="How did my presentation go?",
                    assertions=[
                        _assert("no_unsupported_claim", path="user.presentation.outcome", required=True),
                        _assert(
                            "memory_provenance_match",
                            path="user.presentation",
                            options={"horizon_not": "resolved_without_user"},
                            required=True,
                        ),
                    ],
                ),
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "MEM-015",
            "persistent_memory",
            "Verify memory provenance and timestamps are retained",
            [
                _step(1, message="My name is Alex."),
                _step(
                    2,
                    message="Do you remember my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("memory_provenance_match", path="user.name", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "MEM-016",
            "persistent_memory",
            "Ephemeral fact is not treated as permanent",
            [
                _step(1, message="I'm grabbing a sandwich right now."),
                _step(2, action="advance_clock", action_params={"hours": 48}),
                _step(
                    3,
                    message="What am I eating right now?",
                    assertions=[
                        _assert("no_unsupported_claim", path="user.current_meal", required=True),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "MEM-017",
            "persistent_memory",
            "Uncertain fact remains marked as uncertain",
            [
                _step(1, message="I might go hiking this weekend, not sure yet."),
                _step(
                    2,
                    message="Am I definitely going hiking?",
                    assertions=[
                        _assert("no_unsupported_claim", path="user.hiking.confirmed", required=True),
                        _assert(
                            "memory_provenance_match",
                            path="user.hiking",
                            options={"allow_uncertain": True},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
    )
    cases.append(
        _case(
            "MEM-018",
            "persistent_memory",
            "Superseded test memory is no longer retrieved",
            [
                _step(1, message="My name is Alex."),
                _step(2, action="supersede_memory", action_params={"path": "user.name", "match": "Alex"}),
                _step(
                    3,
                    message="What's my name?",
                    assertions=[
                        _assert(
                            "memory_retrieved",
                            path="user.name",
                            expected="Alex",
                            required=True,
                            options={"must_be_absent": True},
                        ),
                    ],
                ),
            ],
            severity="high",
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category F — Human
# ---------------------------------------------------------------------------

def _human_cases() -> list[TestCaseDef]:
    msgs = [
        ("HUMAN-001", "Hey, what are you up to?"),
        ("HUMAN-002", "Oh nice."),
        ("HUMAN-003", "Haha, fair enough."),
        ("HUMAN-004", "I'm exhausted today."),
        ("HUMAN-005", "Work has been really stressful lately."),
        ("HUMAN-006", "I had a pretty good day, actually."),
        ("HUMAN-007", "Nothing much, just chilling."),
        ("HUMAN-008", "Tell me a short anecdote from your week."),
        ("HUMAN-009", "What kind of music do you like?"),
        ("HUMAN-010", "What do you like doing on Sundays?"),
        ("HUMAN-011", "I don't feel like talking much right now."),
        ("HUMAN-012", "You sound a bit too formal."),
        ("HUMAN-013", "I disagree — I think remote work is better."),
        ("HUMAN-014", "Yep."),
        ("HUMAN-015", "Alright, talk later."),
    ]
    return [
        _case(
            key,
            "human_like_conversation",
            f"Human-like turn: {msg[:40]}",
            [
                _step(
                    1,
                    message=msg,
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                    ],
                )
            ],
            evaluation_mode="live",
            severity="low",
        )
        for key, msg in msgs
    ]


def _human_multiturn_cases() -> list[TestCaseDef]:
    """Multi-turn dating-app naturalness cases added for the post-fix benchmark.

    These extend the existing HUMAN-* catalog; they do not change product logic.
    """
    return [
        _case(
            "HUMAN-016",
            "human_like_conversation",
            "Meal follow-up after an office/location turn",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T12:00:00+00:00"}),
                _step(2, message="Where are you right now?"),
                _step(
                    3,
                    message="What are you having for lunch?",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("no_unsupported_claim", required=True),
                        _assert("topic_relevance", path="food_followup", evaluation_mode="live", required=False),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="medium",
        ),
        _case(
            "HUMAN-017",
            "human_like_conversation",
            "Work follow-up chain: location, task, project, leaving, home time",
            [
                _step(1, action="set_clock", action_params={"utc": "2026-06-10T13:30:00+00:00"}),
                _step(2, message="Where are you right now?"),
                _step(3, message="What are you working on?"),
                _step(4, message="What's the project about?"),
                _step(5, message="When are you leaving work?"),
                _step(
                    6,
                    message="When will you get home?",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("timeline_consistency", required=True),
                        _assert("no_unsupported_claim", required=True),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="medium",
        ),
        _case(
            "HUMAN-018",
            "human_like_conversation",
            "Long session (15+ turns) then recall an earlier user fact",
            [
                _step(1, message="My name is Alex."),
                _step(2, message="I own a Honda CR-Z."),
                _step(3, message="I enjoy photography."),
                _step(4, message="Hey, what are you up to?"),
                _step(5, message="Oh nice."),
                _step(6, message="How's work going?"),
                _step(7, message="Yeah"),
                _step(8, message="Do you like music?"),
                _step(9, message="Cool"),
                _step(10, message="I usually go for drives on weekends."),
                _step(11, message="What do you like doing on Sundays?"),
                _step(12, message="Ahaan"),
                _step(13, message="I had a pretty good day, actually."),
                _step(14, message="Haha, fair enough"),
                _step(15, message="I'm a bit tired though."),
                _step(16, message="Anyway"),
                _step(17, message="What are you working on?"),
                _step(18, message="Let's talk hobbies instead."),
                _step(
                    19,
                    message="What car do I drive, and what's my name?",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("memory_persisted", path="user.car", expected="Honda", required=True),
                        _assert("memory_retrieved", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.car", expected="Honda", required=True),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="high",
        ),
    ]


# ---------------------------------------------------------------------------
# Category G — Proactive
# ---------------------------------------------------------------------------

def _proactive_cases() -> list[TestCaseDef]:
    return [
        _case(
            "PROACTIVE-001",
            "proactive_engagement",
            "Resume a conversation after the user returns",
            [
                _step(1, message="I have a presentation next Friday."),
                _step(2, action="end_and_reopen_conversation"),
                _step(
                    3,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed"},
                    assertions=[
                        _assert("proactive_permission_respected", required=True),
                    ],
                ),
            ],
        ),
        _case(
            "PROACTIVE-002",
            "proactive_engagement",
            "Follow up on an earlier presentation plan",
            [
                _step(1, message="I have an important presentation next Friday."),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                    assertions=[_assert("proactive_permission_respected", required=True)],
                ),
            ],
        ),
        _case(
            "PROACTIVE-003",
            "proactive_engagement",
            "Follow up on a planned weekend drive",
            [
                _step(1, message="I usually go for drives on weekends."),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                    assertions=[_assert("proactive_permission_respected", required=True)],
                ),
            ],
        ),
        _case(
            "PROACTIVE-004",
            "proactive_engagement",
            "Continue a topic when the user expresses stress",
            [
                _step(
                    1,
                    message="Work has been really stressful lately.",
                    assertions=[
                        _assert("topic_relevance", path="stress", evaluation_mode="live", required=False),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                    ],
                )
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "PROACTIVE-005",
            "proactive_engagement",
            "Resume an earlier topic after a pause",
            [
                _step(1, message="I've been learning photography."),
                _step(2, message="Anyway."),
                _step(
                    3,
                    message="Hey again",
                    assertions=[
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "PROACTIVE-006",
            "proactive_engagement",
            "Avoid repetitive questions when the user gives short answers",
            [
                _step(1, message="Yep."),
                _step(2, message="Ok."),
                _step(
                    3,
                    message="Mhmm.",
                    assertions=[
                        _assert("tone_quality", evaluation_mode="live", required=False),
                        _assert(
                            "exact_match",
                            path="avoid_interview_loop",
                            options={"max_trailing_questions": 1},
                            required=False,
                        ),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "PROACTIVE-007",
            "proactive_engagement",
            "Respect a request to stop messaging",
            [
                _step(1, message="Please don't message me proactively."),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False},
                            required=True,
                        )
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PROACTIVE-008",
            "proactive_engagement",
            "Disabled proactive messaging produces no unsolicited message",
            [
                _step(
                    1,
                    action="set_proactive",
                    action_params={"enabled": False},
                ),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": False},
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False},
                            required=True,
                        )
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PROACTIVE-009",
            "proactive_engagement",
            "Verify message frequency caps",
            [
                _step(1, action="set_proactive", action_params={"enabled": True, "max_per_day": 1}),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True, "force_count_today": 1},
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False, "reason_contains": "max_per_day"},
                            required=True,
                        )
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PROACTIVE-010",
            "proactive_engagement",
            "Verify quiet hours via sleeping / low availability gate",
            [
                _step(
                    1,
                    action="set_persona_availability",
                    action_params={"sleeping": True, "availability": 0.1},
                ),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False},
                            required=True,
                        )
                    ],
                ),
            ],
            description="App has no named quiet-hours setting; tests sleeping/availability gate.",
            severity="high",
        ),
        _case(
            "PROACTIVE-011",
            "proactive_engagement",
            "Follow-up is not sent before its configured trigger",
            [
                _step(1, action="set_proactive", action_params={"enabled": True, "min_interval_hours": 12}),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={
                        "situation": "user_resumed",
                        "enable_outbound": True,
                        "last_proactive_minutes_ago": 30,
                    },
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False, "reason_contains": "min_interval"},
                            required=True,
                        )
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PROACTIVE-012",
            "proactive_engagement",
            "Same follow-up is not sent repeatedly",
            [
                _step(1, action="set_proactive", action_params={"enabled": True, "max_per_day": 1}),
                _step(
                    2,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                ),
                _step(
                    3,
                    action="schedule_resume",
                    action_params={"situation": "user_resumed", "enable_outbound": True},
                    assertions=[
                        _assert(
                            "proactive_permission_respected",
                            options={"expect_allow": False},
                            required=True,
                        )
                    ],
                ),
            ],
            severity="high",
        ),
    ]


# ---------------------------------------------------------------------------
# Category H — Format
# ---------------------------------------------------------------------------

def _format_cases() -> list[TestCaseDef]:
    return [
        _case(
            "FORMAT-001",
            "response_formatting",
            "Simple greeting produces a suitable response",
            [
                _step(
                    1,
                    message="Hey",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("bubble_count_range", options={"min": 1, "max": 4}, required=True),
                    ],
                )
            ],
        ),
        _case(
            "FORMAT-002",
            "response_formatting",
            "Two-part question receives complete answers",
            [
                _step(
                    1,
                    message="Where do you live and what do you do?",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        ),
                    ],
                )
            ],
        ),
        _case(
            "FORMAT-003",
            "response_formatting",
            "Longer response uses meaningful bubbles if supported",
            [
                _step(
                    1,
                    message="Tell me a bit about your job and your city.",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("bubble_count_range", options={"min": 1, "max": 6}, required=True),
                    ],
                )
            ],
            severity="low",
        ),
        _case(
            "FORMAT-004",
            "response_formatting",
            "Emotional message receives acknowledgement",
            [
                _step(
                    1,
                    message="I'm really stressed today.",
                    assertions=[
                        _assert("tone_quality", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                )
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FORMAT-005",
            "response_formatting",
            "Follow-up uses conversational context",
            [
                _step(1, message="I love photography."),
                _step(
                    2,
                    message="Any favourite spots?",
                    assertions=[
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FORMAT-006",
            "response_formatting",
            "Goodbye does not generate an unnecessary extended conversation",
            [
                _step(
                    1,
                    message="Bye for now",
                    assertions=[
                        _assert("bubble_count_range", options={"min": 1, "max": 3}, required=True),
                        _assert("tone_quality", evaluation_mode="live", required=False),
                    ],
                )
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FORMAT-007",
            "response_formatting",
            "Backend returns valid structured output",
            [
                _step(
                    1,
                    message="Hi",
                    assertions=[_assert("response_schema_valid", required=True)],
                )
            ],
        ),
        _case(
            "FORMAT-008",
            "response_formatting",
            "Bubbles remain in the correct order",
            [
                _step(
                    1,
                    message="Tell me about your job.",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert("bubble_count_range", options={"min": 1, "max": 6}, required=True),
                    ],
                )
            ],
        ),
        _case(
            "FORMAT-009",
            "response_formatting",
            "Frontend does not display raw JSON",
            [
                _step(
                    1,
                    message="Hello",
                    assertions=[
                        _assert(
                            "exact_match",
                            path="no_raw_json_leak",
                            options={"forbid_substrings": ["behaviour_plan", "response_plan", '{"']},
                            required=True,
                        )
                    ],
                )
            ],
        ),
        _case(
            "FORMAT-010",
            "response_formatting",
            "Invalid model output is handled safely",
            [
                _step(
                    1,
                    action="force_invalid_model_output",
                    action_params={},
                ),
                _step(
                    2,
                    message="Hey",
                    assertions=[
                        _assert("response_schema_valid", required=True),
                        _assert(
                            "exact_match",
                            path="no_raw_json_leak",
                            options={"forbid_substrings": ["Traceback", "behaviour_plan"]},
                            required=True,
                        ),
                    ],
                ),
            ],
            severity="high",
        ),
    ]


# ---------------------------------------------------------------------------
# Category I — Unknown
# ---------------------------------------------------------------------------

def _unknown_cases() -> list[TestCaseDef]:
    qs = [
        ("UNKNOWN-001", "Ask what the user ate yesterday when never provided", "What did I eat yesterday?"),
        ("UNKNOWN-002", "Ask what the user is doing right now without a source", "What am I doing right now?"),
        ("UNKNOWN-003", "Ask what Sarah did at an unrecorded historical time", "What exactly did you do on 3 March 2019 at 14:12?"),
        ("UNKNOWN-004", "Ask what her manager said when no such event is recorded", "What did your manager say in yesterday's 1:1?"),
        ("UNKNOWN-005", "Ask whether a planned holiday was booked", "Did you book that holiday to Spain?"),
        ("UNKNOWN-006", "Ask for the user's favorite food when not established", "What's my favourite food?"),
        ("UNKNOWN-007", "Ask for details of an unrecorded hiking trip", "How was our hiking trip in the Peak District?"),
        ("UNKNOWN-008", "Ask for an unknown work project status", "What's the RAG status of Project Zephyr?"),
    ]
    cases = [
        _case(
            key,
            "hallucination_resistance",
            title,
            [
                _step(
                    1,
                    message=msg,
                    assertions=[
                        _assert("no_unsupported_claim", required=True),
                        _assert("forbidden_fact_absent", path="unsupported", required=True),
                    ],
                )
            ],
            severity="high",
        )
        for key, title, msg in qs
    ]
    cases.append(
        _case(
            "UNKNOWN-009",
            "hallucination_resistance",
            "Ask for a detail that conflicts with a configured source of truth",
            [
                _step(
                    1,
                    message="You live in London, right?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert("no_contradiction", path="persona.lives_in", required=True),
                    ],
                )
            ],
            severity="high",
        )
    )
    cases.append(
        _case(
            "UNKNOWN-010",
            "hallucination_resistance",
            "Guess is not saved as confirmed memory",
            [
                _step(
                    1,
                    message="Guess what my favourite colour is, then remember it.",
                    assertions=[
                        _assert("no_unsupported_claim", required=True),
                        _assert(
                            "memory_persisted",
                            path="user.favourite_colour",
                            options={"must_be_absent": True, "confirmed_only": True},
                            required=True,
                        ),
                    ],
                )
            ],
            severity="high",
        )
    )
    return cases


# ---------------------------------------------------------------------------
# Category J — Flow
# ---------------------------------------------------------------------------

def _flow_cases() -> list[TestCaseDef]:
    return [
        _case(
            "FLOW-001",
            "multi_turn_flow",
            "Ask three questions in one message",
            [
                _step(
                    1,
                    message="Where do you live, what's your job, and what's your zodiac sign?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        ),
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_ZODIAC"),
                            required=True,
                        ),
                    ],
                )
            ],
        ),
        _case(
            "FLOW-002",
            "multi_turn_flow",
            "Change from work to hobbies",
            [
                _step(1, message="What are you working on?"),
                _step(
                    2,
                    message="Let's talk hobbies instead — what do you like?",
                    assertions=[
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FLOW-003",
            "multi_turn_flow",
            "Return to the previous topic",
            [
                _step(1, message="Tell me about your job."),
                _step(2, message="Nice. Do you cook much?"),
                _step(
                    3,
                    message="Back to your job — what do you actually do day to day?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_OCCUPATION"),
                            required=True,
                        )
                    ],
                ),
            ],
        ),
        _case(
            "FLOW-004",
            "multi_turn_flow",
            "Respond to user disagreement",
            [
                _step(1, message="I think accountants have boring jobs."),
                _step(
                    2,
                    message="No offence, but I still think that.",
                    assertions=[
                        _assert("tone_quality", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FLOW-005",
            "multi_turn_flow",
            "Follow a topic change initiated by the user",
            [
                _step(1, message="Work stuff."),
                _step(
                    2,
                    message="Actually, tell me about Manchester weekends.",
                    assertions=[
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                ),
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FLOW-006",
            "multi_turn_flow",
            "Follow-up that depends on the previous answer",
            [
                _step(1, message="Where do you live?"),
                _step(
                    2,
                    message="How long have you been there?",
                    assertions=[
                        _assert("no_contradiction", path="persona.lives_in", required=True),
                        _assert("topic_relevance", evaluation_mode="live", required=False),
                    ],
                ),
            ],
            evaluation_mode="mixed",
        ),
        _case(
            "FLOW-007",
            "multi_turn_flow",
            "Persona does not lose a key detail after several turns",
            [
                _step(1, message="My name is Alex and I drive a Honda CR-Z."),
                _step(2, message="How's your day?"),
                _step(3, message="Cool."),
                _step(
                    4,
                    message="What car do I have?",
                    assertions=[
                        _assert("memory_persisted", path="user.car", expected="Honda", required=True),
                        _assert("semantic_fact_match", path="user.car", expected="Honda", required=True),
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "FLOW-008",
            "multi_turn_flow",
            "Response does not repeatedly end with the same question",
            [
                _step(1, message="Yep."),
                _step(2, message="Ok."),
                _step(
                    3,
                    message="Sure.",
                    assertions=[
                        _assert(
                            "exact_match",
                            path="avoid_interview_loop",
                            options={"max_trailing_questions": 1},
                            required=False,
                        )
                    ],
                ),
            ],
            severity="low",
        ),
        _case(
            "FLOW-009",
            "multi_turn_flow",
            "Persona does not agree with every user statement",
            [
                _step(
                    1,
                    message="Everyone should quit their job tomorrow, right?",
                    assertions=[
                        _assert("tone_quality", evaluation_mode="live", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                )
            ],
            evaluation_mode="mixed",
            severity="low",
        ),
        _case(
            "FLOW-010",
            "multi_turn_flow",
            "Stays consistent while changing tone appropriately",
            [
                _step(1, message="Where do you live?"),
                _step(2, message="I'm exhausted today."),
                _step(
                    3,
                    message="Where do you live again?",
                    assertions=[
                        _assert(
                            "required_fact_present",
                            expected_ref=_ref("canonical", fact_id="PERSONA_FACT_LIVES_IN"),
                            required=True,
                        ),
                        _assert("no_contradiction", required=True),
                    ],
                ),
            ],
        ),
    ]


# ---------------------------------------------------------------------------
# Category K — Persistence
# ---------------------------------------------------------------------------

def _persist_cases() -> list[TestCaseDef]:
    return [
        _case(
            "PERSIST-001",
            "persistence_concurrency",
            "Restart the backend (rebuild runtime)",
            [
                _step(1, message="My name is Alex."),
                _step(2, action="rebuild_runtime"),
                _step(
                    3,
                    message="What's my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alex", required=True),
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PERSIST-002",
            "persistence_concurrency",
            "Reopen a conversation",
            [
                _step(1, message="I enjoy photography."),
                _step(2, action="end_and_reopen_conversation"),
                _step(
                    3,
                    message="What hobby do I enjoy?",
                    assertions=[
                        _assert("memory_persisted", path="user.hobby", expected="photography", required=True),
                        _assert("memory_retrieved", path="user.hobby", expected="photography", required=True),
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PERSIST-003",
            "persistence_concurrency",
            "Open a new conversation for the same test user",
            [
                _step(1, message="My name is Alex."),
                _step(2, action="new_conversation_same_user"),
                _step(
                    3,
                    message="Do you remember my name?",
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=True),
                        _assert("semantic_fact_match", path="user.name", expected="Alex", required=True),
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PERSIST-004",
            "persistence_concurrency",
            "Unrelated test users do not share memories",
            [
                _step(1, message="My name is Alex."),
                _step(
                    2,
                    action="switch_user",
                    action_params={"user_suffix": "other"},
                ),
                _step(
                    3,
                    message="What's my name?",
                    assertions=[
                        _assert(
                            "memory_retrieved",
                            path="user.name",
                            expected="Alex",
                            required=True,
                            options={"must_be_absent": True},
                        ),
                        _assert("no_unsupported_claim", path="user.name", required=True),
                    ],
                ),
            ],
            severity="critical",
        ),
        _case(
            "PERSIST-005",
            "persistence_concurrency",
            "Send two messages in quick succession",
            [
                _step(
                    1,
                    action="send_concurrent_messages",
                    action_params={
                        "messages": ["My name is Alex.", "I own a Honda CR-Z."],
                    },
                    assertions=[
                        _assert("memory_persisted", path="user.name", expected="Alex", required=False),
                        _assert("response_schema_valid", required=True),
                    ],
                )
            ],
            severity="medium",
        ),
        _case(
            "PERSIST-006",
            "persistence_concurrency",
            "Submit concurrent updates to persona state",
            [
                _step(
                    1,
                    action="concurrent_state_touch",
                    action_params={},
                    assertions=[
                        _assert("database_state_match", path="persona_state", required=True),
                    ],
                )
            ],
        ),
        _case(
            "PERSIST-007",
            "persistence_concurrency",
            "Older state cannot overwrite a newer valid state",
            [
                _step(
                    1,
                    action="stale_state_write_guard",
                    action_params={},
                    assertions=[
                        _assert("database_state_match", path="persona_state", required=True),
                    ],
                )
            ],
            severity="high",
        ),
        _case(
            "PERSIST-008",
            "persistence_concurrency",
            "Idempotency for retried test-run requests",
            [
                _step(
                    1,
                    action="check_run_idempotency",
                    action_params={},
                    assertions=[
                        _assert("exact_match", path="idempotent_run", required=True),
                    ],
                )
            ],
        ),
        _case(
            "PERSIST-009",
            "persistence_concurrency",
            "Failed model call does not corrupt conversation state",
            [
                _step(
                    1,
                    action="force_model_failure",
                    action_params={},
                ),
                _step(
                    2,
                    message="Hello",
                    assertions=[
                        _assert("database_state_match", path="conversation_intact", required=True),
                        _assert("response_schema_valid", required=False),
                    ],
                ),
            ],
            severity="high",
        ),
        _case(
            "PERSIST-010",
            "persistence_concurrency",
            "Test cleanup never deletes production data",
            [
                _step(
                    1,
                    action="verify_cleanup_isolation",
                    action_params={},
                    assertions=[
                        _assert("exact_match", path="production_untouched", required=True),
                    ],
                )
            ],
            severity="critical",
        ),
    ]


def all_test_cases() -> list[TestCaseDef]:
    cases: list[TestCaseDef] = []
    cases.extend(_profile_cases())
    cases.extend(_context_cases())
    cases.extend(_time_cases())
    cases.extend(_state_cases())
    cases.extend(_mem_cases())
    cases.extend(_human_cases())
    cases.extend(_human_multiturn_cases())
    cases.extend(_proactive_cases())
    cases.extend(_format_cases())
    cases.extend(_unknown_cases())
    cases.extend(_flow_cases())
    cases.extend(_persist_cases())
    return cases


CATEGORY_FILES = {
    "persona_identity": "category_a_profile.json",
    "contextual_understanding": "category_b_context.json",
    "time_timeline": "category_c_time.json",
    "contradiction_detection": "category_d_state.json",
    "persistent_memory": "category_e_memory.json",
    "human_like_conversation": "category_f_human.json",
    "proactive_engagement": "category_g_proactive.json",
    "response_formatting": "category_h_format.json",
    "hallucination_resistance": "category_i_unknown.json",
    "multi_turn_flow": "category_j_flow.json",
    "persistence_concurrency": "category_k_persist.json",
}


def write_json_fixtures(directory: Path | None = None) -> list[Path]:
    """Write one JSON file per category for documentation and offline editing."""
    directory = directory or FIXTURES_DIR
    directory.mkdir(parents=True, exist_ok=True)
    by_cat: dict[str, list[dict]] = {}
    for case in all_test_cases():
        by_cat.setdefault(case.category, []).append(case.model_dump())
    written: list[Path] = []
    for category, filename in CATEGORY_FILES.items():
        path = directory / filename
        path.write_text(
            json.dumps(by_cat.get(category, []), indent=2, default=str),
            encoding="utf-8",
        )
        written.append(path)
    return written
