"""MongoDB client singleton and index bootstrap."""

from __future__ import annotations

from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from persona_runtime.config import Settings, get_settings
from persona_runtime.exceptions import DatabaseError
from persona_runtime.logging_utils import get_logger

logger = get_logger(__name__)

_client: MongoClient | None = None


COLLECTION_NAMES = {
    "identity": "Identity",
    "persona_state": "PersonaState",
    "relationships": "Relationships",
    "episodic": "EpisodicMemories",
    "semantic": "SemanticMemories",
    "emotional": "EmotionalMemories",
    "relationship_memory": "RelationshipMemories",
    "procedural": "ProceduralMemories",
    "working": "WorkingMemories",
    "autobiographical": "AutobiographicalMemories",
    "life_event": "LifeEventMemories",
    "conversations": "Conversations",
    "messages": "ConversationMessages",
    "conversation_contexts": "ConversationContexts",
    "prompts": "Prompts",
    "events": "Events",
    "response_jobs": "ResponseJobs",
    "timeline_events": "TimelineEvents",
    # Persona consistency QA (isolated from production collections)
    "persona_test_suites": "PersonaTestSuites",
    "persona_test_cases": "PersonaTestCases",
    "persona_test_steps": "PersonaTestSteps",
    "persona_test_runs": "PersonaTestRuns",
    "persona_test_results": "PersonaTestResults",
    "persona_test_step_results": "PersonaTestStepResults",
    "persona_test_issues": "PersonaTestIssues",
}

MEMORY_COLLECTIONS = {
    "episodic": COLLECTION_NAMES["episodic"],
    "semantic": COLLECTION_NAMES["semantic"],
    "emotional": COLLECTION_NAMES["emotional"],
    "relationship": COLLECTION_NAMES["relationship_memory"],
    "procedural": COLLECTION_NAMES["procedural"],
    "working": COLLECTION_NAMES["working"],
    "autobiographical": COLLECTION_NAMES["autobiographical"],
    "life_event": COLLECTION_NAMES["life_event"],
}


def get_client(settings: Settings | None = None) -> MongoClient:
    global _client
    if _client is not None:
        return _client
    settings = settings or get_settings()
    try:
        _client = MongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
        )
        _client.admin.command("ping")
    except Exception as exc:  # noqa: BLE001
        _client = None
        raise DatabaseError(f"MongoDB connection failed: {exc}") from exc
    return _client


def get_db(settings: Settings | None = None) -> Database:
    settings = settings or get_settings()
    return get_client(settings)[settings.db_name]


def get_collection(name: str, settings: Settings | None = None) -> Collection:
    key = name if name in COLLECTION_NAMES else None
    collection_name = COLLECTION_NAMES[key] if key else name
    return get_db(settings)[collection_name]


def reset_client() -> None:
    global _client
    if _client is not None:
        _client.close()
    _client = None


def ensure_indexes(db: Database | None = None) -> None:
    if db is None:
        db = get_db()
    identity = db[COLLECTION_NAMES["identity"]]
    identity.create_index(
        [
            ("persona_id", ASCENDING),
            ("doc_type", ASCENDING),
            ("category", ASCENDING),
            ("subcategory_key", ASCENDING),
        ],
        unique=True,
        name="identity_unique_subcategory",
    )
    identity.create_index([("persona_id", ASCENDING), ("doc_type", ASCENDING)])

    state = db[COLLECTION_NAMES["persona_state"]]
    state.create_index([("persona_id", ASCENDING)], unique=True)

    timeline = db[COLLECTION_NAMES["timeline_events"]]
    timeline.create_index([("event_id", ASCENDING)], unique=True)
    timeline.create_index(
        [("persona_id", ASCENDING), ("scheduled_start", ASCENDING)],
        name="timeline_persona_start",
    )
    timeline.create_index(
        [("persona_id", ASCENDING), ("local_date", ASCENDING), ("status", ASCENDING)],
        name="timeline_persona_date_status",
    )
    timeline.create_index(
        [("persona_id", ASCENDING), ("status", ASCENDING)],
        name="timeline_persona_status",
    )

    relationships = db[COLLECTION_NAMES["relationships"]]
    relationships.create_index(
        [("persona_id", ASCENDING), ("other_person_id", ASCENDING)],
        unique=True,
    )

    conversations = db[COLLECTION_NAMES["conversations"]]
    conversations.create_index(
        [("persona_id", ASCENDING), ("user_id", ASCENDING), ("status", ASCENDING)]
    )
    conversations.create_index([("conversation_id", ASCENDING)], unique=True)

    messages = db[COLLECTION_NAMES["messages"]]
    messages.create_index([("conversation_id", ASCENDING), ("timestamp", ASCENDING)])
    messages.create_index([("conversation_id", ASCENDING), ("sequence", ASCENDING)])
    messages.create_index([("conversation_id", ASCENDING), ("status", ASCENDING)])
    messages.create_index([("message_id", ASCENDING)], unique=True)

    response_jobs = db[COLLECTION_NAMES["response_jobs"]]
    response_jobs.create_index([("job_id", ASCENDING)], unique=True)
    response_jobs.create_index([("status", ASCENDING), ("scheduled_for", ASCENDING)])
    response_jobs.create_index([("persona_id", ASCENDING), ("conversation_id", ASCENDING)])
    try:
        response_jobs.create_index(
            [("conversation_id", ASCENDING)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["scheduled", "running"]}},
            name="one_open_job_per_conversation",
        )
    except Exception:  # noqa: BLE001
        # mongomock / older servers may not support partial unique indexes
        response_jobs.create_index([("conversation_id", ASCENDING), ("status", ASCENDING)])

    conversation_contexts = db[COLLECTION_NAMES["conversation_contexts"]]
    conversation_contexts.create_index([("conversation_id", ASCENDING)], unique=True)
    conversation_contexts.create_index(
        [("persona_id", ASCENDING), ("user_id", ASCENDING)]
    )

    prompts = db[COLLECTION_NAMES["prompts"]]
    prompts.create_index([("name", ASCENDING), ("version", ASCENDING)], unique=True)
    prompts.create_index([("name", ASCENDING), ("active", ASCENDING)])

    events = db[COLLECTION_NAMES["events"]]
    events.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    events.create_index([("event_type", ASCENDING)])

    for mem_name in MEMORY_COLLECTIONS.values():
        col = db[mem_name]
        col.create_index([("persona_id", ASCENDING), ("status", ASCENDING)])
        col.create_index([("memory_id", ASCENDING)], unique=True)
        col.create_index([("user_id", ASCENDING), ("status", ASCENDING)])
        col.create_index([("conversation_id", ASCENDING)])
        col.create_index([("created_at", ASCENDING)])
        col.create_index([("importance", ASCENDING)])

    semantic = db[COLLECTION_NAMES["semantic"]]
    semantic.create_index(
        [
            ("persona_id", ASCENDING),
            ("scope", ASCENDING),
            ("subject", ASCENDING),
            ("predicate", ASCENDING),
            ("status", ASCENDING),
        ]
    )

    rel_mem = db[COLLECTION_NAMES["relationship_memory"]]
    rel_mem.create_index([("other_person_id", ASCENDING), ("status", ASCENDING)])

    # QA suite indexes
    suites = db[COLLECTION_NAMES["persona_test_suites"]]
    suites.create_index([("name", ASCENDING), ("version", ASCENDING)], unique=True)
    suites.create_index([("suite_id", ASCENDING)], unique=True)

    cases = db[COLLECTION_NAMES["persona_test_cases"]]
    cases.create_index([("test_key", ASCENDING)], unique=True)
    cases.create_index([("suite_id", ASCENDING), ("category", ASCENDING)])
    cases.create_index([("case_id", ASCENDING)], unique=True)
    cases.create_index([("is_active", ASCENDING)])

    steps = db[COLLECTION_NAMES["persona_test_steps"]]
    steps.create_index(
        [("test_case_id", ASCENDING), ("step_order", ASCENDING)],
        unique=True,
    )
    steps.create_index([("step_id", ASCENDING)], unique=True)

    runs = db[COLLECTION_NAMES["persona_test_runs"]]
    runs.create_index([("run_id", ASCENDING)], unique=True)
    runs.create_index([("status", ASCENDING), ("started_at", ASCENDING)])
    # Non-unique: uniqueness enforced in QARepository.create_run (mongomock
    # struggles with sparse unique indexes when many null keys exist).
    runs.create_index([("idempotency_key", ASCENDING)], name="idempotency_key_lookup")

    results = db[COLLECTION_NAMES["persona_test_results"]]
    results.create_index([("result_id", ASCENDING)], unique=True)
    results.create_index([("test_run_id", ASCENDING), ("test_case_id", ASCENDING)])
    results.create_index([("test_run_id", ASCENDING), ("status", ASCENDING)])

    step_results = db[COLLECTION_NAMES["persona_test_step_results"]]
    step_results.create_index([("step_result_id", ASCENDING)], unique=True)
    step_results.create_index([("test_result_id", ASCENDING), ("step_id", ASCENDING)])

    issues = db[COLLECTION_NAMES["persona_test_issues"]]
    issues.create_index([("issue_id", ASCENDING)], unique=True)
    issues.create_index([("test_run_id", ASCENDING), ("severity", ASCENDING)])
    issues.create_index([("test_run_id", ASCENDING), ("test_case_id", ASCENDING)])

    logger.info("MongoDB indexes ensured for database=%s", db.name)


def set_client_for_tests(client: Any) -> None:
    """Allow tests to inject mongomock."""
    global _client
    _client = client
