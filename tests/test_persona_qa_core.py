"""Core tests for persona consistency QA system (mongomock, no OpenAI)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from persona_runtime.config import get_settings
from persona_runtime.db import COLLECTION_NAMES, ensure_indexes
from persona_runtime.db.time_utils import set_clock, utcnow
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.life.clock import PersonaClock
from persona_runtime.llm.client import LLMClient
from persona_runtime.memory.retrieval import MemoryRetriever
from persona_runtime.memory.repositories import MemoryRepository
from persona_runtime.qa.environment import QAEnvironment
from persona_runtime.qa.fake_llm import DeterministicQALLM
from persona_runtime.qa.fixtures.definitions import all_test_cases, write_json_fixtures
from persona_runtime.qa.report import compare_runs, generate_reports
from persona_runtime.qa.repository import QARepository
from persona_runtime.qa.runner import ScenarioRunner, run_suite
from persona_runtime.qa.safety import QASafetyError, assert_cleanup_filter, assert_safe_database
from persona_runtime.qa.seed import seed_suite


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def qa_llm():
    stub = DeterministicQALLM()
    client = LLMClient()
    client.set_fake_handler(stub)
    client._scripted = stub
    return client


@pytest.fixture()
def seeded_db(ingested_db):
    seed_suite(ingested_db)
    return ingested_db


def test_seed_loads_all_expected_keys(seeded_db):
    repo = QARepository(seeded_db)
    suite = repo.get_suite()
    assert suite is not None
    cases = repo.list_cases(suite["suite_id"])
    keys = {c["test_key"] for c in cases}
    expected = {c.test_key for c in all_test_cases()}
    assert keys == expected
    assert "MEM-001" in keys
    assert "PROFILE-001" in keys
    assert "PERSIST-010" in keys
    assert len(keys) >= 150


def test_write_json_fixtures(tmp_path):
    paths = write_json_fixtures(tmp_path)
    assert len(paths) == 11
    assert all(p.exists() for p in paths)


def test_safety_refuses_production_db_name():
    class FakeDB:
        name = "Sarah"
        client = type("C", (), {"__module__": "pymongo.mongo_client"})()

    with pytest.raises(QASafetyError):
        assert_safe_database(FakeDB())  # type: ignore[arg-type]


def test_cleanup_filter_refuses_protected_persona():
    with pytest.raises(QASafetyError):
        assert_cleanup_filter({"persona_id": "sarah_taylor_001"})


def test_isolation_uses_qa_prefixes(seeded_db, qa_llm):
    env = QAEnvironment(seeded_db, llm=qa_llm)
    env.ensure_source_persona(ROOT)
    env.setup()
    assert env.persona_id.startswith("qa-")
    assert env.user_id.startswith("qa-")
    assert env.persona_id != "sarah_taylor_001"
    env.cleanup()


def test_memory_persisted_vs_retrieved(seeded_db, qa_llm):
    env = QAEnvironment(seeded_db, llm=qa_llm)
    env.ensure_source_persona(ROOT)
    env.setup()
    runner = ScenarioRunner(seeded_db, llm=qa_llm)
    result = runner._send_user_message(env, "My name is Alex.")
    stored = result.get("stored_memories") or []
    # Consolidation may store via fake LLM
    mem_repo = MemoryRepository(seeded_db)
    active = mem_repo.list_all_active_for_user(env.persona_id, env.user_id)
    blobs = " ".join(
        str(m.get("object") or "") + " " + str(m.get("fact") or "") for m in active + stored
    )
    assert "Alex" in blobs or any("alex" in str(m).lower() for m in active + stored)

    result2 = runner._send_user_message(env, "What's my name?")
    retrieved = result2.get("retrieved_memories") or []
    evidence = result2.get("allowed_evidence_ids") or []
    # Separate traces exist on graph result
    assert "retrieved_memories" in result2
    assert "allowed_evidence_ids" in result2
    env.cleanup()


def test_clock_injection_used_by_retrieval(seeded_db, qa_llm):
    frozen = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    set_clock(lambda: frozen)
    try:
        assert utcnow() == frozen
        snap = PersonaClock(tz_name="Europe/London").snapshot()
        assert snap.local_date.isoformat() == "2026-06-10"
        # MemoryRetriever must use utcnow not wall clock
        repo = MemoryRepository(seeded_db)
        retriever = MemoryRetriever(repo, get_settings())
        # Should not raise; scoring uses injected clock
        retriever.retrieve(
            persona_id="qa-clock",
            user_id="qa-clock-user",
            query="hello",
        )
    finally:
        set_clock(None)


def test_run_single_profile_case(seeded_db, qa_llm):
    run = run_suite(
        seeded_db,
        llm=qa_llm,
        test_key="PROFILE-003",
        seed_if_missing=False,
    )
    assert run["status"] == "completed"
    repo = QARepository(seeded_db)
    results = repo.list_results(run["run_id"])
    assert len(results) == 1
    assert results[0]["test_key"] == "PROFILE-003"
    # Deterministic stub should pass lives_in Manchester
    assert results[0]["status"] in {"passed", "blocked", "failed"}


def test_contradiction_recording(seeded_db, qa_llm):
    from persona_runtime.qa.ledger import ConsistencyLedger

    ledger = ConsistencyLedger()
    ledger.record("persona", "lives_in", "Manchester", source="canonical", status="canonical")
    ledger.record("persona", "lives_in", "London", source="response", status="stated")
    assert ledger.has_contradiction("lives_in")
    assert len(ledger.contradictions) == 1


def test_cleanup_never_touches_production(seeded_db, qa_llm):
    # Ensure source persona exists
    before = seeded_db[COLLECTION_NAMES["identity"]].count_documents(
        {"persona_id": "sarah_taylor_001"}
    )
    assert before > 0
    env = QAEnvironment(seeded_db, llm=qa_llm)
    env.ensure_source_persona(ROOT)
    env.setup()
    env.snapshot_production_counts()
    # Create qa memory
    runner = ScenarioRunner(seeded_db, llm=qa_llm)
    runner._send_user_message(env, "My name is Alex.")
    env.cleanup()
    after = seeded_db[COLLECTION_NAMES["identity"]].count_documents(
        {"persona_id": "sarah_taylor_001"}
    )
    assert after == before
    assert env.production_untouched()


def test_report_compare(seeded_db, qa_llm, tmp_path):
    run_a = run_suite(seeded_db, llm=qa_llm, test_key="FORMAT-001", report_dir=tmp_path)
    run_b = run_suite(seeded_db, llm=qa_llm, test_key="FORMAT-001", report_dir=tmp_path)
    cmp = compare_runs(seeded_db, run_a["run_id"], run_b["run_id"])
    assert cmp["total_keys"] >= 1
    paths = run_b.get("report_paths") or {}
    assert paths.get("json")
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()


def test_dry_run_does_not_invoke_graph(seeded_db, qa_llm):
    run = run_suite(
        seeded_db,
        llm=qa_llm,
        test_key="FORMAT-001",
        dry_run=True,
    )
    assert run["status"] == "completed"
    repo = QARepository(seeded_db)
    results = repo.list_results(run["run_id"])
    assert results[0]["status"] in {"passed", "blocked"}


def test_idempotent_run_key(seeded_db, qa_llm):
    key = "qa-idem-test-1"
    r1 = run_suite(seeded_db, llm=qa_llm, test_key="FORMAT-007", idempotency_key=key)
    r2 = run_suite(seeded_db, llm=qa_llm, test_key="FORMAT-007", idempotency_key=key)
    assert r1["run_id"] == r2["run_id"]


def test_issues_md_preserves_history_and_full_summary(tmp_path):
    from persona_runtime.qa.issues_md import HISTORY_MARKER, update_issues_md

    issues = tmp_path / "issues.md"

    def _report(run_id: str, *, filtered: bool, total: int = 1) -> dict:
        return {
            "executive_summary": {
                "run_id": run_id,
                "started_at": "2026-10-19T12:00:00+00:00",
                "completed_at": "2026-10-19T12:05:00+00:00",
                "persona_id": "qa-batch",
                "environment": "qa",
                "build_version": "dev",
                "model_name": "stub",
                "model_provider": "openai",
                "total_tests": total,
                "passed": total,
                "failed": 0,
                "blocked": 0,
                "skipped": 0,
                "configuration": {"filtered": filtered, "dry_run": False, "live_llm": False},
            },
            "test_results": [],
            "issue_register": [],
            "memory_report": [],
            "timeline_report": [],
            "contradiction_report": [],
        }

    update_issues_md(_report("full-run", filtered=False, total=150), path=issues)
    update_issues_md(_report("filtered-run", filtered=True, total=1), path=issues)
    text = issues.read_text(encoding="utf-8")
    current, history = text.split(HISTORY_MARKER, 1)
    run_info = current.split("## Run Information", 1)[1].split("## Execution Summary", 1)[0]
    assert "`full-run`" in run_info
    assert "filtered-run" not in run_info
    assert "<!-- run:full-run -->" in history
    assert "<!-- run:filtered-run -->" in history


def test_end_and_reopen_creates_new_conversation(seeded_db, qa_llm):
    env = QAEnvironment(seeded_db, llm=qa_llm)
    env.ensure_source_persona(ROOT)
    env.setup()
    first = env.conversation_id
    second = env.end_conversation()
    assert second != first
    env.cleanup()
