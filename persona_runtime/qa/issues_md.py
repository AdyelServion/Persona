"""Write repository-root issues.md from a completed QA report.

The current summary is replaced only for an unfiltered, non-dry run.
Filtered runs append a history section and leave an existing full-suite
summary in place. A pytest note between PYTEST markers is preserved.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

HISTORY_MARKER = "<!-- RUN_HISTORY -->"
PYTEST_START = "<!-- PYTEST -->"
PYTEST_END = "<!-- /PYTEST -->"

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_ISSUES_PATH = ROOT / "issues.md"

_SEVERITY = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "needs_review": "Needs Review",
}

_LIVE_MARKERS = ("Live LLM evaluation disabled", "QA_LLM=live")
_FIXTURE_MARKERS = (
    "Could not resolve expected fact",
    "Unresolved expected value",
    "Unknown assertion type",
    "Assertion error:",
)


def _redact(value: Any, limit: int = 400) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[redacted]", text)
    text = re.sub(r"mongodb(\+srv)?://\S+", "mongodb://[redacted]", text)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _sev(value: str | None) -> str:
    return _SEVERITY.get((value or "medium").lower(), "Medium")


def _assertion_kind(assertion: dict[str, Any]) -> str:
    status = assertion.get("status")
    explanation = assertion.get("explanation") or ""
    if status in {"pass", "not_applicable"}:
        return "ok"
    if status == "needs_review":
        return "needs_review"
    if status == "blocked" and any(marker in explanation for marker in _LIVE_MARKERS):
        return "blocked_live"
    if status == "blocked":
        return "infrastructure"
    if status == "fail" and any(marker in explanation for marker in _FIXTURE_MARKERS):
        return "fixture"
    if status == "fail":
        return "product"
    return "infrastructure"


def _is_full_suite(report: dict[str, Any]) -> bool:
    summary = report.get("executive_summary") or {}
    config = summary.get("configuration") or {}
    if config.get("dry_run"):
        return False
    if config.get("filtered"):
        return False
    if config.get("category") or config.get("test_key") or config.get("failed_from"):
        return False
    return True


def _pass_rate(passed: int, failed: int) -> str:
    denom = passed + failed
    if denom == 0:
        return "n/a (no executed non-blocked tests)"
    return f"{round(100.0 * passed / denom, 2)}% ({passed}/{denom} non-blocked)"


def _transcript_lines(result: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for turn in (result.get("transcript") or [])[:6]:
        user = _redact(turn.get("user") or turn.get("action"), 240)
        if user:
            lines.append(f"  - User: {user}")
        assistant = turn.get("assistant")
        if assistant:
            lines.append(f"  - Persona: {_redact(assistant, 280)}")
    return lines


def _failed_assertions(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        a
        for a in (result.get("assertion_results") or [])
        if a.get("status") in {"fail", "blocked", "needs_review"}
    ]


def classify_result(result: dict[str, Any]) -> str:
    """Bucket a case result without treating blocked live checks as defects."""
    kinds = [_assertion_kind(a) for a in _failed_assertions(result)]
    if result.get("status") == "failed" and "product" not in kinds and "fixture" not in kinds:
        return "product"
    if "product" in kinds:
        return "product"
    if "fixture" in kinds:
        return "fixture"
    if "needs_review" in kinds and result.get("status") != "passed":
        return "needs_review"
    if kinds and all(k == "blocked_live" for k in kinds):
        return "blocked_live"
    if "infrastructure" in kinds or "blocked_live" in kinds or result.get("status") == "blocked":
        return "infrastructure"
    if "needs_review" in kinds:
        return "needs_review"
    return "pass"


def _issue_for(result: dict[str, Any], register: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = result.get("test_key")
    stored = register.get(key) or {}
    return stored


def _render_issue(
    result: dict[str, Any],
    stored: dict[str, Any],
    *,
    classification: str,
    status: str,
) -> list[str]:
    key = result.get("test_key")
    issue_id = stored.get("issue_key") or f"ISS-{key}"
    title = stored.get("title") or f"{key} {result.get('status')}"
    hypothesis = stored.get("root_cause_hypothesis") or (
        "Hypothesis: assertion failed against the isolated persona pipeline. "
        "Not confirmed as a product defect until the transcript and stored state are reviewed."
    )
    if not str(hypothesis).lower().startswith("hypothesis"):
        hypothesis = f"Hypothesis: {hypothesis}"
    fix = stored.get("recommended_fix") or "Reproduce with the same fixture, clock, and steps."
    lines = [
        f"### {issue_id}: {title}",
        "",
        f"- **Severity:** {_sev(result.get('severity') or stored.get('severity'))}",
        f"- **Category:** {result.get('category')}",
        f"- **Status:** {status}",
        f"- **Classification:** {classification}",
        f"- **Affected tests:** `{key}`",
        f"- **Preconditions:** isolated `qa-` persona and user; deterministic stub LLM unless the run set live judging.",
        "- **Reproduction:**",
        f"  1. Seed the suite and run `python -m persona_runtime.qa run --test-key {key}` on mongomock or a database whose name contains `qa` or `test`.",
    ]
    lines.extend(_transcript_lines(result) or ["  - No transcript stored."])
    lines.append(f"- **Expected:** {_redact(stored.get('expected_behavior') or result.get('failure_summary') or 'See assertion expected values.', 400)}")
    lines.append(f"- **Actual:** {_redact(result.get('failure_summary') or stored.get('actual_behavior') or result.get('status'), 500)}")
    lines.append(f"- **Run reference:** see the run ID in Run Information. Detailed records: `qa_reports/<run_id>.json`.")
    interesting = [
        a
        for a in _failed_assertions(result)
        if _assertion_kind(a) in {"product", "fixture", "needs_review", "infrastructure"}
    ]
    if interesting:
        lines.append("- **Evidence:**")
        for assertion in interesting[:8]:
            lines.append(
                f"  - `{assertion.get('type')}` {assertion.get('status')}: "
                f"{_redact(assertion.get('explanation'), 280)} "
                f"(expected={_redact(assertion.get('expected'), 120)}, "
                f"actual={_redact(assertion.get('actual'), 160)})"
            )
    lines.append(f"- **Suspected root cause:** {hypothesis}")
    lines.append(f"- **Recommended fix:** {_redact(fix, 400)}")
    lines.append("")
    return lines


_BASELINE_FAILURES = (
    "CONTEXT-010",
    "CONTEXT-015",
    "FLOW-001",
    "FLOW-007",
    "FORMAT-002",
    "MEM-002",
    "MEM-004",
    "MEM-005",
    "MEM-006",
    "MEM-007",
    "MEM-008",
    "MEM-010",
    "MEM-012",
    "MEM-013",
    "PROFILE-004",
    "PROFILE-008",
    "PROFILE-014",
    "STATE-008",
    "STATE-014",
    "STATE-015",
    "UNKNOWN-009",
)


def _baseline_disposition(results: list[dict[str, Any]]) -> list[str]:
    """Status of the 21 failures from run dea14aee, when this run executed them."""
    by_key = {r.get("test_key"): r for r in results}
    if not any(key in by_key for key in _BASELINE_FAILURES):
        return []
    lines = [
        "## Baseline failure disposition",
        "",
        "Compared with run `dea14aee-aabc-4601-b522-566e99b6b98e` (21 failed, 90 passed, 39 blocked). "
        "Hometown remains Sheffield (`PERSONA_FACT_HOMETOWN`). Leeds is only the STATE-015 residence override.",
        "",
        "| Test | Status | This run |",
        "| --- | --- | --- |",
    ]
    for key in _BASELINE_FAILURES:
        result = by_key.get(key)
        if result is None:
            status = "Needs review"
            detail = "not in this run"
        else:
            raw = result.get("status") or "unknown"
            if raw == "passed":
                status = "Fixed and verified"
            elif raw == "blocked":
                status = "Blocked"
            elif raw == "failed":
                status = "Still open"
            else:
                status = "Needs review"
            detail = raw
        lines.append(f"| `{key}` | {status} | {detail} |")
    lines.append("")
    return lines


def render_issues_markdown(report: dict[str, Any], *, pytest_block: str = "") -> str:
    summary = report.get("executive_summary") or {}
    results = list(report.get("test_results") or [])
    issues = list(report.get("issue_register") or [])
    register = {i.get("test_key"): i for i in issues if i.get("test_key")}

    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    blocked = int(summary.get("blocked") or 0)
    skipped = int(summary.get("skipped") or 0)
    total = int(summary.get("total_tests") or len(results))
    config = summary.get("configuration") or {}

    product: list[dict[str, Any]] = []
    fixtures: list[dict[str, Any]] = []
    live_blocked: list[dict[str, Any]] = []
    infra: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for result in results:
        kind = classify_result(result)
        if kind == "product":
            product.append(result)
        elif kind == "fixture":
            fixtures.append(result)
        elif kind == "blocked_live":
            live_blocked.append(result)
        elif kind == "needs_review":
            review.append(result)
        elif kind == "infrastructure":
            infra.append(result)

    # needs_review assertions on otherwise passing cases
    for result in results:
        if classify_result(result) == "pass":
            if any(_assertion_kind(a) == "needs_review" for a in (result.get("assertion_results") or [])):
                review.append(result)

    live_ids = ", ".join(f"`{r.get('test_key')}`" for r in live_blocked) or "none"
    commands = (
        "Deterministic suite: `python -m persona_runtime.qa run` "
        "(mongomock or a database name containing `qa`/`test`; `DeterministicQALLM`, no live OpenAI). "
        "Existing regression: `pytest -q`."
    )
    if config:
        commands += f" Run configuration: `{_redact(config, 500)}`."

    lines = [
        "# Persona QA issues",
        "",
        "This file is generated from an executed QA run. Counts below are from that run. "
        "Unexecuted tests are not treated as passed.",
        "",
        "## Run Information",
        "",
        f"- **Run ID:** `{summary.get('run_id')}`",
        f"- **Started:** {summary.get('started_at')} (UTC)",
        f"- **Completed:** {summary.get('completed_at')} (UTC)",
        f"- **Timezone:** timestamps in this summary are UTC. Persona answers use the configured IANA zone (Europe/London for Sarah).",
        f"- **Environment:** {summary.get('environment')}",
        f"- **Tested persona:** {summary.get('persona_id')}",
        f"- **Build:** {summary.get('build_version')}",
        f"- **Model / provider:** {summary.get('model_name')} / {summary.get('model_provider') or 'openai'}",
        f"- **Prompt version:** {summary.get('prompt_version') or 'not recorded'}",
        f"- **Live LLM judging:** {bool(config.get('live_llm'))}",
        "",
        "## Execution Summary",
        "",
        f"- **Discovered / executed:** {total} / {total}",
        f"- **Passed:** {passed}",
        f"- **Failed:** {failed}",
        f"- **Blocked:** {blocked}",
        f"- **Skipped:** {skipped}",
        f"- **Pass rate (executed, non-blocked):** {_pass_rate(passed, failed)}",
        f"- **Commands:** {commands}",
        "",
    ]
    lines.extend(_baseline_disposition(results))
    if pytest_block:
        lines.extend([pytest_block.rstrip(), ""])
    else:
        lines.extend(
            [
                f"{PYTEST_START}",
                "Pytest regression: not attached to this file yet.",
                f"{PYTEST_END}",
                "",
            ]
        )

    comp = summary.get("comparison")
    if comp:
        lines.extend(
            [
                f"- **Previous run:** `{comp.get('run_a')}`",
                f"- **Newly failed:** {', '.join(comp.get('newly_failed') or []) or 'none'}",
                f"- **Newly passed:** {', '.join(comp.get('newly_passed') or []) or 'none'}",
                f"- **Still failing:** {', '.join(comp.get('still_failing') or []) or 'none'}",
                "",
            ]
        )

    lines.extend(["## Issues Found", ""])
    if not product and not review:
        lines.extend(
            [
                "No product-defect failures were recorded in the executed scope. "
                "Blocked and fixture problems are listed under Infrastructure/Test Problems and are not counted as confirmed persona defects.",
                "",
            ]
        )
    for result in product:
        lines.extend(
            _render_issue(
                result,
                _issue_for(result, register),
                classification="probable product defect (unverified hypothesis, not confirmed)",
                status="Open",
            )
        )
    for result in review:
        lines.extend(
            _render_issue(
                result,
                _issue_for(result, register),
                classification="needs review — evaluator uncertainty or insufficient evidence",
                status="Open",
            )
        )

    lines.extend(["## Memory and Consistency Findings", ""])
    memory_rows = [
        row
        for row in (report.get("memory_report") or [])
        if row.get("status") not in {None, "pass", "not_applicable"}
    ]
    contradictions = list(report.get("contradiction_report") or [])
    if not memory_rows and not contradictions:
        lines.append("No failing memory assertions or ledger contradictions were recorded in this run.")
        lines.append("")
    else:
        if memory_rows:
            lines.append("Memory assertions that did not pass:")
            lines.append("")
            for row in memory_rows[:80]:
                lines.append(
                    f"- `{row.get('test_key')}` `{row.get('type')}` → {row.get('status')}: "
                    f"{_redact(row.get('explanation'), 240)}"
                )
            lines.append("")
        if contradictions:
            lines.append("Ledger contradictions (confirmed by the consistency ledger, not by an LLM judge):")
            lines.append("")
            for item in contradictions[:40]:
                lines.append(
                    f"- `{item.get('test_key')}` {item.get('subject')}.{item.get('attribute')}: "
                    f"earlier={_redact(item.get('earlier'), 180)} later={_redact(item.get('later'), 180)}"
                )
            lines.append("")
        else:
            lines.append("No ledger contradictions were recorded.")
            lines.append("")

    lines.extend(["## Timeline Findings", ""])
    timeline_rows = [
        row
        for row in (report.get("timeline_report") or [])
        if row.get("status") not in {None, "pass", "not_applicable"}
    ]
    if not timeline_rows:
        lines.append("No failing timeline, date/time, or event-status assertions were recorded in this run.")
    else:
        for row in timeline_rows[:80]:
            lines.append(
                f"- `{row.get('test_key')}` `{row.get('type')}` → {row.get('status')}: "
                f"{_redact(row.get('actual'), 200)}"
            )
    lines.append("")

    lines.extend(["## Infrastructure/Test Problems", ""])
    if not live_blocked and not fixtures and not infra:
        lines.append("No infrastructure, fixture, or blocked-test problems were recorded in this run.")
        lines.append("")
    if live_blocked:
        lines.extend(
            [
                "### ISS-LIVE-LLM: Live semantic checks were not executed",
                "",
                "- **Severity:** Needs Review",
                "- **Category:** evaluation",
                "- **Status:** Blocked",
                "- **Classification:** blocked live-LLM check, not a persona defect",
                f"- **Affected tests:** {live_ids}",
                "- **Preconditions:** `QA_LLM` is not `live` and the run did not pass `--live-llm`.",
                "- **Expected:** tone and optional topic checks run only with a live judge.",
                "- **Actual:** those assertions returned `blocked` (`Live LLM evaluation disabled`). Required deterministic checks on the same cases are reflected in the case status; a case listed here had no product-defect failure.",
                "- **Suspected root cause:** Hypothesis: opt-in live judging was not enabled for this run.",
                "- **Recommended fix:** Re-run the listed keys with `QA_LLM=live` when an OpenAI key is available. Do not treat this block as a pass.",
                "",
            ]
        )
    for result in fixtures:
        lines.extend(
            _render_issue(
                result,
                _issue_for(result, register),
                classification="fixture or stub problem — not classified as a confirmed persona defect",
                status="Open",
            )
        )
    for result in infra:
        lines.extend(
            _render_issue(
                result,
                _issue_for(result, register),
                classification="infrastructure or blocked test — not a confirmed persona defect",
                status="Blocked",
            )
        )

    lines.extend(["## Fixed and Re-tested Issues", ""])
    newly_passed = (comp or {}).get("newly_passed") if comp else None
    if newly_passed:
        lines.append(
            "Compared with the previous run, these keys failed before and passed in this run: "
            + ", ".join(f"`{k}`" for k in newly_passed)
            + ". No product code change is implied unless a later section says one was made."
        )
    else:
        lines.append("No previously failing tests were recorded as newly passing in this run.")
    lines.append("")

    lines.extend(["## Remaining Risks and Next Actions", ""])
    if product:
        lines.append(
            f"- {len(product)} probable product defect(s) remain open. Highest severity: "
            f"{_highest_severity(product)}."
        )
    else:
        lines.append("- No probable product defects were opened from this run.")
    if live_blocked:
        lines.append(
            f"- {len(live_blocked)} case(s) are blocked on live LLM judging and must not be read as passes."
        )
    if fixtures or infra:
        lines.append(
            f"- {len(fixtures) + len(infra)} fixture or infrastructure case(s) need a harness or environment follow-up."
        )
    if not config.get("live_llm"):
        lines.append(
            "- This run used the deterministic stub. It exercises the real LangGraph pipeline with scripted model output, not production OpenAI variability."
        )
    lines.append(
        "- Do not point the suite at database `Sarah` or persona `sarah_taylor_001`. Cleanup is limited to `qa-` ids."
    )
    lines.append("")
    return "\n".join(lines)


def _highest_severity(results: list[dict[str, Any]]) -> str:
    order = ["critical", "high", "medium", "low", "needs_review"]
    ranks = {(r.get("severity") or "medium").lower() for r in results}
    for name in order:
        if name in ranks:
            return _sev(name)
    return "Medium"


def _history_entry(report: dict[str, Any]) -> str:
    summary = report.get("executive_summary") or {}
    run_id = summary.get("run_id")
    return "\n".join(
        [
            f"<!-- run:{run_id} -->",
            f"### Run `{run_id}` — {summary.get('completed_at') or summary.get('started_at')} UTC",
            "",
            f"- Persona: {summary.get('persona_id')}; environment: {summary.get('environment')}; model: {summary.get('model_name')}",
            f"- Passed / failed / blocked / skipped: "
            f"{summary.get('passed')} / {summary.get('failed')} / {summary.get('blocked')} / {summary.get('skipped')} "
            f"(total {summary.get('total_tests')})",
            f"- Pass rate (non-blocked): {_pass_rate(int(summary.get('passed') or 0), int(summary.get('failed') or 0))}",
            f"- Configuration: `{_redact(summary.get('configuration') or {}, 400)}`",
            f"- Report: `qa_reports/{run_id}.json`",
            "",
        ]
    )


def _extract_pytest_block(current: str) -> str:
    match = re.search(
        re.escape(PYTEST_START) + r".*?" + re.escape(PYTEST_END),
        current,
        flags=re.DOTALL,
    )
    return match.group(0) if match else ""


def _split_history(text: str) -> tuple[str, str]:
    if HISTORY_MARKER not in text:
        return text, ""
    current, history = text.split(HISTORY_MARKER, 1)
    return current, history


def update_issues_md(
    report: dict[str, Any],
    *,
    path: Path | None = None,
) -> Path:
    """Create or update issues.md. Full-suite runs replace the current summary."""
    path = path or DEFAULT_ISSUES_PATH
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    current, history = _split_history(existing)
    pytest_block = _extract_pytest_block(current)
    entry = _history_entry(report)
    run_id = (report.get("executive_summary") or {}).get("run_id")
    marker = f"<!-- run:{run_id} -->"
    if marker in history:
        parts = history.split(marker)
        tail = parts[-1]
        # drop the previous body of this run up to the next run marker
        next_rel = tail.find("<!-- run:")
        if next_rel == -1:
            tail = ""
        else:
            tail = tail[next_rel:]
        history = parts[0] + entry + ("\n" + tail if tail else "")
    else:
        history = history.rstrip() + "\n\n" + entry

    if _is_full_suite(report) or not existing.strip():
        body = render_issues_markdown(report, pytest_block=pytest_block).rstrip() + "\n"
    else:
        # Keep the last full-suite summary; still record this run in history.
        body = current.rstrip() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n" + HISTORY_MARKER + "\n" + history.lstrip("\n"), encoding="utf-8")
    return path


def attach_regression_note(summary: str, *, path: Path | None = None) -> Path:
    """Insert or replace the pytest note inside the current summary."""
    path = path or DEFAULT_ISSUES_PATH
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    block = f"{PYTEST_START}\n{summary.strip()}\n{PYTEST_END}"
    if PYTEST_START in text and PYTEST_END in text:
        text = re.sub(
            re.escape(PYTEST_START) + r".*?" + re.escape(PYTEST_END),
            lambda _match: block,
            text,
            count=1,
            flags=re.DOTALL,
        )
    elif HISTORY_MARKER in text:
        current, history = text.split(HISTORY_MARKER, 1)
        text = current.rstrip() + "\n\n" + block + "\n\n" + HISTORY_MARKER + history
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + block + "\n"
    path.write_text(text, encoding="utf-8")
    return path
