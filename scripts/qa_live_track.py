"""Run prioritized live-OpenAI QA subsets against qa-* clones.

Harness-only. Does not change product prompts or persona logic.
Uses existing run_suite(test_keys=...) because the CLI has no multi-key flag.
"""

from __future__ import annotations

import argparse
import json
import os
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
from persona_runtime.qa.runner import run_suite
from persona_runtime.qa.safety import assert_safe_database
from persona_runtime.qa.seed import seed_suite

MANIFEST = ROOT / "qa_reports" / "post_fix_run_manifest.json"

B1 = [
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

B2 = [
    "CONTEXT-010",
    "CONTEXT-015",
    "FLOW-001",
    "FLOW-007",
    "FORMAT-002",
    "MEM-001",
    "MEM-002",
    "MEM-003",
    "MEM-004",
    "MEM-005",
    "MEM-006",
    "MEM-007",
    "MEM-008",
    "MEM-009",
    "MEM-010",
    "MEM-012",
    "MEM-013",
    "MEM-014",
    "MEM-015",
    "MEM-016",
    "MEM-017",
    "MEM-018",
    "PROFILE-004",
    "PROFILE-008",
    "PROFILE-014",
    "STATE-008",
    "STATE-014",
    "STATE-015",
    "UNKNOWN-009",
]

B3 = [f"HUMAN-{i:03d}" for i in range(1, 19)]

SETS = {"B1": B1, "B2": B2, "B3": B3}


def _append_manifest(entry: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"runs": []}
    if MANIFEST.exists():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"runs": []}
    data.setdefault("runs", []).append(entry)
    MANIFEST.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live QA track runner")
    parser.add_argument("--set", dest="set_name", required=True, choices=sorted(SETS))
    parser.add_argument("--trial", type=int, default=1)
    args = parser.parse_args(argv)

    qa_db = os.environ.get("QA_DB_NAME") or "SarahQA"
    reset_settings_cache()
    settings = get_settings()
    object.__setattr__(settings, "db_name", qa_db)

    # Isolated mongomock: same pipeline, qa-* clones only. Avoids ~45s/case
    # real-Mongo index+clone overhead observed on SarahQA.
    client = mongomock.MongoClient()
    set_client_for_tests(client)
    db = client[qa_db]
    assert_safe_database(db, qa_db_name=qa_db)
    ensure_indexes(db)
    PromptRepository(db).seed()
    PersonaIngestionService(db).ingest(ROOT)
    seed_suite(db, qa_db_name=qa_db)

    keys = SETS[args.set_name]
    llm = LLMClient(settings)
    run = run_suite(
        db,
        settings=settings,
        llm=llm,
        test_keys=keys,
        live_llm=True,
        trials=1,
        qa_db_name=qa_db,
        idempotency_key=f"post-fix-{args.set_name}-t{args.trial}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    entry = {
        "track": "B",
        "set": args.set_name,
        "trial": args.trial,
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "passed": run.get("passed_count"),
        "failed": run.get("failed_count"),
        "blocked": run.get("blocked_count"),
        "skipped": run.get("skipped_count"),
        "report_paths": run.get("report_paths"),
        "live_llm": True,
        "model": settings.openai_model,
        "keys": keys,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_manifest(entry)
    print(json.dumps(entry, indent=2, default=str))
    if (run.get("failed_count") or 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
