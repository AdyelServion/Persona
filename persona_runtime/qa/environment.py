"""Isolated QA environment: clone persona, controllable clock, safe cleanup."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.config import Settings, get_settings
from persona_runtime.db import COLLECTION_NAMES, MEMORY_COLLECTIONS, ensure_indexes
from persona_runtime.db.time_utils import set_clock, utcnow
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.life.simulator import LifeSimulator
from persona_runtime.logging_utils import get_logger
from persona_runtime.persona.loader import PersonaIngestionService
from persona_runtime.persona.repositories import PersonaRepository
from persona_runtime.qa.safety import (
    QA_PERSONA_PREFIX,
    QA_USER_PREFIX,
    PROTECTED_PERSONA_IDS,
    PROTECTED_USER_IDS,
    assert_cleanup_filter,
    assert_qa_persona_id,
    assert_qa_user_id,
    assert_safe_database,
)
from persona_runtime.state.repositories import PersonaStateRepository

logger = get_logger(__name__)


class QAEnvironment:
    """Per-run isolated persona/user with injectable clock."""

    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        llm: Any = None,
        source_persona_id: str | None = None,
        run_suffix: str | None = None,
        qa_db_name: str | None = None,
    ):
        assert_safe_database(db, qa_db_name=qa_db_name)
        self.db = db
        self.settings = settings or get_settings()
        self.llm = llm
        self.qa_db_name = qa_db_name
        self.run_suffix = run_suffix or uuid4().hex[:10]
        self.source_persona_id = source_persona_id or self.settings.default_persona_id
        self.persona_id = f"{QA_PERSONA_PREFIX}{self.run_suffix}"
        self.user_id = f"{QA_USER_PREFIX}{self.run_suffix}"
        assert_qa_persona_id(self.persona_id)
        assert_qa_user_id(self.user_id)
        self.conversation_id: str | None = None
        self.runtime: PersonaRuntime | None = None
        self._clock_fn: Callable[[], datetime] | None = None
        self._frozen: datetime | None = None
        self.production_snapshot: dict[str, int] = {}

    def snapshot_production_counts(self) -> dict[str, int]:
        """Counts for protected ids — used by PERSIST-010."""
        snap: dict[str, int] = {}
        for pid in PROTECTED_PERSONA_IDS:
            snap[f"identity:{pid}"] = self.db[COLLECTION_NAMES["identity"]].count_documents(
                {"persona_id": pid}
            )
            snap[f"state:{pid}"] = self.db[COLLECTION_NAMES["persona_state"]].count_documents(
                {"persona_id": pid}
            )
        for uid in PROTECTED_USER_IDS:
            snap[f"conversations:{uid}"] = self.db[COLLECTION_NAMES["conversations"]].count_documents(
                {"user_id": uid}
            )
            for mem_name in MEMORY_COLLECTIONS.values():
                snap[f"{mem_name}:{uid}"] = self.db[mem_name].count_documents({"user_id": uid})
        self.production_snapshot = snap
        return snap

    def ensure_source_persona(self, root_dir) -> None:
        """Ingest default persona markdown if source identity is missing."""
        repo = PersonaRepository(self.db)
        try:
            repo.get_root(self.source_persona_id)
        except Exception:  # noqa: BLE001
            PersonaIngestionService(self.db).ingest(root_dir)

    def setup(self, *, clone_from_source: bool = True) -> PersonaRuntime:
        ensure_indexes(self.db)
        self.snapshot_production_counts()
        if clone_from_source:
            self._clone_identity()
        else:
            # Minimal: ingest already happened into source; still require clone for isolation
            self._clone_identity()
        state_repo = PersonaStateRepository(self.db)
        state_repo.ensure_default_state(self.persona_id, tz_name=self.settings.timezone)
        LifeSimulator(state_repo, tz_name=self.settings.timezone).ensure_life_state(
            self.persona_id
        )
        self.runtime = PersonaRuntime(settings=self.settings, llm=self.llm, db=self.db)
        conv = self.runtime.conversation_repo.get_or_create(self.persona_id, self.user_id)
        self.conversation_id = conv["conversation_id"]
        return self.runtime

    def _clone_identity(self) -> None:
        identity = self.db[COLLECTION_NAMES["identity"]]
        source_docs = list(identity.find({"persona_id": self.source_persona_id}))
        if not source_docs:
            raise RuntimeError(
                f"Source persona {self.source_persona_id} not found; ingest before QA clone."
            )
        # Remove any previous qa clone with same id
        identity.delete_many({"persona_id": self.persona_id})
        for doc in source_docs:
            cloned = copy.deepcopy(doc)
            cloned.pop("_id", None)
            cloned["persona_id"] = self.persona_id
            cloned["qa_cloned_from"] = self.source_persona_id
            identity.insert_one(cloned)

        # Clone persona-scoped memories (autobiographical / life_event)
        for key in ("autobiographical", "life_event"):
            col = self.db[COLLECTION_NAMES[key]]
            col.delete_many({"persona_id": self.persona_id})
            for doc in col.find({"persona_id": self.source_persona_id}):
                cloned = copy.deepcopy(doc)
                cloned.pop("_id", None)
                cloned["persona_id"] = self.persona_id
                if cloned.get("memory_id"):
                    cloned["memory_id"] = str(uuid4())
                col.insert_one(cloned)

        # Fresh state/timeline for qa persona (do not copy live timeline)
        self.db[COLLECTION_NAMES["persona_state"]].delete_many({"persona_id": self.persona_id})
        self.db[COLLECTION_NAMES["timeline_events"]].delete_many({"persona_id": self.persona_id})

    def rebuild_runtime(self) -> PersonaRuntime:
        """Simulate backend restart: new PersonaRuntime on same DB."""
        self.runtime = PersonaRuntime(settings=self.settings, llm=self.llm, db=self.db)
        return self.runtime

    def set_frozen_clock(self, when: datetime) -> None:
        when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        self._frozen = when.astimezone(timezone.utc)

        def _clock() -> datetime:
            assert self._frozen is not None
            return self._frozen

        self._clock_fn = _clock
        set_clock(_clock)

    def advance_clock(self, *, hours: float = 0, minutes: float = 0, seconds: float = 0) -> datetime:
        if self._frozen is None:
            self._frozen = utcnow()
        self._frozen = self._frozen + timedelta(hours=hours, minutes=minutes, seconds=seconds)
        self.set_frozen_clock(self._frozen)
        if self.runtime:
            LifeSimulator(
                self.runtime.state_repo, tz_name=self.settings.timezone
            ).ensure_life_state(self.persona_id)
        return self._frozen

    def clear_clock(self) -> None:
        set_clock(None)
        self._clock_fn = None
        self._frozen = None

    def end_conversation(self) -> str:
        """Mark current conversation inactive so get_or_create opens a new one."""
        assert self.runtime and self.conversation_id
        self.db[COLLECTION_NAMES["conversations"]].update_one(
            {"conversation_id": self.conversation_id},
            {"$set": {"status": "closed", "updated_at": utcnow()}},
        )
        conv = self.runtime.conversation_repo.get_or_create(self.persona_id, self.user_id)
        self.conversation_id = conv["conversation_id"]
        return self.conversation_id

    def new_conversation_same_user(self) -> str:
        return self.end_conversation()

    def switch_user(self, suffix: str = "other") -> str:
        self.user_id = f"{QA_USER_PREFIX}{self.run_suffix}-{suffix}"
        assert_qa_user_id(self.user_id)
        assert self.runtime
        conv = self.runtime.conversation_repo.get_or_create(self.persona_id, self.user_id)
        self.conversation_id = conv["conversation_id"]
        return self.user_id

    def correct_canonical_fact(self, fact_id: str, object_value: str) -> None:
        """Fixture-only correction on the qa clone."""
        identity = self.db[COLLECTION_NAMES["identity"]]
        identity.update_one(
            {
                "persona_id": self.persona_id,
                "doc_type": "canonical_fact",
                "fact_id": fact_id,
            },
            {"$set": {"object": object_value, "updated_at": utcnow()}},
        )

    def supersede_memories_matching(self, *, match: str) -> int:
        count = 0
        for mem_name in MEMORY_COLLECTIONS.values():
            col = self.db[mem_name]
            for doc in col.find(
                {
                    "persona_id": self.persona_id,
                    "user_id": self.user_id,
                    "status": "active",
                }
            ):
                blob = " ".join(
                    str(doc.get(k) or "")
                    for k in ("fact", "event_description", "object", "subject", "predicate")
                )
                if match.lower() in blob.lower():
                    col.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"status": "superseded", "updated_at": utcnow()}},
                    )
                    count += 1
        return count

    def set_persona_availability(self, *, sleeping: bool = False, availability: float = 0.5) -> None:
        col = self.db[COLLECTION_NAMES["persona_state"]]
        col.update_one(
            {"persona_id": self.persona_id},
            {
                "$set": {
                    "current_state.sleeping": sleeping,
                    "current_state.availability": availability,
                    "updated_at": utcnow(),
                }
            },
        )

    def patch_conversation_context(self, updates: dict[str, Any]) -> None:
        if not self.conversation_id:
            return
        self.db[COLLECTION_NAMES["conversation_contexts"]].update_one(
            {"conversation_id": self.conversation_id},
            {"$set": {**updates, "updated_at": utcnow()}},
            upsert=False,
        )

    def cleanup(self) -> dict[str, int]:
        """Delete only qa-prefixed data for this environment."""
        assert_qa_persona_id(self.persona_id)
        assert_qa_user_id(self.user_id)
        deleted: dict[str, int] = {}

        def _del(col_name: str, filt: dict[str, Any]) -> None:
            assert_cleanup_filter(filt)
            res = self.db[col_name].delete_many(filt)
            deleted[col_name] = deleted.get(col_name, 0) + res.deleted_count

        convs = list(
            self.db[COLLECTION_NAMES["conversations"]].find(
                {"persona_id": self.persona_id},
                {"conversation_id": 1},
            )
        )
        msgs = self.db[COLLECTION_NAMES["messages"]]
        for c in convs:
            cid = c.get("conversation_id")
            if cid:
                res = msgs.delete_many({"conversation_id": cid})
                deleted["ConversationMessages"] = (
                    deleted.get("ConversationMessages", 0) + res.deleted_count
                )

        _del(COLLECTION_NAMES["identity"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["persona_state"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["timeline_events"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["relationships"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["conversations"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["conversation_contexts"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["response_jobs"], {"persona_id": self.persona_id})
        _del(COLLECTION_NAMES["events"], {"persona_id": self.persona_id})

        for mem_name in MEMORY_COLLECTIONS.values():
            _del(mem_name, {"persona_id": self.persona_id})

        self.clear_clock()
        return deleted

    def production_untouched(self) -> bool:
        current = {}
        for pid in PROTECTED_PERSONA_IDS:
            current[f"identity:{pid}"] = self.db[COLLECTION_NAMES["identity"]].count_documents(
                {"persona_id": pid}
            )
            current[f"state:{pid}"] = self.db[COLLECTION_NAMES["persona_state"]].count_documents(
                {"persona_id": pid}
            )
        for uid in PROTECTED_USER_IDS:
            current[f"conversations:{uid}"] = self.db[COLLECTION_NAMES["conversations"]].count_documents(
                {"user_id": uid}
            )
            for mem_name in MEMORY_COLLECTIONS.values():
                current[f"{mem_name}:{uid}"] = self.db[mem_name].count_documents({"user_id": uid})
        return current == self.production_snapshot
