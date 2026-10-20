"""Build post-fix QA / benchmark deliverables from executed run JSON.

Harness/reporting only. Live rubric scores never override deterministic
fact, database, or timeline assertions.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_DIR = ROOT / "qa_reports"
MANIFEST = REPORT_DIR / "post_fix_run_manifest.json"
BASELINE_FIXED = "711fea9b-d185-4a3b-ac73-a051f4518309"
BASELINE_FAILED = "dea14aee-aabc-4601-b522-566e99b6b98e"

PRIOR_FAILURES = [
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
]

BLOCKED_LIVE = [
    "CONTEXT-001",
    "CONTEXT-002",
    "CONTEXT-003",
    "CONTEXT-004",
    "CONTEXT-005",
    "CONTEXT-006",
    "CONTEXT-007",
    "CONTEXT-008",
    "CONTEXT-009",
    "CONTEXT-011",
    "CONTEXT-012",
    "FLOW-002",
    "FLOW-004",
    "FLOW-005",
    "FLOW-006",
    "FLOW-009",
    "FORMAT-004",
    "FORMAT-005",
    "FORMAT-006",
    "HUMAN-001",
    "HUMAN-002",
    "HUMAN-003",
    "HUMAN-004",
    "HUMAN-005",
    "HUMAN-006",
    "HUMAN-007",
    "HUMAN-008",
    "HUMAN-009",
    "HUMAN-010",
    "HUMAN-011",
    "HUMAN-012",
    "HUMAN-013",
    "HUMAN-014",
    "HUMAN-015",
    "MEM-011",
    "PROACTIVE-004",
    "PROACTIVE-005",
    "PROACTIVE-006",
    "PROFILE-009",
]

NEW_KEYS = ["HUMAN-016", "HUMAN-017", "HUMAN-018"]

RUBRIC_DIMS = [
    "contextual_relevance",
    "directness_completeness",
    "natural_phrasing",
    "voice_personality",
    "conversational_continuity",
    "emotional_appropriateness",
    "variety",
    "appropriate_self_disclosure",
    "proportional_length",
]

PENALTY_FLAGS = [
    "generic_filler",
    "ignored_or_omitted_part",
    "repetitive_wording",
    "overly_formal_or_robotic",
    "unmotivated_topic_shift",
    "forced_flirting_or_agreement",
    "contradiction_or_unsupported_claim",
]


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _results_by_key(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in report.get("test_results") or []:
        key = row.get("test_key")
        if key:
            out[key] = row
    return out


def _exec_summary(report: dict[str, Any]) -> dict[str, Any]:
    return report.get("executive_summary") or {}


def _transcript_text(row: dict[str, Any]) -> str:
    lines = []
    for turn in row.get("transcript") or []:
        if turn.get("user"):
            lines.append(f"User: {turn['user']}")
        if turn.get("assistant"):
            lines.append(f"Assistant: {turn['assistant']}")
    if not lines and row.get("actual_response"):
        lines.append(f"Assistant: {row['actual_response']}")
    return "\n".join(lines)


def _last_assistant(row: dict[str, Any]) -> str:
    text = ""
    for turn in row.get("transcript") or []:
        if turn.get("assistant"):
            text = str(turn["assistant"])
    return text or str(row.get("actual_response") or "")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _key_state() -> str:
    try:
        from persona_runtime.config import get_settings

        key = get_settings().openai_api_key or ""
    except Exception:
        key = os.environ.get("OPENAI_API_KEY") or ""
    if not key:
        return "unset"
    if key.strip() in {"sk-test-not-real", "test", "dummy"} or key.startswith("sk-test"):
        return "placeholder"
    return "present"


def score_live_rows(rows: list[dict[str, Any]], *, model: str) -> list[dict[str, Any]]:
    """Post-hoc 1-5 rubric. Does not change case pass/fail."""
    if _key_state() != "present":
        return []
    from persona_runtime.llm.client import LLMClient

    judge_model = os.environ.get("QA_JUDGE_MODEL") or model
    client = LLMClient()
    if os.environ.get("QA_JUDGE_MODEL"):
        object.__setattr__(client.settings, "openai_model", judge_model)

    scored: list[dict[str, Any]] = []
    system = (
        "You evaluate a fictional dating-app persona reply. "
        "Score each dimension 1-5. Return JSON only with keys: "
        + ", ".join(RUBRIC_DIMS)
        + ", rationale (object of short strings), flags (object of bools for "
        + ", ".join(PENALTY_FLAGS)
        + "). "
        "Do not reward fabricated certainty. Do not demand slang, emojis, "
        "flirtation, or a question at the end. Casual adult dating-app tone."
    )
    for row in rows:
        payload = {
            "test_key": row.get("test_key"),
            "transcript": _transcript_text(row)[:4000],
        }
        try:
            raw = client.complete_json(
                system=system,
                user=json.dumps(payload),
                temperature=0.0,
            )
            if isinstance(raw, str):
                raw = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            raw = {"error": str(exc)}
        scores = {}
        for dim in RUBRIC_DIMS:
            try:
                scores[dim] = float(raw.get(dim) or 0)
            except (TypeError, ValueError):
                scores[dim] = 0.0
        scored.append(
            {
                "test_key": row.get("test_key"),
                "run_id": row.get("_run_id"),
                "trial": row.get("_trial"),
                "scores": scores,
                "rationale": raw.get("rationale") or {},
                "flags": raw.get("flags") or {},
                "error": raw.get("error"),
                "evaluator_model": judge_model,
                "same_model_as_response": judge_model == model,
            }
        )
    return scored


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    c = {"passed": 0, "failed": 0, "blocked": 0, "skipped": 0, "other": 0}
    for row in rows:
        status = row.get("status") or "other"
        if status in c:
            c[status] += 1
        else:
            c["other"] += 1
    return c


def _assertion_stats(rows: list[dict[str, Any]], prefix: str | None = None, types: set[str] | None = None) -> dict[str, int]:
    stats = {"pass": 0, "fail": 0, "blocked": 0, "needs_review": 0, "not_applicable": 0, "other": 0}
    for row in rows:
        for a in row.get("assertion_results") or []:
            atype = a.get("type") or ""
            if prefix and not atype.startswith(prefix):
                continue
            if types and atype not in types:
                continue
            st = a.get("status") or "other"
            if st in stats:
                stats[st] += 1
            else:
                stats["other"] += 1
    return stats


def _rate(passed: int, eligible: int) -> str:
    if eligible <= 0:
        return "n/a"
    return f"{100.0 * passed / eligible:.1f}% ({passed}/{eligible})"


def _disposition(track_a: str | None, track_b: str | None) -> str:
    if track_a == "failed" or track_b == "failed":
        return "still_reproducible"
    if track_b == "blocked" and track_a == "passed":
        return "verified_fixed_deterministic_live_blocked_or_unscored"
    if track_a == "passed" and (track_b in {None, "passed", "blocked"}):
        if track_b == "passed":
            return "verified_fixed"
        if track_b is None:
            return "verified_fixed_deterministic_only"
        return "verified_fixed_deterministic_live_blocked_or_unscored"
    if track_a == "blocked" or track_b == "blocked":
        return "blocked_unverified"
    if track_a is None and track_b is None:
        return "blocked_unverified"
    return "needs_review"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track-a", default="")
    parser.add_argument("--score-live", action="store_true")
    parser.add_argument("--pytest-summary", default="")
    parser.add_argument("--commands", default="")
    args = parser.parse_args(argv)

    manifest = {"runs": []}
    if MANIFEST.exists():
        manifest = _load_json(MANIFEST)

    reports: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("runs") or []:
        rid = entry.get("run_id")
        if not rid:
            continue
        path = REPORT_DIR / f"{rid}.json"
        if path.exists():
            reports[rid] = _load_json(path)
            reports[rid]["_manifest"] = entry

    track_a_id = args.track_a
    if not track_a_id:
        for entry in manifest.get("runs") or []:
            if entry.get("track") == "A":
                track_a_id = entry.get("run_id")
    track_a = reports.get(track_a_id or "")
    if not track_a and track_a_id:
        path = REPORT_DIR / f"{track_a_id}.json"
        if path.exists():
            track_a = _load_json(path)
            reports[track_a_id] = track_a

    prior_fixed = _load_json(REPORT_DIR / f"{BASELINE_FIXED}.json") if (REPORT_DIR / f"{BASELINE_FIXED}.json").exists() else {}
    prior_fail = _load_json(REPORT_DIR / f"{BASELINE_FAILED}.json") if (REPORT_DIR / f"{BASELINE_FAILED}.json").exists() else {}

    live_rows: list[dict[str, Any]] = []
    for rid, report in reports.items():
        entry = report.get("_manifest") or {}
        if not entry.get("live_llm") and not (report.get("executive_summary") or {}).get("configuration", {}).get("live_llm"):
            continue
        trial = entry.get("trial") or 1
        for row in report.get("test_results") or []:
            cloned = dict(row)
            cloned["_run_id"] = rid
            cloned["_trial"] = trial
            cloned["_set"] = entry.get("set")
            live_rows.append(cloned)

    det_rows = list((track_a or {}).get("test_results") or [])
    det_by_key = _results_by_key(track_a or {})
    live_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in live_rows:
        live_by_key[row.get("test_key")].append(row)

    model = ((track_a or {}).get("executive_summary") or {}).get("model_name") or "gpt-4o-mini"
    if live_rows:
        model = ((_exec_summary(reports.get(live_rows[0].get("_run_id"), {})) or {}).get("model_name") or model)

    scores: list[dict[str, Any]] = []
    if args.score_live and live_rows:
        # Score B3 human-like plus a sample of other live cases (cap cost).
        prefer = [r for r in live_rows if str(r.get("test_key") or "").startswith("HUMAN-")]
        extra = [r for r in live_rows if not str(r.get("test_key") or "").startswith("HUMAN-")]
        to_score = prefer + extra[:20]
        scores = score_live_rows(to_score, model=model)

    score_path = REPORT_DIR / "naturalness_scores.json"
    score_path.write_text(json.dumps(scores, indent=2, default=str), encoding="utf-8")

    # Metrics
    det_counts = _counts(det_rows)
    det_eligible = det_counts["passed"] + det_counts["failed"]
    det_pass_rate = _rate(det_counts["passed"], det_eligible)

    fact_types = {"required_fact_present", "semantic_fact_match", "forbidden_fact_absent", "no_unsupported_claim"}
    fact_stats = _assertion_stats(det_rows, types=fact_types)
    fact_eligible = fact_stats["pass"] + fact_stats["fail"]
    mem_persist = _assertion_stats(det_rows, types={"memory_persisted"})
    mem_retr = _assertion_stats(det_rows, types={"memory_retrieved"})
    mem_sem = _assertion_stats(det_rows, types={"semantic_fact_match"})
    consist = _assertion_stats(det_rows, types={"no_contradiction", "database_state_match"})
    time_stats = _assertion_stats(det_rows, types={"timeline_consistency", "date_time_match", "event_status_match"})

    multi_keys = ["CONTEXT-010", "CONTEXT-015", "FLOW-001", "FORMAT-002", "HUMAN-017"]
    multi_pass = 0
    multi_total = 0
    for key in multi_keys:
        row = det_by_key.get(key)
        if not row:
            continue
        facts = [a for a in (row.get("assertion_results") or []) if a.get("type") == "required_fact_present"]
        if not facts:
            facts = [a for a in (row.get("assertion_results") or []) if a.get("required")]
        multi_total += len(facts) or 1
        multi_pass += sum(1 for a in facts if a.get("status") == "pass") if facts else (1 if row.get("status") == "passed" else 0)

    unsupported = _assertion_stats(det_rows, types={"no_unsupported_claim"})
    unsup_fail = unsupported["fail"]
    unsup_eval = unsupported["pass"] + unsupported["fail"]

    replies = [_norm(_last_assistant(r)) for r in det_rows if _last_assistant(r)]
    how_about = sum(1 for t in replies if t.endswith("how about you?") or "how about you?" in t)
    dupes = 0
    seen: dict[str, int] = {}
    for t in replies:
        if len(t) < 12:
            continue
        seen[t] = seen.get(t, 0) + 1
    for t, n in seen.items():
        if n > 1:
            dupes += n - 1
    comparable = max(1, len([t for t in replies if len(t) >= 12]))

    latencies = [int(r.get("duration_ms") or 0) for r in det_rows if r.get("duration_ms")]
    live_lat = [int(r.get("duration_ms") or 0) for r in live_rows if r.get("duration_ms")]

    def _pct(vals: list[int], p: float) -> str:
        if not vals:
            return "n/a"
        s = sorted(vals)
        idx = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
        return str(s[idx])

    dim_avgs: dict[str, float] = {}
    if scores:
        for dim in RUBRIC_DIMS:
            vals = [s["scores"][dim] for s in scores if s["scores"].get(dim)]
            dim_avgs[dim] = round(statistics.mean(vals), 2) if vals else 0.0
    overall_nat = round(statistics.mean(dim_avgs.values()), 2) if dim_avgs else None
    nat_100 = round((overall_nat / 5.0) * 100, 1) if overall_nat else None

    live_counts = _counts(live_rows)
    live_eligible = live_counts["passed"] + live_counts["failed"]

    # CSV
    csv_path = REPORT_DIR / "benchmark_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "test_key",
                "track",
                "set",
                "trial",
                "status",
                "model",
                "latency_ms",
                "run_id",
                "issue_ids",
                "naturalness_avg",
            ]
        )
        score_ix = {(s.get("test_key"), s.get("run_id"), s.get("trial")): s for s in scores}
        for row in det_rows:
            writer.writerow(
                [
                    row.get("test_key"),
                    "A",
                    "",
                    1,
                    row.get("status"),
                    _exec_summary(track_a or {}).get("model_name"),
                    row.get("duration_ms"),
                    track_a_id,
                    row.get("test_key") if row.get("status") == "failed" else "",
                    "",
                ]
            )
        for row in live_rows:
            sc = score_ix.get((row.get("test_key"), row.get("_run_id"), row.get("_trial")))
            navg = ""
            if sc and sc.get("scores"):
                vals = [v for v in sc["scores"].values() if v]
                navg = round(statistics.mean(vals), 2) if vals else ""
            writer.writerow(
                [
                    row.get("test_key"),
                    "B",
                    row.get("_set"),
                    row.get("_trial"),
                    row.get("status"),
                    model,
                    row.get("duration_ms"),
                    row.get("_run_id"),
                    row.get("test_key") if row.get("status") == "failed" else "",
                    navg,
                ]
            )

    # Failures detail
    failures = [r for r in det_rows if r.get("status") == "failed"]
    live_failures = [r for r in live_rows if r.get("status") == "failed"]

    gating = []
    for row in det_rows + live_rows:
        key = row.get("test_key") or ""
        if row.get("status") != "failed":
            continue
        if key.startswith("MEM-") or "isolation" in (row.get("category") or ""):
            gating.append(f"{key}: memory/privacy-related failure")
        if key.startswith("UNKNOWN-") or key in {"STATE-008", "STATE-015", "UNKNOWN-009"}:
            gating.append(f"{key}: known-fact / contradiction failure")
        if key.startswith("PROACTIVE-"):
            gating.append(f"{key}: proactive/boundary failure")

    if gating:
        readiness = "not ready"
        readiness_why = "Gating failures observed: " + "; ".join(gating[:8])
    elif det_eligible and det_counts["failed"] == 0 and live_rows and live_counts["failed"] == 0:
        readiness = "ready for limited beta with stated limitations"
        readiness_why = (
            "Deterministic eligible tests passed and no live product failures were recorded, "
            "but LLM-as-judge naturalness is uncalibrated and same-model judging applies."
        )
    elif det_eligible and det_counts["failed"] == 0:
        readiness = "promising but not validated"
        readiness_why = (
            "Deterministic eligible tests passed; live naturalness was blocked or incomplete, "
            "so production-model behavior is not validated."
        )
    else:
        readiness = "not ready"
        readiness_why = "Deterministic and/or live eligible failures remain."

    now = datetime.now(timezone.utc).isoformat()
    commands = args.commands or "(see memory.md)"
    pytest_summary = args.pytest_summary or "not recorded"

    # full QA report
    a_sum = _exec_summary(track_a or {})
    pf_sum = _exec_summary(prior_fixed)
    pfail_sum = _exec_summary(prior_fail)

    def _fail_block(row: dict[str, Any], track: str) -> str:
        failed_a = [
            a
            for a in (row.get("assertion_results") or [])
            if a.get("status") in {"fail", "blocked"}
        ]
        bits = [
            f"### {row.get('test_key')} — {row.get('status')} ({track}, {row.get('category')})",
            f"- **Severity:** {row.get('severity') or 'medium'}",
            f"- **Duration:** {row.get('duration_ms')} ms",
            f"- **Failure summary:** {row.get('failure_summary') or 'n/a'}",
            "- **Transcript:**",
            "```",
            _transcript_text(row)[:2500] or "(empty)",
            "```",
        ]
        for a in failed_a[:8]:
            bits.append(
                f"- **Assertion `{a.get('type')}`** status={a.get('status')}: "
                f"expected={a.get('expected')} actual={a.get('actual')} — {a.get('explanation')}"
            )
        bits.append(
            f"- **Repro:** `python -m persona_runtime.qa run --test-key {row.get('test_key')}` "
            f"{'--live-llm' if track == 'B' else ''} on QA_DB_NAME=SarahQA"
        )
        bits.append("- **Root-cause confidence:** low until product code is inspected; report records observed behavior only.")
        return "\n".join(bits)

    prior_disp_lines = []
    for key in PRIOR_FAILURES:
        ta = (det_by_key.get(key) or {}).get("status")
        tb_rows = live_by_key.get(key) or []
        tb = tb_rows[0].get("status") if tb_rows else None
        prior_disp_lines.append(f"| `{key}` | {ta or 'unrun'} | {tb or 'unrun'} | {_disposition(ta, tb)} |")

    live_disp_lines = []
    for key in BLOCKED_LIVE:
        tb_rows = live_by_key.get(key) or []
        tb = tb_rows[0].get("status") if tb_rows else None
        ta = (det_by_key.get(key) or {}).get("status")
        status = "verified_fixed" if tb == "passed" else ("still_blocked" if not tb_rows else tb)
        live_disp_lines.append(f"| `{key}` | {ta or 'unrun'} | {tb or 'unrun'} | {status} |")

    cats = defaultdict(lambda: {"passed": 0, "failed": 0, "blocked": 0, "skipped": 0, "total": 0})
    for row in det_rows:
        c = cats[row.get("category") or "unknown"]
        c["total"] += 1
        st = row.get("status") or "other"
        if st in c:
            c[st] += 1

    full_md = f"""# Full Persona QA Report

## Executive summary

Independent post-fix QA pass on the Sarah dating-app persona (cloned `qa-*` targets only). Tracks are **not** combined into one pass rate.

- **Generated:** {now} (UTC)
- **Persona clock timezone:** Europe/London
- **Clone source (not runtime target):** sarah_taylor_001
- **Runtime targets:** qa-* only
- **Model / provider:** {model} / openai
- **Prompt versions:** integer versions in `persona_runtime/prompts/registry.py` (no prompt hash exists)
- **Git revision:** working tree, git unavailable
- **Readiness:** **{readiness}** — {readiness_why}

### Track A — deterministic (stub LLM)

- **Run ID:** `{track_a_id or 'n/a'}`
- **Executed:** {len(det_rows)}
- **Passed / failed / blocked / skipped:** {det_counts['passed']} / {det_counts['failed']} / {det_counts['blocked']} / {det_counts['skipped']}
- **Deterministic functional pass rate (eligible only):** {det_pass_rate}
- **Blocked live-judge assertions on this track are not passes.**

### Track B — live OpenAI

- **Live case rows:** {len(live_rows)}
- **Passed / failed / blocked / skipped:** {live_counts['passed']} / {live_counts['failed']} / {live_counts['blocked']} / {live_counts['skipped']}
- **Live eligible pass rate:** {_rate(live_counts['passed'], live_eligible)}
- **Evaluator:** same configured model unless `QA_JUDGE_MODEL` was set. Same-model judging is a disclosed limitation.
- **`--trials` harness flag was not used** (it stores only one trial). HUMAN naturalness used three separate filtered runs.

### Baseline comparison

| Run | Passed | Failed | Blocked | Notes |
| --- | ---: | ---: | ---: | --- |
| `{BASELINE_FAILED}` | {pfail_sum.get('passed_count', 'n/a')} | {pfail_sum.get('failed_count', 'n/a')} | {pfail_sum.get('blocked_count', 'n/a')} | Pre-fix baseline (21 failures) |
| `{BASELINE_FIXED}` | {pf_sum.get('passed_count', 'n/a')} | {pf_sum.get('failed_count', 'n/a')} | {pf_sum.get('blocked_count', 'n/a')} | Previous deterministic 100% eligible |
| This Track A `{track_a_id}` | {det_counts['passed']} | {det_counts['failed']} | {det_counts['blocked']} | Includes new HUMAN-016–018 |

Hometown canon remains **Sheffield**. Leeds is university + STATE-015 residence override only. Current residence is **Manchester**.

## Commands actually run

```
{commands}
```

Pytest: {pytest_summary}

## Coverage by category (Track A)

| Category | Total | Passed | Failed | Blocked | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
"""
    for cat, c in sorted(cats.items()):
        full_md += f"| {cat} | {c['total']} | {c['passed']} | {c['failed']} | {c['blocked']} | {c['skipped']} |\n"

    full_md += f"""
## Prior failure disposition (independent retest)

| Test | Track A | Track B | Disposition |
| --- | --- | --- | --- |
{chr(10).join(prior_disp_lines)}

## Previously blocked live-judge keys

| Test | Track A | Track B | Disposition |
| --- | --- | --- | --- |
{chr(10).join(live_disp_lines)}

## New keys (not in the 150-case baseline)

| Test | Track A | Track B trials |
| --- | --- | --- |
"""
    for key in NEW_KEYS:
        tb = ", ".join(f"t{r.get('_trial')}={r.get('status')}" for r in live_by_key.get(key, [])) or "unrun"
        full_md += f"| `{key}` | {(det_by_key.get(key) or {}).get('status') or 'unrun'} | {tb} |\n"

    full_md += "\n## Track A failures\n\n"
    if not failures:
        full_md += "No deterministic product-defect failures were recorded in the executed Track A scope.\n"
    else:
        full_md += "\n\n".join(_fail_block(r, "A") for r in failures)

    full_md += "\n\n## Track B failures\n\n"
    if not live_rows:
        full_md += (
            "Track B was not executed or produced no rows. Live naturalness remains **BLOCKED**. "
            "Rerun: set a real `OPENAI_API_KEY`, `$env:QA_LLM='live'; $env:QA_DB_NAME='SarahQA'; "
            "python scripts/qa_live_track.py --set B1` (then B2 and B3 trials 1–3).\n"
        )
    elif not live_failures:
        full_md += "No live product-defect failures were recorded in the executed Track B scope.\n"
    else:
        full_md += "\n\n".join(_fail_block(r, "B") for r in live_failures)

    full_md += f"""

## Memory, fact, timeline (Track A assertions)

- Known-fact assertion accuracy: {_rate(fact_stats['pass'], fact_eligible)}
- Memory persisted: {_rate(mem_persist['pass'], mem_persist['pass'] + mem_persist['fail'])}
- Memory retrieved: {_rate(mem_retr['pass'], mem_retr['pass'] + mem_retr['fail'])}
- Semantic use in reply: {_rate(mem_sem['pass'], mem_sem['pass'] + mem_sem['fail'])}
- Consistency assertions: {_rate(consist['pass'], consist['pass'] + consist['fail'])}
- Timeline assertions: {_rate(time_stats['pass'], time_stats['pass'] + time_stats['fail'])}
- Multi-part required parts: {_rate(multi_pass, multi_total)}
- Unsupported-claim assertion fails: {unsup_fail} / {unsup_eval}

## Style / repetition (diagnostic, Track A stub text)

- Near-duplicate replies (exact normalized match, length ≥ 12): {dupes} / {comparable}
- Replies containing “how about you?”: {how_about} / {len(replies)}
- These rates describe **DeterministicQALLM** output on Track A, not the live model.

## Latency

- Track A median / p95 ms: {_pct(latencies, 50)} / {_pct(latencies, 95)} (n={len(latencies)})
- Track B median / p95 ms: {_pct(live_lat, 50)} / {_pct(live_lat, 95)} (n={len(live_lat)})
- Token/cost: only recorded if the client logged usage; this report does not invent costs.

## Harness notes (not product defects)

- Added HUMAN-016/017/018 in `definitions.py` for required multi-turn coverage.
- `--trials` remains a no-op after the first iteration; three HUMAN live runs were used instead.
- Consistency ledger may list successive different facts in one multi-part reply under `persona.fact`. Those lines are harness noise unless Sheffield/Manchester/Leeds or job facts actually conflict.
- `tests/test_naturalness_eval.py` was **not** run with `RUN_LLM_EVAL=1` because it targets `sarah_taylor_001`.
- Django UI bubble merge/split was **not** verified against production chat.

## Recommendations

- Calibrate automated naturalness scores with the human review pack before any “human-like” claim.
- Keep live and deterministic pass rates separate in CI.
- If live judging is required for release, add an independent `QA_JUDGE_MODEL` (not present today).
"""
    (REPORT_DIR / "full_qa_report.md").write_text(full_md, encoding="utf-8")

    dim_table = ""
    for dim in RUBRIC_DIMS:
        dim_table += f"| {dim} | {dim_avgs.get(dim, 'n/a')} |\n"

    high_ex = ""
    low_ex = ""
    if scores:
        def _avg(s):
            vals = [v for v in s.get("scores", {}).values() if v]
            return statistics.mean(vals) if vals else 0

        ranked = sorted(scores, key=_avg, reverse=True)
        if ranked:
            high_ex = f"`{ranked[0].get('test_key')}` avg={_avg(ranked[0]):.2f}: {ranked[0].get('rationale')}"
            low_ex = f"`{ranked[-1].get('test_key')}` avg={_avg(ranked[-1]):.2f}: {ranked[-1].get('rationale')}"

    bench = f"""# Persona Benchmark Report

## One-page summary

- **Readiness:** **{readiness}**
- **Why:** {readiness_why}
- **Track A eligible pass rate:** {det_pass_rate}
- **Track B eligible pass rate:** {_rate(live_counts['passed'], live_eligible)} ({len(live_rows)} live rows)
- **Human-style estimate (1–5):** {overall_nat if overall_nat is not None else 'n/a'}  | experimental 0–100: {nat_100 if nat_100 is not None else 'n/a'}
- **Sample scored replies:** {len(scores)}
- **Evaluator model:** {scores[0]['evaluator_model'] if scores else 'not run'} (same as response model unless QA_JUDGE_MODEL set)
- **Gating failures:** {'; '.join(gating) if gating else 'none recorded'}
- **This is not a scientifically validated human-likeness metric.**

## Methodology

Track A runs the real LangGraph pipeline with `DeterministicQALLM` on isolated `qa-*` clones (`QA_DB_NAME=SarahQA`). Track B uses the configured OpenAI model for generation and the existing pass/fail live judge, plus an optional post-hoc 1–5 rubric that **cannot** override fact/DB/timeline assertions. `--trials` is unused because the runner stores one trial per case; HUMAN conversations were repeated as three filtered runs.

Limitations: same-model judge bias; no prompt hash; no invented token costs; UI rendering untested; `sarah_taylor_001` never used as a runtime target.

## Per-dimension naturalness (live scored subset)

| Dimension | Mean (1–5) |
| --- | --- |
{dim_table or '| (no live scores) | n/a |'}

High example: {high_ex or 'n/a'}

Low example: {low_ex or 'n/a'}

## Functional metrics (Track A)

| Metric | Value |
| --- | --- |
| Deterministic eligible pass rate | {det_pass_rate} |
| Known-fact assertions | {_rate(fact_stats['pass'], fact_eligible)} |
| Multi-part completeness | {_rate(multi_pass, multi_total)} |
| Memory persist | {_rate(mem_persist['pass'], mem_persist['pass'] + mem_persist['fail'])} |
| Memory retrieve | {_rate(mem_retr['pass'], mem_retr['pass'] + mem_retr['fail'])} |
| Memory used in reply | {_rate(mem_sem['pass'], mem_sem['pass'] + mem_sem['fail'])} |
| Consistency | {_rate(consist['pass'], consist['pass'] + consist['fail'])} |
| Timeline | {_rate(time_stats['pass'], time_stats['pass'] + time_stats['fail'])} |
| Unsupported-claim fail rate | {_rate(unsup_fail, unsup_eval)} |
| Reply exact-dup rate (stub) | {dupes} / {comparable} |
| Track A latency median/p95 ms | {_pct(latencies, 50)} / {_pct(latencies, 95)} |
| Track B latency median/p95 ms | {_pct(live_lat, 50)} / {_pct(live_lat, 95)} |

## Optional experimental PQI

Not published as an industry benchmark. If used internally: 0.35 * deterministic_eligible + 0.20 * fact + 0.15 * memory_retrieve + 0.15 * (naturalness/5) + 0.15 * consistency, **but any gating failure sets readiness to not ready** regardless of the index.

## Human evaluation still required

Use `qa_reports/human_review_pack.md` to calibrate automated 1–5 scores. Do not treat this file as human-reviewed.
"""
    (REPORT_DIR / "benchmark_report.md").write_text(bench, encoding="utf-8")

    # Human review pack
    pack_rows = []
    source = live_rows or det_rows
    wanted = [
        "HUMAN-001",
        "HUMAN-004",
        "HUMAN-011",
        "HUMAN-013",
        "HUMAN-016",
        "HUMAN-017",
        "HUMAN-018",
        "CONTEXT-010",
        "CONTEXT-015",
        "MEM-012",
        "MEM-013",
        "STATE-015",
        "FLOW-001",
        "UNKNOWN-009",
        "PROACTIVE-007",
    ]
    by_key_any = {r.get("test_key"): r for r in source}
    for i, key in enumerate(wanted, start=1):
        row = by_key_any.get(key)
        if not row:
            continue
        pack_rows.append((f"R{i:02d}", key, row))

    pack = """# Human review pack (anonymized)

Blinded sample for calibrating automated naturalness scores. **Model scores in other reports are not human-reviewed.**

## Instructions

1. Do not look up the original test key until after scoring.
2. Score each conversation 1–5 on every dimension below.
3. Flag any privacy leak, fabricated fact, pressure to reply, or contradiction.
4. Casual adult dating-app tone: warm, relaxed, curious, playful when appropriate. Do not require slang, emojis, flirtation, or a closing question.

## Rubric (1–5)

| Dimension | 1 | 3 | 5 |
| --- | --- | --- | --- |
| Contextual relevance | Ignores the user | Partial | Answers the actual turn |
| Directness / completeness | Omits asked parts | Partial slots | All asked parts |
| Natural phrasing | Assistant/FAQ voice | Mixed | Dating-app human |
| Voice / personality | Generic | Some Sarah | Consistent Sarah |
| Continuity | Drops thread | Occasional | Resolves references |
| Emotional appropriateness | Jarring | Adequate | Fits user affect |
| Variety | Mechanical repeats | Some variation | Natural variation |
| Self-disclosure | None or invented | Safe | Configured or clearly fictional-authorized |
| Length / bubbles | Wall or empty | Slightly off | Proportional |

## Score sheet

| Blind ID | Contextual | Directness | Natural | Voice | Continuity | Emotion | Variety | Disclosure | Length | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
"""
    for bid, _key, _row in pack_rows:
        pack += f"| {bid} |  |  |  |  |  |  |  |  |  |  |\n"

    pack += "\n## Transcripts\n\n"
    for bid, key, row in pack_rows:
        pack += f"### {bid}\n\n"
        pack += f"<!-- mapping {bid} = {key} ; unblind after scoring -->\n\n"
        pack += "```\n" + (_transcript_text(row)[:3500] or "(empty)") + "\n```\n\n"

    pack += (
        "\nOriginal keys (unblind after scoring): "
        + ", ".join(f"{bid}={key}" for bid, key, _ in pack_rows)
        + "\n"
    )
    (REPORT_DIR / "human_review_pack.md").write_text(pack, encoding="utf-8")

    print(
        json.dumps(
            {
                "track_a": track_a_id,
                "det_counts": det_counts,
                "live_rows": len(live_rows),
                "live_counts": live_counts,
                "scores": len(scores),
                "readiness": readiness,
                "written": [
                    "qa_reports/full_qa_report.md",
                    "qa_reports/benchmark_report.md",
                    "qa_reports/human_review_pack.md",
                    "qa_reports/benchmark_results.csv",
                    "qa_reports/naturalness_scores.json",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
