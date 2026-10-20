"""Track A: full deterministic suite on isolated mongomock (qa-* only).

Matches the previous baseline methodology (mongomock + DeterministicQALLM).
Real Mongo SarahQA was ~45s/case on index+clone; mongomock is the safe,
reproducible path used by run 711fea9b. No product code changes.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import mongomock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QA_DB_NAME", "SarahQA")

from persona_runtime.config import get_settings, reset_settings_cache
from persona_runtime.db import ensure_indexes, set_client_for_tests
from persona_runtime.llm.client import LLMClient
from persona_runtime.persona.loader import PersonaIngestionService
from persona_runtime.prompts.registry import PromptRepository
from persona_runtime.qa.fake_llm import DeterministicQALLM
from persona_runtime.qa.runner import run_suite
from persona_runtime.qa.safety import assert_safe_database
from persona_runtime.qa.seed import seed_suite

MANIFEST = ROOT / "qa_reports" / "post_fix_run_manifest.json"


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


def main() -> int:
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

    stub = DeterministicQALLM()
    llm = LLMClient(settings)
    llm.set_fake_handler(stub)

    run = run_suite(
        db,
        settings=settings,
        llm=llm,
        live_llm=False,
        trials=1,
        qa_db_name=qa_db,
        seed_if_missing=False,
    )
    entry = {
        "track": "A",
        "set": "full",
        "trial": 1,
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "passed": run.get("passed_count"),
        "failed": run.get("failed_count"),
        "blocked": run.get("blocked_count"),
        "skipped": run.get("skipped_count"),
        "report_paths": run.get("report_paths"),
        "live_llm": False,
        "backend": "mongomock",
        "model": settings.openai_model,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    _append_manifest(entry)
    print(json.dumps(entry, indent=2, default=str))
    if (run.get("failed_count") or 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
