"""Mongo repositories for QA suites, runs, results, and issues."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import utcnow
from persona_runtime.qa.models import TestCaseDef


class QARepository:
    def __init__(self, db: Database):
        self.db = db
        self.suites = db[COLLECTION_NAMES["persona_test_suites"]]
        self.cases = db[COLLECTION_NAMES["persona_test_cases"]]
        self.steps = db[COLLECTION_NAMES["persona_test_steps"]]
        self.runs = db[COLLECTION_NAMES["persona_test_runs"]]
        self.results = db[COLLECTION_NAMES["persona_test_results"]]
        self.step_results = db[COLLECTION_NAMES["persona_test_step_results"]]
        self.issues = db[COLLECTION_NAMES["persona_test_issues"]]

    def upsert_suite(
        self,
        *,
        name: str,
        description: str,
        version: str,
        is_active: bool = True,
    ) -> dict[str, Any]:
        now = utcnow()
        existing = self.suites.find_one({"name": name, "version": version})
        if existing:
            self.suites.update_one(
                {"_id": existing["_id"]},
                {
                    "$set": {
                        "description": description,
                        "is_active": is_active,
                        "updated_at": now,
                    }
                },
            )
            existing.update({"description": description, "is_active": is_active, "updated_at": now})
            return existing
        doc = {
            "suite_id": str(uuid4()),
            "name": name,
            "description": description,
            "version": version,
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        }
        self.suites.insert_one(doc)
        return doc

    def replace_suite_cases(self, suite_id: str, cases: list[TestCaseDef | dict[str, Any]]) -> int:
        """Replace all cases/steps for a suite with the provided definitions."""
        old_cases = list(self.cases.find({"suite_id": suite_id}, {"case_id": 1}))
        old_ids = [c["case_id"] for c in old_cases]
        if old_ids:
            self.steps.delete_many({"test_case_id": {"$in": old_ids}})
            self.cases.delete_many({"suite_id": suite_id})

        now = utcnow()
        count = 0
        for raw in cases:
            case = TestCaseDef.model_validate(raw) if isinstance(raw, dict) else raw
            case_id = str(uuid4())
            case_doc = {
                "case_id": case_id,
                "suite_id": suite_id,
                "test_key": case.test_key,
                "category": case.category,
                "title": case.title,
                "description": case.description,
                "priority": case.priority,
                "severity": case.severity,
                "preconditions": case.preconditions,
                "setup_actions": case.setup_actions,
                "assertions": [a.model_dump() for a in case.assertions],
                "tags": case.tags,
                "evaluation_mode": case.evaluation_mode,
                "is_active": case.is_active,
                "created_at": now,
                "updated_at": now,
            }
            self.cases.insert_one(case_doc)
            for step in case.steps:
                step_doc = {
                    "step_id": str(uuid4()),
                    "test_case_id": case_id,
                    "step_order": step.order,
                    "step_type": step.step_type if not step.action else "action",
                    "user_message": step.user_message,
                    "action": step.action,
                    "expected_facts": step.expected_facts,
                    "forbidden_facts": step.forbidden_facts,
                    "expected_behavior": step.expected_behavior,
                    "expected_state_changes": step.expected_state_changes,
                    "wait_for_event": step.wait_for_event,
                    "assertions": [a.model_dump() for a in step.assertions],
                    "action_params": step.action_params,
                    "created_at": now,
                }
                self.steps.insert_one(step_doc)
            count += 1
        return count

    def get_suite(self, name: str = "sarah_consistency", version: str = "1") -> dict[str, Any] | None:
        return self.suites.find_one({"name": name, "version": version})

    def list_cases(
        self,
        suite_id: str,
        *,
        category: str | None = None,
        test_key: str | None = None,
        test_keys: list[str] | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        q: dict[str, Any] = {"suite_id": suite_id}
        if active_only:
            q["is_active"] = True
        if category:
            q["category"] = category
        if test_key:
            q["test_key"] = test_key
        if test_keys:
            q["test_key"] = {"$in": test_keys}
        return list(self.cases.find(q).sort([("category", 1), ("test_key", 1)]))

    def list_steps(self, test_case_id: str) -> list[dict[str, Any]]:
        return list(self.steps.find({"test_case_id": test_case_id}).sort("step_order", 1))

    def get_case_by_key(self, test_key: str) -> dict[str, Any] | None:
        return self.cases.find_one({"test_key": test_key})

    def create_run(self, doc: dict[str, Any]) -> dict[str, Any]:
        now = utcnow()
        run = {
            "run_id": doc.get("run_id") or str(uuid4()),
            "suite_id": doc["suite_id"],
            "environment": doc.get("environment", "qa"),
            "persona_id": doc.get("persona_id"),
            "test_user_id": doc.get("test_user_id"),
            "build_version": doc.get("build_version", "dev"),
            "model_provider": doc.get("model_provider", "openai"),
            "model_name": doc.get("model_name"),
            "prompt_version": doc.get("prompt_version"),
            "started_at": now,
            "completed_at": None,
            "status": "running",
            "passed_count": 0,
            "failed_count": 0,
            "blocked_count": 0,
            "skipped_count": 0,
            "duration_ms": 0,
            "configuration": doc.get("configuration") or {},
            "idempotency_key": doc.get("idempotency_key"),
            "previous_run_id": doc.get("previous_run_id"),
            "report_paths": {},
        }
        if run.get("idempotency_key"):
            existing = self.runs.find_one({"idempotency_key": run["idempotency_key"]})
            if existing:
                return existing
        self.runs.insert_one(run)
        return run

    def update_run(self, run_id: str, updates: dict[str, Any]) -> None:
        updates = dict(updates)
        updates["updated_at"] = utcnow()
        self.runs.update_one({"run_id": run_id}, {"$set": updates})

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.find_one({"run_id": run_id})

    def latest_completed_run(self, suite_id: str) -> dict[str, Any] | None:
        return self.runs.find_one(
            {"suite_id": suite_id, "status": "completed"},
            sort=[("started_at", -1)],
        )

    def create_result(self, doc: dict[str, Any]) -> dict[str, Any]:
        result = {
            "result_id": doc.get("result_id") or str(uuid4()),
            "test_run_id": doc["test_run_id"],
            "test_case_id": doc["test_case_id"],
            "test_key": doc.get("test_key"),
            "category": doc.get("category"),
            "status": doc.get("status", "failed"),
            "actual_response": doc.get("actual_response"),
            "actual_state": doc.get("actual_state"),
            "assertion_results": doc.get("assertion_results") or [],
            "failure_summary": doc.get("failure_summary"),
            "severity": doc.get("severity"),
            "duration_ms": doc.get("duration_ms", 0),
            "transcript": doc.get("transcript") or [],
            "created_at": utcnow(),
        }
        self.results.insert_one(result)
        return result

    def create_step_result(self, doc: dict[str, Any]) -> dict[str, Any]:
        step_result = {
            "step_result_id": doc.get("step_result_id") or str(uuid4()),
            "test_result_id": doc["test_result_id"],
            "step_id": doc.get("step_id"),
            "step_order": doc.get("step_order"),
            "conversation_id": doc.get("conversation_id"),
            "message_id": doc.get("message_id"),
            "user_input": doc.get("user_input"),
            "actual_response": doc.get("actual_response"),
            "persona_state_before": doc.get("persona_state_before"),
            "persona_state_after": doc.get("persona_state_after"),
            "retrieved_memory_ids": doc.get("retrieved_memory_ids") or [],
            "stored_memory_ids": doc.get("stored_memory_ids") or [],
            "assertion_results": doc.get("assertion_results") or [],
            "created_at": utcnow(),
        }
        self.step_results.insert_one(step_result)
        return step_result

    def create_issue(self, doc: dict[str, Any]) -> dict[str, Any]:
        issue = {
            "issue_id": doc.get("issue_id") or str(uuid4()),
            "issue_key": doc.get("issue_key") or f"ISS-{uuid4().hex[:8]}",
            "test_run_id": doc["test_run_id"],
            "test_case_id": doc.get("test_case_id"),
            "test_key": doc.get("test_key"),
            "category": doc.get("category"),
            "severity": doc.get("severity", "medium"),
            "title": doc.get("title"),
            "description": doc.get("description"),
            "expected_behavior": doc.get("expected_behavior"),
            "actual_behavior": doc.get("actual_behavior"),
            "evidence": doc.get("evidence") or {},
            "root_cause_hypothesis": doc.get("root_cause_hypothesis"),
            "recommended_fix": doc.get("recommended_fix"),
            "status": doc.get("status", "open"),
            "created_at": utcnow(),
        }
        self.issues.insert_one(issue)
        return issue

    def list_results(self, test_run_id: str) -> list[dict[str, Any]]:
        return list(self.results.find({"test_run_id": test_run_id}).sort("test_key", 1))

    def list_issues(self, test_run_id: str) -> list[dict[str, Any]]:
        return list(self.issues.find({"test_run_id": test_run_id}).sort("severity", 1))

    def list_failed_keys(self, test_run_id: str) -> list[str]:
        return [
            r["test_key"]
            for r in self.results.find(
                {"test_run_id": test_run_id, "status": {"$in": ["failed", "blocked"]}},
                {"test_key": 1},
            )
            if r.get("test_key")
        ]
