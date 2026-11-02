"""MULTIUSER / EXTROVERT / OUTBOUND QA suites run end-to-end (mongomock, fake LLM)."""

from __future__ import annotations

import pytest

from persona_runtime.llm.client import LLMClient
from persona_runtime.qa.fake_llm import DeterministicQALLM
from persona_runtime.qa.repository import QARepository
from persona_runtime.qa.runner import run_suite
from persona_runtime.qa.safety import QASafetyError, assert_qa_app_user
from persona_runtime.qa.seed import seed_suite


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


@pytest.mark.parametrize(
    "category",
    ["multi_user_isolation", "extrovert_engagement", "proactive_outbound"],
)
def test_new_qa_suites_pass(seeded_db, qa_llm, category):
    run = run_suite(seeded_db, llm=qa_llm, category=category, seed_if_missing=False)
    assert run["status"] == "completed"
    results = QARepository(seeded_db).list_results(run["run_id"])
    assert results
    failures = {}
    for r in results:
        if r["status"] == "passed":
            continue
        bad = [
            (a.get("type"), a.get("explanation"), a.get("actual"))
            for a in r.get("assertion_results") or []
            if a.get("status") in {"fail", "blocked"} and a.get("evaluation_method") != "llm"
        ]
        if bad or r["status"] == "failed":
            failures[r["test_key"]] = bad or r["status"]
    assert not failures, failures


def test_qa_refuses_non_qa_app_users():
    with pytest.raises(QASafetyError):
        assert_qa_app_user({"user_id": "u_real_person"})
    with pytest.raises(QASafetyError):
        assert_qa_app_user(None)
    assert_qa_app_user({"user_id": "qa-abc-john"})
