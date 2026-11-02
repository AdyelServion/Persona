#!/usr/bin/env python
"""Live capability QA: CAP-001..015, a regression subset, pytest, and markdown reports."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QA_DB_NAME", "SarahQA")
os.environ["QA_LLM"] = "live"

import mongomock

from persona_runtime.config import get_settings, reset_settings_cache
from persona_runtime.db import ensure_indexes, set_client_for_tests
from persona_runtime.llm.client import LLMClient
from persona_runtime.persona.loader import PersonaIngestionService
from persona_runtime.prompts.registry import PromptRepository
from persona_runtime.qa.capability_report import write_capability_reports
from persona_runtime.qa.fixtures.definitions import write_json_fixtures
from persona_runtime.qa.runner import run_suite
from persona_runtime.qa.safety import assert_safe_database
from persona_runtime.qa.seed import seed_suite

CAP_KEYS = [f"CAP-{i:03d}" for i in range(1, 16)]
REGRESSION_KEYS = [
    "MEM-001",
    "MEM-011",
    "MULTIUSER-001",
    "PROACTIVE-004",
    "TIME-001",
    "FORMAT-004",
    "PROFILE-005",
]


def _pytest() -> dict:
    cmd = [sys.executable, "-m", "pytest", "tests/test_capability.py", "tests/test_persona_qa_core.py", "-q"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-2000:],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-regression", action="store_true")
    parser.add_argument("--cap-only", action="store_true")
    parser.add_argument("--keys", nargs="*", default=None, help="Run only these test keys")
    args = parser.parse_args(argv)

    write_json_fixtures()

    qa_db = os.environ.get("QA_DB_NAME") or "SarahQA"
    reset_settings_cache()
    settings = get_settings()
    object.__setattr__(settings, "db_name", qa_db)

    client = mongomock.MongoClient()
    set_client_for_tests(client)
    db = client[qa_db]
    assert_safe_database(db, qa_db_name=qa_db)
    ensure_indexes(db)
    PromptRepository(db).seed()
    PersonaIngestionService(db).ingest(ROOT)
    seed_suite(db, qa_db_name=qa_db)

    llm = LLMClient(settings)
    if args.keys:
        keys = list(args.keys)
    else:
        keys = list(CAP_KEYS)
        if not args.cap_only and not args.skip_regression:
            keys.extend(REGRESSION_KEYS)

    run = run_suite(
        db,
        settings=settings,
        llm=llm,
        test_keys=keys,
        live_llm=True,
        trials=1,
        qa_db_name=qa_db,
        idempotency_key=f"capability-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    paths = write_capability_reports(db, run["run_id"])
    from persona_runtime.qa.repository import QARepository

    failed_keys = [
        r.get("test_key")
        for r in QARepository(db).list_results(run["run_id"])
        if r.get("status") in {"failed", "blocked"}
    ]

    pytest_result = {"skipped": True}
    if not args.skip_pytest:
        pytest_result = _pytest()

    summary = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "passed": run.get("passed_count"),
        "failed": run.get("failed_count"),
        "blocked": run.get("blocked_count"),
        "failed_keys": failed_keys,
        "report_paths": paths,
        "pytest": {"returncode": pytest_result.get("returncode"), "skipped": pytest_result.get("skipped", False)},
        "keys": keys,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(summary, indent=2, default=str))
    if pytest_result.get("stdout"):
        print(pytest_result["stdout"])
    if (run.get("failed_count") or 0) > 0:
        return 1
    if pytest_result.get("returncode"):
        return pytest_result["returncode"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
