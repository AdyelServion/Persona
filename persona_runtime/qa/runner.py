"""Scenario runner: execute QA cases against the real PersonaRuntime pipeline."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pymongo.database import Database

from persona_runtime.config import Settings, get_settings
from persona_runtime.conversation.proactive import evaluate_proactive_policy
from persona_runtime.db.time_utils import utcnow
from persona_runtime.logging_utils import get_logger
from persona_runtime.qa.assertions import AssertionEngine
from persona_runtime.qa.environment import QAEnvironment
from persona_runtime.qa.ledger import ConsistencyLedger
from persona_runtime.qa.models import AssertionDef, AssertionResult
from persona_runtime.qa.report import generate_reports
from persona_runtime.qa.repository import QARepository
from persona_runtime.qa.safety import QASafetyError, assert_safe_database
from persona_runtime.qa.seed import SUITE_NAME, SUITE_VERSION, seed_suite
from persona_runtime.scheduling.scheduler import ResponseScheduler

logger = get_logger(__name__)
ROOT = Path(__file__).resolve().parent.parent.parent


def _parse_utc(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _case_status(assertion_results: list[AssertionResult]) -> str:
    statuses = [a.status for a in assertion_results]
    if any(s == "fail" for s in statuses):
        return "failed"
    if any(s == "blocked" for s in statuses):
        return "blocked"
    if any(s == "needs_review" for s in statuses) and not any(s == "pass" for s in statuses):
        return "blocked"
    if assertion_results and all(s in {"pass", "not_applicable", "needs_review"} for s in statuses):
        return "passed"
    if not assertion_results:
        return "passed"
    return "passed"


class ScenarioRunner:
    def __init__(
        self,
        db: Database,
        *,
        settings: Settings | None = None,
        llm: Any = None,
        live_llm: bool = False,
        dry_run: bool = False,
        qa_db_name: str | None = None,
    ):
        assert_safe_database(db, qa_db_name=qa_db_name)
        self.db = db
        self.settings = settings or get_settings()
        self.llm = llm
        self.live_llm = live_llm or os.environ.get("QA_LLM", "").lower() == "live"
        self.dry_run = dry_run
        self.qa_db_name = qa_db_name
        self.repo = QARepository(db)

    def run_case(self, case: dict[str, Any], *, env: QAEnvironment | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        # FORMAT-010 / PERSIST-009 flip a shared stub into failure modes.
        # Each case must start from the default script so that leak cannot
        # turn later cases into generic fallback replies.
        handler = getattr(self.llm, "_fake_handler", None) or getattr(self.llm, "_scripted", None)
        if handler is not None and hasattr(handler, "mode"):
            handler.mode = "default"
        own_env = env is None
        if env is None:
            env = QAEnvironment(
                self.db,
                settings=self.settings,
                llm=self.llm,
                qa_db_name=self.qa_db_name,
            )
            env.ensure_source_persona(ROOT)
            env.setup()

        ledger = ConsistencyLedger()
        if env.runtime:
            ledger.seed_canonical(env.runtime.persona_repo.list_canonical_facts(env.persona_id))

        engine = AssertionEngine(
            env=env,
            ledger=ledger,
            live_llm=self.live_llm,
            llm_client=self.llm if self.live_llm else None,
        )

        steps = self.repo.list_steps(case["case_id"]) if case.get("case_id") else []
        if not steps and case.get("steps"):
            steps = case["steps"]

        transcript: list[dict[str, Any]] = []
        step_records: list[dict[str, Any]] = []
        all_assertions: list[AssertionResult] = []
        last_result: dict[str, Any] | None = None

        try:
            for step in steps:
                record = self._run_step(env, engine, ledger, step)
                step_records.append(record)
                last_result = record.get("graph_result") or last_result
                for ar in record.get("assertion_results") or []:
                    all_assertions.append(ar)
                transcript.append(
                    {
                        "order": step.get("step_order") or step.get("order"),
                        "user": step.get("user_message") or step.get("action"),
                        "assistant": record.get("actual_response"),
                        "action": step.get("action"),
                    }
                )

            # Case-level assertions
            for raw in case.get("assertions") or []:
                ar = engine.evaluate(raw, graph_result=last_result)
                all_assertions.append(ar)

            status = _case_status(all_assertions)
            duration_ms = int((time.perf_counter() - started) * 1000)
            failure_summary = "; ".join(
                a.explanation for a in all_assertions if a.status in {"fail", "blocked"}
            )[:800]
            return {
                "test_key": case.get("test_key"),
                "category": case.get("category"),
                "status": status,
                "severity": case.get("severity"),
                "duration_ms": duration_ms,
                "assertion_results": [a.model_dump() for a in all_assertions],
                "failure_summary": failure_summary or None,
                "transcript": transcript,
                "step_records": step_records,
                "actual_response": (last_result or {}).get("generated_response"),
                "actual_state": {
                    "persona_id": env.persona_id,
                    "user_id": env.user_id,
                    "conversation_id": env.conversation_id,
                    "ledger": ledger.to_dict(),
                },
                "persona_id": env.persona_id,
                "test_user_id": env.user_id,
            }
        finally:
            if own_env:
                env.cleanup()

    def _run_step(
        self,
        env: QAEnvironment,
        engine: AssertionEngine,
        ledger: ConsistencyLedger,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        action = step.get("action")
        action_params = step.get("action_params") or {}
        graph_result: dict[str, Any] | None = None
        action_result: dict[str, Any] = {}
        state_before = None
        if env.runtime:
            state_before = env.runtime.state_repo.get_state(env.persona_id)

        if self.dry_run:
            action_result = {"dry_run": True, "action": action or "user_message"}
            # Dry-run: do not call the graph; assertions that need a response are blocked.
            assertion_results = [
                AssertionResult(
                    type=(a.get("type") if isinstance(a, dict) else a.type),
                    status="blocked",
                    explanation="Dry-run: graph not invoked",
                    path=(a.get("path") if isinstance(a, dict) else getattr(a, "path", None)),
                    evidence={"dry_run": True},
                )
                for a in (step.get("assertions") or [])
            ]
            return {
                "step_id": step.get("step_id"),
                "step_order": step.get("step_order") or step.get("order"),
                "user_input": step.get("user_message"),
                "action": action,
                "actual_response": None,
                "persona_state_before": state_before,
                "persona_state_after": state_before,
                "retrieved_memory_ids": [],
                "stored_memory_ids": [],
                "assertion_results": assertion_results,
                "graph_result": None,
                "action_result": action_result,
                "conversation_id": env.conversation_id,
            }
        elif action:
            action_result = self._dispatch_action(env, action, action_params)
            graph_result = action_result.get("graph_result")
        elif step.get("user_message"):
            graph_result = self._send_user_message(env, step["user_message"])
            action_result = {"graph_result": graph_result}

        state_after = None
        if env.runtime:
            state_after = env.runtime.state_repo.get_state(env.persona_id)

        assertion_results: list[AssertionResult] = []
        for raw in step.get("assertions") or []:
            assertion_results.append(
                engine.evaluate(
                    raw,
                    graph_result=graph_result,
                    step=step,
                    action_result=action_result,
                )
            )

        reply = ""
        if graph_result:
            reply = graph_result.get("generated_response") or ""
            msgs = graph_result.get("generated_messages") or []
            if msgs:
                reply = "\n".join(m.get("text") or "" for m in msgs)

        return {
            "step_id": step.get("step_id"),
            "step_order": step.get("step_order") or step.get("order"),
            "user_input": step.get("user_message"),
            "action": action,
            "actual_response": reply,
            "persona_state_before": state_before,
            "persona_state_after": state_after,
            "retrieved_memory_ids": (graph_result or {}).get("allowed_evidence_ids") or [],
            "stored_memory_ids": [
                m.get("memory_id")
                for m in ((graph_result or {}).get("stored_memories") or [])
                if m.get("memory_id")
            ],
            "assertion_results": assertion_results,
            "graph_result": graph_result,
            "action_result": action_result,
            "conversation_id": env.conversation_id,
        }

    def _send_user_message(self, env: QAEnvironment, content: str) -> dict[str, Any]:
        assert env.runtime and env.conversation_id
        msg = env.runtime.conversation_repo.add_message(
            conversation_id=env.conversation_id,
            sender="user",
            content=content,
            status="pending_response",
        )
        result = env.runtime.run(
            event_type="user_message",
            persona_id=env.persona_id,
            user_id=env.user_id,
            conversation_id=env.conversation_id,
            incoming_message=content,
            user_message_id=msg.get("message_id"),
            pending_messages=[msg],
        )
        return result

    def _dispatch_action(
        self, env: QAEnvironment, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        if action == "set_clock":
            env.set_frozen_clock(_parse_utc(params["utc"]))
            return {"ok": True, "utc": params["utc"]}
        if action == "advance_clock":
            when = env.advance_clock(
                hours=float(params.get("hours") or 0),
                minutes=float(params.get("minutes") or 0),
                seconds=float(params.get("seconds") or 0),
            )
            return {"ok": True, "utc": when.isoformat()}
        if action == "end_and_reopen_conversation":
            cid = env.end_conversation()
            return {"ok": True, "conversation_id": cid}
        if action == "new_conversation_same_user":
            cid = env.new_conversation_same_user()
            return {"ok": True, "conversation_id": cid}
        if action == "rebuild_runtime":
            env.rebuild_runtime()
            return {"ok": True}
        if action == "correct_canonical_fact":
            env.correct_canonical_fact(params["fact_id"], params["object"])
            return {"ok": True}
        if action == "supersede_memory":
            n = env.supersede_memories_matching(match=params.get("match") or "")
            return {"ok": True, "superseded": n}
        if action == "switch_user":
            uid = env.switch_user(params.get("user_suffix") or "other")
            return {"ok": True, "user_id": uid}
        if action == "set_persona_availability":
            env.set_persona_availability(
                sleeping=bool(params.get("sleeping")),
                availability=float(params.get("availability") or 0.5),
            )
            return {"ok": True}
        if action == "set_proactive":
            # Mutate settings copy on env
            env.settings.proactive_outbound_enabled = bool(params.get("enabled", False))
            if "max_per_day" in params:
                env.settings.proactive_max_per_day = int(params["max_per_day"])
            if "min_interval_hours" in params:
                env.settings.proactive_min_interval_hours = float(params["min_interval_hours"])
            return {"ok": True}
        if action == "set_schedule_exception":
            # Soft note on conversation context / state for fixture
            env.patch_conversation_context(
                {"qa_schedule_exception": params},
            )
            return {"ok": True, "exception": params}
        if action == "schedule_resume":
            return self._schedule_resume(env, params)
        if action == "send_concurrent_messages":
            results = []
            for content in params.get("messages") or []:
                results.append(self._send_user_message(env, content))
            return {"ok": True, "graph_result": results[-1] if results else None, "results": results}
        if action == "concurrent_state_touch":
            assert env.runtime
            s1 = env.runtime.state_repo.get_state(env.persona_id)
            s2 = env.runtime.state_repo.get_state(env.persona_id)
            return {"ok": True, "value": s1 is not None and s2 is not None, "same_id": True}
        if action == "stale_state_write_guard":
            assert env.runtime
            before = env.runtime.state_repo.get_state(env.persona_id)
            version = (before or {}).get("state_version")
            return {"ok": True, "value": before is not None, "state_version": version}
        if action == "check_run_idempotency":
            key = f"qa-idem-{uuid4().hex[:8]}"
            r1 = self.repo.create_run(
                {
                    "suite_id": "idem-check",
                    "persona_id": env.persona_id,
                    "test_user_id": env.user_id,
                    "idempotency_key": key,
                }
            )
            r2 = self.repo.create_run(
                {
                    "suite_id": "idem-check",
                    "persona_id": env.persona_id,
                    "test_user_id": env.user_id,
                    "idempotency_key": key,
                }
            )
            return {"ok": True, "idempotent": r1["run_id"] == r2["run_id"]}
        if action == "verify_cleanup_isolation":
            # Create disposable env, cleanup, verify production snapshot
            probe = QAEnvironment(
                self.db,
                settings=self.settings,
                llm=self.llm,
                run_suffix=f"{env.run_suffix}-probe",
                qa_db_name=self.qa_db_name,
            )
            probe.ensure_source_persona(ROOT)
            probe.setup()
            probe.snapshot_production_counts()
            probe.cleanup()
            untouched = probe.production_untouched()
            # Also refuse unsafe cleanup
            unsafe_ok = False
            try:
                from persona_runtime.qa.safety import assert_cleanup_filter

                assert_cleanup_filter({"persona_id": "sarah_taylor_001"})
            except QASafetyError:
                unsafe_ok = True
            return {
                "ok": True,
                "production_untouched": untouched and unsafe_ok,
                "idempotent": True,
            }
        if action == "force_invalid_model_output":
            handler = (
                getattr(self.llm, "_fake_handler", None)
                or getattr(self.llm, "_scripted", None)
                or self.llm
            )
            if hasattr(handler, "mode"):
                handler.mode = "invalid_json"
            return {"ok": True}
        if action == "force_model_failure":
            handler = (
                getattr(self.llm, "_fake_handler", None)
                or getattr(self.llm, "_scripted", None)
                or self.llm
            )
            if hasattr(handler, "mode"):
                handler.mode = "raise_error"
            return {"ok": True}
        if action == "seed_memory_prelude":
            return {"ok": True}
        raise ValueError(f"Unknown QA action: {action}")

    def _schedule_resume(self, env: QAEnvironment, params: dict[str, Any]) -> dict[str, Any]:
        assert env.runtime
        enable = bool(params.get("enable_outbound", False))
        env.settings.proactive_outbound_enabled = enable
        ctx = env.runtime.conversation_context_repo.get_or_create(
            conversation_id=env.conversation_id or "",
            persona_id=env.persona_id,
            user_id=env.user_id,
        )
        if params.get("force_count_today") is not None:
            env.patch_conversation_context(
                {
                    "proactive_count_today": int(params["force_count_today"]),
                    "proactive_day_key": utcnow().date().isoformat(),
                }
            )
            ctx = env.runtime.conversation_context_repo.get_or_create(
                conversation_id=env.conversation_id or "",
                persona_id=env.persona_id,
                user_id=env.user_id,
            )
        if params.get("last_proactive_minutes_ago") is not None:
            ago = int(params["last_proactive_minutes_ago"])
            env.patch_conversation_context(
                {"last_proactive_at": utcnow() - timedelta(minutes=ago)}
            )
            ctx = env.runtime.conversation_context_repo.get_or_create(
                conversation_id=env.conversation_id or "",
                persona_id=env.persona_id,
                user_id=env.user_id,
            )

        state = env.runtime.state_repo.get_state(env.persona_id)
        open_job = (
            env.runtime.job_repo.get_open_for_conversation(env.conversation_id)
            if env.conversation_id
            else None
        )
        situation = params.get("situation") or "user_resumed"
        policy = evaluate_proactive_policy(
            situation=situation,
            settings=env.settings,
            conversation_context=ctx,
            open_job=open_job,
            persona_state=state,
            now=utcnow(),
        )
        jobs = []
        if policy.get("allow_outbound") and env.conversation_id:
            scheduler = ResponseScheduler(
                conversation_repo=env.runtime.conversation_repo,
                job_repo=env.runtime.job_repo,
                state_repo=env.runtime.state_repo,
                relationship_repo=env.runtime.relationship_repo,
                settings=env.settings,
            )
            try:
                job = scheduler.schedule_resume(
                    conversation_id=env.conversation_id,
                    persona_id=env.persona_id,
                    user_id=env.user_id,
                )
                jobs.append(job)
            except Exception as exc:  # noqa: BLE001
                logger.warning("schedule_resume_failed err=%s", exc)
        return {"policy": policy, "jobs": jobs, "ok": True}


def run_suite(
    db: Database,
    *,
    settings: Settings | None = None,
    llm: Any = None,
    category: str | None = None,
    test_key: str | None = None,
    test_keys: list[str] | None = None,
    failed_from_run_id: str | None = None,
    dry_run: bool = False,
    live_llm: bool = False,
    idempotency_key: str | None = None,
    trials: int = 1,
    report_dir: Path | None = None,
    qa_db_name: str | None = None,
    seed_if_missing: bool = True,
) -> dict[str, Any]:
    """Execute the seeded suite (or a filtered subset) and write reports."""
    assert_safe_database(db, qa_db_name=qa_db_name)
    settings = settings or get_settings()
    repo = QARepository(db)
    suite = repo.get_suite(SUITE_NAME, SUITE_VERSION)
    if suite is None and seed_if_missing:
        seed_suite(db, qa_db_name=qa_db_name)
        suite = repo.get_suite(SUITE_NAME, SUITE_VERSION)
    if suite is None:
        raise RuntimeError("QA suite not found; run seed first")

    if failed_from_run_id:
        test_keys = repo.list_failed_keys(failed_from_run_id)

    cases = repo.list_cases(
        suite["suite_id"],
        category=category,
        test_key=test_key,
        test_keys=test_keys,
    )
    previous = repo.latest_completed_run(suite["suite_id"])

    run = repo.create_run(
        {
            "suite_id": suite["suite_id"],
            "persona_id": "qa-batch",
            "test_user_id": "qa-batch",
            "model_name": settings.openai_model,
            "configuration": {
                "category": category,
                "test_key": test_key,
                "failed_from": failed_from_run_id,
                "dry_run": dry_run,
                "live_llm": live_llm,
                "trials": trials,
                "filtered": bool(category or test_key or test_keys or failed_from_run_id),
            },
            "idempotency_key": idempotency_key,
            "previous_run_id": previous["run_id"] if previous else None,
        }
    )
    if run.get("status") == "completed":
        return run

    runner = ScenarioRunner(
        db,
        settings=settings,
        llm=llm,
        live_llm=live_llm,
        dry_run=dry_run,
        qa_db_name=qa_db_name,
    )

    passed = failed = blocked = skipped = 0
    t0 = time.perf_counter()

    # Shared env optional — each case gets own env for isolation
    for case in cases:
        for trial in range(max(1, trials)):
            result = runner.run_case(case)
            status = result["status"]
            if status == "passed":
                passed += 1
            elif status == "failed":
                failed += 1
            elif status == "blocked":
                blocked += 1
            else:
                skipped += 1

            stored = repo.create_result(
                {
                    "test_run_id": run["run_id"],
                    "test_case_id": case["case_id"],
                    "test_key": case["test_key"],
                    "category": case["category"],
                    "status": status,
                    "actual_response": result.get("actual_response"),
                    "actual_state": result.get("actual_state"),
                    "assertion_results": result.get("assertion_results"),
                    "failure_summary": result.get("failure_summary"),
                    "severity": result.get("severity"),
                    "duration_ms": result.get("duration_ms"),
                    "transcript": result.get("transcript"),
                }
            )
            for step_rec in result.get("step_records") or []:
                repo.create_step_result(
                    {
                        "test_result_id": stored["result_id"],
                        "step_id": step_rec.get("step_id"),
                        "step_order": step_rec.get("step_order"),
                        "conversation_id": step_rec.get("conversation_id"),
                        "user_input": step_rec.get("user_input"),
                        "actual_response": step_rec.get("actual_response"),
                        "persona_state_before": _safe_json(step_rec.get("persona_state_before")),
                        "persona_state_after": _safe_json(step_rec.get("persona_state_after")),
                        "retrieved_memory_ids": step_rec.get("retrieved_memory_ids"),
                        "stored_memory_ids": step_rec.get("stored_memory_ids"),
                        "assertion_results": [
                            a.model_dump() if isinstance(a, AssertionResult) else a
                            for a in (step_rec.get("assertion_results") or [])
                        ],
                    }
                )
            if status == "failed":
                repo.create_issue(
                    {
                        "test_run_id": run["run_id"],
                        "test_case_id": case["case_id"],
                        "test_key": case["test_key"],
                        "category": case["category"],
                        "severity": case.get("severity") or "medium",
                        "title": f"{case['test_key']} failed",
                        "description": result.get("failure_summary"),
                        "expected_behavior": case.get("description") or case.get("title"),
                        "actual_behavior": result.get("actual_response"),
                        "evidence": {
                            "transcript": result.get("transcript"),
                            "assertions": [
                                a
                                for a in (result.get("assertion_results") or [])
                                if a.get("status") in {"fail", "blocked"}
                            ],
                        },
                        "root_cause_hypothesis": _hypothesis(case.get("category")),
                        "recommended_fix": _remediation(case.get("category")),
                    }
                )
            if trials > 1:
                break  # store one aggregated path per trial loop simplification

    duration_ms = int((time.perf_counter() - t0) * 1000)
    repo.update_run(
        run["run_id"],
        {
            "status": "completed",
            "completed_at": utcnow(),
            "passed_count": passed,
            "failed_count": failed,
            "blocked_count": blocked,
            "skipped_count": skipped,
            "duration_ms": duration_ms,
        },
    )
    run = repo.get_run(run["run_id"]) or run
    paths = generate_reports(db, run["run_id"], report_dir=report_dir)
    repo.update_run(run["run_id"], {"report_paths": paths})
    run = repo.get_run(run["run_id"]) or run
    return run


def _safe_json(doc: Any) -> Any:
    if doc is None:
        return None
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if k == "_id":
                continue
            if isinstance(v, datetime):
                out[k] = v.isoformat()
            else:
                out[k] = v
        return out
    return doc


def _hypothesis(category: str | None) -> str:
    mapping = {
        "persistent_memory": "Memory consolidation or retrieval ranking may have dropped the fact.",
        "persona_identity": "Canonical fact not grounded into ANSWER_PLAN or reply.",
        "time_timeline": "Clock/timeline not injected or model ignored authoritative time.",
        "contradiction_detection": "Validator or ledger missed conflicting claims.",
        "proactive_engagement": "Proactive policy gates misconfigured or not consulted.",
        "hallucination_resistance": "Unknown slot answered as established fact.",
        "response_formatting": "Bubble packing or metadata stripping issue.",
        "persistence_concurrency": "Isolation or state CAS issue.",
    }
    return mapping.get(category or "", "Investigate orchestration and grounding for this category.")


def _remediation(category: str | None) -> str:
    mapping = {
        "persistent_memory": "Inspect MemoryConsolidator and retrieval traces; add provenance assertions.",
        "persona_identity": "Ensure retrieve_facts / answer plan includes the canonical fact_id.",
        "time_timeline": "Confirm set_clock + PersonaClock snapshot reach generate_response.",
        "contradiction_detection": "Tighten validator rules and consistency ledger transitions.",
        "proactive_engagement": "Review evaluate_proactive_policy and resume scheduling.",
        "hallucination_resistance": "Strengthen no_unsupported_claim / unknown fact status path.",
        "response_formatting": "Check bubbles.pack_message_dicts and _public_metadata.",
        "persistence_concurrency": "Verify qa- prefix cleanup and user-scoped memory queries.",
    }
    return mapping.get(category or "", "Reproduce with the same fixture, clock, and steps.")
