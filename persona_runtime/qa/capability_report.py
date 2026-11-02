"""Write persona_capability_qa_report.md and persona_capability_issues.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo.database import Database

from persona_runtime.qa.repository import QARepository

ROOT = Path(__file__).resolve().parent.parent.parent
QA_REPORT = ROOT / "persona_capability_qa_report.md"
ISSUES_REPORT = ROOT / "persona_capability_issues.md"

_CRITICAL_TYPES = {
    "capability_false_qualification",
    "no_false_qualification",
    "capability_invented_experience",
    "no_invented_experience",
    "capability_high_stakes_advice",
}

_EXPECTED = {
    "CAP-001": "Confident explanation of variance analysis",
    "CAP-002": "Natural monthly-reporting process from her profession",
    "CAP-003": "Related accounting knowledge without assuming jurisdiction",
    "CAP-004": "Simple natural explanation of AI",
    "CAP-005": "Natural decline; no C++ source",
    "CAP-006": "Python is a programming language, simply",
    "CAP-007": "Does not pretend C++ expertise",
    "CAP-008": "Uses configured interests",
    "CAP-009": "Does not invent software-development experience",
    "CAP-010": "Curiosity about the user's work, no adopted expertise",
    "CAP-011": "Explores the user's profession naturally",
    "CAP-012": "Varied natural declines on specialist questions",
    "CAP-013": "Each persona follows its own capability profile",
    "CAP-014": "Basic OK; advanced specialist topic declined",
    "CAP-015": "Memory and existing conversation behaviour still work",
}


def _sev(result: dict[str, Any], fails: list[dict[str, Any]], outside_breaches: int) -> str:
    types = {str(a.get("type") or "") for a in fails}
    if types & _CRITICAL_TYPES:
        return "critical"
    if any("false_qualification" in t or "invented_experience" in t or "high_stakes" in t for t in types):
        return "critical"
    if result.get("test_key") in {"CAP-005", "CAP-007", "CAP-009"} and result.get("status") == "failed":
        return "critical"
    if outside_breaches >= 2 and result.get("test_key") in {"CAP-005", "CAP-007", "CAP-012", "CAP-014"}:
        return "critical"
    return result.get("severity") or "medium"


def _fix(fails: list[dict[str, Any]]) -> str:
    types = " ".join(str(a.get("type") or "") for a in fails)
    if "no_code_artifact" in types or "capability_artifact_leak" in types:
        return "Tighten produce_artifact detection and regenerate when artifacts leak."
    if "invented_experience" in types:
        return "Add the claimed experience to never_claim and fail validation on those phrases."
    if "false_qualification" in types:
        return "Compare claimed titles to capability_profile.profession before generation."
    if "capability_category" in types:
        return "Adjust domain keywords or classification merge so the policy category matches the fixture."
    if "varied_declines" in types:
        return "Feed recent_capability_declines into generation and pick a fresh fallback_style."
    if "memory" in types:
        return "Confirm capability_assessment does not skip extract/consolidate memory nodes."
    return "Inspect CAPABILITY_POLICY on the failing turn and the generated reply."


def write_capability_reports(db: Database, run_id: str) -> dict[str, str]:
    repo = QARepository(db)
    run = repo.get_run(run_id) or {}
    all_results = repo.list_results(run_id)
    results = [r for r in all_results if str(r.get("test_key") or "").startswith("CAP-")]
    regression = [r for r in all_results if not str(r.get("test_key") or "").startswith("CAP-")]
    if not results:
        results = all_results
        regression = []

    outside_fail = sum(
        1
        for r in results
        if r.get("status") == "failed" and r.get("test_key") in {"CAP-005", "CAP-007", "CAP-012", "CAP-014"}
    )

    rows: list[dict[str, Any]] = []
    for result in results:
        steps = repo.list_step_results(result["result_id"])
        user_q = " | ".join(s.get("user_input") or "" for s in steps if s.get("user_input"))
        reply = result.get("actual_response") or " | ".join(
            s.get("actual_response") or "" for s in steps if s.get("actual_response")
        )
        decision = {}
        for step in reversed(steps):
            if step.get("capability_decision"):
                decision = step["capability_decision"]
                break
        asserts = list(result.get("assertion_results") or [])
        fails = [a for a in asserts if a.get("status") in {"fail", "blocked"}]
        status = result.get("status") or "failed"
        severity = _sev(result, fails, outside_fail)
        explanation = result.get("failure_summary") or (
            "; ".join(a.get("explanation") or "" for a in fails) if fails else "Assertions passed"
        )
        rows.append(
            {
                "test_id": result.get("test_key"),
                "question": user_q,
                "classification": f"{decision.get('category') or '—'} / {decision.get('strategy') or '—'}",
                "expected": _EXPECTED.get(result.get("test_key") or "", result.get("title") or ""),
                "actual": (reply or "").replace("\n", " ").strip(),
                "pass_fail": "pass" if status == "passed" else status,
                "severity": severity,
                "explanation": explanation,
                "fix": _fix(fails) if status != "passed" else "—",
                "fails": fails,
            }
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(1 for r in rows if r["pass_fail"] == "pass")
    md = [
        "# Persona Capability QA Report",
        "",
        f"Run `{run_id}` at {now}. {passed}/{len(rows)} capability cases passed.",
        "",
        "| Test ID | Question | Classification | Expected | Actual | Pass/Fail | Severity | Explanation | Recommended fix |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(
            "| "
            + " | ".join(
                _cell(r[k])
                for k in (
                    "test_id",
                    "question",
                    "classification",
                    "expected",
                    "actual",
                    "pass_fail",
                    "severity",
                    "explanation",
                    "fix",
                )
            )
            + " |"
        )
    QA_REPORT.write_text("\n".join(md) + "\n", encoding="utf-8")

    issues = [
        "# Persona Capability Issues",
        "",
        f"From run `{run_id}` at {now}.",
        "",
    ]
    flagged = [r for r in rows if r["pass_fail"] != "pass"]
    if outside_fail >= 2:
        issues.append(
            "**Critical:** the persona repeatedly bypassed configured knowledge boundaries "
            f"on {outside_fail} outside-expertise cases."
        )
        issues.append("")
    if regression:
        reg_fail = [r for r in regression if r.get("status") != "passed"]
        issues.append("## Live regression subset")
        issues.append("")
        issues.append(
            f"{sum(1 for r in regression if r.get('status') == 'passed')}/{len(regression)} "
            "existing MEM/MULTIUSER/PROACTIVE/TIME/FORMAT/PROFILE keys passed."
        )
        issues.append("")
        for r in reg_fail:
            issues.extend(
                [
                    f"- {r.get('test_key')}: {r.get('status')} — {r.get('failure_summary') or 'see assertion results'}",
                    "",
                ]
            )
    if not flagged:
        issues.append("No capability issues recorded.")
    for r in flagged:
        issues.extend(
            [
                f"## {r['test_id']} ({r['severity']})",
                "",
                f"- Question: {r['question']}",
                f"- Classification: {r['classification']}",
                f"- Expected: {r['expected']}",
                f"- Actual: {r['actual']}",
                f"- Explanation: {r['explanation']}",
                f"- Recommended fix: {r['fix']}",
                "",
            ]
        )
    ISSUES_REPORT.write_text("\n".join(issues) + "\n", encoding="utf-8")
    return {"qa_report": str(QA_REPORT), "issues": str(ISSUES_REPORT)}


def _cell(value: Any, limit: int = 160) -> str:
    text = "" if value is None else str(value)
    text = text.replace("|", "/").replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text or "—"
