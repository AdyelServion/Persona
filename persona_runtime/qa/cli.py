"""CLI: python -m persona_runtime.qa seed|run|compare."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from persona_runtime.config import get_settings, reset_settings_cache
from persona_runtime.db import ensure_indexes, get_db, reset_client
from persona_runtime.qa.fixtures.definitions import write_json_fixtures
from persona_runtime.qa.report import compare_runs, generate_reports
from persona_runtime.qa.runner import run_suite
from persona_runtime.qa.safety import assert_safe_database
from persona_runtime.qa.seed import seed_suite


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="persona_runtime.qa", description="Persona consistency QA")
    sub = p.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Seed suite definitions into MongoDB")
    seed.add_argument("--write-json", action="store_true", help="Also write category JSON fixtures")

    run = sub.add_parser("run", help="Run the QA suite")
    run.add_argument("--category", default=None)
    run.add_argument("--test-key", default=None)
    run.add_argument("--failed-from", default=None, help="Re-run failed keys from a prior run_id")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--trials", type=int, default=1)
    run.add_argument("--idempotency-key", default=None)
    run.add_argument("--report-dir", default=None)
    run.add_argument(
        "--live-llm",
        action="store_true",
        help="Enable LLM judge (or set QA_LLM=live)",
    )

    cmp = sub.add_parser("compare", help="Compare two runs")
    cmp.add_argument("run_a")
    cmp.add_argument("run_b")

    dump = sub.add_parser("write-fixtures", help="Write JSON fixtures without seeding DB")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "write-fixtures":
        paths = write_json_fixtures()
        print(json.dumps({"written": [str(p) for p in paths]}, indent=2))
        return 0

    reset_settings_cache()
    settings = get_settings()
    qa_db = os.environ.get("QA_DB_NAME")
    if qa_db:
        # Point settings at QA database for this process
        object.__setattr__(settings, "db_name", qa_db)

    db = get_db(settings)
    try:
        assert_safe_database(db, qa_db_name=qa_db)
    except Exception as exc:  # noqa: BLE001
        print(f"Safety gate: {exc}", file=sys.stderr)
        return 2

    ensure_indexes(db)

    if args.command == "seed":
        result = seed_suite(db, write_json=bool(args.write_json), qa_db_name=qa_db)
        print(json.dumps(result, indent=2, default=str))
        return 0

    if args.command == "compare":
        result = compare_runs(db, args.run_a, args.run_b)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "run":
        live = bool(args.live_llm) or os.environ.get("QA_LLM", "").lower() == "live"
        report_dir = Path(args.report_dir) if args.report_dir else None
        if live:
            from persona_runtime.llm.client import LLMClient

            llm: Any = LLMClient(settings)
        else:
            from persona_runtime.qa.fake_llm import DeterministicQALLM
            from persona_runtime.llm.client import LLMClient

            # Wrap stub so PersonaRuntime receives an LLMClient-compatible handler
            stub = DeterministicQALLM()
            llm = LLMClient(settings)
            llm.set_fake_handler(stub)
        run = run_suite(
            db,
            settings=settings,
            llm=llm,
            category=args.category,
            test_key=args.test_key,
            failed_from_run_id=args.failed_from,
            dry_run=bool(args.dry_run),
            live_llm=live,
            idempotency_key=args.idempotency_key,
            trials=args.trials,
            report_dir=report_dir,
            qa_db_name=qa_db,
        )
        print(
            json.dumps(
                {
                    "run_id": run.get("run_id"),
                    "status": run.get("status"),
                    "passed": run.get("passed_count"),
                    "failed": run.get("failed_count"),
                    "blocked": run.get("blocked_count"),
                    "skipped": run.get("skipped_count"),
                    "report_paths": run.get("report_paths"),
                },
                indent=2,
                default=str,
            )
        )
        if (run.get("failed_count") or 0) > 0:
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
