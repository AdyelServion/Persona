"""QA report generation: JSON + Markdown with previous-run comparison."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pymongo.database import Database

from persona_runtime.qa.issues_md import update_issues_md
from persona_runtime.qa.repository import QARepository

DEFAULT_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "qa_reports"


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def compare_runs(db: Database, run_a_id: str, run_b_id: str) -> dict[str, Any]:
    repo = QARepository(db)
    a_results = {r["test_key"]: r for r in repo.list_results(run_a_id)}
    b_results = {r["test_key"]: r for r in repo.list_results(run_b_id)}
    keys = sorted(set(a_results) | set(b_results))
    newly_failed: list[str] = []
    newly_passed: list[str] = []
    still_failing: list[str] = []
    for key in keys:
        sa = (a_results.get(key) or {}).get("status")
        sb = (b_results.get(key) or {}).get("status")
        if sa == "passed" and sb == "failed":
            newly_failed.append(key)
        elif sa == "failed" and sb == "passed":
            newly_passed.append(key)
        elif sa == "failed" and sb == "failed":
            still_failing.append(key)
    return {
        "run_a": run_a_id,
        "run_b": run_b_id,
        "newly_failed": newly_failed,
        "newly_passed": newly_passed,
        "still_failing": still_failing,
        "total_keys": len(keys),
    }


def generate_reports(
    db: Database,
    run_id: str,
    *,
    report_dir: Path | None = None,
) -> dict[str, str]:
    repo = QARepository(db)
    run = repo.get_run(run_id)
    if not run:
        raise ValueError(f"Unknown run_id: {run_id}")
    results = repo.list_results(run_id)
    issues = repo.list_issues(run_id)

    previous = None
    comparison = None
    if run.get("previous_run_id"):
        previous = repo.get_run(run["previous_run_id"])
        comparison = compare_runs(db, run["previous_run_id"], run_id)

    total = len(results) or 1
    passed = run.get("passed_count") or sum(1 for r in results if r.get("status") == "passed")
    failed = run.get("failed_count") or sum(1 for r in results if r.get("status") == "failed")
    blocked = run.get("blocked_count") or sum(1 for r in results if r.get("status") == "blocked")
    skipped = run.get("skipped_count") or sum(1 for r in results if r.get("status") == "skipped")
    pass_rate = round(100.0 * passed / total, 2)

    contradictions: list[dict[str, Any]] = []
    memory_rows: list[dict[str, Any]] = []
    timeline_rows: list[dict[str, Any]] = []
    for r in results:
        state = r.get("actual_state") or {}
        ledger = state.get("ledger") or {}
        for c in ledger.get("contradictions") or []:
            contradictions.append({"test_key": r.get("test_key"), **c})
        for ar in r.get("assertion_results") or []:
            if ar.get("type", "").startswith("memory"):
                memory_rows.append(
                    {
                        "test_key": r.get("test_key"),
                        "type": ar.get("type"),
                        "status": ar.get("status"),
                        "explanation": ar.get("explanation"),
                        "evidence": ar.get("evidence"),
                    }
                )
            if ar.get("type") in {"timeline_consistency", "date_time_match", "event_status_match"}:
                timeline_rows.append(
                    {
                        "test_key": r.get("test_key"),
                        "type": ar.get("type"),
                        "status": ar.get("status"),
                        "actual": ar.get("actual"),
                    }
                )

    remediation: dict[str, list[str]] = defaultdict(list)
    for issue in issues:
        group = _remediation_group(issue.get("category"))
        remediation[group].append(
            f"{issue.get('issue_key')}: {issue.get('title')} — {issue.get('recommended_fix')}"
        )

    critical_high = [
        i
        for i in issues
        if i.get("severity") in {"critical", "high"}
    ]

    report = {
        "executive_summary": {
            "run_id": run_id,
            "started_at": _json_safe(run.get("started_at")),
            "completed_at": _json_safe(run.get("completed_at")),
            "persona_id": run.get("persona_id"),
            "environment": run.get("environment"),
            "build_version": run.get("build_version"),
            "model_provider": run.get("model_provider"),
            "model_name": run.get("model_name"),
            "prompt_version": run.get("prompt_version"),
            "configuration": _json_safe(run.get("configuration") or {}),
            "total_tests": len(results),
            "passed": passed,
            "failed": failed,
            "blocked": blocked,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "critical_high_issues": len(critical_high),
            "previous_run_id": run.get("previous_run_id"),
            "comparison": comparison,
        },
        "test_results": _json_safe(results),
        "contradiction_report": contradictions,
        "memory_report": memory_rows,
        "timeline_report": timeline_rows,
        "issue_register": _json_safe(issues),
        "recommended_remediation": dict(remediation),
        "previous_run": _json_safe(previous) if previous else None,
    }

    out_dir = report_dir or DEFAULT_REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    md_path = out_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")
    paths = {"json": str(json_path), "markdown": str(md_path)}
    # Only the default reports directory updates the repo-root issues log.
    # Temporary report dirs (unit tests) must not replace that summary.
    if report_dir is None or Path(report_dir).resolve() == DEFAULT_REPORT_DIR.resolve():
        paths["issues"] = str(update_issues_md(report))
    return paths


def _remediation_group(category: str | None) -> str:
    mapping = {
        "persona_identity": "Persona configuration problems",
        "persistent_memory": "Memory engine problems",
        "time_timeline": "Timeline and state-management problems",
        "contradiction_detection": "Timeline and state-management problems",
        "contextual_understanding": "Prompt or orchestration problems",
        "multi_turn_flow": "Prompt or orchestration problems",
        "human_like_conversation": "Response-generation problems",
        "response_formatting": "Frontend formatting problems",
        "proactive_engagement": "Prompt or orchestration problems",
        "hallucination_resistance": "Prompt or orchestration problems",
        "persistence_concurrency": "Database and persistence problems",
    }
    return mapping.get(category or "", "Evaluation false positives requiring human review")


def _to_markdown(report: dict[str, Any]) -> str:
    s = report["executive_summary"]
    lines = [
        "# Persona QA Report",
        "",
        "## Executive Summary",
        "",
        f"- **Run ID:** {s['run_id']}",
        f"- **Started:** {s.get('started_at')}",
        f"- **Completed:** {s.get('completed_at')}",
        f"- **Persona:** {s.get('persona_id')}",
        f"- **Environment:** {s.get('environment')} / {s.get('build_version')}",
        f"- **Model:** {s.get('model_name')}",
        f"- **Total:** {s['total_tests']}",
        f"- **Passed / Failed / Blocked / Skipped:** "
        f"{s['passed']} / {s['failed']} / {s['blocked']} / {s['skipped']}",
        f"- **Pass rate:** {s['pass_rate']}%",
        f"- **Critical/High issues:** {s['critical_high_issues']}",
    ]
    comp = s.get("comparison")
    if comp:
        lines.extend(
            [
                "",
                "### Comparison with previous run",
                f"- Previous: `{comp.get('run_a')}`",
                f"- Newly failed: {', '.join(comp.get('newly_failed') or []) or 'none'}",
                f"- Newly passed: {', '.join(comp.get('newly_passed') or []) or 'none'}",
                f"- Still failing: {', '.join(comp.get('still_failing') or []) or 'none'}",
            ]
        )

    lines.extend(["", "## Test Results", ""])
    for r in report["test_results"]:
        lines.append(
            f"### {r.get('test_key')} — {r.get('status')} ({r.get('category')})"
        )
        lines.append(f"- Duration: {r.get('duration_ms')} ms")
        if r.get("failure_summary"):
            lines.append(f"- Failure: {r.get('failure_summary')}")
        for turn in r.get("transcript") or []:
            lines.append(f"- User: {turn.get('user')}")
            if turn.get("assistant"):
                preview = str(turn.get("assistant"))[:240].replace("\n", " ")
                lines.append(f"- Assistant: {preview}")
        failed_as = [
            a
            for a in (r.get("assertion_results") or [])
            if a.get("status") in {"fail", "blocked", "needs_review"}
        ]
        for a in failed_as:
            lines.append(
                f"- Assertion `{a.get('type')}` → {a.get('status')}: {a.get('explanation')}"
            )
        lines.append("")

    lines.extend(["## Contradiction Report", ""])
    if not report["contradiction_report"]:
        lines.append("No contradictions recorded.")
    for c in report["contradiction_report"]:
        lines.append(
            f"- `{c.get('test_key')}` {c.get('subject')}.{c.get('attribute')}: "
            f"{c.get('earlier')} vs {c.get('later')}"
        )

    lines.extend(["", "## Memory Report", ""])
    if not report["memory_report"]:
        lines.append("No memory assertion rows.")
    for m in report["memory_report"][:100]:
        lines.append(
            f"- `{m.get('test_key')}` {m.get('type')} → {m.get('status')}: {m.get('explanation')}"
        )

    lines.extend(["", "## Timeline Report", ""])
    if not report["timeline_report"]:
        lines.append("No timeline assertion rows.")
    for t in report["timeline_report"][:100]:
        lines.append(f"- `{t.get('test_key')}` {t.get('type')} → {t.get('status')}")

    lines.extend(["", "## Issue Register", ""])
    if not report["issue_register"]:
        lines.append("No issues.")
    for issue in report["issue_register"]:
        lines.extend(
            [
                f"### {issue.get('issue_key')} [{issue.get('severity')}]",
                f"- Test: `{issue.get('test_key')}`",
                f"- Title: {issue.get('title')}",
                f"- Expected: {issue.get('expected_behavior')}",
                f"- Actual: {str(issue.get('actual_behavior') or '')[:300]}",
                f"- Hypothesis: {issue.get('root_cause_hypothesis')}",
                f"- Fix: {issue.get('recommended_fix')}",
                "",
            ]
        )

    lines.extend(["## Recommended Remediation", ""])
    for group, items in (report.get("recommended_remediation") or {}).items():
        lines.append(f"### {group}")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
