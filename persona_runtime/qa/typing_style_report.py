"""Write persona_typing_style_qa_report.md and persona_typing_style_issues.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo.database import Database

from persona_runtime.graph.bubbles import contains_emoji
from persona_runtime.qa.repository import QARepository
from persona_runtime.qa.typing_style_score import fact_failures_from_assertions, score_reply

ROOT = Path(__file__).resolve().parent.parent.parent
QA_REPORT = ROOT / "persona_typing_style_qa_report.md"
ISSUES_REPORT = ROOT / "persona_typing_style_issues.md"

_BEFORE = [
    ("what are you doing right now?", "I am currently working on a financial report.", "just working on the monthly reports atm"),
    ("what did you have for lunch?", "I am just having my lunch before returning to work.", "had some pasta earlier"),
    ("do you know python?", "I do not know much about that subject.", "i know a little about it, but its not really my area"),
]


def _cell(value: Any) -> str:
    text = str(value if value is not None else "").replace("\n", " ").replace("|", "\\|").strip()
    return text or "—"


def _rows_from_run(db: Database, run_id: str) -> list[dict[str, Any]]:
    repo = QARepository(db)
    results = [r for r in repo.list_results(run_id) if str(r.get("test_key") or "").startswith("STYLE-")]
    rows: list[dict[str, Any]] = []
    for result in results:
        steps = repo.list_step_results(result["result_id"])
        user_q = " | ".join(s.get("user_input") or "" for s in steps if s.get("user_input"))
        reply = result.get("actual_response") or " | ".join(
            s.get("actual_response") or "" for s in steps if s.get("actual_response")
        )
        asserts = list(result.get("assertion_results") or [])
        scored = score_reply(
            reply or "",
            emoji=contains_emoji(reply or ""),
            fact_failures=fact_failures_from_assertions(asserts),
        )
        if result.get("status") == "blocked" and not (reply or "").strip():
            scored["overall"] = "Blocked"
            scored["severity"] = "needs_review"
            scored["explanation"] = result.get("failure_summary") or "Live generation did not run."
            scored["fix"] = "Re-run with QA_LLM=live and a configured model."
        elif result.get("status") == "failed" and scored["overall"] == "Pass":
            scored["overall"] = "Fail"
            scored["severity"] = scored["severity"] if scored["severity"] != "none" else "medium"
            summary = result.get("failure_summary") or "A pipeline assertion failed."
            scored["explanation"] = summary
            scored["factual"] = "Fail"
            scored["fix"] = "Inspect the failing assertion. Do not relax the fact to chase tone."
        rows.append(
            {
                "test_id": result.get("test_key"),
                "user_input": user_q,
                "actual": (reply or "").replace("\n", " / ").strip(),
                **scored,
            }
        )
    return rows


def _render(rows: list[dict[str, Any]], *, heading_note: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    passed = sum(1 for r in rows if r.get("overall") == "Pass")
    report = [
        "# Persona typing style QA report",
        "",
        f"{heading_note} Scored {passed}/{len(rows)} at {now}.",
        "",
        "A pass needs the line to read like a chat message. Lowercase or one slang word is not enough, "
        "and a misspelling is not a pass by itself.",
        "",
        "## Before and after",
        "",
        "The before column is the polished register the old prompt produced. "
        "The after column is an acceptable texting line, not a required verbatim reply.",
        "",
        "| User input | Previous register | Acceptable texting |",
        "|---|---|---|",
    ]
    for user, before, after in _BEFORE:
        report.append(f"| {_cell(user)} | {_cell(before)} | {_cell(after)} |")
    report.extend(
        [
            "",
            "## Results",
            "",
            "| Test ID | User input | Actual Sarah response | Emoji | Natural style | Punctuation | Slang | Typo | Factual | Overall | Severity | Explanation | Fix |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    issues = [
        "# Persona typing style issues",
        "",
        f"{heading_note} Written {now}.",
        "",
    ]
    open_issues = [r for r in rows if r.get("overall") != "Pass"]
    if not open_issues:
        issues.append("No open style issues in this run.")
    else:
        issues.append("| Test ID | Severity | Overall | Explanation | Fix |")
        issues.append("|---|---|---|---|---|")
    for row in rows:
        report.append(
            "| "
            + " | ".join(
                _cell(row.get(key))
                for key in (
                    "test_id",
                    "user_input",
                    "actual",
                    "emoji",
                    "natural",
                    "punctuation",
                    "slang",
                    "typo",
                    "factual",
                    "overall",
                    "severity",
                    "explanation",
                    "fix",
                )
            )
            + " |"
        )
        if row.get("overall") != "Pass":
            issues.append(
                "| "
                + " | ".join(
                    _cell(row.get(key))
                    for key in ("test_id", "severity", "overall", "explanation", "fix")
                )
                + " |"
            )
    return "\n".join(report) + "\n", "\n".join(issues) + "\n"


def write_typing_style_reports(db: Database, run_id: str) -> dict[str, str]:
    rows = _rows_from_run(db, run_id)
    report, issues = _render(rows, heading_note=f"Run `{run_id}`.")
    QA_REPORT.write_text(report, encoding="utf-8")
    ISSUES_REPORT.write_text(issues, encoding="utf-8")
    return {"report": str(QA_REPORT), "issues": str(ISSUES_REPORT)}


def write_blocked_typing_style_reports(reason: str) -> dict[str, str]:
    """Record that live replies were not generated. Does not invent Sarah's text."""
    rows = [
        {
            "test_id": f"STYLE-{i:03d}",
            "user_input": "",
            "actual": "",
            "emoji": "—",
            "natural": "—",
            "punctuation": "—",
            "slang": "—",
            "typo": "—",
            "factual": "—",
            "overall": "Blocked",
            "severity": "needs_review",
            "explanation": reason,
            "fix": "Re-run scripts/typing_style_qa.py with QA_LLM=live.",
        }
        for i in range(1, 25)
    ]
    report, issues = _render(rows, heading_note="Live generation was not run.")
    QA_REPORT.write_text(report, encoding="utf-8")
    ISSUES_REPORT.write_text(issues, encoding="utf-8")
    return {"report": str(QA_REPORT), "issues": str(ISSUES_REPORT)}
